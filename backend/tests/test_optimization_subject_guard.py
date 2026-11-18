"""Optimization subject guard — scope is inherent, enforced server-side.

An optimization conversation's scope is its own ``agent_type_id``. Every
optimization handler that takes an ``agent_type_id`` must accept only that
subject; any other agent type is refused with the structured ``out_of_scope``
result and **zero reads/writes** for the other agent type. This is what makes
the "one agent only" guarantee real — the mission text is defence in depth, the
guard is the enforcement.

Legacy behaviour is preserved exactly:

* no ``conversation_session_id`` (one-shot ``__command`` runs and other internal
  callers) → unguarded, as today;
* a non-optimization conversation (business/assistant/integration) → unguarded;
* an unknown/unparseable conversation id → unguarded.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.tenant_context import (
    TenantContext,
    reset_current_tenant_context,
    set_current_tenant_context,
)
from app.db.models.agents import (
    AgentInputType,
    AgentOutputType,
    AgentPlan,
    AgentPlanStatus,
    AgentType,
    ModelConfig,
    ModelProvider,
)
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.optimization_live_test import OptimizationLiveTestRequest
from app.db.models.optimized_plan import OptimizedImplementationPlan, OptimizedPlanStatus
from app.db.models.script_registry import ScriptDefinition
from app.db.models.tenant import Tenant, TenantStatus
from app.db.session import Base
from app.services.agents.optimization_mode import (
    OPTIMIZATION_CHANNEL,
    OUT_OF_SCOPE_STATUS,
    require_subject_match,
)
from app.services.tenancy.root_tenant import invalidate_root_tenant_cache

AGENT_RUNTIME_MODEL = "guard-agent-model"
AUTHORING_MODEL = "guard-authoring-model"
SECRET_STEP = "OTHER-AGENT-PLAN-STEP-DO-NOT-LEAK"


# ── Fixtures / helpers ───────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def isolated_db() -> AsyncSession:
    invalidate_root_tenant_cache()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )()
    session.add(
        Tenant(
            id=uuid.uuid4(),
            slug="guard-workspace",
            name="Guard Workspace",
            status=TenantStatus.active,
            is_system_tenant=True,
        )
    )
    await session.commit()
    yield session
    await session.rollback()
    await session.close()
    await engine.dispose()
    invalidate_root_tenant_cache()


@contextmanager
def _as_tenant(tenant: Tenant):
    token = set_current_tenant_context(
        TenantContext(
            tenant_id=tenant.id,
            slug=tenant.slug,
            name=tenant.name,
            is_system_tenant=bool(tenant.is_system_tenant),
        )
    )
    try:
        yield
    finally:
        reset_current_tenant_context(token)


async def _tenant(db: AsyncSession) -> Tenant:
    return (
        await db.execute(select(Tenant).where(Tenant.slug == "guard-workspace"))
    ).scalar_one()


async def _agent_type(db: AsyncSession, tenant_id: uuid.UUID) -> AgentType:
    db.add(
        ModelConfig(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            display_name=f"guard-model-config-{uuid.uuid4().hex[:8]}",
            provider_type=ModelProvider.openai,
            api_base_url="http://localhost:9999/v1",
            enabled_models=[AGENT_RUNTIME_MODEL, AUTHORING_MODEL],
        )
    )
    agent_type = AgentType(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=f"guard-agent-{uuid.uuid4().hex[:8]}",
        model_id=AGENT_RUNTIME_MODEL,
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.markdown,
        is_active=True,
    )
    db.add(agent_type)
    await db.flush()
    return agent_type


async def _session(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_type: AgentType,
    channel: str = OPTIMIZATION_CHANNEL,
) -> ConversationSession:
    session = ConversationSession(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        agent_type_id=agent_type.id,
        channel=channel,
        status=ConversationStatus.active,
    )
    db.add(session)
    await db.flush()
    return session


async def _seed_other_agent_state(
    db: AsyncSession, tenant_id: uuid.UUID, other: AgentType
) -> None:
    """Plan + optimized plan + script for the OTHER agent type."""
    db.add(
        AgentPlan(
            id=uuid.uuid4(),
            agent_type_id=other.id,
            plan_steps=[{"step": SECRET_STEP}],
            generation_status=AgentPlanStatus.success,
        )
    )
    db.add(
        OptimizedImplementationPlan(
            id=uuid.uuid4(),
            agent_type_id=other.id,
            agent_plan_id=uuid.uuid4(),
            status=OptimizedPlanStatus.ready,
            plan_steps=[{"step": SECRET_STEP}],
        )
    )
    db.add(
        ScriptDefinition(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            agent_type_id=other.id,
            name="other-agent-script",
            description="must never be readable from the subject's conversation",
        )
    )
    await db.flush()


def _tenant_ctx(tenant: Tenant) -> TenantContext:
    return TenantContext(
        tenant_id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        is_system_tenant=bool(tenant.is_system_tenant),
    )


def _body(**overrides):
    from app.api.v1.internal.optimization_tools import SystemToolRequest

    payload: dict = {"session_id": "conv-session-1", "tool_args": {}}
    payload.update(overrides)
    return SystemToolRequest(**payload)


# ── The guard primitive ─────────────────────────────────────────────────────


class TestRequireSubjectMatch:
    @pytest.mark.asyncio
    async def test_subject_is_allowed(self, isolated_db):
        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        await isolated_db.commit()

        result = await require_subject_match(isolated_db, session.id, subject.id)
        assert result is None

    @pytest.mark.asyncio
    async def test_any_other_agent_type_is_refused_with_a_structured_result(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        other = await _agent_type(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        await isolated_db.commit()

        result = await require_subject_match(isolated_db, session.id, other.id)
        assert result is not None
        assert result["status"] == OUT_OF_SCOPE_STATUS
        assert result["reason_code"] == OUT_OF_SCOPE_STATUS
        assert str(subject.id) in result["reason"]
        assert result["subject_agent_type_id"] == str(subject.id)

    @pytest.mark.asyncio
    async def test_missing_agent_type_is_refused_in_an_optimization_session(
        self, isolated_db
    ):
        """A guard-needing call with no agent type cannot be 'the subject'."""
        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        await isolated_db.commit()

        result = await require_subject_match(isolated_db, session.id, None)
        assert result is not None
        assert result["status"] == OUT_OF_SCOPE_STATUS

    @pytest.mark.asyncio
    async def test_no_conversation_id_keeps_legacy_behaviour(self, isolated_db):
        tenant = await _tenant(isolated_db)
        other = await _agent_type(isolated_db, tenant.id)
        await isolated_db.commit()

        assert (
            await require_subject_match(isolated_db, None, other.id)
        ) is None
        assert (
            await require_subject_match(isolated_db, "", other.id)
        ) is None
        assert (
            await require_subject_match(isolated_db, "not-a-uuid", other.id)
        ) is None

    @pytest.mark.asyncio
    async def test_business_conversation_keeps_legacy_behaviour(self, isolated_db):
        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        other = await _agent_type(isolated_db, tenant.id)
        business = await _session(isolated_db, tenant.id, subject, channel="web")
        await isolated_db.commit()

        assert (
            await require_subject_match(isolated_db, business.id, other.id)
        ) is None

    @pytest.mark.asyncio
    async def test_unknown_conversation_id_keeps_legacy_behaviour(self, isolated_db):
        tenant = await _tenant(isolated_db)
        other = await _agent_type(isolated_db, tenant.id)
        await isolated_db.commit()

        assert (
            await require_subject_match(isolated_db, uuid.uuid4(), other.id)
        ) is None


# ── Every optimization handler refuses a foreign agent type ─────────────────


class TestHandlersRefuseForeignAgentType:
    @pytest.mark.asyncio
    async def test_get_implementation_plan_refuses_and_leaks_nothing(
        self, isolated_db
    ):
        from app.api.v1.internal.optimization_tools import get_implementation_plan_tool

        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        other = await _agent_type(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        await _seed_other_agent_state(isolated_db, tenant.id, other)
        await isolated_db.commit()

        with _as_tenant(tenant):
            response = await get_implementation_plan_tool(
                _body(
                    agent_type_id=str(other.id),
                    conversation_session_id=str(session.id),
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert response.result["status"] == OUT_OF_SCOPE_STATUS
        assert SECRET_STEP not in str(response.result)

    @pytest.mark.asyncio
    async def test_get_optimized_implementation_plan_refuses(self, isolated_db):
        from app.api.v1.internal.optimization_tools import (
            get_optimized_implementation_plan_tool,
        )

        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        other = await _agent_type(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        await _seed_other_agent_state(isolated_db, tenant.id, other)
        await isolated_db.commit()

        with _as_tenant(tenant):
            response = await get_optimized_implementation_plan_tool(
                _body(
                    agent_type_id=str(other.id),
                    conversation_session_id=str(session.id),
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert response.result["status"] == OUT_OF_SCOPE_STATUS
        assert SECRET_STEP not in str(response.result)

    @pytest.mark.asyncio
    async def test_generate_optimized_plan_writes_nothing_for_the_other_agent_type(
        self, isolated_db
    ):
        from app.api.v1.internal.optimization_tools import generate_optimized_plan_tool

        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        other = await _agent_type(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        await _seed_other_agent_state(isolated_db, tenant.id, other)
        await isolated_db.commit()
        before = int(
            (
                await isolated_db.execute(
                    select(func.count()).select_from(OptimizedImplementationPlan)
                )
            ).scalar_one()
        )

        with _as_tenant(tenant):
            response = await generate_optimized_plan_tool(
                _body(
                    agent_type_id=str(other.id),
                    conversation_session_id=str(session.id),
                    tool_args={"steps": [{"step": "tampered"}]},
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert response.result["status"] == OUT_OF_SCOPE_STATUS
        after = int(
            (
                await isolated_db.execute(
                    select(func.count()).select_from(OptimizedImplementationPlan)
                )
            ).scalar_one()
        )
        assert after == before

    @pytest.mark.asyncio
    async def test_generate_script_writes_nothing_for_the_other_agent_type(
        self, isolated_db
    ):
        from app.api.v1.internal.optimization_tools import generate_script_tool

        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        other = await _agent_type(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        await _seed_other_agent_state(isolated_db, tenant.id, other)
        await isolated_db.commit()
        before = int(
            (
                await isolated_db.execute(
                    select(func.count()).select_from(ScriptDefinition)
                )
            ).scalar_one()
        )

        with _as_tenant(tenant):
            response = await generate_script_tool(
                _body(
                    agent_type_id=str(other.id),
                    conversation_session_id=str(session.id),
                    tool_args={
                        "name": "tampered",
                        "python_source": "def run(context, tools):\n    return {}\n",
                    },
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert response.result["status"] == OUT_OF_SCOPE_STATUS
        after = int(
            (
                await isolated_db.execute(
                    select(func.count()).select_from(ScriptDefinition)
                )
            ).scalar_one()
        )
        assert after == before

    @pytest.mark.asyncio
    async def test_execute_script_refuses_before_any_sandbox_run(
        self, isolated_db
    ):
        from app.api.v1.internal.optimization_tools import execute_script_tool

        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        other = await _agent_type(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        await _seed_other_agent_state(isolated_db, tenant.id, other)
        await isolated_db.commit()

        with _as_tenant(tenant):
            response = await execute_script_tool(
                _body(
                    agent_type_id=str(other.id),
                    conversation_session_id=str(session.id),
                    tool_args={
                        "python_source": "def run(context, tools):\n    return {}\n",
                        "input": {},
                    },
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert response.result["status"] == OUT_OF_SCOPE_STATUS

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handler_name",
        ["list_scripts_tool", "get_scripts_tool"],
    )
    async def test_script_listings_refuse(self, isolated_db, handler_name):
        from app.api.v1.internal import optimization_tools

        handler = getattr(optimization_tools, handler_name)
        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        other = await _agent_type(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        await _seed_other_agent_state(isolated_db, tenant.id, other)
        await isolated_db.commit()

        with _as_tenant(tenant):
            response = await handler(
                _body(
                    agent_type_id=str(other.id),
                    conversation_session_id=str(session.id),
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert response.result["status"] == OUT_OF_SCOPE_STATUS
        assert "other-agent-script" not in str(response.result)

    @pytest.mark.asyncio
    async def test_get_script_refuses(self, isolated_db):
        from app.api.v1.internal.optimization_tools import get_script_tool

        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        other = await _agent_type(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        await _seed_other_agent_state(isolated_db, tenant.id, other)
        await isolated_db.commit()

        with _as_tenant(tenant):
            response = await get_script_tool(
                _body(
                    agent_type_id=str(other.id),
                    conversation_session_id=str(session.id),
                    tool_args={"name": "other-agent-script"},
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert response.result["status"] == OUT_OF_SCOPE_STATUS
        assert "other-agent-script" not in str(response.result)

    @pytest.mark.asyncio
    async def test_get_execution_log_refuses(self, isolated_db):
        from app.api.v1.internal.optimization_tools import get_execution_log_tool

        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        other = await _agent_type(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        await isolated_db.commit()

        with _as_tenant(tenant):
            response = await get_execution_log_tool(
                _body(
                    agent_type_id=str(other.id),
                    conversation_session_id=str(session.id),
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert response.result["status"] == OUT_OF_SCOPE_STATUS

    @pytest.mark.asyncio
    async def test_request_live_test_refuses_and_writes_no_ledger_row(
        self, isolated_db
    ):
        from app.api.v1.internal.system_tools import request_live_test_tool

        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        other = await _agent_type(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        await isolated_db.commit()
        before = int(
            (
                await isolated_db.execute(
                    select(func.count()).select_from(OptimizationLiveTestRequest)
                )
            ).scalar_one()
        )

        with _as_tenant(tenant):
            response = await request_live_test_tool(
                _body(
                    agent_type_id=str(other.id),
                    conversation_session_id=str(session.id),
                    # A live test now names a SAVED script version (never an
                    # operation list); the subject guard refuses before the
                    # ledger is touched either way.
                    tool_args={
                        "script_version_id": str(uuid.uuid4()),
                        "reason": "tamper",
                    },
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert response.result["status"] == OUT_OF_SCOPE_STATUS
        after = int(
            (
                await isolated_db.execute(
                    select(func.count()).select_from(OptimizationLiveTestRequest)
                )
            ).scalar_one()
        )
        assert after == before

    @pytest.mark.asyncio
    async def test_request_live_test_outside_an_optimization_conversation_is_refused(
        self, isolated_db
    ):
        """No conversation id (or a business conversation) can never mint a
        live test — the ledger only exists inside optimization mode."""
        from app.api.v1.internal.system_tools import request_live_test_tool

        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        business = await _session(isolated_db, tenant.id, subject, channel="web")
        await isolated_db.commit()

        # A live test now names a SAVED script version (never an operation list).
        operations = {
            "script_version_id": str(uuid.uuid4()),
            "reason": "tamper",
        }
        with _as_tenant(tenant):
            no_session = await request_live_test_tool(
                _body(agent_type_id=str(subject.id), tool_args=operations),
                _tenant_ctx(tenant),
                isolated_db,
            )
            business_response = await request_live_test_tool(
                _body(
                    agent_type_id=str(subject.id),
                    conversation_session_id=str(business.id),
                    tool_args=operations,
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert no_session.result["status"] == "refused"
        assert no_session.result["reason_code"] == OUT_OF_SCOPE_STATUS
        assert business_response.result["status"] == "refused"
        assert business_response.result["reason_code"] == OUT_OF_SCOPE_STATUS
        assert (
            int(
                (
                    await isolated_db.execute(
                        select(func.count()).select_from(OptimizationLiveTestRequest)
                    )
                ).scalar_one()
            )
            == 0
        )


# ── The subject itself is allowed (no over-refusal) ─────────────────────────


class TestSubjectIsAllowed:
    @pytest.mark.asyncio
    async def test_own_agent_type_reads_its_own_plan(self, isolated_db):
        from app.api.v1.internal.optimization_tools import get_implementation_plan_tool

        tenant = await _tenant(isolated_db)
        subject = await _agent_type(isolated_db, tenant.id)
        session = await _session(isolated_db, tenant.id, subject)
        await _seed_other_agent_state(isolated_db, tenant.id, subject)
        await isolated_db.commit()

        with _as_tenant(tenant):
            response = await get_implementation_plan_tool(
                _body(
                    agent_type_id=str(subject.id),
                    conversation_session_id=str(session.id),
                ),
                _tenant_ctx(tenant),
                isolated_db,
            )

        assert response.result.get("status") != OUT_OF_SCOPE_STATUS
        assert response.result["agent_type_id"] == str(subject.id)
        assert response.result["steps"] == [{"step": SECRET_STEP}]

    @pytest.mark.asyncio
    async def test_unscoped_command_path_is_unchanged(self, isolated_db):
        """A ``__command`` run (no conversation id) reads any agent type it
        names — exactly as before this change."""
        from app.api.v1.internal.optimization_tools import get_implementation_plan_tool

        tenant = await _tenant(isolated_db)
        other = await _agent_type(isolated_db, tenant.id)
        await _seed_other_agent_state(isolated_db, tenant.id, other)
        await isolated_db.commit()

        with _as_tenant(tenant):
            response = await get_implementation_plan_tool(
                _body(agent_type_id=str(other.id)),
                _tenant_ctx(tenant),
                isolated_db,
            )
        assert response.result.get("status") != OUT_OF_SCOPE_STATUS
        assert response.result["agent_type_id"] == str(other.id)
