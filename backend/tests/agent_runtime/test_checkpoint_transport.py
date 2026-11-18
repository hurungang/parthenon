"""Agent Runtime checkpoint transport — CH-only courier, typed failures.

Every call must target the Communication Hub relay surface, carry the signed
tenant header set through the shared egress hook, and surface failures as typed
errors the executor can act on (degrade vs fail closed).  The module must stay
free of any database/datastore access.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.agent_runtime import checkpoint_transport as transport_module
from app.agent_runtime.checkpoint_transport import (
    TURN_IDEMPOTENCY_HEADER,
    CheckpointTransportClient,
    CheckpointTransportError,
    ResumeClaimContentionError,
    ResumeIndexNotFoundError,
    ResumeIndexRead,
    turn_idempotency_headers,
)

_CONV_ID = uuid.uuid4()


def _resume_body(**overrides) -> dict:
    body = {
        "resume_id": str(uuid.uuid4()),
        "conversation_session_id": str(_CONV_ID),
        "resume_key": "rk-opaque",
        "idempotency_key": "idem-key",
        "state": "waiting_for_human",
        "resume_outcome": None,
        "expires_at": None,
        "write_applied": False,
        "is_terminal": False,
        "terminal_reason_code": None,
        "terminal_message_key": None,
        "attempt_count": 0,
        "outcome_turn_id": None,
        "active_resume_id": str(uuid.uuid4()),
    }
    body.update(overrides)
    return body


class _Recorder:
    """httpx.MockTransport handler that records requests and replays responses."""

    def __init__(self, responder) -> None:
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict] = []
        self._responder = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.bodies.append(json.loads(request.content or b"{}"))
        return self._responder(request)

    @property
    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]

    @property
    def methods(self) -> list[str]:
        return [r.method for r in self.requests]


def _client(responder) -> tuple[CheckpointTransportClient, _Recorder]:
    recorder = _Recorder(responder)
    client = CheckpointTransportClient(
        comm_hub_url="http://comm-hub.test:8002",
        http_transport=httpx.MockTransport(recorder),
    )
    return client, recorder


def test_no_database_access_in_module_source() -> None:
    """AR must remain a courier — no SQLAlchemy / DB session in this path."""
    source = Path(transport_module.__file__).read_text()
    for forbidden in ("sqlalchemy", "AsyncSession", "get_db", "DATABASE_URL"):
        assert forbidden not in source


@pytest.mark.asyncio
async def test_save_checkpoint_targets_ch_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    forwarded = {"X-Internal-Tenant-Id": "tenant-1"}
    monkeypatch.setattr(
        "app.core.internal_http.forward_tenant_headers", lambda: dict(forwarded)
    )

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "resume_id": str(uuid.uuid4()),
                "payload_kind": "agent_turn_state",
                "schema_version": 1,
                "payload_bytes": 42,
                "is_consumed": False,
                "expires_at": None,
            },
        )

    client, recorder = _client(responder)
    expires = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = await client.save_checkpoint(
        _CONV_ID, {"schema_version": 1}, schema_version=1, expires_at=expires
    )

    assert result.payload_bytes == 42
    assert recorder.methods == ["PUT"]
    assert recorder.urls == [
        f"http://comm-hub.test:8002/internal/checkpoint/{_CONV_ID}"
    ]
    # Tenant headers come from the single shared egress hook (never hand-merged).
    assert recorder.requests[0].headers["X-Internal-Tenant-Id"] == "tenant-1"
    assert recorder.bodies[0]["schema_version"] == 1
    assert recorder.bodies[0]["payload"] == {"schema_version": 1}


@pytest.mark.asyncio
async def test_load_checkpoint_returns_none_when_absent() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"null")

    client, recorder = _client(responder)
    assert await client.load_checkpoint(_CONV_ID) is None
    assert recorder.methods == ["GET"]


@pytest.mark.asyncio
async def test_resume_index_and_claim_paths() -> None:
    seen: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/claim"):
            return httpx.Response(
                200,
                json={
                    "status": "acquired",
                    "resume": _resume_body(),
                    "holder_instance_id": "ar-1",
                    "claim_expires_at": None,
                },
            )
        return httpx.Response(200, json=_resume_body())

    client, _recorder = _client(responder)

    record = await client.save_resume_index(
        _CONV_ID,
        intervene_request_id=uuid.uuid4(),
        expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        idempotency_key="idem-key",
    )
    assert isinstance(record, ResumeIndexRead)
    assert record.idempotency_key == "idem-key"

    claim = await client.claim(_CONV_ID, instance_id="ar-1", lease_seconds=30)
    assert claim.status == "acquired"

    await client.release(_CONV_ID, instance_id="ar-1")
    await client.complete_resume(_CONV_ID, outcome="resume_failed")

    assert seen == [
        f"PUT /internal/turn-resume/{_CONV_ID}",
        f"POST /internal/turn-resume/{_CONV_ID}/claim",
        f"POST /internal/turn-resume/{_CONV_ID}/release",
        f"POST /internal/turn-resume/{_CONV_ID}/complete",
    ]


@pytest.mark.asyncio
async def test_missing_relay_maps_to_unavailable() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    client, _recorder = _client(responder)
    with pytest.raises(transport_module.CheckpointTransportUnavailableError):
        await client.save_checkpoint(_CONV_ID, {"x": 1})


@pytest.mark.asyncio
async def test_connection_failure_maps_to_unavailable() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client, _recorder = _client(responder)
    with pytest.raises(transport_module.CheckpointTransportUnavailableError):
        await client.load_checkpoint(_CONV_ID)


@pytest.mark.asyncio
async def test_claim_conflict_maps_to_contention() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "held"})

    client, _recorder = _client(responder)
    with pytest.raises(ResumeClaimContentionError):
        await client.claim(_CONV_ID, instance_id="ar-1")


@pytest.mark.asyncio
async def test_other_http_errors_map_to_typed_transport_error() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(413, json={"detail": "too large"})

    client, _recorder = _client(responder)
    with pytest.raises(CheckpointTransportError) as exc_info:
        await client.save_checkpoint(_CONV_ID, {"x": 1})
    assert not isinstance(exc_info.value, transport_module.CheckpointTransportUnavailableError)


@pytest.mark.asyncio
async def test_get_resume_index_none_when_404() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "No live resume record"})

    client, _recorder = _client(responder)
    assert await client.get_resume_index(_CONV_ID) is None


@pytest.mark.asyncio
async def test_save_resume_index_404_is_resume_not_found() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "relay down"})

    client, _recorder = _client(responder)
    with pytest.raises(transport_module.CheckpointTransportUnavailableError):
        await client.save_resume_index(_CONV_ID)

    def responder_not_found(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"detail": "No live resume record for conversation"}
        )

    client2, _ = _client(responder_not_found)
    with pytest.raises(ResumeIndexNotFoundError):
        await client2.save_resume_index(_CONV_ID)


def test_turn_idempotency_headers_only_inside_a_paused_turn() -> None:
    assert turn_idempotency_headers(None) == {}
    assert turn_idempotency_headers("") == {}
    assert turn_idempotency_headers("abc") == {TURN_IDEMPOTENCY_HEADER: "abc"}
