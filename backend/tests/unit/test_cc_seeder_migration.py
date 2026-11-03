"""FIX-20261101-000319 — AssistantSeeder migration to the ``cc____`` namespace.

A tenant provisioned by the PREVIOUS seeder version has:
  - per-tenant mirror ``McpTool`` rows named ``system____<mgmt>`` under the
    per-tenant ``system`` server,
  - the assistant management skill bound to those rows.

After seeding with the new code the tenant must have:
  - a per-tenant "Control Center" McpServer (slug ``cc``),
  - per-tenant ``cc____<bare>`` McpTool rows for all management + meta tools,
  - the management skill rebound to the NEW cc rows,
  - the OLD ``system____<mgmt>`` rows retired (gone — not grantable/listed),
  - general ``system____`` rows untouched.
Idempotent across restarts.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models.mcp_hub import McpServer, McpTool
from app.db.models.skills import Skill, SkillToolBinding
from app.db.models.tenant import Tenant
from app.services.agents.assistant_seeder import (
    MANAGEMENT_SKILL_NAME,
    AssistantSeeder,
    _tenant_cc_server_id,
)
from app.services.agents.system_tool_registry import SystemToolRegistry

_MANAGEMENT = SystemToolRegistry.get_management_tool_names()
_META = {
    "invoke_management_tool",
    "get_management_tool_schema",
    "list_management_tools",
    "search_assistant_knowledge",
}
_SEEDED = _MANAGEMENT | _META


async def _create_tenant(session, slug: str) -> Tenant:
    tenant = Tenant(id=uuid.uuid4(), slug=slug, name=slug.title(), status="active")
    session.add(tenant)
    await session.flush()
    return tenant


async def _seed_old_style(session, tenant_id) -> None:
    """Recreate the pre-migration state: system____ management rows + bindings."""
    old_server_id = uuid.uuid5(uuid.NAMESPACE_OID, f"parthenon:system-server:{tenant_id}")
    session.add(
        McpServer(
            id=old_server_id,
            tenant_id=tenant_id,
            name="system",
            slug="system",
            description="Built-in system tools available to all agents",
            base_url="",
            status="active",
        )
    )
    await session.flush()
    skill = (
        await session.execute(
            select(Skill).where(
                Skill.name == MANAGEMENT_SKILL_NAME, Skill.tenant_id == tenant_id
            )
        )
    ).scalar_one()
    order = 0
    for bare in sorted(_SEEDED):
        row_id = uuid.uuid5(
            uuid.NAMESPACE_OID, f"parthenon:legacy:{tenant_id}:{bare}"
        )
        session.add(
            McpTool(
                id=row_id,
                tenant_id=tenant_id,
                server_id=old_server_id,
                name=f"system____{bare}",
                original_name=bare,
                description=f"legacy {bare}",
                input_schema={"type": "object", "properties": {}},
                is_active=True,
            )
        )
        session.add(
            SkillToolBinding(skill_id=skill.id, tool_id=row_id, order=order)
        )
        order += 1
    await session.flush()


@pytest.mark.asyncio
async def test_seeder_provisions_cc_entity_and_migrates_bindings(db_session) -> None:
    tenant = await _create_tenant(db_session, "cc-mig-a")
    await AssistantSeeder().run(db_session)  # seed old-style (v1) rows first
    await db_session.commit()
    await _seed_old_style(db_session, tenant.id)
    await db_session.commit()

    # Now run the NEW seeder — must migrate.
    await AssistantSeeder().run(db_session)
    await db_session.commit()

    # CC server exists for the tenant.
    cc_server = await db_session.get(McpServer, _tenant_cc_server_id(tenant.id))
    assert cc_server is not None
    assert cc_server.slug == "cc"

    # cc____ rows exist for every management + meta tool, under the CC server.
    cc_rows = (
        await db_session.execute(
            select(McpTool).where(
                McpTool.tenant_id == tenant.id,
                McpTool.server_id == cc_server.id,
            )
        )
    ).scalars().all()
    by_original = {t.original_name: t for t in cc_rows}
    # cc rows = management + the 4 meta tools, PLUS human_intervene (a
    # general meta tool that keeps its system____ name but needs a
    # per-tenant row on the CC server so the skill can bind it).
    assert set(by_original) == _SEEDED | {"human_intervene"}
    for bare, row in by_original.items():
        expected_prefix = "system____" if bare == "human_intervene" else "cc____"
        assert row.name == f"{expected_prefix}{bare}"
        assert row.is_active is True

    # Old system____ management rows are retired.
    legacy_rows = (
        await db_session.execute(
            select(McpTool).where(
                McpTool.tenant_id == tenant.id,
                McpTool.name.like("system____%"),
                McpTool.original_name.in_(_SEEDED),
            )
        )
    ).scalars().all()
    assert legacy_rows == []

    # The management skill is bound ONLY to the new cc rows now.
    skill = (
        await session_exec_skill(db_session, tenant.id)
    )
    bindings = (
        await db_session.execute(
            select(SkillToolBinding).where(SkillToolBinding.skill_id == skill.id)
        )
    ).scalars().all()
    bound_ids = {b.tool_id for b in bindings}
    assert bound_ids == {t.id for t in cc_rows}


async def session_exec_skill(session, tenant_id) -> Skill:
    return (
        await session.execute(
            select(Skill).where(
                Skill.name == MANAGEMENT_SKILL_NAME, Skill.tenant_id == tenant_id
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_seeder_migration_is_idempotent_across_restarts(db_session) -> None:
    tenant = await _create_tenant(db_session, "cc-mig-b")
    await AssistantSeeder().run(db_session)
    await db_session.commit()
    await _seed_old_style(db_session, tenant.id)
    await db_session.commit()

    await AssistantSeeder().run(db_session)
    await db_session.commit()
    await AssistantSeeder().run(db_session)
    await db_session.commit()

    cc_server = await db_session.get(McpServer, _tenant_cc_server_id(tenant.id))
    cc_rows = (
        await db_session.execute(
            select(McpTool).where(McpTool.server_id == cc_server.id)
        )
    ).scalars().all()
    assert len(cc_rows) == len(_SEEDED) + 1  # no duplicates (+ human_intervene)

    skill = await session_exec_skill(db_session, tenant.id)
    bindings = (
        await db_session.execute(
            select(SkillToolBinding).where(SkillToolBinding.skill_id == skill.id)
        )
    ).scalars().all()
    assert len(bindings) == len(_SEEDED) + 1  # no duplicates (+ human_intervene)

    legacy_rows = (
        await db_session.execute(
            select(McpTool).where(
                McpTool.tenant_id == tenant.id,
                McpTool.name.like("system____%"),
                McpTool.original_name.in_(_SEEDED),
            )
        )
    ).scalars().all()
    assert legacy_rows == []


@pytest.mark.asyncio
async def test_seeder_fresh_tenant_has_no_legacy_rows(db_session) -> None:
    tenant = await _create_tenant(db_session, "cc-mig-c")
    await AssistantSeeder().run(db_session)
    await db_session.commit()

    legacy_rows = (
        await db_session.execute(
            select(McpTool).where(
                McpTool.tenant_id == tenant.id,
                McpTool.name.like("system____%"),
                McpTool.original_name.in_(_SEEDED),
            )
        )
    ).scalars().all()
    assert legacy_rows == []

    cc_server = await db_session.get(McpServer, _tenant_cc_server_id(tenant.id))
    assert cc_server is not None
    assert cc_server.slug == "cc"


@pytest.mark.asyncio
async def test_seeder_keeps_general_system_rows_intact(db_session) -> None:
    """General tools bound to the management skill via system rows survive."""
    tenant = await _create_tenant(db_session, "cc-mig-d")
    await AssistantSeeder().run(db_session)
    await db_session.commit()

    # A general system tool row (e.g. system____save_data mirror) exists and
    # stays after the migration runs.
    general_row = McpTool(
        id=uuid.uuid5(uuid.NAMESPACE_OID, f"parthenon:general:{tenant.id}"),
        tenant_id=tenant.id,
        server_id=uuid.uuid5(uuid.NAMESPACE_OID, f"parthenon:system-server:{tenant.id}"),
        name="system____save_data",
        original_name="save_data",
        description="general",
        input_schema={"type": "object", "properties": {}},
        is_active=True,
    )
    db_session.add(general_row)
    await db_session.commit()

    await AssistantSeeder().run(db_session)
    await db_session.commit()

    still_there = await db_session.get(McpTool, general_row.id)
    assert still_there is not None
    assert still_there.name == "system____save_data"
