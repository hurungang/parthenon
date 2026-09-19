"""Integration tests: ``GET /agents/runtime/topology/stream`` (SSE, Phase 15).

The stream endpoint is a ``text/event-stream`` ``StreamingResponse`` that:

- authenticates via the ``?token=`` query param (browser ``EventSource``
  cannot set Authorization headers — the Communication Hub chat WebSocket
  pattern), falling back to the ``Authorization: Bearer`` header;
- enforces the SAME agent-read permission as the REST topology endpoint
  BEFORE the stream opens (permission parity — 401/403, never a partial
  stream);
- emits the full ``RuntimeTopologyRead`` payload ONLY when its hash changed
  (change-gated emission) and keeps idle connections alive with
  ``: heartbeat`` comments;
- stops cleanly when the client disconnects.

Uses a module-scoped StaticPool in-memory SQLite (no live PostgreSQL),
mirroring ``test_runtime_topology_api.py``. The auth middleware is patched
to a PASS-THROUGH (no identity attached) so every test exercises the
endpoint's own token validation path.

Testing note: httpx's ``ASGITransport`` buffers the whole ASGI response
(``await self.app(...)``), so an infinite SSE stream would never complete.
The streaming tests therefore patch ``TOPOLOGY_STREAM_MAX_LIFETIME_SECONDS``
down to a fraction of a second — the generator emits its initial payload,
hash-gates repeats, heartbeats, and then closes by itself, producing a
bounded response body that asserts the exact event contract. The disconnect
test keeps the real (infinite) lifetime and cancels the in-flight request,
asserting the server-side polling stops (generator cancellation cleanup).
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.session import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from sqlalchemy.dialects.postgresql import UUID as _PG_UUID  # noqa: E402

_STREAM_URL = "/api/v1/agents/runtime/topology/stream"

# Accelerated stream cadence: the generator reads these module globals at
# call time, so patching keeps the tests fast without sleeping on the real
# ~2s / ~15s intervals.
_FAST_POLL_SECONDS = 0.01
_FAST_HEARTBEAT_SECONDS = 0.05
# Bounded stream lifetime for "complete response" tests: long enough for an
# initial payload + several poll ticks + a heartbeat, short enough to close.
_BOUNDED_LIFETIME_SECONDS = 0.2

_orig_pg_uuid_result_processor = _PG_UUID.result_processor


def _sqlite_tolerant_uuid_result_processor(self, dialect, coltype):
    orig_proc = _orig_pg_uuid_result_processor(self, dialect, coltype)
    if dialect.name != "sqlite" or orig_proc is None:
        return orig_proc

    def proc(value: object) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, int):
            return uuid.UUID(int=value)
        return orig_proc(value)

    return proc


_PG_UUID.result_processor = _sqlite_tolerant_uuid_result_processor


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def test_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        use_insertmanyvalues=False,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def stream_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """Client whose auth middleware is a pass-through — NO identity attached.

    The SSE stream endpoint therefore authenticates itself from the
    ``?token=`` query param / ``Authorization`` header on every request.
    """
    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    from app.middleware.auth import JWTAuthMiddleware  # noqa: E402

    async def passthrough_dispatch(self, request, call_next):
        return await call_next(request)

    with patch.object(JWTAuthMiddleware, "dispatch", passthrough_dispatch), patch(
        "app.api.v1.agents.TOPOLOGY_STREAM_POLL_SECONDS", _FAST_POLL_SECONDS
    ), patch(
        "app.api.v1.agents.TOPOLOGY_STREAM_HEARTBEAT_SECONDS", _FAST_HEARTBEAT_SECONDS
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

    app.dependency_overrides.clear()


# ── Projection stubbing helpers ────────────────────────────────────────────────


def _make_projection(node_session_id: uuid.UUID | None = None, title: str = "Stream Job"):
    """Build a real ``RuntimeTopologyProjection`` with one running agent node."""
    from app.services.control_center.runtime_topology_controller import (
        RuntimeTopologyProjection,
        TopologyNode,
    )

    sid = node_session_id or uuid.uuid4()
    node = TopologyNode(
        session_id=sid,
        agent_type_id=uuid.uuid4(),
        agent_type_name="Stream Agent",
        status="running",
        depth_from_root=0,
        parent_session_id=None,
        started_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        termination_category=None,
        kind="agent",
        title=title,
    )
    return RuntimeTopologyProjection(
        nodes=[node],
        edges=[],
        root_session_ids=[sid],
    )


def _patch_controller(monkeypatch, projections):
    """Point the module-level controller singleton at a stub returning the
    given projections in sequence (the last one repeats forever)."""
    import app.api.v1.agents as agents_module

    class _StubController:
        def __init__(self) -> None:
            self.calls = 0

        async def get_active_topology(self, db, **kwargs):
            self.calls += 1
            idx = min(self.calls - 1, len(projections) - 1)
            return projections[idx]

    stub = _StubController()
    monkeypatch.setattr(agents_module, "_runtime_topology_controller", stub)
    return stub


def _patch_valid_token(
    monkeypatch, sub: str = "stream-user-sub", is_super_admin: bool = False
) -> list[str]:
    """Make the OIDC tier accept any token, returning fixed claims."""
    import app.api.v1.agents as agents_module

    seen_tokens: list[str] = []

    async def fake_validate(token: str):
        seen_tokens.append(token)
        return {"sub": sub}, is_super_admin

    monkeypatch.setattr(agents_module, "validate_raw_token", fake_validate)
    return seen_tokens


def _patch_allow_permission(monkeypatch) -> list[dict]:
    """Allow-all permission gate that records its arguments."""
    import app.api.v1.agents as agents_module

    calls: list[dict] = []

    async def allow(db, claims, module, action, *, is_super_admin=False):
        calls.append(
            {
                "module": module,
                "action": action,
                "claims": claims,
                "is_super_admin": is_super_admin,
            }
        )
        return claims

    monkeypatch.setattr(agents_module, "authorize_identity", allow)
    return calls


def _bounded_lifetime(monkeypatch) -> None:
    """Close the stream by itself after ``_BOUNDED_LIFETIME_SECONDS`` so the
    buffered ASGI response completes (see module docstring)."""
    monkeypatch.setattr(
        "app.api.v1.agents.TOPOLOGY_STREAM_MAX_LIFETIME_SECONDS",
        _BOUNDED_LIFETIME_SECONDS,
    )


async def _sse_events(response) -> tuple[list[str], list[str]]:
    """Split a completed SSE body into ``(data_payloads, comment_lines)``."""
    body = response.text
    data: list[str] = []
    comments: list[str] = []
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("data: "):
            data.append(chunk[len("data: "):])
        elif chunk.startswith(":"):
            comments.append(chunk)
    return data, comments


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_token_opens_stream_and_emits_initial_payload(
    stream_client, monkeypatch
):
    """A valid ``?token=`` JWT opens an ``text/event-stream`` whose events are
    full ``RuntimeTopologyRead`` payloads, and the SAME agent-read permission
    (``RT_AGENT`` / "read") was enforced before the stream opened."""
    _bounded_lifetime(monkeypatch)
    seen_tokens = _patch_valid_token(monkeypatch)
    perm_calls = _patch_allow_permission(monkeypatch)
    sid = uuid.uuid4()
    _patch_controller(monkeypatch, [_make_projection(sid)])

    response = await stream_client.get(f"{_STREAM_URL}?token=good-jwt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    data, _comments = await _sse_events(response)
    assert len(data) == 1, "a stable projection must emit the payload exactly once"
    payload = json.loads(data[0])
    assert payload["nodes"][0]["session_id"] == str(sid)
    assert payload["nodes"][0]["kind"] == "agent"
    assert payload["root_session_ids"] == [str(sid)]

    # Auth contract: the query-param token reached the OIDC validation tier.
    assert seen_tokens == ["good-jwt"]
    # Permission parity: same module/action as the REST endpoint.
    assert len(perm_calls) == 1
    assert perm_calls[0]["module"] == "agent"
    assert perm_calls[0]["action"] == "read"


@pytest.mark.asyncio
async def test_missing_token_rejected_before_stream(stream_client, monkeypatch):
    """No ``?token=`` and no Authorization header → 401 JSON, never an open
    stream (content-type is not ``text/event-stream``)."""
    _patch_valid_token(monkeypatch)
    _patch_allow_permission(monkeypatch)
    _patch_controller(monkeypatch, [_make_projection()])

    response = await stream_client.get(_STREAM_URL)
    assert response.status_code == 401
    assert "text/event-stream" not in response.headers.get("content-type", "")
    assert response.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_token_rejected_before_stream(stream_client, monkeypatch):
    """A token the OIDC tier rejects → 401 before any event is sent."""
    import app.api.v1.agents as agents_module

    async def reject(token: str):
        return None, False

    monkeypatch.setattr(agents_module, "validate_raw_token", reject)
    _patch_allow_permission(monkeypatch)
    stub = _patch_controller(monkeypatch, [_make_projection()])

    response = await stream_client.get(f"{_STREAM_URL}?token=garbage")
    assert response.status_code == 401
    assert "text/event-stream" not in response.headers.get("content-type", "")
    assert stub.calls == 0, "rejected connections must never compute a projection"


@pytest.mark.asyncio
async def test_permission_denied_rejected_with_parity(stream_client, monkeypatch):
    """A valid token but a caller WITHOUT the agent-read permission is
    rejected with 403 — the stream is not a permission bypass (parity with
    ``GET /agents/runtime/topology``)."""
    import app.api.v1.agents as agents_module
    from fastapi import HTTPException

    _patch_valid_token(monkeypatch)

    async def deny(db, claims, module, action, *, is_super_admin=False):
        raise HTTPException(status_code=403, detail="Permission denied by policy")

    monkeypatch.setattr(agents_module, "authorize_identity", deny)
    stub = _patch_controller(monkeypatch, [_make_projection()])

    response = await stream_client.get(f"{_STREAM_URL}?token=good-jwt")
    assert response.status_code == 403
    assert "text/event-stream" not in response.headers.get("content-type", "")
    # Rejected BEFORE the stream opened — no projection was ever computed.
    assert stub.calls == 0


@pytest.mark.asyncio
async def test_super_admin_claims_bypass_permission_gate(stream_client, monkeypatch):
    """Super-admin claims validated from the query param bypass the permission
    gate (same wildcard semantics as the REST endpoint) and open the stream."""
    _bounded_lifetime(monkeypatch)
    seen_tokens = _patch_valid_token(monkeypatch, sub="super_admin:x", is_super_admin=True)
    perm_calls = _patch_allow_permission(monkeypatch)
    _patch_controller(monkeypatch, [_make_projection()])

    response = await stream_client.get(f"{_STREAM_URL}?token=sa-jwt")

    assert response.status_code == 200
    data, _ = await _sse_events(response)
    assert len(data) == 1
    assert seen_tokens == ["sa-jwt"]
    assert perm_calls[0]["is_super_admin"] is True


@pytest.mark.asyncio
async def test_bearer_header_accepted_for_header_capable_clients(
    stream_client, monkeypatch
):
    """The normal ``Authorization: Bearer`` path also works (validated by the
    endpoint because the stream path is middleware-public)."""
    _bounded_lifetime(monkeypatch)
    seen_tokens = _patch_valid_token(monkeypatch)
    _patch_allow_permission(monkeypatch)
    _patch_controller(monkeypatch, [_make_projection()])

    response = await stream_client.get(
        _STREAM_URL, headers={"Authorization": "Bearer header-jwt"}
    )

    assert response.status_code == 200
    data, _ = await _sse_events(response)
    assert len(data) == 1
    assert seen_tokens == ["header-jwt"]


@pytest.mark.asyncio
async def test_hash_gated_emission_with_heartbeats(stream_client, monkeypatch):
    """Unchanged projections emit NO data events (heartbeats only); a
    projection change emits exactly ONE new data event — then repeats are
    suppressed again."""
    sid_a, sid_b = uuid.uuid4(), uuid.uuid4()
    projection_a = _make_projection(sid_a, title="Before change")
    projection_b = _make_projection(sid_b, title="After change")
    stub = _patch_controller(monkeypatch, [projection_a, projection_a, projection_b])
    _patch_valid_token(monkeypatch)
    _patch_allow_permission(monkeypatch)
    _bounded_lifetime(monkeypatch)

    response = await stream_client.get(f"{_STREAM_URL}?token=good-jwt")

    assert response.status_code == 200
    data, comments = await _sse_events(response)

    # Initial payload (A) + exactly one event for the A→B change; the
    # unchanged ticks in between and after emit nothing.
    assert len(data) == 2, f"expected initial + changed payloads only, got {len(data)}"
    first = json.loads(data[0])
    second = json.loads(data[1])
    assert first["nodes"][0]["session_id"] == str(sid_a)
    assert second["nodes"][0]["session_id"] == str(sid_b)

    # Heartbeats keep the connection alive during the unchanged period.
    assert len(comments) >= 1
    assert all(c.strip() == ": heartbeat" for c in comments)

    # The stub was polled repeatedly — far more than the two states it
    # served — proving hash-gated emission (no redundant traffic).
    assert stub.calls >= 5


@pytest.mark.asyncio
async def test_client_disconnect_stops_the_stream(stream_client, monkeypatch):
    """Cancelling the in-flight request (client disconnect) cancels the
    server-side generator cleanly — no leaked loop, no further projection
    polls after the disconnect."""
    _patch_valid_token(monkeypatch)
    _patch_allow_permission(monkeypatch)
    stub = _patch_controller(monkeypatch, [_make_projection()])
    # Real (infinite) lifetime — the request never completes on its own.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            stream_client.get(f"{_STREAM_URL}?token=good-jwt"), timeout=0.25
        )

    calls_at_disconnect = stub.calls
    # Give any (incorrectly) still-running generator time to poll again —
    # a leaked loop would add ~10 calls at the accelerated 10ms cadence.
    await asyncio.sleep(0.1)
    assert stub.calls <= calls_at_disconnect + 2, (
        "projection polling must stop shortly after the client disconnects"
    )


@pytest.mark.asyncio
async def test_stream_payload_matches_rest_shape(stream_client, monkeypatch):
    """The streamed payload deserialises into the ``RuntimeTopologyRead``
    schema — no push/pull field drift."""
    from app.schemas.agents import RuntimeTopologyRead

    _bounded_lifetime(monkeypatch)
    _patch_valid_token(monkeypatch)
    _patch_allow_permission(monkeypatch)
    sid = uuid.uuid4()
    projection = _make_projection(sid)
    projection.nodes[0].trigger_source = "user"
    projection.nodes[0].trigger_source_label = "Alice"
    projection.nodes[0].tool_calls = []
    _patch_controller(monkeypatch, [projection])

    response = await stream_client.get(f"{_STREAM_URL}?token=good-jwt")

    assert response.status_code == 200
    data, _ = await _sse_events(response)
    parsed = RuntimeTopologyRead.model_validate_json(data[0])
    assert parsed.nodes[0].session_id == sid
    assert parsed.nodes[0].trigger_source == "user"
    assert parsed.nodes[0].tool_calls == []
