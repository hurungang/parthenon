"""FIX-20261101-000319 — Skill ↔ tool association via management tools.

``create_skill`` / ``update_skill`` accept ``tool_ids`` and/or ``tool_names``
(canonical ``server____tool`` names or UUIDs — including ``cc____`` tools) and
create ``SkillToolBinding`` rows:
  - create = bind all provided,
  - update = ADDITIVE MERGE (never remove; re-bind is an idempotent no-op),
  - unknown tool → structured 404 with an actionable message, no partial write,
  - resolution is strictly tenant-scoped.
Also covers the MCP-server tool discovery read path and the knowledge rule.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.internal.management_tools import (
    ManagementToolRequest,
    _create_resource,
    _get_resource,
    _update_resource,
)
from app.db.models.mcp_hub import McpServer, McpTool
from app.db.models.skills import SkillToolBinding
from app.services.agents.assistant_knowledge import search_knowledge


async def _mk_server(db, tenant_id, slug="supabase") -> McpServer:
    server = McpServer(
        tenant_id=tenant_id,
        name=slug.title(),
        slug=slug,
        description="test server",
        base_url="https://example.com",
        status="active",
    )
    db.add(server)
    await db.flush()
    return server


async def _mk_tool(db, tenant_id, server_id, bare="query", name=None) -> McpTool:
    server = await db.get(McpServer, server_id)
    slug = server.slug if server else "test"
    tool = McpTool(
        tenant_id=tenant_id,
        server_id=server_id,
        name=name or f"{slug}____{bare}",
        original_name=bare,
        description="d",
        input_schema={"type": "object", "properties": {}},
        is_active=True,
    )
    db.add(tool)
    await db.flush()
    return tool


@pytest.mark.asyncio
async def test_create_skill_with_tool_names_binds_tools(db_session) -> None:
    tenant = uuid.uuid4()
    server = await _mk_server(db_session, tenant)
    tool = await _mk_tool(db_session, tenant, server.id, "run_sql")

    result = await _create_resource(
        db_session,
        "skills",
        {
            "name": "sql-runner",
            "data": {"description": "runs sql", "tool_names": [f"supabase____run_sql"]},
        },
        tenant,
        "user-1",
    )
    skill_id = uuid.UUID(result["record"]["id"])
    bindings = (
        await db_session.execute(
            select(SkillToolBinding).where(SkillToolBinding.skill_id == skill_id)
        )
    ).scalars().all()
    assert [b.tool_id for b in bindings] == [tool.id]


@pytest.mark.asyncio
async def test_create_skill_with_tool_ids_binds_tools(db_session) -> None:
    tenant = uuid.uuid4()
    server = await _mk_server(db_session, tenant, "github")
    tool = await _mk_tool(db_session, tenant, server.id, "list_prs")

    result = await _create_resource(
        db_session,
        "skills",
        {"name": "pr-skill", "data": {"tool_ids": [str(tool.id)]}},
        tenant,
        "user-1",
    )
    skill_id = uuid.UUID(result["record"]["id"])
    bindings = (
        await db_session.execute(
            select(SkillToolBinding).where(SkillToolBinding.skill_id == skill_id)
        )
    ).scalars().all()
    assert [b.tool_id for b in bindings] == [tool.id]


@pytest.mark.asyncio
async def test_update_skill_bindings_are_additive_and_idempotent(db_session) -> None:
    tenant = uuid.uuid4()
    server = await _mk_server(db_session, tenant)
    tool_a = await _mk_tool(db_session, tenant, server.id, "tool_a")
    tool_b = await _mk_tool(db_session, tenant, server.id, "tool_b")

    created = await _create_resource(
        db_session,
        "skills",
        {"name": "adder", "data": {"tool_names": [f"supabase____tool_a"]}},
        tenant,
        "user-1",
    )
    skill_id = uuid.UUID(created["record"]["id"])

    # Additive merge: add tool_b.
    await _update_resource(
        db_session,
        "skills",
        {"id": str(skill_id), "data": {"tool_names": ["supabase____tool_b"]}},
        tenant,
    )
    bindings = (
        await db_session.execute(
            select(SkillToolBinding).where(SkillToolBinding.skill_id == skill_id)
        )
    ).scalars().all()
    assert {b.tool_id for b in bindings} == {tool_a.id, tool_b.id}

    # Idempotent re-bind: no duplicates.
    await _update_resource(
        db_session,
        "skills",
        {"id": str(skill_id), "data": {"tool_names": ["supabase____tool_a"]}},
        tenant,
    )
    bindings = (
        await db_session.execute(
            select(SkillToolBinding).where(SkillToolBinding.skill_id == skill_id)
        )
    ).scalars().all()
    assert {b.tool_id for b in bindings} == {tool_a.id, tool_b.id}


@pytest.mark.asyncio
async def test_unknown_tool_returns_structured_404_no_partial_write(db_session) -> None:
    tenant = uuid.uuid4()
    server = await _mk_server(db_session, tenant)
    tool = await _mk_tool(db_session, tenant, server.id, "good_tool")

    with pytest.raises(HTTPException) as exc_info:
        await _create_resource(
            db_session,
            "skills",
            {
                "name": "broken",
                "data": {"tool_names": ["supabase____good_tool", "supabase____missing_tool"]},
            },
            tenant,
            "user-1",
        )
    assert exc_info.value.status_code == 404
    assert "missing_tool" in str(exc_info.value.detail)

    # No partial write: neither the skill nor any binding exists.
    skills = (
        await db_session.execute(
            select(SkillToolBinding).where(SkillToolBinding.tool_id == tool.id)
        )
    ).scalars().all()
    assert skills == []


@pytest.mark.asyncio
async def test_tool_resolution_is_tenant_scoped(db_session) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    server_b = await _mk_server(db_session, tenant_b, "othertenant")
    await _mk_tool(db_session, tenant_b, server_b.id, "foreign_tool")

    with pytest.raises(HTTPException) as exc_info:
        await _create_resource(
            db_session,
            "skills",
            {"name": "cross", "data": {"tool_names": ["othertenant____foreign_tool"]}},
            tenant_a,
            "user-1",
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_cc_tools_are_bindable(db_session) -> None:
    tenant = uuid.uuid4()
    cc_server = McpServer(
        id=uuid.uuid5(uuid.NAMESPACE_OID, f"parthenon:cc-server:{tenant}"),
        tenant_id=tenant,
        name="Control Center",
        slug="cc",
        description="Control Center management capabilities",
        base_url="",
        status="active",
    )
    db_session.add(cc_server)
    await db_session.flush()
    cc_tool = McpTool(
        tenant_id=tenant,
        server_id=cc_server.id,
        name="cc____create_skill",
        original_name="create_skill",
        description="d",
        input_schema={"type": "object", "properties": {}},
        is_active=True,
    )
    db_session.add(cc_tool)
    await db_session.flush()

    result = await _create_resource(
        db_session,
        "skills",
        {"name": "mgmt-wrapper", "data": {"tool_names": ["cc____create_skill"]}},
        tenant,
        "user-1",
    )
    skill_id = uuid.UUID(result["record"]["id"])
    bindings = (
        await db_session.execute(
            select(SkillToolBinding).where(SkillToolBinding.skill_id == skill_id)
        )
    ).scalars().all()
    assert [b.tool_id for b in bindings] == [cc_tool.id]


@pytest.mark.asyncio
async def test_get_mcp_server_returns_its_tools(db_session) -> None:
    tenant = uuid.uuid4()
    server = await _mk_server(db_session, tenant, "supabase")
    await _mk_tool(db_session, tenant, server.id, "run_sql")
    await _mk_tool(db_session, tenant, server.id, "list_tables")

    result = await _get_resource(
        db_session, "mcp_servers", {"id": str(server.id)}, tenant
    )
    tools = result["record"]["tools"]
    assert {t["name"] for t in tools} == {
        "supabase____run_sql",
        "supabase____list_tables",
    }


def test_knowledge_contains_skill_tool_binding_rule() -> None:
    results = search_knowledge("bind tools to a skill when creating it", top_k=5)
    ids = [r["id"] for r in results]
    assert "skill-tool-binding" in ids
    entry = next(r for r in results if r["id"] == "skill-tool-binding")
    text = entry["rule_text"]
    assert "tool_ids" in text
    assert "cc____" in text
    assert "cannot do anything" in text or "without bindings" in text
