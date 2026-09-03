"""Integration tests: ``GET /agents/runtime/topology`` ``needs_intervention`` contract.

The runtime topology endpoint returns a ``RuntimeTopologyRead`` whose
``nodes[*]`` now carry a boolean ``needs_intervention`` field.  These tests
assert:

- every node in the response carries a *boolean* ``needs_intervention``;
- a node whose session has a pending ``InterveneRequest`` is flagged ``True``
  (both agent-kind and conversation-kind join keys);
- a node with no pending request (or only non-pending requests) stays
  ``False``;
- existing node fields (session_id, status, kind, title, parent_session_id)
  remain present.

Uses a module-scoped StaticPool in-memory SQLite (no live PostgreSQL), mirroring
``test_intervention_api_integration.py``.
"""
from __future__ import annotations

import os
import uuid
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

from app.db.models.agents import (  # noqa: E402
    AgentInputType,
    AgentJob,
    AgentJobStatus,
    AgentOutputType,
    AgentType,
)
from app.db.models.conversations import (  # noqa: E402
    ConversationSession,
    ConversationStatus,
)
from app.db.models.intervene import (  # noqa: E402
    InterveneRequest,
    InterveneRequestStatus,
    InterventionType,
)
from app.db.models.identity import Identity  # noqa: E402
from app.db.session import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from sqlalchemy.dialects.postgresql import UUID as _PG_UUID  # noqa: E402

_INTEGRATION_URL = "sqlite+aiosqlite:///:memory:"
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


@pytest_asyncio.fixture(scope="module")
async def test_engine():
    engine = create_async_engine(
        _INTEGRATION_URL,
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
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def async_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
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

    from app.api.deps import require_permission  # noqa: E402
    from app.core.resource_types import RT_AGENT  # noqa: E402
    from app.middleware.auth import JWTAuthMiddleware  # noqa: E402

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-user-sub"}
        return await call_next(request)

    patcher = patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)
    patcher.start()

    def _allow_all():
        return {"sub": "test-user-sub", "platform_user_id": None}

    app.dependency_overrides[require_permission(RT_AGENT, "read")] = _allow_all

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    patcher.stop()
    app.dependency_overrides.clear()


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _create_agent_type(db: AsyncSession, prefix: str) -> AgentType:
    at = AgentType(
        name=f"{prefix}-{uuid.uuid4().hex[:8]}",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
        is_active=True,
    )
    db.add(at)
    await db.flush()
    return at


async def _create_job(db: AsyncSession, at_id: uuid.UUID, status: AgentJobStatus) -> AgentJob:
    job = AgentJob(
        id=uuid.uuid4(),
        agent_type_id=at_id,
        status=status,
        input_data={"query": "runtime-topology-contract"},
    )
    db.add(job)
    await db.flush()
    return job


async def _create_job_with_trigger(
    db: AsyncSession,
    at_id: uuid.UUID,
    status: AgentJobStatus,
    triggered_by_user_id: uuid.UUID,
) -> AgentJob:
    job = AgentJob(
        id=uuid.uuid4(),
        agent_type_id=at_id,
        status=status,
        triggered_by_user_id=triggered_by_user_id,
        input_data={"query": "runtime-topology-provenance"},
    )
    db.add(job)
    await db.flush()
    return job


async def _create_job_with_parent(
    db: AsyncSession,
    at_id: uuid.UUID,
    status: AgentJobStatus,
    parent_job_id: uuid.UUID,
    input_data: dict | None = None,
) -> AgentJob:
    job = AgentJob(
        id=uuid.uuid4(),
        agent_type_id=at_id,
        status=status,
        parent_job_id=parent_job_id,
        input_data=input_data if input_data is not None else {"query": "runtime-topology-child"},
    )
    db.add(job)
    await db.flush()
    return job


async def _create_active_conversation(db: AsyncSession, at_id: uuid.UUID) -> ConversationSession:
    conv = ConversationSession(
        agent_type_id=at_id,
        triggered_by_user_id=None,
        status=ConversationStatus.active,
    )
    db.add(conv)
    await db.flush()
    return conv


async def _create_intervene(
    db: AsyncSession,
    at_id: uuid.UUID,
    agent_session_id: uuid.UUID,
    conversation_session_id: uuid.UUID | None = None,
    status: InterveneRequestStatus = InterveneRequestStatus.pending,
) -> InterveneRequest:
    req = InterveneRequest(
        id=uuid.uuid4(),
        agent_session_id=agent_session_id,
        agent_type_id=at_id,
        conversation_session_id=conversation_session_id,
        intervention_type=InterventionType.approval,
        reason="awaiting operator approval",
        status=status,
        delegation_depth=0,
    )
    db.add(req)
    await db.flush()
    return req


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_every_node_carries_boolean_needs_intervention(db_session, async_client):
    """Every node carries a boolean ``needs_intervention`` and the
    existing node fields remain present.  With no pending request the
    created nodes are ``False``.
    """
    at = await _create_agent_type(db_session, "rt-bool")
    job = await _create_job(db_session, at.id, AgentJobStatus.running)
    conv = await _create_active_conversation(db_session, at.id)
    await db_session.commit()

    resp = await async_client.get("/api/v1/agents/runtime/topology")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert isinstance(body["nodes"], list)
    assert len(body["nodes"]) >= 2

    by_id: dict[str, dict] = {n["session_id"]: n for n in body["nodes"]}
    for node in body["nodes"]:
        assert "needs_intervention" in node, f"node missing needs_intervention: {node}"
        assert isinstance(node["needs_intervention"], bool)
        # Existing fields are unchanged.
        assert "session_id" in node
        assert "status" in node
        assert "kind" in node
        assert "title" in node
        assert "parent_session_id" in node
        assert "agent_type_id" in node
        assert "depth_from_root" in node

    assert by_id[str(job.id)]["needs_intervention"] is False
    assert by_id[str(conv.id)]["needs_intervention"] is False
    assert by_id[str(conv.id)]["kind"] == "conversation"


@pytest.mark.asyncio
async def test_pending_agent_request_flags_node(db_session, async_client):
    """A pending ``InterveneRequest`` keyed by ``agent_session_id``
    flags the matching agent-kind node.
    """
    at = await _create_agent_type(db_session, "rt-agent")
    job = await _create_job(db_session, at.id, AgentJobStatus.running)
    await _create_intervene(db_session, at.id, agent_session_id=job.id)
    await db_session.commit()

    resp = await async_client.get("/api/v1/agents/runtime/topology")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    node = next(n for n in body["nodes"] if n["session_id"] == str(job.id))
    assert node["kind"] == "agent"
    assert node["needs_intervention"] is True


@pytest.mark.asyncio
async def test_pending_conversation_request_flags_sleep_node(db_session, async_client):
    """A pending ``InterveneRequest`` keyed by ``conversation_session_id``
    flags the matching sleeping conversation-kind node.
    """
    at = await _create_agent_type(db_session, "rt-conv")
    conv = await _create_active_conversation(db_session, at.id)
    # A terminal backing agent job so the intervene request has a valid FK;
    # it is not running/queued so it does not appear in the live topology.
    backing_job = await _create_job(db_session, at.id, AgentJobStatus.completed)
    await _create_intervene(
        db_session,
        at.id,
        agent_session_id=backing_job.id,
        conversation_session_id=conv.id,
    )
    await db_session.commit()

    resp = await async_client.get("/api/v1/agents/runtime/topology")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    conv_node = next(n for n in body["nodes"] if n["session_id"] == str(conv.id))
    assert conv_node["kind"] == "conversation"
    assert conv_node["status"] == "sleep"
    assert conv_node["needs_intervention"] is True


@pytest.mark.asyncio
async def test_non_pending_request_does_not_flag_node(db_session, async_client):
    """A responded intervention request (non-pending) does NOT flag the
    node.
    """
    at = await _create_agent_type(db_session, "rt-nonpending")
    job = await _create_job(db_session, at.id, AgentJobStatus.running)
    await _create_intervene(
        db_session,
        at.id,
        agent_session_id=job.id,
        status=InterveneRequestStatus.responded,
    )
    await db_session.commit()

    resp = await async_client.get("/api/v1/agents/runtime/topology")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    node = next(n for n in body["nodes"] if n["session_id"] == str(job.id))
    assert node["needs_intervention"] is False


# ── Trigger provenance + tool-call history contract ─────────────────────────────


@pytest.mark.asyncio
async def test_nodes_carry_trigger_provenance_and_tool_calls_fields(db_session, async_client):
    """Every node carries ``trigger_source``, ``trigger_source_label`` and a
    ``tool_calls`` list, in addition to the existing fields.
    """
    at = await _create_agent_type(db_session, "rt-provenance")
    job = await _create_job(db_session, at.id, AgentJobStatus.running)
    await db_session.commit()

    resp = await async_client.get("/api/v1/agents/runtime/topology")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    node = next(n for n in body["nodes"] if n["session_id"] == str(job.id))
    assert "trigger_source" in node
    assert "trigger_source_label" in node
    assert "tool_calls" in node
    assert isinstance(node["tool_calls"], list)
    # Untriggered node degrades to "unknown", no label, empty tool calls.
    assert node["trigger_source"] == "unknown"
    assert node["trigger_source_label"] is None
    assert node["tool_calls"] == []


@pytest.mark.asyncio
async def test_user_triggered_node_resolves_display_name(db_session, async_client):
    """A directly user-triggered node surfaces ``trigger_source="user"`` with
    the triggering user's display name as the label.
    """
    ident = Identity(
        id=uuid.uuid4(),
        subject=f"provenance-user-{uuid.uuid4().hex}",
        display_name="Alice Operator",
    )
    db_session.add(ident)
    await db_session.flush()

    at = await _create_agent_type(db_session, "rt-user-trigger")
    job = await _create_job_with_trigger(
        db_session, at.id, AgentJobStatus.running, ident.id
    )
    await db_session.commit()

    resp = await async_client.get("/api/v1/agents/runtime/topology")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    node = next(n for n in body["nodes"] if n["session_id"] == str(job.id))
    assert node["trigger_source"] == "user"
    assert node["trigger_source_label"] == "Alice Operator"


@pytest.mark.asyncio
async def test_tool_calls_surface_as_route_list(db_session, async_client):
    """A node with tool calls returns an ordered route list (tool name + MCP
    slug).  The backend resolves namespaced ``server____tool`` names.
    """
    from datetime import datetime, timezone

    at = await _create_agent_type(db_session, "rt-toolcalls")
    job = await _create_job(db_session, at.id, AgentJobStatus.running)
    await db_session.flush()

    conv = ConversationSession(
        agent_type_id=at.id,
        triggered_by_user_id=None,
        status=ConversationStatus.active,
        agent_job_id=job.id,
    )
    db_session.add(conv)
    await db_session.flush()

    from app.db.models.conversations import ConversationTurn, ToolCallRecord, TurnRole

    turn = ConversationTurn(session_id=conv.id, role=TurnRole.agent, content="tool")
    db_session.add(turn)
    await db_session.flush()

    db_session.add(
        ToolCallRecord(
            id=uuid.uuid4(),
            turn_id=turn.id,
            tool_name="github____list_prs",
            created_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
    )
    await db_session.commit()

    resp = await async_client.get("/api/v1/agents/runtime/topology")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    node = next(n for n in body["nodes"] if n["session_id"] == str(job.id))
    assert len(node["tool_calls"]) == 1
    call = node["tool_calls"][0]
    assert call["tool_name"] == "github____list_prs"
    assert call["mcp_slug"] == "github"


# ── Live-data correction round: terminal children, HITL live status,
#    conversation linked-job drivers ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_waiting_for_human_jobs_included_in_live_topology(db_session, async_client):
    """A job paused in ``waiting_for_human`` appears in the default (live)
    topology view — the endpoint includes that status in both the live and
    the terminal status lists.
    """
    at = await _create_agent_type(db_session, "rt-hitl-live")
    job = await _create_job(db_session, at.id, AgentJobStatus.waiting_for_human)
    await db_session.commit()

    resp = await async_client.get("/api/v1/agents/runtime/topology")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    node = next(n for n in body["nodes"] if n["session_id"] == str(job.id))
    assert node["status"] == "waiting_for_human"
    assert node["kind"] == "agent"


@pytest.mark.asyncio
async def test_terminal_children_of_active_job_appear_with_edge(db_session, async_client):
    """A terminal (failed) direct child of an included running parent is
    returned by the live topology so the delegation edge renders — the
    live case being a parent paused for HITL whose delegated attempts
    already failed.
    """
    at = await _create_agent_type(db_session, "rt-terminal-children")
    parent = await _create_job(db_session, at.id, AgentJobStatus.waiting_for_human)
    child = await _create_job_with_parent(
        db_session, at.id, AgentJobStatus.failed, parent.id
    )
    await db_session.commit()

    resp = await async_client.get("/api/v1/agents/runtime/topology")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    by_id = {n["session_id"]: n for n in body["nodes"]}
    assert str(parent.id) in by_id
    assert str(child.id) in by_id, "terminal direct child must be in the live response"

    child_node = by_id[str(child.id)]
    assert child_node["status"] == "failed"
    assert child_node["parent_session_id"] == str(parent.id)

    edge = next(
        e
        for e in body["edges"]
        if e["child_session_id"] == str(child.id)
        and e["parent_session_id"] == str(parent.id)
    )
    assert edge["depth_from_root"] == 1


@pytest.mark.asyncio
async def test_conversation_counts_chat_spawned_linked_job_as_active(db_session, async_client):
    """A chat-spawned linked job (``input_data.__conv_session_id``) drives
    its source conversation: the conversation node computes status
    ``"active"`` (not ``"sleep"``) and an edge conversation → job is
    returned so the spawned run renders under the conversation.
    """
    at = await _create_agent_type(db_session, "rt-conv-driver")
    conv = await _create_active_conversation(db_session, at.id)
    linked_job = await _create_job_with_parent(
        db_session,
        at.id,
        AgentJobStatus.running,
        parent_job_id=None,
        input_data={"__conv_session_id": str(conv.id)},
    )
    await db_session.commit()

    resp = await async_client.get("/api/v1/agents/runtime/topology")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    conv_node = next(n for n in body["nodes"] if n["session_id"] == str(conv.id))
    assert conv_node["kind"] == "conversation"
    assert conv_node["status"] == "active", (
        "chat-spawned live job must keep the conversation active, not sleep"
    )

    job_node = next(n for n in body["nodes"] if n["session_id"] == str(linked_job.id))
    assert job_node["parent_session_id"] == str(conv.id)

    assert any(
        e["parent_session_id"] == str(conv.id)
        and e["child_session_id"] == str(linked_job.id)
        for e in body["edges"]
    )
