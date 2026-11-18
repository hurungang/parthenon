"""Optimization-mode context — the mission replaces the business instruction.

An optimization conversation is a ``ConversationSession`` on the subject agent
type with ``channel="optimization"``. Its turn context (built by
``GET /internal/agents/agent-types/{id}/context`` with ``conv_session_id``) must:

* carry the **optimization mission** instead of the agent's business system
  instruction, SOP content and skills,
* expose the authoring + self-context optimization tools **plus**
  ``request_live_test`` and **no** business MCP/decision tools,
* run on the workspace optimizer model (explicit selection else the
  plan-authoring model) — never the agent's runtime model — and fail closed
  with ``412 optimizer_model_unavailable`` when no usable model exists,
* suppress the typed output contract (conversational shape),
* keep the subject's own identity, role and grants (identity parity — no
  elevated, service, shared or bridging identity),
* leave every unscoped caller (normal run, ``__command``, business
  conversation, assistant, integration) byte-identical.

Nothing in this module is a prompt-only guarantee: the server-side mode is the
session's persisted channel, and the guard is ``resolve_optimization_mode``.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.tenant_context import (
    TenantContext,
    reset_current_tenant_context,
    set_current_tenant_context,
)
from app.db.models.agents import (
    AgentIdentity,
    AgentIdentityType,
    AgentInputType,
    AgentOutputType,
    AgentRole,
    AgentRoleIdentity,
    AgentRoleSkill,
    AgentType,
    AgentTypeSkillBinding,
    ModelConfig,
    ModelProvider,
)
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.mcp_hub import McpServer, McpTool
from app.db.models.skills import Skill, SkillToolBinding
from app.db.models.tenant import Tenant, TenantStatus
from app.db.session import Base
from app.services.agents.builtin_skills import (
    REQUEST_LIVE_TEST_TOOL,
    get_inherent_tool_names,
    get_inherent_tool_names_for,
    get_optimization_mode_tool_names,
)
from app.services.agents.command_prompts import OPTIMIZE_AND_VERIFY_SLUG
from app.services.agents.optimization_mode import OPTIMIZATION_CHANNEL
from app.services.agents.tool_naming import build_tool_name
from app.services.agents.workflow_generation_settings import (
    WORKFLOW_GENERATION_MODEL_KEY,
)
from app.services.tenancy.root_tenant import invalidate_root_tenant_cache
from app.services.tenancy.tenant_settings_service import set_value

AGENT_RUNTIME_MODEL = "agent-runtime-model"
AUTHORING_MODEL = "authoring-model"
OPTIMIZER_MODEL = "optimizer-model"
STALE_MODEL = "removed-model"
BUSINESS_TOOL = "crm/searchCustomers"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def isolated_db() -> AsyncSession:
    """Fresh in-memory engine + root tenant per test."""
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
            slug="mode-workspace",
            name="Mode Workspace",
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
    from sqlalchemy import select

    return (
        await db.execute(select(Tenant).where(Tenant.slug == "mode-workspace"))
    ).scalar_one()


async def _enable_model(
    db: AsyncSession, tenant_id: uuid.UUID, model_id: str
) -> ModelConfig:
    config = ModelConfig(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        display_name=f"mode-{model_id}-{uuid.uuid4().hex[:6]}",
        provider_type=ModelProvider.openai,
        api_base_url="http://localhost:9999/v1",
        encrypted_api_key="gAAAAAB-encrypted-secret-blob",
        enabled_models=[model_id],
    )
    db.add(config)
    await db.flush()
    return config


async def _subject(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    input_type: AgentInputType = AgentInputType.typed,
    role_id: uuid.UUID | None = None,
    identity_id: uuid.UUID | None = None,
    output_data_type_id: uuid.UUID | None = None,
) -> AgentType:
    agent_type = AgentType(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=f"mode-agent-{uuid.uuid4().hex[:8]}",
        description="mode subject",
        model_id=AGENT_RUNTIME_MODEL,
        input_type=input_type,
        output_type=(
            AgentOutputType.auto
            if input_type == AgentInputType.conversation
            else AgentOutputType.markdown
        ),
        system_instruction="You are the BUSINESS instruction for this agent.",
        role_id=role_id,
        identity_id=identity_id,
        output_data_type_id=output_data_type_id,
        is_active=True,
    )
    db.add(agent_type)
    await db.flush()
    return agent_type


async def _business_grant(
    db: AsyncSession, tenant_id: uuid.UUID, agent_type: AgentType
) -> tuple[AgentRole, AgentIdentity, str]:
    """Give the subject a role, an identity and one real MCP tool grant.

    Returns ``(role, identity, canonical_tool_name)`` — the exact envelope a
    business run uses and an optimization turn must inherit unchanged.
    """
    identity = AgentIdentity(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=f"mode-identity-{uuid.uuid4().hex[:8]}",
        identity_type=AgentIdentityType.realm_user,
        status="active",
    )
    role = AgentRole(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=f"mode-role-{uuid.uuid4().hex[:8]}",
    )
    server = McpServer(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="CRM",
        slug="crm",
        base_url="http://localhost:9999",
    )
    tool = McpTool(
        id=uuid.uuid4(),
        server_id=server.id,
        tenant_id=tenant_id,
        name=BUSINESS_TOOL,
        original_name="searchCustomers",
        is_active=True,
    )
    skill = Skill(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=f"mode-skill-{uuid.uuid4().hex[:8]}",
        is_active=True,
    )
    db.add_all([identity, role, server, tool, skill])
    await db.flush()
    db.add_all(
        [
            AgentRoleIdentity(role_id=role.id, identity_id=identity.id),
            AgentRoleSkill(role_id=role.id, skill_id=skill.id),
            SkillToolBinding(skill_id=skill.id, tool_id=tool.id, order=0),
            AgentTypeSkillBinding(
                agent_type_id=agent_type.id, skill_id=skill.id, order=0
            ),
        ]
    )
    agent_type.role_id = role.id
    agent_type.identity_id = identity.id
    await db.flush()
    return role, identity, build_tool_name("crm", "searchCustomers")


async def _optimization_session(
    db: AsyncSession, tenant_id: uuid.UUID, agent_type_id: uuid.UUID
) -> ConversationSession:
    session = ConversationSession(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        agent_type_id=agent_type_id,
        channel=OPTIMIZATION_CHANNEL,
        status=ConversationStatus.active,
    )
    db.add(session)
    await db.flush()
    return session


async def _business_session(
    db: AsyncSession, tenant_id: uuid.UUID, agent_type_id: uuid.UUID
) -> ConversationSession:
    session = ConversationSession(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        agent_type_id=agent_type_id,
        channel="web",
        status=ConversationStatus.active,
    )
    db.add(session)
    await db.flush()
    return session


async def _context(db: AsyncSession, agent_type_id: uuid.UUID, **kwargs):
    from app.api.v1.internal.agent_data import get_agent_context

    return await get_agent_context(agent_type_id=agent_type_id, db=db, **kwargs)


# ── Mission replaces the business instruction / SOP / skills ────────────────


class TestMissionReplacesBusinessInstruction:
    @pytest.mark.asyncio
    async def test_optimization_turn_gets_the_mission_not_the_business_prompt(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        await _enable_model(isolated_db, tenant.id, AUTHORING_MODEL)
        await set_value(
            isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
        )
        agent_type = await _subject(isolated_db, tenant.id, input_type=AgentInputType.conversation)
        session = await _optimization_session(
            isolated_db, tenant.id, agent_type.id
        )
        await isolated_db.commit()

        with _as_tenant(tenant):
            context = await _context(
                isolated_db, agent_type.id, conv_session_id=session.id
            )

        assert context.system_instruction
        assert "BUSINESS instruction" not in context.system_instruction
        # The mission is the stored optimize-and-verify command prompt with the
        # subject interpolated, plus the conversational rules.
        assert str(agent_type.id) in context.system_instruction
        assert "{agent_type_id}" not in context.system_instruction
        assert "optimization conversation" in context.system_instruction.lower()
        assert "replay" in context.system_instruction.lower()
        # An explicit operator request is a VALID live-test reason: the mission
        # must not tell the optimizer to refuse it merely because replay passed.
        mission = context.system_instruction.lower()
        assert "explicitly asks for a live verification" in mission
        assert "do not refuse an explicit operator request" in mission
        # Business SOP / MCP context is not composed at all.
        assert context.sop_content is None
        assert context.mcp_session_context is None

    @pytest.mark.asyncio
    async def test_optimization_turn_omits_the_bound_business_skills(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        await _enable_model(isolated_db, tenant.id, AUTHORING_MODEL)
        await set_value(
            isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
        )
        agent_type = await _subject(isolated_db, tenant.id)
        _role, _identity, business_tool = await _business_grant(
            isolated_db, tenant.id, agent_type
        )
        session = await _optimization_session(isolated_db, tenant.id, agent_type.id)
        business = await _business_session(isolated_db, tenant.id, agent_type.id)
        await isolated_db.commit()

        with _as_tenant(tenant):
            business_ctx = await _context(
                isolated_db, agent_type.id, conv_session_id=business.id
            )
            optimization_ctx = await _context(
                isolated_db, agent_type.id, conv_session_id=session.id
            )

        business_skill_names = {s.name for s in business_ctx.skills}
        optimization_skill_names = {s.name for s in optimization_ctx.skills}
        assert any(name.startswith("mode-skill-") for name in business_skill_names)
        assert not any(name.startswith("mode-skill-") for name in optimization_skill_names)
        # The inherent (zero-binding) skills survive — they are not business skills.
        assert "self-context" in optimization_skill_names
        # The business grant is visible to a business run and absent from the loop.
        assert business_tool in business_ctx.allowed_tools
        assert business_tool not in optimization_ctx.allowed_tools


# ── Tool set inside optimization mode ───────────────────────────────────────


class TestOptimizationToolSet:
    @pytest.mark.asyncio
    async def test_optimization_tools_present_and_no_business_tools(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        await _enable_model(isolated_db, tenant.id, AUTHORING_MODEL)
        await set_value(
            isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
        )
        agent_type = await _subject(isolated_db, tenant.id)
        _role, _identity, business_tool = await _business_grant(
            isolated_db, tenant.id, agent_type
        )
        session = await _optimization_session(isolated_db, tenant.id, agent_type.id)
        await isolated_db.commit()

        with _as_tenant(tenant):
            context = await _context(
                isolated_db, agent_type.id, conv_session_id=session.id
            )

        allowed = set(context.allowed_tools)
        # The full authoring + self-context set (not the reduced non-optimize one).
        for bare in get_inherent_tool_names():
            assert build_tool_name("system", bare) in allowed, bare
        # request_live_test is available ONLY in optimization mode.
        for bare in get_optimization_mode_tool_names():
            assert build_tool_name("system", bare) in allowed
        assert build_tool_name("system", REQUEST_LIVE_TEST_TOOL) in allowed
        # Every business MCP/decision tool is excluded from the loop.
        assert business_tool not in allowed
        assert not any(name.startswith("decision____") for name in allowed)

    @pytest.mark.asyncio
    async def test_request_live_test_is_registered_and_optimization_only(
        self, isolated_db
    ):
        """The optimization-only tool is registry-validated and never leaks into
        a normal run — the gated set is strict."""
        from app.services.agents.system_tool_registry import SystemToolRegistry

        assert REQUEST_LIVE_TEST_TOOL in SystemToolRegistry.get_names()
        assert REQUEST_LIVE_TEST_TOOL not in get_inherent_tool_names()
        assert REQUEST_LIVE_TEST_TOOL not in get_inherent_tool_names_for(True)

        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        agent_type = await _subject(isolated_db, tenant.id)
        await isolated_db.commit()

        with _as_tenant(tenant):
            context = await _context(isolated_db, agent_type.id)

        assert build_tool_name("system", REQUEST_LIVE_TEST_TOOL) not in set(
            context.allowed_tools
        )


# ── Model selection inside optimization mode ────────────────────────────────


class TestOptimizationModelSelection:
    @pytest.mark.asyncio
    async def test_optimizer_model_is_used_instead_of_the_agent_runtime_model(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        optimizer_config = await _enable_model(
            isolated_db, tenant.id, OPTIMIZER_MODEL
        )
        await set_value(
            isolated_db, tenant.id, "optimizer_model_id", OPTIMIZER_MODEL
        )
        agent_type = await _subject(isolated_db, tenant.id)
        session = await _optimization_session(isolated_db, tenant.id, agent_type.id)
        await isolated_db.commit()

        with _as_tenant(tenant):
            context = await _context(
                isolated_db, agent_type.id, conv_session_id=session.id
            )

        assert context.model_id == OPTIMIZER_MODEL
        assert context.model_config_id == optimizer_config.id

    @pytest.mark.asyncio
    async def test_unset_optimizer_model_inherits_the_authoring_model(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        authoring_config = await _enable_model(
            isolated_db, tenant.id, AUTHORING_MODEL
        )
        await set_value(
            isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
        )
        agent_type = await _subject(isolated_db, tenant.id)
        session = await _optimization_session(isolated_db, tenant.id, agent_type.id)
        await isolated_db.commit()

        with _as_tenant(tenant):
            context = await _context(
                isolated_db, agent_type.id, conv_session_id=session.id
            )

        assert context.model_id == AUTHORING_MODEL
        assert context.model_config_id == authoring_config.id

    @pytest.mark.asyncio
    async def test_no_usable_optimizer_model_fails_closed_412(self, isolated_db):
        tenant = await _tenant(isolated_db)
        # Only the agent's runtime model exists — never substituted.
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        agent_type = await _subject(isolated_db, tenant.id)
        session = await _optimization_session(isolated_db, tenant.id, agent_type.id)
        await isolated_db.commit()

        with _as_tenant(tenant):
            with pytest.raises(HTTPException) as exc_info:
                await _context(
                    isolated_db, agent_type.id, conv_session_id=session.id
                )

        assert exc_info.value.status_code == 412
        detail = exc_info.value.detail
        assert detail["error"] == "optimizer_model_unavailable"
        assert detail["reason_code"] == "optimizer_model_not_configured"
        assert detail["reason"]

    @pytest.mark.asyncio
    async def test_stale_optimizer_model_fails_closed_with_not_enabled(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        await set_value(isolated_db, tenant.id, "optimizer_model_id", STALE_MODEL)
        agent_type = await _subject(isolated_db, tenant.id)
        session = await _optimization_session(isolated_db, tenant.id, agent_type.id)
        await isolated_db.commit()

        with _as_tenant(tenant):
            with pytest.raises(HTTPException) as exc_info:
                await _context(
                    isolated_db, agent_type.id, conv_session_id=session.id
                )

        detail = exc_info.value.detail
        assert detail["error"] == "optimizer_model_unavailable"
        assert detail["reason_code"] == "optimizer_model_not_enabled"
        assert STALE_MODEL in detail["reason"]

    @pytest.mark.asyncio
    async def test_optimization_context_carries_identifiers_only(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        await _enable_model(isolated_db, tenant.id, OPTIMIZER_MODEL)
        await set_value(
            isolated_db, tenant.id, "optimizer_model_id", OPTIMIZER_MODEL
        )
        agent_type = await _subject(isolated_db, tenant.id)
        session = await _optimization_session(isolated_db, tenant.id, agent_type.id)
        await isolated_db.commit()

        with _as_tenant(tenant):
            context = await _context(
                isolated_db, agent_type.id, conv_session_id=session.id
            )

        dumped = context.model_dump_json()
        assert "encrypted-secret-blob" not in dumped
        assert "gAAAAAB" not in dumped
        assert context.model_id == OPTIMIZER_MODEL


# ── Conversational shape: no typed input/output contract ────────────────────


class TestConversationalShape:
    @pytest.mark.asyncio
    async def test_typed_subject_optimization_turn_has_no_output_contract(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        await _enable_model(isolated_db, tenant.id, AUTHORING_MODEL)
        await set_value(
            isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
        )
        agent_type = await _subject(
            isolated_db,
            tenant.id,
            input_type=AgentInputType.typed,
            output_data_type_id=None,
        )
        agent_type.output_schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        session = await _optimization_session(isolated_db, tenant.id, agent_type.id)
        await isolated_db.commit()

        with _as_tenant(tenant):
            context = await _context(
                isolated_db, agent_type.id, conv_session_id=session.id
            )

        assert context.input_type == "conversation"
        assert context.output_type == "auto"
        assert context.output_schema is None
        assert context.output_schema_prompt is None
        assert context.output_json_schema is None
        assert context.output_data_type_id is None
        assert context.output_data_type_name is None

    @pytest.mark.asyncio
    async def test_same_typed_subject_keeps_its_typed_contract_for_a_business_run(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        agent_type = await _subject(
            isolated_db, tenant.id, input_type=AgentInputType.typed
        )
        agent_type.output_schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        await isolated_db.commit()

        with _as_tenant(tenant):
            context = await _context(isolated_db, agent_type.id)

        assert context.input_type == "typed"
        assert context.output_type == "markdown"
        assert context.output_schema == {
            "type": "object",
            "properties": {"a": {"type": "string"}},
        }


# ── Identity / role / grant parity ──────────────────────────────────────────


class TestIdentityParity:
    @pytest.mark.asyncio
    async def test_optimization_turn_inherits_the_subject_envelope(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        await _enable_model(isolated_db, tenant.id, AUTHORING_MODEL)
        await set_value(
            isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
        )
        agent_type = await _subject(isolated_db, tenant.id)
        role, identity, _business_tool = await _business_grant(
            isolated_db, tenant.id, agent_type
        )
        session = await _optimization_session(isolated_db, tenant.id, agent_type.id)
        business = await _business_session(isolated_db, tenant.id, agent_type.id)
        await isolated_db.commit()

        with _as_tenant(tenant):
            business_ctx = await _context(
                isolated_db, agent_type.id, conv_session_id=business.id
            )
            optimization_ctx = await _context(
                isolated_db, agent_type.id, conv_session_id=session.id
            )

        assert optimization_ctx.identity_name == identity.name
        assert optimization_ctx.identity_name == business_ctx.identity_name
        assert optimization_ctx.role_id == role.id
        assert optimization_ctx.role_id == business_ctx.role_id
        assert optimization_ctx.role_name == role.name
        assert optimization_ctx.role_name == business_ctx.role_name
        assert optimization_ctx.identity_role_valid is True
        # No bridging / elevated identity and no widened grant: the loop's tool
        # set is exactly the optimization set, nothing more.
        expected_tools = {
            build_tool_name("system", bare) for bare in get_inherent_tool_names()
        } | {
            build_tool_name("system", bare)
            for bare in get_optimization_mode_tool_names()
        }
        assert set(optimization_ctx.allowed_tools) <= expected_tools


# ── Unscoped / business callers are byte-identical ──────────────────────────


class TestUnscopedContextsUnchanged:
    @pytest.mark.asyncio
    async def test_missing_conversation_id_keeps_the_business_context(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        await _enable_model(isolated_db, tenant.id, AUTHORING_MODEL)
        await set_value(
            isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
        )
        agent_type = await _subject(
            isolated_db, tenant.id, input_type=AgentInputType.conversation
        )
        await isolated_db.commit()

        with _as_tenant(tenant):
            context = await _context(isolated_db, agent_type.id)

        assert context.system_instruction == agent_type.system_instruction
        assert context.optimization is None
        assert context.model_id == AGENT_RUNTIME_MODEL

    @pytest.mark.asyncio
    async def test_foreign_conversation_id_keeps_the_business_context(
        self, isolated_db
    ):
        """A conversation about another agent type never switches this turn's
        mode (defence in depth — the mode is subject-matched)."""
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        await _enable_model(isolated_db, tenant.id, AUTHORING_MODEL)
        await set_value(
            isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
        )
        other = await _subject(isolated_db, tenant.id, input_type=AgentInputType.conversation)
        subject = await _subject(isolated_db, tenant.id, input_type=AgentInputType.conversation)
        foreign = await _optimization_session(isolated_db, tenant.id, other.id)
        await isolated_db.commit()

        with _as_tenant(tenant):
            context = await _context(
                isolated_db, subject.id, conv_session_id=foreign.id
            )

        assert context.optimization is None
        assert context.system_instruction == subject.system_instruction
        assert context.model_id == AGENT_RUNTIME_MODEL

    @pytest.mark.asyncio
    async def test_command_run_keeps_authoring_tools_without_request_live_test(
        self, isolated_db
    ):
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        await _enable_model(isolated_db, tenant.id, AUTHORING_MODEL)
        await set_value(
            isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
        )
        agent_type = await _subject(
            isolated_db, tenant.id, input_type=AgentInputType.conversation
        )
        from app.db.models.agents import AgentJob

        job = AgentJob(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            agent_type_id=agent_type.id,
            input_data={
                "__command": OPTIMIZE_AND_VERIFY_SLUG,
                "__command_agent_type_id": str(agent_type.id),
            },
        )
        isolated_db.add(job)
        await isolated_db.commit()

        with _as_tenant(tenant):
            context = await _context(
                isolated_db, agent_type.id, session_id=job.id
            )

        allowed = set(context.allowed_tools)
        assert build_tool_name("system", "generate_optimized_plan") in allowed
        assert build_tool_name("system", REQUEST_LIVE_TEST_TOOL) not in allowed
        # ``__command`` runs keep the authoring model and their own mission.
        assert context.model_id == AUTHORING_MODEL
        assert context.optimization is None
        assert context.input_type == "conversation"

    @pytest.mark.asyncio
    async def test_business_conversation_keeps_instruction_and_grants_afterwards(
        self, isolated_db
    ):
        """Ending/ignoring the optimization conversation leaves no residual mode."""
        tenant = await _tenant(isolated_db)
        await _enable_model(isolated_db, tenant.id, AGENT_RUNTIME_MODEL)
        await _enable_model(isolated_db, tenant.id, AUTHORING_MODEL)
        await set_value(
            isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
        )
        agent_type = await _subject(
            isolated_db, tenant.id, input_type=AgentInputType.conversation
        )
        _role, _identity, business_tool = await _business_grant(
            isolated_db, tenant.id, agent_type
        )
        optimization = await _optimization_session(
            isolated_db, tenant.id, agent_type.id
        )
        business = await _business_session(isolated_db, tenant.id, agent_type.id)
        await isolated_db.commit()

        with _as_tenant(tenant):
            await _context(
                isolated_db, agent_type.id, conv_session_id=optimization.id
            )
            context = await _context(
                isolated_db, agent_type.id, conv_session_id=business.id
            )

        assert context.system_instruction == agent_type.system_instruction
        assert context.optimization is None
        assert business_tool in context.allowed_tools
        assert build_tool_name("system", REQUEST_LIVE_TEST_TOOL) not in set(
            context.allowed_tools
        )
        assert context.model_id == AGENT_RUNTIME_MODEL
