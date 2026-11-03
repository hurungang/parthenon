"""FIX-20261101-120618 Work Item 2 — built-in inherent skills.

Every agent must get the optimization / self-context system tools
(get_implementation_plan, get_optimized_implementation_plan, get_scripts,
get_execution_log, generate_optimized_plan, generate_script, execute_script,
list_scripts, get_script) INHERENTLY — zero user configuration, zero
per-agent binding rows.

Injection happens dynamically at context-build time in
``get_agent_context`` (both the role'd and role-less branches) via
``app.services.agents.builtin_skills``.  Definitions derive from
``SystemToolRegistry`` at request time (idempotent + cheap).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.session import Base
from app.db.models.agents import (
    AgentInputType,
    AgentOutputType,
    AgentRole,
    AgentRoleSkill,
    AgentType,
    AgentTypeSkillBinding,
    GuardrailConversationalContinuationPolicy,
    GuardrailConversationalTokenVisibilityMode,
    GuardrailTokenEnforcementMode,
    GuardrailTokenFallbackMode,
)
from app.db.models.mcp_hub import McpTool
from app.db.models.skills import Skill, SkillToolBinding
from app.db.models.tenant import Tenant
from app.services.agents.builtin_skills import (
    INHERENT_SKILL_NAMES,
    get_inherent_skill_definitions,
    get_inherent_tool_names,
)
from app.services.agents.assistant_seeder import AssistantSeeder
from app.services.agents.system_tool_registry import SystemToolRegistry


@pytest_asyncio.fixture
async def isolated_db() -> AsyncSession:
    """Fresh in-memory engine per test (mirrors the FIX-035145 fixture)."""
    from app.services.tenancy.root_tenant import invalidate_root_tenant_cache

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
        Tenant(id=uuid.uuid4(), slug="root", name="Root", is_system_tenant=True)
    )
    await session.commit()
    yield session
    await session.rollback()
    await session.close()
    await engine.dispose()
    invalidate_root_tenant_cache()


async def _create_tenant(session: AsyncSession, slug: str) -> Tenant:
    tenant = Tenant(id=uuid.uuid4(), slug=slug, name=slug.title(), status="active")
    session.add(tenant)
    await session.flush()
    return tenant


def _sanitized(canonical: str) -> str:
    return canonical.replace("____", "__")


def _inherent_def_names() -> set[str]:
    return {
        _sanitized(f"system____{name}") for name in get_inherent_tool_names()
    }


# ── Registry-derived inherent set ────────────────────────────────────────────


def test_inherent_set_contents() -> None:
    """The inherent set is exactly the documented optimization toolset."""
    assert INHERENT_SKILL_NAMES == ("self-context", "workflow-optimization")
    assert get_inherent_tool_names() == frozenset({
        "get_implementation_plan",
        "get_optimized_implementation_plan",
        "get_scripts",
        "get_execution_log",
        "generate_optimized_plan",
        "generate_script",
        "execute_script",
        "list_scripts",
        "get_script",
    })
    # All derived from the live registry (must stay in sync automatically).
    for name in get_inherent_tool_names():
        assert SystemToolRegistry.get(name) is not None
    # None of the inherent tools are management tools (they stay system____).
    management = SystemToolRegistry.get_management_tool_names()
    assert not (get_inherent_tool_names() & management)


def test_inherent_definitions_have_descriptions() -> None:
    """Skill definitions carry descriptions so agents can discover them."""
    for definition in get_inherent_skill_definitions():
        assert definition.name in INHERENT_SKILL_NAMES
        assert len(definition.description) > 20
        assert definition.tool_names, definition.name


# ── Role'd agent: role tools PLUS inherent ───────────────────────────────────


@pytest.mark.asyncio
async def test_roled_agent_context_includes_inherent_tools(isolated_db) -> None:
    """A role'd agent gets its role-resolved tools PLUS the inherent set."""
    from app.api.v1.internal.agent_data import get_agent_context

    tenant = await _create_tenant(isolated_db, "inherent-roled")

    role = AgentRole(
        id=uuid.uuid4(), tenant_id=tenant.id, name="worker", description="worker"
    )
    skill = Skill(id=uuid.uuid4(), tenant_id=tenant.id, name="worker-skill")
    tool = McpTool(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        server_id=uuid.uuid4(),
        name="hello____ping",
        original_name="ping",
        description="ping tool",
        input_schema={"type": "object", "properties": {}},
        is_active=True,
    )
    isolated_db.add_all([role, skill, tool])
    await isolated_db.flush()
    isolated_db.add(AgentRoleSkill(role_id=role.id, skill_id=skill.id))
    isolated_db.add(SkillToolBinding(skill_id=skill.id, tool_id=tool.id))
    agent_type = AgentType(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="worker-agent",
        description="w",
        role_id=role.id,
        input_type=AgentInputType.conversation,
        output_type=AgentOutputType.auto,
        is_active=True,
        guardrail_token_enforcement_mode=GuardrailTokenEnforcementMode.observe,
        guardrail_token_fallback_mode=GuardrailTokenFallbackMode.observe_and_log,
        guardrail_conversational_token_visibility_mode=GuardrailConversationalTokenVisibilityMode.enabled,
        guardrail_conversational_continuation_policy=GuardrailConversationalContinuationPolicy.allow,
    )
    isolated_db.add(agent_type)
    await isolated_db.commit()

    context = await get_agent_context(agent_type_id=agent_type.id, db=isolated_db)

    # 1. The role-resolved MCP tool still resolves.
    assert "hello____ping" in context.allowed_tools

    # 2. Every inherent tool is in allowed_tools under canonical system____ names.
    for bare in get_inherent_tool_names():
        assert f"system____{bare}" in context.allowed_tools, bare

    # 3. Tool definitions carry registry schemas under sanitised canonical names.
    def_names = {
        d["function"]["name"] for d in context.tool_definitions
        if d.get("type") == "function"
    }
    assert _inherent_def_names() <= def_names
    schema = next(
        d for d in context.tool_definitions
        if d["function"]["name"] == "system__get_scripts"
    )
    expected = SystemToolRegistry.get_schema("get_scripts")
    assert schema is not None
    assert schema["function"]["parameters"] == expected["function"]["parameters"]

    # 4. The inherent skills are surfaced in the skills summary.
    skill_names = {s.name for s in context.skills}
    assert set(INHERENT_SKILL_NAMES) <= skill_names


@pytest.mark.asyncio
async def test_no_binding_rows_created(isolated_db) -> None:
    """Inherent injection must NOT create AgentTypeSkillBinding rows."""
    from app.api.v1.internal.agent_data import get_agent_context

    tenant = await _create_tenant(isolated_db, "inherent-norows")
    agent_type = AgentType(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="plain-agent",
        description="p",
        input_type=AgentInputType.conversation,
        output_type=AgentOutputType.auto,
        is_active=True,
        guardrail_token_enforcement_mode=GuardrailTokenEnforcementMode.observe,
        guardrail_token_fallback_mode=GuardrailTokenFallbackMode.observe_and_log,
        guardrail_conversational_token_visibility_mode=GuardrailConversationalTokenVisibilityMode.enabled,
        guardrail_conversational_continuation_policy=GuardrailConversationalContinuationPolicy.allow,
    )
    isolated_db.add(agent_type)
    await isolated_db.commit()

    before = len((await isolated_db.execute(select(AgentTypeSkillBinding))).scalars().all())
    await get_agent_context(agent_type_id=agent_type.id, db=isolated_db)
    after = len((await isolated_db.execute(select(AgentTypeSkillBinding))).scalars().all())
    assert before == 0 and after == 0


# ── Role-less agent (assistant): meta tools + inherent set ──────────────────


@pytest.mark.asyncio
async def test_roleless_assistant_gets_inherent_tools(isolated_db) -> None:
    """The assistant (role-less) gets cc meta tools PLUS the inherent set."""
    from app.api.v1.internal.agent_data import get_agent_context

    await AssistantSeeder().run(isolated_db)
    await isolated_db.commit()

    root_tenant = (
        await isolated_db.execute(
            select(Tenant).where(Tenant.is_system_tenant.is_(True))
        )
    ).scalar_one()
    assistant = (
        await isolated_db.execute(
            select(AgentType).where(
                AgentType.tenant_id == root_tenant.id,
                AgentType.name == "control-center-assistant",
            )
        )
    ).scalar_one()

    context = await get_agent_context(agent_type_id=assistant.id, db=isolated_db)

    for bare in get_inherent_tool_names():
        assert f"system____{bare}" in context.allowed_tools, bare

    def_names = {
        d["function"]["name"] for d in context.tool_definitions
        if d.get("type") == "function"
    }
    assert _inherent_def_names() <= def_names
    # Meta tools still present.
    assert "cc__invoke_management_tool" in def_names
