"""FIX-20261101-223511 — Skill↔tool binding visibility + zero-binding guard.

Covers:
- ``create_skill`` without tools → result carries a structured, non-fatal
  ``warnings`` entry (zero-binding guard);
- ``create_skill`` WITH tools → no warning;
- ``update_skill`` that touches tools but leaves zero bindings → warning;
- ``get_skill`` / ``list_skills`` include ``tool_bindings`` (tool name +
  owning server slug/name);
- the ``SkillRead`` REST schema exposes ``tool_bindings``;
- the knowledge corpus surfaces the canonical confirmation-preview format.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.api.v1.internal.management_tools import (
    _create_resource,
    _get_resource,
    _list_resource,
    _update_resource,
)
from app.db.models.mcp_hub import McpServer, McpTool
from app.services.agents.assistant_knowledge import search_knowledge

WARNING_FRAGMENT = "no tools bound"


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


async def _mk_tool(db, tenant_id, server_id, bare="run_sql") -> McpTool:
    server = await db.get(McpServer, server_id)
    slug = server.slug if server else "test"
    tool = McpTool(
        tenant_id=tenant_id,
        server_id=server_id,
        name=f"{slug}____{bare}",
        original_name=bare,
        description="d",
        input_schema={"type": "object", "properties": {}},
        is_active=True,
    )
    db.add(tool)
    await db.flush()
    return tool


# ── Feature 2: zero-binding guard ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_skill_without_tools_carries_warning(db_session) -> None:
    """FAILING-FIRST: create_skill without tools previously returned no warning."""
    result = await _create_resource(
        db_session,
        "skills",
        {"name": "bare-skill-223511", "data": {"description": "no tools"}},
        uuid.uuid4(),
        "user-1",
    )
    warnings = result.get("warnings")
    assert isinstance(warnings, list) and len(warnings) == 1
    assert WARNING_FRAGMENT in warnings[0]
    # Non-fatal: the record is still returned.
    assert result["record"]["name"] == "bare-skill-223511"


@pytest.mark.asyncio
async def test_create_skill_with_tools_has_no_warning(db_session) -> None:
    tenant = uuid.uuid4()
    server = await _mk_server(db_session, tenant)
    await _mk_tool(db_session, tenant, server.id, "run_sql")

    result = await _create_resource(
        db_session,
        "skills",
        {"name": "bound-skill-223511", "data": {"tool_names": ["supabase____run_sql"]}},
        tenant,
        "user-1",
    )
    assert result.get("warnings") in (None, [])


@pytest.mark.asyncio
async def test_update_skill_touching_tools_with_zero_bindings_warns(db_session) -> None:
    tenant = uuid.uuid4()
    created = await _create_resource(
        db_session, "skills", {"name": "upd-warn-223511"}, tenant, "user-1"
    )
    skill_id = created["record"]["id"]

    result = await _update_resource(
        db_session,
        "skills",
        {"id": skill_id, "data": {"tool_ids": []}},
        tenant,
    )
    warnings = result.get("warnings")
    assert isinstance(warnings, list) and WARNING_FRAGMENT in warnings[0]


@pytest.mark.asyncio
async def test_update_skill_adding_tools_has_no_warning(db_session) -> None:
    tenant = uuid.uuid4()
    server = await _mk_server(db_session, tenant)
    await _mk_tool(db_session, tenant, server.id, "query")
    created = await _create_resource(
        db_session, "skills", {"name": "upd-ok-223511"}, tenant, "user-1"
    )
    result = await _update_resource(
        db_session,
        "skills",
        {"id": created["record"]["id"], "data": {"tool_names": ["supabase____query"]}},
        tenant,
    )
    assert result.get("warnings") in (None, [])


# ── Feature 1: tool_bindings in read results ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_skill_includes_tool_bindings(db_session) -> None:
    tenant = uuid.uuid4()
    server = await _mk_server(db_session, tenant, "github")
    tool = await _mk_tool(db_session, tenant, server.id, "list_prs")
    created = await _create_resource(
        db_session,
        "skills",
        {"name": "vis-skill-223511", "data": {"tool_ids": [str(tool.id)]}},
        tenant,
        "user-1",
    )

    got = await _get_resource(db_session, "skills", {"id": created["record"]["id"]}, tenant)
    bindings = got["record"]["tool_bindings"]
    assert len(bindings) == 1
    assert bindings[0]["name"] == "github____list_prs"
    assert bindings[0]["original_name"] == "list_prs"
    assert bindings[0]["server_slug"] == "github"
    assert bindings[0]["server_name"] == "Github"


@pytest.mark.asyncio
async def test_list_skills_include_tool_bindings(db_session) -> None:
    tenant = uuid.uuid4()
    server = await _mk_server(db_session, tenant, "supabase")
    tool = await _mk_tool(db_session, tenant, server.id, "run_sql")
    await _create_resource(
        db_session,
        "skills",
        {"name": "list-vis-223511", "data": {"tool_names": ["supabase____run_sql"]}},
        tenant,
        "user-1",
    )

    listed = await _list_resource(db_session, "skills", {}, tenant)
    row = next(r for r in listed["records"] if r["name"] == "list-vis-223511")
    assert len(row["tool_bindings"]) == 1
    binding = row["tool_bindings"][0]
    assert binding["name"] == "supabase____run_sql"
    assert binding["original_name"] == "run_sql"
    assert binding["server_slug"] == "supabase"
    assert binding["server_name"] == "Supabase"


# ── REST SkillRead schema exposes tool_bindings ──────────────────────────────


def test_skill_read_schema_exposes_tool_bindings() -> None:
    """FAILING-FIRST: SkillRead previously had no tool_bindings field."""
    from app.schemas.skills import SkillRead

    tool = SimpleNamespace(
        name="supabase____run_sql",
        original_name="run_sql",
        server=SimpleNamespace(slug="supabase", name="Supabase"),
    )
    binding = SimpleNamespace(order=0, tool_id=uuid.uuid4(), tool=tool)
    skill = SimpleNamespace(
        id=uuid.uuid4(),
        name="sql-runner",
        description=None,
        is_active=True,
        is_system=False,
        instructions_with_tools=None,
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        updated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        tool_bindings=[binding],
    )
    skill_read = SkillRead.model_validate(skill)
    assert skill_read.tool_bindings is not None
    assert len(skill_read.tool_bindings) == 1
    assert skill_read.tool_bindings[0].name == "supabase____run_sql"
    assert skill_read.tool_bindings[0].server_slug == "supabase"
    assert skill_read.tool_bindings[0].server_name == "Supabase"


# ── Feature 3: canonical confirmation preview format knowledge ───────────────


def test_knowledge_confirmation_preview_format_retrieval() -> None:
    """FAILING-FIRST: the canonical preview-format contract did not exist."""
    for query in ("confirmation preview format", "how to format the approval table"):
        results = search_knowledge(query, top_k=5)
        ids = [r["id"] for r in results]
        assert "confirmation-preview-format" in ids, f"missing for query: {query}"
    entry = next(
        r for r in search_knowledge("confirmation preview format", top_k=5)
        if r["id"] == "confirmation-preview-format"
    )
    text = entry["rule_text"]
    # The canonical contract markers.
    assert "| Field | Value |" in text
    assert "human_intervene" in text
