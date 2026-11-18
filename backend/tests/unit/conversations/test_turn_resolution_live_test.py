"""Answer path — consume the live-test approval once, run, then resume.

The operator's answer to a live-test approval is handled by
``prepare_live_test_decision`` in the same transaction as the stored response,
and the approved run happens **after** the answer commits and **before** the
single resume is dispatched — so the paused tool returns what actually ran.

Guarantees proved here:

* an ordinary question/approval has no linked ledger row → ``handled=False``
  and the existing ask/decide chain runs untouched;
* approval ⇒ ``approved`` + this answer owns the one execution attempt;
* denial ⇒ ``denied``, nothing runs, the denial resume is dispatched;
* an overdue approval is closed ``expired`` and the pause settles as
  ``unresumable/expired`` — no execution, no resume;
* a replayed/re-delivered approval finds a terminal row and only delivers the
  stored outcome (never a second execution);
* the endpoint order is claim → run → resume, and a duplicate answer never
  re-executes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.resource_types import RT_AGENT_TRAILS
from app.api.deps import require_permission
from app.db.models.agents import AgentInputType, AgentOutputType, AgentType
from app.db.models.conversation_turn_resume import ConversationTurnResume
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.identity import Identity
from app.db.models.intervene import (
    InterveneRequest,
    InterveneRequestStatus,
    InterventionType,
)
from app.db.models.optimization_live_test import (
    OptimizationLiveTestRequest,
    OptimizationLiveTestStatus,
)
from app.db.models.tenant import Tenant, TenantStatus
from app.db.session import Base, get_db
from app.main import create_app
from app.services.conversations import turn_resolution
from app.services.conversations.turn_resolution import (
    REASON_EXPIRED,
    prepare_live_test_decision,
)
from app.services.conversations.turn_resume_store import ConversationTurnResumeStore

NOW = datetime.now(timezone.utc)
PERMITTED_TOOL = "crm____searchCustomers"


async def _seed(
    db: AsyncSession,
    *,
    status: OptimizationLiveTestStatus = OptimizationLiveTestStatus.pending,
    expires_in: timedelta = timedelta(minutes=10),
    with_resume: bool = True,
):
    agent_type = AgentType(
        id=uuid.uuid4(),
        name=f"answer-agent-{uuid.uuid4().hex[:8]}",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.markdown,
        is_active=True,
    )
    db.add(agent_type)
    await db.flush()
    session = ConversationSession(
        id=uuid.uuid4(),
        agent_type_id=agent_type.id,
        channel="optimization",
        status=ConversationStatus.active,
    )
    db.add(session)
    await db.flush()
    intervene = InterveneRequest(
        id=uuid.uuid4(),
        agent_type_id=agent_type.id,
        intervention_type=InterventionType.approval,
        reason="Live test approval",
        conversation_session_id=session.id,
        expires_at=NOW + expires_in,
    )
    db.add(intervene)
    await db.flush()
    row = OptimizationLiveTestRequest(
        id=uuid.uuid4(),
        conversation_session_id=session.id,
        target_agent_type_id=agent_type.id,
        intervene_request_id=intervene.id,
        status=status,
        requested_operations=[
            {
                "tool_name": PERMITTED_TOOL,
                "arguments": {"q": "ada"},
                "purpose": "lookup",
            }
        ],
        expires_at=NOW + expires_in,
    )
    db.add(row)
    resume = None
    if with_resume:
        resume = await ConversationTurnResumeStore().create_or_reuse(
            session.id,
            db,
            intervene_request_id=intervene.id,
            expires_at=NOW + expires_in,
        )
        row.resume_id = resume.id
    await db.flush()
    return agent_type, session, intervene, row, resume


class TestPrepareLiveTestDecision:
    @pytest.mark.asyncio
    async def test_an_ordinary_intervention_is_not_handled(
        self, db_session: AsyncSession
    ):
        agent_type = AgentType(
            id=uuid.uuid4(),
            name=f"plain-agent-{uuid.uuid4().hex[:8]}",
            input_type=AgentInputType.conversation,
            output_type=AgentOutputType.auto,
            is_active=True,
        )
        db_session.add(agent_type)
        await db_session.flush()
        session = ConversationSession(
            id=uuid.uuid4(),
            agent_type_id=agent_type.id,
            channel="web",
            status=ConversationStatus.active,
        )
        db_session.add(session)
        await db_session.flush()
        intervene = InterveneRequest(
            id=uuid.uuid4(),
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.text,
            reason="Which customer?",
            conversation_session_id=session.id,
        )
        db_session.add(intervene)
        await db_session.flush()

        decision = await prepare_live_test_decision(
            db_session, intervene, approved=None
        )

        assert decision.handled is False
        assert decision.request_id is None
        assert decision.should_execute is False
        assert decision.resume_payload == {}

    @pytest.mark.asyncio
    async def test_approval_claims_the_single_execution(self, db_session: AsyncSession):
        _a, _s, intervene, row, _r = await _seed(db_session)

        decision = await prepare_live_test_decision(
            db_session, intervene, approved=True
        )

        assert decision.handled is True
        assert decision.request_id == row.id
        assert decision.status == "approved"
        assert decision.should_execute is True
        assert decision.expired is False
        await db_session.refresh(row)
        assert row.status is OptimizationLiveTestStatus.approved
        # Consent only — no evidence yet.
        assert row.executed_operations is None
        assert row.execution_started_at is None

    @pytest.mark.asyncio
    async def test_denial_runs_nothing_and_carries_the_stored_outcome(
        self, db_session: AsyncSession
    ):
        _a, _s, intervene, row, _r = await _seed(db_session)

        decision = await prepare_live_test_decision(
            db_session, intervene, approved=False
        )

        assert decision.handled is True
        assert decision.status == "denied"
        assert decision.should_execute is False
        assert decision.resume_payload["live_test_status"] == "denied"
        await db_session.refresh(row)
        assert row.status is OptimizationLiveTestStatus.denied
        assert row.executed_operations is None

    @pytest.mark.asyncio
    async def test_no_approval_value_is_treated_as_a_denial(
        self, db_session: AsyncSession
    ):
        _a, _s, intervene, row, _r = await _seed(db_session)

        decision = await prepare_live_test_decision(
            db_session, intervene, approved=None
        )

        assert decision.handled is True
        assert decision.status == "denied"

    @pytest.mark.asyncio
    async def test_overdue_approval_is_expired_and_settles_the_pause(
        self, db_session: AsyncSession
    ):
        _a, session, intervene, row, resume = await _seed(
            db_session, expires_in=timedelta(minutes=-5)
        )
        # The resume window is closed as well.
        resume.expires_at = NOW - timedelta(minutes=5)
        await db_session.flush()

        with patch.object(
            turn_resolution, "push_outcome_message", AsyncMock()
        ):
            decision = await prepare_live_test_decision(
                db_session, intervene, approved=True
            )

        assert decision.handled is True
        assert decision.expired is True
        assert decision.should_execute is False
        assert decision.status == "expired"
        await db_session.refresh(row)
        assert row.status is OptimizationLiveTestStatus.expired
        await db_session.refresh(intervene)
        assert intervene.status is InterveneRequestStatus.expired

    @pytest.mark.asyncio
    async def test_a_terminal_request_returns_the_stored_outcome(
        self, db_session: AsyncSession
    ):
        _a, _s, intervene, row, _r = await _seed(
            db_session, status=OptimizationLiveTestStatus.executed
        )
        row.executed_operations = [
            {"tool_name": PERMITTED_TOOL, "status": "success", "result_summary": "{}"}
        ]
        row.execution_started_at = NOW
        row.execution_finished_at = NOW
        await db_session.flush()

        decision = await prepare_live_test_decision(
            db_session, intervene, approved=True
        )

        assert decision.handled is True
        assert decision.should_execute is False
        assert decision.status == "executed"
        assert decision.resume_payload["executed_operations"] == [
            {"tool_name": PERMITTED_TOOL, "status": "success", "result_summary": "{}"}
        ]

    @pytest.mark.asyncio
    async def test_an_expired_terminal_request_refuses_the_late_answer(
        self, db_session: AsyncSession
    ):
        _a, _s, intervene, row, _r = await _seed(
            db_session, status=OptimizationLiveTestStatus.expired
        )

        decision = await prepare_live_test_decision(
            db_session, intervene, approved=True
        )

        assert decision.expired is True
        assert decision.should_execute is False
        assert decision.status == "expired"

    @pytest.mark.asyncio
    async def test_the_expiry_reason_is_the_shared_terminal_vocabulary(self):
        assert REASON_EXPIRED == "expired"
        assert turn_resolution.message_key_for_reason(REASON_EXPIRED) == (
            "chat.resume.expired"
        )


# ── Endpoint ordering: claim → run → resume ─────────────────────────────────


@pytest_asyncio.fixture
async def respond_env():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        session.add(
            Tenant(
                id=uuid.uuid4(),
                slug="respond-workspace",
                name="Respond",
                status=TenantStatus.active,
                is_system_tenant=True,
            )
        )
        operator = Identity(
            id=uuid.uuid4(),
            subject="respond-operator",
            display_name="Operator",
        )
        session.add(operator)
        await session.commit()
        operator_id = operator.id

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "respond-operator"}
        request.state.identity_id = operator_id
        return await call_next(request)

    async def passthrough_resolution(self, request, call_next):
        request.state.tenancy_enabled = False
        return await call_next(request)

    from app.middleware.auth import JWTAuthMiddleware
    from app.middleware.tenant_resolution import TenantResolutionMiddleware

    app = create_app()
    app.dependency_overrides[require_permission(RT_AGENT_TRAILS, "read")] = (
        lambda: {"sub": "respond-operator", "roles": ["admin"]}
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch), patch.object(
        TenantResolutionMiddleware, "dispatch", passthrough_resolution
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield {"client": client, "session_factory": SessionLocal}

    await engine.dispose()


class TestRespondOrdering:
    @pytest.mark.asyncio
    async def test_approve_runs_the_test_before_dispatching_the_resume(
        self, respond_env
    ):
        factory = respond_env["session_factory"]
        async with factory() as session:
            agent_type, conv, intervene, row, _resume = await _seed(session)
            await session.commit()
            session_id, request_id = conv.id, intervene.id

        order: list[str] = []

        async def _fake_execute(db, request_id, *, tenant_context=None):  # noqa: ANN001
            order.append("execute")
            return {
                "live_test_status": "executed",
                "live_test_request_id": str(request_id),
                "executed_operations": [
                    {"tool_name": PERMITTED_TOOL, "status": "success"}
                ],
            }

        async def _fake_dispatch(db, intervene_request, advance, value, *, tenant_context=None):  # noqa: ANN001
            order.append("resume")
            assert value["live_test_status"] == "executed"
            assert value["executed_operations"]

        with patch.object(
            turn_resolution, "execute_approved_live_test", _fake_execute
        ), patch.object(
            turn_resolution, "dispatch_answered_conversation_turn", _fake_dispatch
        ):
            response = await respond_env["client"].post(
                f"/api/v1/conversations/{session_id}/interventions/{request_id}/respond",
                json={"request_id": str(request_id), "approval_value": True},
            )

        assert response.status_code == 200, response.text
        assert order == ["execute", "resume"]

        async with factory() as session:
            refreshed = await session.get(OptimizationLiveTestRequest, row.id)
            assert refreshed.status is OptimizationLiveTestStatus.approved

    @pytest.mark.asyncio
    async def test_duplicate_answer_never_reexecutes(self, respond_env):
        factory = respond_env["session_factory"]
        async with factory() as session:
            _a, conv, intervene, _row, _resume = await _seed(session)
            await session.commit()
            session_id, request_id = conv.id, intervene.id

        execute = AsyncMock(
            return_value={"live_test_status": "executed", "executed_operations": []}
        )
        dispatch = AsyncMock()

        with patch.object(
            turn_resolution, "execute_approved_live_test", execute
        ), patch.object(
            turn_resolution, "dispatch_answered_conversation_turn", dispatch
        ):
            first = await respond_env["client"].post(
                f"/api/v1/conversations/{session_id}/interventions/{request_id}/respond",
                json={"request_id": str(request_id), "approval_value": True},
            )
            second = await respond_env["client"].post(
                f"/api/v1/conversations/{session_id}/interventions/{request_id}/respond",
                json={"request_id": str(request_id), "approval_value": True},
            )

        assert first.status_code == 200, first.text
        # The stored answer wins: the second response cannot respond again.
        assert second.status_code == 400
        assert execute.await_count == 1
        assert dispatch.await_count == 1

    @pytest.mark.asyncio
    async def test_deny_dispatches_the_denial_resume_only(self, respond_env):
        factory = respond_env["session_factory"]
        async with factory() as session:
            _a, conv, intervene, row, _resume = await _seed(session)
            await session.commit()
            session_id, request_id = conv.id, intervene.id

        execute = AsyncMock()
        dispatch = AsyncMock()

        with patch.object(
            turn_resolution, "execute_approved_live_test", execute
        ), patch.object(
            turn_resolution, "dispatch_answered_conversation_turn", dispatch
        ):
            response = await respond_env["client"].post(
                f"/api/v1/conversations/{session_id}/interventions/{request_id}/respond",
                json={"request_id": str(request_id), "approval_value": False},
            )

        assert response.status_code == 200, response.text
        execute.assert_not_awaited()
        dispatch.assert_awaited_once()
        value = dispatch.await_args.args[3]
        assert value["live_test_status"] == "denied"

        async with factory() as session:
            refreshed = await session.get(OptimizationLiveTestRequest, row.id)
            assert refreshed.status is OptimizationLiveTestStatus.denied
            assert refreshed.executed_operations is None
