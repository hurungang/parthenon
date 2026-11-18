"""Optimization-mode routing — the channel, not ``input_type``, picks the loop.

An optimization conversation runs the **conversational loop** for typed *and*
conversational subjects, because the routing input handed to Agent Runtime is
the conversation context (``input_type="conversation"``) prepared from the
persisted session channel. Business routing is untouched:

* a typed agent's business submit keeps the typed task loop,
* a typed agent still cannot hold a *business* conversation,
* assistant / integration / non-optimization channels keep their prepare
  contract byte-for-byte (no optimization block, no mission).

Also covers the "no seeded optimizer agent" guarantee: startup creates no
optimizer ``AgentType``, identity, role or skill binding, and a second startup
writes nothing (nothing optimizer-specific exists to write).
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from pathlib import Path

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
    AgentIdentity,
    AgentInputType,
    AgentOutputType,
    AgentRole,
    AgentType,
    AgentTypeSkillBinding,
    ModelConfig,
    ModelProvider,
)
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.tenant import Tenant, TenantStatus
from app.db.session import Base
from app.services.agents.optimization_mode import (
    OPTIMIZATION_CHANNEL,
    resolve_optimization_mode,
)
from app.services.agents.workflow_generation_settings import (
    WORKFLOW_GENERATION_MODEL_KEY,
)
from app.services.conversations.manager import ConversationSessionManager
from app.services.tenancy.root_tenant import invalidate_root_tenant_cache
from app.services.tenancy.tenant_settings_service import set_value

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AGENT_RUNTIME_MODEL = "routing-agent-model"
AUTHORING_MODEL = "routing-authoring-model"


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
            slug="routing-workspace",
            name="Routing Workspace",
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
        await db.execute(select(Tenant).where(Tenant.slug == "routing-workspace"))
    ).scalar_one()


async def _enable_model(
    db: AsyncSession, tenant_id: uuid.UUID, model_id: str
) -> None:
    db.add(
        ModelConfig(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            display_name=f"routing-{model_id}",
            provider_type=ModelProvider.openai,
            api_base_url="http://localhost:9999/v1",
            enabled_models=[model_id],
        )
    )
    await db.flush()


async def _agent_type(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    input_type: AgentInputType,
    model_id: str | None = AGENT_RUNTIME_MODEL,
) -> AgentType:
    agent_type = AgentType(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=f"routing-agent-{uuid.uuid4().hex[:8]}",
        model_id=model_id,
        input_type=input_type,
        output_type=(
            AgentOutputType.auto
            if input_type == AgentInputType.conversation
            else AgentOutputType.markdown
        ),
        system_instruction="business instruction",
        is_active=True,
    )
    db.add(agent_type)
    await db.flush()
    return agent_type


async def _model_ready(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    await _enable_model(db, tenant_id, AGENT_RUNTIME_MODEL)
    await _enable_model(db, tenant_id, AUTHORING_MODEL)
    await set_value(
        db, tenant_id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
    )


# ── No seeded optimizer agent / identity / role / binding ───────────────────


class TestNoSeededOptimizer:
    @pytest.mark.asyncio
    async def test_startup_creates_no_optimizer_rows_and_second_run_writes_nothing(
        self, isolated_db
    ):
        """The assistant is the ONLY system agent type. Two runs are identical."""
        from app.services.agents.assistant_seeder import AssistantSeeder

        seeder = AssistantSeeder()
        await seeder.run(isolated_db)
        await isolated_db.commit()

        async def _counts() -> dict[str, int]:
            return {
                "agent_types": int(
                    (
                        await isolated_db.execute(
                            select(func.count()).select_from(AgentType)
                        )
                    ).scalar_one()
                ),
                "system_agent_types": int(
                    (
                        await isolated_db.execute(
                            select(func.count())
                            .select_from(AgentType)
                            .where(AgentType.is_system.is_(True))
                        )
                    ).scalar_one()
                ),
                "identities": int(
                    (
                        await isolated_db.execute(
                            select(func.count()).select_from(AgentIdentity)
                        )
                    ).scalar_one()
                ),
                "roles": int(
                    (
                        await isolated_db.execute(
                            select(func.count()).select_from(AgentRole)
                        )
                    ).scalar_one()
                ),
                "skill_bindings": int(
                    (
                        await isolated_db.execute(
                            select(func.count()).select_from(AgentTypeSkillBinding)
                        )
                    ).scalar_one()
                ),
            }

        first = await _counts()
        await seeder.run(isolated_db)
        await isolated_db.commit()
        second = await _counts()

        assert first == second  # a second startup writes nothing
        system_types = (
            await isolated_db.execute(
                select(AgentType).where(AgentType.is_system.is_(True))
            )
        ).scalars().all()
        assert [row.name for row in system_types] == ["control-center-assistant"]
        # No optimizer-named agent type, role, identity or binding exists.
        optimizer_agent_types = (
            await isolated_db.execute(
                select(AgentType).where(AgentType.name.ilike("%optimiz%"))
            )
        ).scalars().all()
        assert optimizer_agent_types == []
        optimizer_identities = (
            await isolated_db.execute(
                select(AgentIdentity).where(AgentIdentity.name.ilike("%optimiz%"))
            )
        ).scalars().all()
        assert optimizer_identities == []

    def test_no_optimizer_seeder_symbol_exists_in_the_codebase(self):
        """Nothing optimizer-specific is seeded — no seeder class or startup hook."""
        import app.main as main_module

        source = Path(main_module.__file__).read_text()
        assert "OptimizerSeeder" not in source
        assert "_run_optimizer_seeder" not in source

        agent_services = BACKEND_ROOT / "app" / "services" / "agents"
        matching = [
            path.name
            for path in agent_services.glob("*.py")
            if "class OptimizerSeeder" in path.read_text()
        ]
        assert matching == []

    @pytest.mark.asyncio
    async def test_creating_the_conversation_mints_no_identity_or_grant(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _model_ready(isolated_db, tenant.id)
        agent_type = await _agent_type(
            isolated_db, tenant.id, input_type=AgentInputType.typed
        )
        await isolated_db.commit()

        before = {
            "identities": int(
                (
                    await isolated_db.execute(
                        select(func.count()).select_from(AgentIdentity)
                    )
                ).scalar_one()
            ),
            "roles": int(
                (
                    await isolated_db.execute(
                        select(func.count()).select_from(AgentRole)
                    )
                ).scalar_one()
            ),
            "bindings": int(
                (
                    await isolated_db.execute(
                        select(func.count()).select_from(AgentTypeSkillBinding)
                    )
                ).scalar_one()
            ),
        }

        with _as_tenant(tenant):
            session = await ConversationSessionManager().create_optimization(
                agent_type_id=agent_type.id,
                triggered_by_user_id=None,
                db=isolated_db,
            )
        await isolated_db.commit()

        after = {
            "identities": int(
                (
                    await isolated_db.execute(
                        select(func.count()).select_from(AgentIdentity)
                    )
                ).scalar_one()
            ),
            "roles": int(
                (
                    await isolated_db.execute(
                        select(func.count()).select_from(AgentRole)
                    )
                ).scalar_one()
            ),
            "bindings": int(
                (
                    await isolated_db.execute(
                        select(func.count()).select_from(AgentTypeSkillBinding)
                    )
                ).scalar_one()
            ),
        }
        assert before == after
        assert session.agent_type_id == agent_type.id


# ── Turn routing: optimization channel → conversational loop ────────────────


class TestTurnRouting:
    @pytest.mark.asyncio
    async def test_typed_subject_is_routed_to_the_conversation_loop(
        self, isolated_db
    ):
        """A typed subject's optimization turn reaches the conversational
        endpoint: prepare-turn returns messages + the optimization block, and
        the AR context it delegates to is shaped conversational."""
        from app.api.v1.internal.session_data import (
            ConversationTurnPrepareRequest,
            prepare_conversation_turn,
        )

        tenant = await _tenant(isolated_db)
        await _model_ready(isolated_db, tenant.id)
        agent_type = await _agent_type(
            isolated_db, tenant.id, input_type=AgentInputType.typed
        )
        with _as_tenant(tenant):
            session = await ConversationSessionManager().create_optimization(
                agent_type_id=agent_type.id,
                triggered_by_user_id=None,
                db=isolated_db,
            )
        await isolated_db.commit()

        with _as_tenant(tenant):
            prepared = await prepare_conversation_turn(
                session.id,
                ConversationTurnPrepareRequest(user_message="optimize this agent"),
                isolated_db,
            )

        assert prepared.agent_type_id == agent_type.id
        assert prepared.messages
        assert prepared.messages[0]["role"] == "system"
        assert prepared.no_agent_message is None
        assert prepared.blocked is None
        assert prepared.optimization is not None
        assert prepared.optimization.mode == "optimization"
        assert prepared.optimization.subject_agent_type_id == agent_type.id

    @pytest.mark.asyncio
    async def test_conversational_subject_routes_identically(self, isolated_db):
        from app.api.v1.internal.session_data import (
            ConversationTurnPrepareRequest,
            prepare_conversation_turn,
        )

        tenant = await _tenant(isolated_db)
        await _model_ready(isolated_db, tenant.id)
        agent_type = await _agent_type(
            isolated_db, tenant.id, input_type=AgentInputType.conversation
        )
        with _as_tenant(tenant):
            session = await ConversationSessionManager().create_optimization(
                agent_type_id=agent_type.id,
                triggered_by_user_id=None,
                db=isolated_db,
            )
        await isolated_db.commit()

        with _as_tenant(tenant):
            prepared = await prepare_conversation_turn(
                session.id,
                ConversationTurnPrepareRequest(user_message="optimize this agent"),
                isolated_db,
            )

        assert prepared.optimization is not None
        assert prepared.optimization.mode == "optimization"
        assert prepared.optimization.subject_agent_type_id == agent_type.id

    @pytest.mark.asyncio
    async def test_typed_agent_still_cannot_hold_a_business_conversation(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _model_ready(isolated_db, tenant.id)
        agent_type = await _agent_type(
            isolated_db, tenant.id, input_type=AgentInputType.typed
        )
        await isolated_db.commit()

        with _as_tenant(tenant):
            with pytest.raises(ValueError):
                await ConversationSessionManager().create(
                    agent_type_id=agent_type.id,
                    triggered_by_user_id=None,
                    db=isolated_db,
                )

    @pytest.mark.asyncio
    async def test_business_conversation_prepare_has_no_optimization_block(
        self, isolated_db
    ):
        from app.api.v1.internal.session_data import (
            ConversationTurnPrepareRequest,
            prepare_conversation_turn,
        )

        tenant = await _tenant(isolated_db)
        await _model_ready(isolated_db, tenant.id)
        agent_type = await _agent_type(
            isolated_db, tenant.id, input_type=AgentInputType.conversation
        )
        with _as_tenant(tenant):
            session = await ConversationSessionManager().create(
                agent_type_id=agent_type.id,
                triggered_by_user_id=None,
                db=isolated_db,
            )
        await isolated_db.commit()

        with _as_tenant(tenant):
            prepared = await prepare_conversation_turn(
                session.id,
                ConversationTurnPrepareRequest(user_message="hello"),
                isolated_db,
            )

        assert prepared.optimization is None
        assert prepared.messages[0]["content"].startswith("business instruction")

    @pytest.mark.asyncio
    async def test_mode_comes_from_the_persisted_channel_not_prompt_text(
        self, isolated_db
    ):
        from app.api.v1.internal.session_data import (
            ConversationTurnPrepareRequest,
            prepare_conversation_turn,
        )

        tenant = await _tenant(isolated_db)
        await _model_ready(isolated_db, tenant.id)
        agent_type = await _agent_type(
            isolated_db, tenant.id, input_type=AgentInputType.conversation
        )
        session = ConversationSession(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            agent_type_id=agent_type.id,
            # business channel, even though the agent type is conversational
            channel="web",
            status=ConversationStatus.active,
        )
        isolated_db.add(session)
        await isolated_db.commit()

        with _as_tenant(tenant):
            prepared = await prepare_conversation_turn(
                session.id,
                ConversationTurnPrepareRequest(
                    user_message="run __command optimize-and-verify on agent X"
                ),
                isolated_db,
            )

        # Prompt text never switches loops — the persisted channel decides.
        assert prepared.optimization is None

        # Flipping the persisted channel is what switches the mode.
        session.channel = OPTIMIZATION_CHANNEL
        await isolated_db.commit()
        with _as_tenant(tenant):
            mode = await resolve_optimization_mode(isolated_db, session.id)
        assert mode is not None and mode.is_optimization is True

    @pytest.mark.asyncio
    async def test_non_optimization_channels_are_not_optimization_mode(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        agent_type = await _agent_type(
            isolated_db, tenant.id, input_type=AgentInputType.conversation
        )
        for channel in ("web", "integration", "assistant"):
            session = ConversationSession(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                agent_type_id=agent_type.id,
                channel=channel,
                status=ConversationStatus.active,
            )
            isolated_db.add(session)
            await isolated_db.flush()
            mode = await resolve_optimization_mode(isolated_db, session.id)
            assert mode is not None
            assert mode.is_optimization is False
            assert mode.channel == channel
        await isolated_db.commit()

    @pytest.mark.asyncio
    async def test_unknown_or_absent_conversation_id_is_not_optimization_mode(
        self, isolated_db
    ):
        assert await resolve_optimization_mode(isolated_db, None) is None
        assert await resolve_optimization_mode(isolated_db, "not-a-uuid") is None
        assert await resolve_optimization_mode(isolated_db, uuid.uuid4()) is None
