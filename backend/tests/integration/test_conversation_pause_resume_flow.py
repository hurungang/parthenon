"""Integration — real-backend pause → approve/deny → exactly-once outcome.

Task 7.5 + 7.7 for resumable-agent-turn-persistence.  Unlike the mocked
service-boundary suites, this file drives the *real* Control Center handlers
against a real (in-memory) relational database and asserts **state agreement**
across all three places the test plan requires:

1. the resume record (``state``, ``resume_outcome``, ``write_applied``),
2. the ``ConversationActivity`` row (``state``, ``is_terminal``,
   ``active_resume_id``),
3. the conversation history (one outcome turn, in order, no duplicates).

Covered:

* pause persists the intervention + waiting activity + a live resume record in
  one flow ("shown as waiting" ⇔ "actually answerable");
* approve → resuming → exactly one confirmed write → complete records
  ``approved_applied`` once, clears ``active_resume_id``, and appends exactly
  one outcome turn (duplicate close appends nothing);
* deny → the closure records ``denied`` with ``write_applied`` false and no
  management write ever happens;
* the persisted checkpoint envelope carries no credentials/tokens (payload
  hygiene at the serializer boundary).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.models.agents import AgentInputType, AgentOutputType, AgentType
from app.db.models.conversation_activity import ActivityState
from app.db.models.conversation_turn_resume import (
    ConversationTurnCheckpoint,
    ConversationTurnResume,
    ResumeOutcome,
    ResumeState,
)
from app.db.models.conversations import (
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
    TurnRole,
    TurnType,
)
from app.db.models.identity import Identity
from app.db.models.skills import Skill
from app.db.session import Base, get_db
from app.main import create_app
from app.services.conversations.activity_store import ConversationActivityStore
from app.services.conversations.turn_resume_store import ConversationTurnResumeStore
from sqlalchemy.dialects.postgresql import UUID as _PG_UUID

_INTEGRATION_URL = "sqlite+aiosqlite:///:memory:"

# SQLite stores UUID columns as bare integers; make the PG UUID result
# processor tolerant so ORM reads round-trip (same shim as the sibling suites).
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

TENANT_ID = uuid.uuid4()
OPERATOR_SUB = "resume-flow-operator"


# ── Fixtures ────────────────────────────────────────────────────────────────


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


@pytest_asyncio.fixture(scope="module")
async def shared_identity(test_engine) -> Identity:
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        ident = Identity(
            id=uuid.uuid4(), subject=OPERATOR_SUB, display_name="Resume Flow Operator"
        )
        session.add(ident)
        await session.commit()
        return ident


@pytest_asyncio.fixture(scope="module")
async def shared_agent_type(test_engine) -> AgentType:
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        at = AgentType(
            name=f"Resume-Flow-{uuid.uuid4().hex}",
            input_type=AgentInputType.conversation,
            output_type=AgentOutputType.auto,
        )
        session.add(at)
        await session.commit()
        return at


@pytest_asyncio.fixture
async def dialog_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """The dialog-facing app (respond endpoint) with auth/permissions bypassed."""
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    from app.api.deps import require_permission
    from app.core.resource_types import RT_AGENT_HUMAN_INTERVENTION, RT_AGENT_TRAILS
    from app.middleware.auth import JWTAuthMiddleware

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": OPERATOR_SUB}
        return await call_next(request)

    patcher = patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)
    patcher.start()

    def _claims():
        return {"sub": OPERATOR_SUB, "platform_user_id": None}

    app.dependency_overrides[require_permission(RT_AGENT_TRAILS, "read")] = _claims
    app.dependency_overrides[require_permission(RT_AGENT_HUMAN_INTERVENTION, "view")] = _claims
    app.dependency_overrides[require_permission(RT_AGENT_HUMAN_INTERVENTION, "respond")] = _claims

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    patcher.stop()
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def internal_client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """The CC internal data-plane router (complete/read) with security bypassed."""
    from fastapi import FastAPI

    from app.api.deps import require_internal_tenant_context, require_service_certificate
    from app.api.v1.internal.session_data import InternalSessionDataRouter
    from app.core.tenant_context import TenantContext

    app = FastAPI()
    app.include_router(InternalSessionDataRouter, prefix="/api/v1")

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_service_certificate] = lambda: None
    app.dependency_overrides[require_internal_tenant_context] = lambda: TenantContext(
        tenant_id=TENANT_ID, slug="resume-flow", name="resume-flow"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def management_client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """The confirmed-write chokepoint (management tools) with auth bypassed."""
    from fastapi import FastAPI

    from app.api.deps import require_internal_tenant_context, require_service_certificate
    from app.api.v1.internal import management_tools
    from app.core.tenant_context import TenantContext

    app = FastAPI()
    app.include_router(management_tools.router, prefix="/api/v1")

    async def _override_db():
        yield db_session

    async def _allow(*_args: Any, **_kwargs: Any) -> None:
        return None

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_service_certificate] = lambda: None
    app.dependency_overrides[require_internal_tenant_context] = lambda: TenantContext(
        tenant_id=TENANT_ID, slug="resume-flow", name="resume-flow"
    )

    original = management_tools._authorize
    management_tools._authorize = _allow  # type: ignore[assignment]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    management_tools._authorize = original  # type: ignore[assignment]


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _pause(
    db: AsyncSession, agent_type_id: uuid.UUID, *, turn_key: str | None = None
) -> tuple[ConversationSession, uuid.UUID, str]:
    """Drive the real conversational pause path; returns (session, request, key)."""
    from app.api.v1.internal.system_tools import SystemToolRequest, human_intervene_tool
    from app.core.tenant_context import TenantContext
    from app.services.control_center import comm_hub_client

    conv = ConversationSession(
        agent_type_id=agent_type_id, status=ConversationStatus.active
    )
    db.add(conv)
    await db.flush()

    key = turn_key or f"turn-{uuid.uuid4().hex}"
    body = SystemToolRequest(
        session_id=str(conv.id),
        agent_type_id=str(agent_type_id),
        conversation_session_id=str(conv.id),
        tool_args={
            "intervention_type": "approval",
            "reason": "**Create Skill: Flow** — confirm?",
            "turn_idempotency_key": key,
        },
    )

    async def _noop(self, **kwargs):  # noqa: ANN001
        return None

    with patch.object(comm_hub_client.CommunicationHubClient, "dispatch_message", _noop):
        response = await human_intervene_tool(
            body,
            TenantContext(tenant_id=TENANT_ID, slug="resume-flow", name="resume-flow"),
            db,
        )
    await db.commit()
    return conv, uuid.UUID(response.result["request_id"]), key


async def _resume_of(db: AsyncSession, request_id: uuid.UUID) -> ConversationTurnResume:
    row = (
        await db.execute(
            select(ConversationTurnResume).where(
                ConversationTurnResume.intervene_request_id == request_id
            )
        )
    ).scalar_one()
    await db.refresh(row)
    return row


async def _agent_turns(db: AsyncSession, session_id: uuid.UUID) -> list[ConversationTurn]:
    rows = (
        await db.execute(
            select(ConversationTurn).where(
                ConversationTurn.session_id == session_id,
                ConversationTurn.role == TurnRole.agent,
                ConversationTurn.turn_type == TurnType.message,
            )
        )
    ).scalars()
    return list(rows)


def _skill_payload(name: str) -> dict:
    return {
        "session_id": "assistant-session",
        "user_sub": OPERATOR_SUB,
        "tool_args": {
            "name": name,
            "data": {"description": "confirmed skill", "instructions": "do it"},
        },
    }


async def _complete(
    client: AsyncClient, conv_id: uuid.UUID, resume_id: uuid.UUID, **body: Any
):
    payload = {"resume_id": str(resume_id), **body}
    return await client.post(
        f"/api/v1/internal/data/conversations/{conv_id}/resume/complete", json=payload
    )


# ── A. Pause capture ────────────────────────────────────────────────────────


class TestPauseCapture:
    @pytest.mark.asyncio
    async def test_pause_persists_waiting_activity_and_live_resume(
        self, db_session, shared_agent_type
    ):
        conv, request_id, _key = await _pause(db_session, shared_agent_type.id)

        resume = await _resume_of(db_session, request_id)
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        # Three-way agreement: shown as waiting ⇔ live, answerable record.
        assert activity.state is ActivityState.waiting_for_human
        assert activity.is_terminal is False
        assert activity.active_resume_id == resume.id
        assert resume.state is ResumeState.waiting_for_human
        assert resume.is_terminal is False
        assert resume.idempotency_key


# ── B. Approve → exactly one write → exactly one outcome ────────────────────


class TestApproveFlow:
    @pytest.mark.asyncio
    async def test_approve_applies_one_write_and_records_one_outcome(
        self,
        db_session,
        dialog_client,
        internal_client,
        management_client,
        shared_identity,
        shared_agent_type,
    ):
        conv, request_id, key = await _pause(db_session, shared_agent_type.id)
        resume = await _resume_of(db_session, request_id)
        skill_name = f"skill-{uuid.uuid4().hex[:8]}"

        # The operator approves.  AR is out of scope here; the dispatch is
        # stubbed and asserted to happen exactly once.
        dispatch = AsyncMock(return_value="resumed")
        with patch(
            "app.services.conversations.turn_resolution.dispatch_answered_conversation_turn",
            new=dispatch,
        ):
            approved = await dialog_client.post(
                f"/api/v1/conversations/{conv.id}/interventions/{request_id}/respond",
                json={"request_id": str(request_id), "approval_value": True},
            )
        assert approved.status_code == 200, approved.text
        dispatch.assert_awaited_once()

        resumed = await _resume_of(db_session, request_id)
        assert resumed.state is ResumeState.resuming
        assert resumed.applied_by_user_id is not None

        # The resumed turn dispatches the confirmed write with the turn key…
        first = await management_client.post(
            "/api/v1/internal/management-tools/create_skill",
            json=_skill_payload(skill_name),
            headers={"X-Turn-Idempotency-Key": key},
        )
        assert first.status_code == 200, first.text
        # …and a replay (duplicate delivery) does not write a second time.
        replay = await management_client.post(
            "/api/v1/internal/management-tools/create_skill",
            json=_skill_payload(skill_name),
            headers={"X-Turn-Idempotency-Key": key},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["result"]["duplicate_dispatch"] is True

        skills = (
            await db_session.execute(
                select(Skill).where(Skill.name == skill_name)
            )
        ).scalars().all()
        assert len(skills) == 1, "the confirmed write must apply exactly once"

        # AR reports the finished turn → the single-transaction closer.
        closed = await _complete(
            internal_client,
            conv.id,
            resume.id,
            outcome=ResumeOutcome.approved_applied.value,
            write_applied=True,
            outcome_turn_content="Done — the skill was created.",
        )
        assert closed.status_code == 200, closed.text
        body = closed.json()
        assert body["state"] == ResumeState.resolved.value
        assert body["resume_outcome"] == ResumeOutcome.approved_applied.value
        assert body["is_terminal"] is True
        assert body["write_applied"] is True
        assert body["outcome_turn_id"] is not None
        assert body["active_resume_id"] is None

        # A duplicate close appends nothing and returns the stored outcome.
        duplicate = await _complete(
            internal_client,
            conv.id,
            resume.id,
            outcome=ResumeOutcome.approved_applied.value,
            write_applied=True,
            outcome_turn_content="Done — the skill was created.",
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["outcome_turn_id"] == body["outcome_turn_id"]

        turns = await _agent_turns(db_session, conv.id)
        assert len(turns) == 1
        assert turns[0].content == "Done — the skill was created."

        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.is_terminal is True
        assert activity.state is ActivityState.finished
        assert activity.active_resume_id is None

        stored = await _resume_of(db_session, request_id)
        assert stored.write_applied is True
        assert stored.applied_at is not None
        assert stored.applied_effect_summary is not None


# ── C. Deny → nothing is written ────────────────────────────────────────────


class TestDenyFlow:
    @pytest.mark.asyncio
    async def test_deny_writes_nothing_and_records_denied_once(
        self,
        db_session,
        dialog_client,
        internal_client,
        management_client,
        shared_identity,
        shared_agent_type,
    ):
        conv, request_id, key = await _pause(db_session, shared_agent_type.id)
        resume = await _resume_of(db_session, request_id)
        skill_name = f"skill-{uuid.uuid4().hex[:8]}"

        dispatch = AsyncMock(return_value="resumed")
        with patch(
            "app.services.conversations.turn_resolution.dispatch_answered_conversation_turn",
            new=dispatch,
        ):
            denied = await dialog_client.post(
                f"/api/v1/conversations/{conv.id}/interventions/{request_id}/respond",
                json={"request_id": str(request_id), "approval_value": False},
            )
        assert denied.status_code == 200, denied.text

        # The denied turn closes as denied with no applied write.
        closed = await _complete(
            internal_client,
            conv.id,
            resume.id,
            outcome=ResumeOutcome.denied.value,
            outcome_turn_content="Understood — nothing was created. Want to adjust?",
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["write_applied"] is False

        # A late/duplicated confirmed write under the same key must be refused.
        late = await management_client.post(
            "/api/v1/internal/management-tools/create_skill",
            json=_skill_payload(skill_name),
            headers={"X-Turn-Idempotency-Key": key},
        )
        assert late.status_code == 409, late.text
        assert late.json()["detail"]["error"] == "resume_terminal_no_write"

        assert (
            await db_session.execute(
                select(Skill).where(Skill.name == skill_name)
            )
        ).scalars().all() == []

        turns = await _agent_turns(db_session, conv.id)
        assert len(turns) == 1
        assert turns[0].content == (
            "Understood — nothing was created. Want to adjust?"
        )

        stored = await _resume_of(db_session, request_id)
        assert stored.state is ResumeState.resolved
        assert stored.resume_outcome is ResumeOutcome.denied
        assert stored.write_applied is False
        assert stored.applied_at is None

        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.is_terminal is True
        assert activity.active_resume_id is None


# ── D. Payload hygiene (serializer boundary) ────────────────────────────────


class TestCheckpointPayloadHygiene:
    _FORBIDDEN_KEY_HINTS = (
        "token",
        "secret",
        "password",
        "api_key",
        "apikey",
        "credential",
        "authorization",
        "client_secret",
        "refresh_token",
    )
    _FORBIDDEN_VALUE_HINTS = ("sk-", "Bearer ", "phn_cl_sk_", "phn_ak_")

    @staticmethod
    def _walk(node: Any):
        if isinstance(node, dict):
            for key, value in node.items():
                yield str(key), value
                yield from TestCheckpointPayloadHygiene._walk(value)
        elif isinstance(node, list):
            for item in node:
                yield from TestCheckpointPayloadHygiene._walk(item)

    @pytest.mark.asyncio
    async def test_persisted_pause_payload_carries_no_credentials(
        self, db_session, internal_client
    ):
        """A real DurableCheckpointSaver envelope round-trips through the CC
        payload store with no credential-shaped key or token-shaped value."""
        from app.db.models.conversations import ConversationSession
        from app.services.conversations.turn_checkpoint_store import (
            ConversationTurnCheckpointStore,
        )

        conv = ConversationSession(status=ConversationStatus.active)
        db_session.add(conv)
        await db_session.flush()
        resume = await ConversationTurnResumeStore().create_or_reuse(conv.id, db_session)
        await db_session.commit()

        envelope = await _real_pause_envelope(conv.id)

        saved = await internal_client.put(
            f"/api/v1/internal/data/conversations/{conv.id}/resume/checkpoint",
            json={"payload": envelope, "schema_version": 1},
        )
        assert saved.status_code == 200, saved.text

        stored = (
            await db_session.execute(
                select(ConversationTurnCheckpoint).where(
                    ConversationTurnCheckpoint.resume_id == resume.id
                )
            )
        ).scalar_one()
        assert stored.payload == envelope, "payload must round-trip unchanged"

        for key, _value in self._walk(stored.payload):
            lowered = key.lower()
            assert not any(hint in lowered for hint in self._FORBIDDEN_KEY_HINTS), (
                f"checkpoint payload leaked a credential-shaped key: {key}"
            )
        flat = repr(stored.payload)
        for hint in self._FORBIDDEN_VALUE_HINTS:
            assert hint not in flat, f"checkpoint payload leaked a secret value ({hint})"

        # The envelope is the framework's typed state — only known metadata keys
        # are added, so no model/agent credentials can ride along.
        assert set(stored.payload) <= {
            "schema_version",
            "format",
            "checkpoint",
            "metadata",
            "pending_writes",
            "agent_type_id",
            "turn_idempotency_key",
            "thread_id",
            "checkpoint_id",
            "checkpoint_ns",
            "parent_checkpoint_id",
        }

        # And the store only ever exposes the opaque payload — never interprets it.
        loaded = await ConversationTurnCheckpointStore().load_payload(resume.id, db_session)
        assert loaded is not None
        assert loaded.payload == envelope


async def _real_pause_envelope(conv_id: uuid.UUID) -> dict[str, Any]:
    """A genuine LangGraph pause envelope produced by DurableCheckpointSaver."""
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    from app.agent_runtime.durable_checkpointer import DurableCheckpointSaver

    class _State(TypedDict):
        value: str

    def _gate(state: _State) -> dict[str, str]:
        answer = interrupt({"request_id": "req-1", "reason": "confirm?"})
        return {"value": str(answer)}

    builder = StateGraph(_State)
    builder.add_node("gate", _gate)
    builder.add_edge(START, "gate")
    builder.add_edge("gate", END)

    captured: list[dict[str, Any]] = []

    class _CaptureTransport:
        async def save_checkpoint(self, conv_id_, payload, **_kwargs):  # noqa: ANN001
            captured.append(payload)
            return type("R", (), {"payload_bytes": 1})()

    saver = DurableCheckpointSaver(
        _CaptureTransport(),  # type: ignore[arg-type]
        conv_id,
        agent_type_id=uuid.uuid4(),
        turn_idempotency_key="idem-hygiene",
    )
    app = builder.compile(checkpointer=saver)
    await app.ainvoke({"value": ""}, {"configurable": {"thread_id": str(conv_id)}})
    await saver.flush()
    await saver.aclose()
    return captured[-1]
