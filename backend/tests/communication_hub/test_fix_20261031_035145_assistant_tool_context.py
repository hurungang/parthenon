"""FIX-20261031-035145 — false-success regression tests for the assistant.

Root cause (two independent gaps that together produced a toolless assistant
whose LLM hallucinated "created"):

1. The conversational delegation path (CH ``ws/chat.py`` → AR
   ``/internal/conversation/turn`` → CC ``get_agent_context``) returned an
   EMPTY tool context for the assistant: ``get_agent_context`` resolved
   tools only inside ``if agent_type.role_id:`` and the assistant agent type
   is seeded WITHOUT a role, so ``allowed_tools`` / ``tool_definitions`` /
   ``tool_name_map`` were all empty and AR ran the model toolless.

2. ``AssistantSeeder._ensure_skill_bindings`` depended on another component
   having seeded per-tenant ``McpTool`` rows for the management tools.
   System tool rows are seeded root-tenant only, so every non-root tenant's
   management skill ended up with 0 bindings ("not seeded yet — binding
   skipped" on every startup, no retry).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.session import Base
from app.db.models.agents import AgentType
from app.db.models.mcp_hub import McpServer, McpTool
from app.db.models.skills import Skill, SkillToolBinding
from app.db.models.tenant import Tenant
from app.services.agents.assistant_seeder import (
    ASSISTANT_AGENT_TYPE_NAME,
    MANAGEMENT_SKILL_NAME,
    AssistantSeeder,
)
from app.services.agents.system_tool_registry import SystemToolRegistry


@pytest_asyncio.fixture
async def isolated_db() -> AsyncSession:
    """Fresh in-memory engine per test.

    These tests create extra tenants/rows; running them on the shared
    session-scoped engine would leak state into other test files (e.g.
    ``tests/unit/test_assistant_seeder.py`` asserts single-row results).
    """
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


async def _create_tenant(session, slug: str) -> Tenant:
    tenant = Tenant(id=uuid.uuid4(), slug=slug, name=slug.title(), status="active")
    session.add(tenant)
    await session.flush()
    return tenant


async def _seed_root_management_tools(session) -> None:
    """Mirror the production ROOT-tenant state: the global system-tool
    seeding stamps ``McpTool`` rows for every registry entry to the root
    tenant.  (``seed_system_tools`` itself trips over a pre-existing SQLite
    test-engine UUID-affinity issue, so the rows are inserted directly
    here — the row shape is identical.)"""
    from sqlalchemy import select as _select

    root = (
        await session.execute(
            _select(Tenant).where(Tenant.is_system_tenant.is_(True))
        )
    ).scalar_one()

    # sqlite test-engine UUID-affinity safety: avoid the all-digit
    # registry SYSTEM_SERVER_ID (coerces to INTEGER under NUMERIC affinity).
    test_server_id = uuid.uuid5(uuid.NAMESPACE_OID, "test-root:system-server")
    server = await session.get(McpServer, test_server_id)
    if server is None:
        session.add(
            McpServer(
                id=test_server_id,
                tenant_id=root.id,
                name="system",
                slug="system",
                description="Built-in system tools available to all agents",
                base_url="",
            )
        )
        await session.flush()

    for entry in (
        SystemToolRegistry.get_mcp_hub_entries()
        + SystemToolRegistry.get_cc_mcp_hub_entries()
    ):
        if entry["original_name"] not in (
            SystemToolRegistry.get_management_tool_names()
            | SystemToolRegistry.get_meta_tool_names()
        ):
            continue
        # Use the seeder's deterministic per-tenant row ids so the fixture
        # and the seeder converge on the SAME rows (no duplicates).
        from app.services.agents.assistant_seeder import _tenant_management_tool_id

        row_id = _tenant_management_tool_id(entry["id"], root.id)
        if await session.get(McpTool, row_id) is not None:
            continue
        session.add(
            McpTool(
                id=row_id,
                tenant_id=root.id,
                server_id=test_server_id,
                name=entry["name"],
                original_name=entry["original_name"],
                description=entry["description"],
                input_schema=entry["input_schema"],
                is_active=True,
            )
        )
    await session.flush()


async def _get_assistant_agent_type(session, tenant_id) -> AgentType:
    return (
        await session.execute(
            select(AgentType).where(
                AgentType.name == ASSISTANT_AGENT_TYPE_NAME,
                AgentType.tenant_id == tenant_id,
            )
        )
    ).scalar_one()


# ── T1: conversational delegation context carries ONLY the meta tools ───────


@pytest.mark.asyncio
async def test_t1_assistant_context_includes_management_tool_definitions(
    isolated_db,
) -> None:
    """The agent_context built for the assistant (role-less, conversational)
    must carry ONLY the constant meta tools (progressive disclosure) in
    ``tool_definitions`` — never all ~36 management execution schemas —
    while every management action remains invocable through
    ``invoke_management_tool`` (dispatch re-authorizes per call)."""
    from app.api.v1.internal.agent_data import get_agent_context

    await _seed_root_management_tools(isolated_db)
    await AssistantSeeder().run(isolated_db)
    await isolated_db.commit()

    root_tenant = (
        await isolated_db.execute(
            select(Tenant).where(Tenant.is_system_tenant.is_(True))
        )
    ).scalar_one()
    assistant = await _get_assistant_agent_type(isolated_db, root_tenant.id)

    context = await get_agent_context(agent_type_id=assistant.id, db=isolated_db)

    meta_names = SystemToolRegistry.get_meta_tool_names()
    management_names = SystemToolRegistry.get_management_tool_names()

    # allowed_tools carries the meta tools with category-aware canonical
    # names: cc____ for the 4 management meta tools, system____ for
    # human_intervene (FIX-20261101-000319).
    for meta in meta_names:
        canonical = f"cc____{meta}"
        if SystemToolRegistry.get(meta).category == "general":
            canonical = f"system____{meta}"
        assert canonical in context.allowed_tools, (
            f"assistant agent_context.allowed_tools missing {canonical}; "
            f"got {context.allowed_tools}"
        )

    # tool_definitions carry ONLY the meta tool schemas (constant, small),
    # under category-aware SANITISED canonical names (cc__… / system__…).
    def_names = [
        d["function"]["name"]
        for d in context.tool_definitions
        if d.get("type") == "function"
    ]

    def canonical_def(meta: str) -> str:
        prefix = "cc" if SystemToolRegistry.get(meta).category == "management" else "system"
        return f"{prefix}____{meta}".replace("____", "__")

    expected_defs = {canonical_def(m) for m in meta_names}
    # FIX-20261101-120618: the built-in inherent skills are injected into
    # EVERY agent context.  Optimization gating: the default (conversational
    # / non-opt-in) run gets the GATED set — self-context tools +
    # execute_script, without the workflow-optimization authoring tools.
    from app.services.agents.builtin_skills import (
        get_inherent_tool_names_for,
    )

    expected_defs |= {
        f"system____{bare}".replace("____", "__")
        for bare in get_inherent_tool_names_for(optimization_enabled=False)
    }
    assert set(def_names) == expected_defs, (
        f"tool_definitions must contain exactly the meta tools {sorted(expected_defs)}; "
        f"got {sorted(def_names)}"
    )
    # Progressive disclosure contract: no execution schema leaks into context.
    def bare_of(name: str) -> str:
        for prefix in ("cc__", "system__"):
            if name.startswith(prefix):
                return name[len(prefix):]
        return name

    leaked = management_names & {bare_of(d) for d in def_names}
    assert not leaked, (
        f"management execution schemas leaked into assistant context: {sorted(leaked)}"
    )
    assert "cc__invoke_management_tool" in def_names


# ── T2: per-tenant management tool rows + skill bindings are self-seeded ────


@pytest.mark.asyncio
async def test_t2_seeder_self_seeds_per_tenant_management_bindings(
    isolated_db,
) -> None:
    """A fresh non-root tenant (no management McpTool rows) must end up with
    the full management tool set bound to its control-center-management
    skill after AssistantSeeder runs — no dependency on another seeder."""
    tenant = await _create_tenant(isolated_db, "fix-035145-fresh")
    await isolated_db.flush()

    # Precondition: this tenant genuinely starts with no management rows.
    preexisting = (
        await isolated_db.execute(
            select(McpTool).where(
                McpTool.tenant_id == tenant.id,
                McpTool.original_name.in_(SystemToolRegistry.get_management_tool_names()),
            )
        )
    ).scalars().all()
    assert preexisting == []

    await AssistantSeeder().run(isolated_db)
    await isolated_db.commit()

    # Per-tenant McpTool rows now exist for every management tool (and the
    # meta tools).
    tools = (
        await isolated_db.execute(
            select(McpTool).where(
                McpTool.tenant_id == tenant.id,
                McpTool.original_name.in_(SystemToolRegistry.get_management_tool_names()),
            )
        )
    ).scalars().all()
    assert {t.original_name for t in tools} == set(
        SystemToolRegistry.get_management_tool_names()
    )
    assert all(t.name.startswith("cc____") for t in tools)

    # Meta tools are also provisioned and bound.
    meta_tools = (
        await isolated_db.execute(
            select(McpTool).where(
                McpTool.tenant_id == tenant.id,
                McpTool.original_name.in_(SystemToolRegistry.get_meta_tool_names()),
            )
        )
    ).scalars().all()
    assert {t.original_name for t in meta_tools} == set(
        SystemToolRegistry.get_meta_tool_names()
    )

    # The tenant's management skill has the bindings.
    skill = (
        await isolated_db.execute(
            select(Skill).where(
                Skill.name == MANAGEMENT_SKILL_NAME,
                Skill.tenant_id == tenant.id,
            )
        )
    ).scalar_one()
    bindings = (
        await isolated_db.execute(
            select(SkillToolBinding).where(SkillToolBinding.skill_id == skill.id)
        )
    ).scalars().all()
    assert bindings, "management skill must have tool bindings after seeding"

    bound_ids = {b.tool_id for b in bindings}
    assert bound_ids >= {t.id for t in tools}, (
        "every management McpTool row must be bound to the skill"
    )

    # Sampled tool: create_skill is bound.
    create_skill = next(t for t in tools if t.original_name == "create_skill")
    assert create_skill.id in bound_ids


@pytest.mark.asyncio
async def test_t2_seeding_is_idempotent_across_restarts(isolated_db) -> None:
    """Running the seeder twice must not duplicate tools or bindings."""
    tenant = await _create_tenant(isolated_db, "fix-035145-idem")
    await isolated_db.flush()

    seeder = AssistantSeeder()
    await seeder.run(isolated_db)
    await isolated_db.commit()
    await seeder.run(isolated_db)
    await isolated_db.commit()

    tools = (
        await isolated_db.execute(
            select(McpTool).where(
                McpTool.tenant_id == tenant.id,
                McpTool.original_name.in_(SystemToolRegistry.get_management_tool_names()),
            )
        )
    ).scalars().all()
    assert len(tools) == len(SystemToolRegistry.get_management_tool_names())

    skill = (
        await isolated_db.execute(
            select(Skill).where(
                Skill.name == MANAGEMENT_SKILL_NAME,
                Skill.tenant_id == tenant.id,
            )
        )
    ).scalar_one()
    bindings = (
        await isolated_db.execute(
            select(SkillToolBinding).where(SkillToolBinding.skill_id == skill.id)
        )
    ).scalars().all()
    assert len(bindings) == (
        len(SystemToolRegistry.get_management_tool_names())
        + len(SystemToolRegistry.get_meta_tool_names())
    )
