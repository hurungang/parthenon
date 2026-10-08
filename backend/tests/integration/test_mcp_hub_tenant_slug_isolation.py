"""Scenario 1 + 8 — per-tenant MCP slug isolation.

Two tenants each register an MCP server with the SAME slug ``supabase``:
registration, tool sync (tenant-stamped tools), skill bindings, tool
resolution and permission grants must all stay inside the creating
tenant; a duplicate slug within ONE tenant is rejected at the DB level.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select, text

from tests.integration._strict_tenant_utils import (  # noqa: F401
    create_two_tenants,
    db,
    make_module_schema_fixture,
)

_schema = make_module_schema_fixture()

SLUG = "supabase"


async def _register_server(db, tenant_id, slug: str = SLUG, name: str | None = None):
    from app.db.models.mcp_hub import McpServer

    server = McpServer(
        tenant_id=tenant_id,
        name=name or f"{slug}-{uuid.uuid4().hex[:6]}",
        slug=slug,
        base_url="http://127.0.0.1:1/mcp",
        status="active",
    )
    db.add(server)
    await db.commit()
    await db.refresh(server)
    return server


def _tools_list_response(tool_names: list[str]):
    resp = MagicMock()
    resp.status_code = 200
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {"name": n, "description": f"{n} tool", "inputSchema": {"type": "object"}}
                for n in tool_names
            ]
        },
    }
    resp.json = MagicMock(return_value=payload)
    resp.text = json.dumps(payload)
    resp.headers = {"content-type": "application/json"}
    resp.content = b"x"
    resp.raise_for_status = MagicMock()
    return resp


def _patch_http(monkeypatch, resp):
    """Make every httpx.AsyncClient POST return the given tools/list response."""
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.services.mcp.tool_sync.httpx.AsyncClient", lambda **kw: cm
    )


class TestPerTenantSlugRegistration:
    async def test_same_slug_in_two_tenants_succeeds(self, db):
        """(tenant, slug) uniqueness: both tenants may register 'supabase'."""
        tenant_a, tenant_b = await create_two_tenants(db)
        server_a = await _register_server(db, tenant_a.id)
        server_b = await _register_server(db, tenant_b.id)
        assert server_a.tenant_id == tenant_a.id
        assert server_b.tenant_id == tenant_b.id

    async def test_duplicate_slug_within_one_tenant_rejected_at_db_level(self, db):
        from sqlalchemy.exc import IntegrityError

        tenant_a, _tenant_b = await create_two_tenants(db)
        await _register_server(db, tenant_a.id)
        with pytest.raises(IntegrityError):
            await _register_server(db, tenant_a.id)
        await db.rollback()

    async def test_composite_unique_constraint_present(self, db):
        rows = (
            await db.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE tablename = 'mcp_servers' "
                    "AND indexname = 'uq_mcp_servers_tenant_slug'"
                )
            )
        ).fetchall()
        assert rows, "per-tenant (tenant_id, slug) unique constraint missing"
        definition = rows[0][0].lower()
        assert "tenant_id" in definition and "slug" in definition


class TestTenantStampedToolSync:
    async def test_sync_stamps_each_server_tenant_and_namespaces_per_tenant(self, db, monkeypatch):
        from app.services.mcp.tool_sync import ToolSyncService

        tenant_a, tenant_b = await create_two_tenants(db)
        server_a = await _register_server(db, tenant_a.id, name="supabase-A")
        server_b = await _register_server(db, tenant_b.id, name="supabase-B")

        _patch_http(monkeypatch, _tools_list_response(["query", "list_tables"]))

        svc = ToolSyncService()
        counts_a = await svc.sync(server_a, db)
        counts_b = await svc.sync(server_b, db)
        await db.commit()

        assert counts_a["added"] == 2
        assert counts_b["added"] == 2

        from app.db.models.mcp_hub import McpTool

        tools_a = (
            (await db.execute(select(McpTool).where(McpTool.server_id == server_a.id)))
            .scalars()
            .all()
        )
        tools_b = (
            (await db.execute(select(McpTool).where(McpTool.server_id == server_b.id)))
            .scalars()
            .all()
        )
        assert all(t.tenant_id == tenant_a.id for t in tools_a)
        assert all(t.tenant_id == tenant_b.id for t in tools_b)
        # Identical wire names in both tenants — collision is expected and safe.
        assert {t.name for t in tools_a} == {t.name for t in tools_b}
        assert "supabase____query" in {t.name for t in tools_a}

    async def test_each_tenant_sees_only_its_own_tool_list(self, db, monkeypatch):
        from sqlalchemy import select as sel

        from app.db.models.mcp_hub import McpTool
        from app.services.mcp.tool_sync import ToolSyncService

        tenant_a, tenant_b = await create_two_tenants(db)
        server_a = await _register_server(db, tenant_a.id, name="supabase-A2")
        server_b = await _register_server(db, tenant_b.id, name="supabase-B2")

        # Different tool sets per tenant's upstream server.
        server_a.base_url = "http://upstream-a/mcp"
        server_b.base_url = "http://upstream-b/mcp"
        await db.commit()
        responses = {
            "http://upstream-a/mcp": _tools_list_response(["query"]),
            "http://upstream-b/mcp": _tools_list_response(["query", "secret_admin_op"]),
        }
        client = AsyncMock()

        async def _post(url, **kw):
            # Match the response to the tenant's own upstream server.
            return responses[url]

        client.post = AsyncMock(side_effect=_post)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "app.services.mcp.tool_sync.httpx.AsyncClient", lambda **kw: cm
        )

        svc = ToolSyncService()
        await svc.sync(server_a, db)
        await svc.sync(server_b, db)
        await db.commit()

        # Tenant A's resolution of `supabase____query` never yields tenant B rows.
        a_visible = (
            (
                await db.execute(
                    sel(McpTool).where(
                        McpTool.name == "supabase____query",
                        McpTool.tenant_id == tenant_a.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(a_visible) == 1
        assert a_visible[0].server_id == server_a.id
        # The tool that only exists on B's upstream is invisible to tenant A.
        b_only = (
            (
                await db.execute(
                    sel(McpTool).where(
                        McpTool.name == "supabase____secret_admin_op",
                        McpTool.tenant_id == tenant_a.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert b_only == []


class TestSkillBindingAndInvocationContainment:
    async def test_skill_binding_resolves_within_creating_tenant(self, db):
        from sqlalchemy import select as sel

        from app.db.models.mcp_hub import McpTool
        from app.db.models.skills import Skill, SkillToolBinding
        from app.services.agents.tool_naming import parse_tool_name

        tenant_a, tenant_b = await create_two_tenants(db)
        server_a = await _register_server(db, tenant_a.id, name="supabase-A3")
        server_b = await _register_server(db, tenant_b.id, name="supabase-B3")

        # Same tool registered on both tenants' servers.
        tool_a = McpTool(
            server_id=server_a.id, tenant_id=tenant_a.id,
            name="supabase____query", original_name="query", is_active=True,
        )
        tool_b = McpTool(
            server_id=server_b.id, tenant_id=tenant_b.id,
            name="supabase____query", original_name="query", is_active=True,
        )
        db.add_all([tool_a, tool_b])
        await db.commit()

        # Each tenant creates a skill referencing the SAME slug/wire name.
        skill_a = Skill(tenant_id=tenant_a.id, name="run-query")
        skill_b = Skill(tenant_id=tenant_b.id, name="run-query")
        db.add_all([skill_a, skill_b])
        await db.flush()
        db.add_all(
            [
                SkillToolBinding(skill_id=skill_a.id, tool_id=tool_a.id, order=0),
                SkillToolBinding(skill_id=skill_b.id, tool_id=tool_b.id, order=0),
            ]
        )
        await db.commit()

        # Wire format parsing is unchanged.
        server_slug, original = parse_tool_name("supabase____query")
        assert (server_slug, original) == ("supabase", "query")

        # Skill A's binding resolves to tenant A's tool only.
        bound_a = (
            (
                await db.execute(
                    sel(McpTool)
                    .join(SkillToolBinding, SkillToolBinding.tool_id == McpTool.id)
                    .where(
                        SkillToolBinding.skill_id == skill_a.id,
                        McpTool.tenant_id == tenant_a.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(bound_a) == 1 and bound_a[0].server_id == server_a.id
        assert all(t.tenant_id == tenant_a.id for t in bound_a)

    async def test_invocation_resolution_matches_calling_tenant_only(self, db):
        """The runtime lookup (`McpTool.name == wire_name` + session tenant
        scope, per runtime_executor) resolves tenant A's server; tenant B's
        same-named server/credentials are never reachable."""
        from sqlalchemy import select as sel

        from app.db.models.mcp_hub import McpTool
        from app.db.tenant_scoping import apply_tenant_scope, scope_for_session

        tenant_a, tenant_b = await create_two_tenants(db)
        server_a = await _register_server(db, tenant_a.id, name="supabase-A4")
        server_b = await _register_server(db, tenant_b.id, name="supabase-B4")
        db.add_all(
            [
                McpTool(server_id=server_a.id, tenant_id=tenant_a.id,
                        name="supabase____query", original_name="query", is_active=True),
                McpTool(server_id=server_b.id, tenant_id=tenant_b.id,
                        name="supabase____query", original_name="query", is_active=True),
            ]
        )
        await db.commit()

        # Tenant A session: the wire name resolves inside tenant A only.
        apply_tenant_scope(db, tenant_a.id)
        assert scope_for_session(db) == tenant_a.id
        tool = (
            (
                await db.execute(
                    sel(McpTool).where(
                        McpTool.name == "supabase____query",
                        McpTool.is_active.is_(True),
                        McpTool.tenant_id == scope_for_session(db),
                    )
                )
            )
            .scalars()
            .one()
        )
        await db.refresh(tool, ["server"])
        assert tool.server_id == server_a.id
        assert tool.server.tenant_id == tenant_a.id

        # A wire name registered ONLY in tenant B is unresolvable from A.
        db.add(
            McpTool(server_id=server_b.id, tenant_id=tenant_b.id,
                    name="supabase____b_only", original_name="b_only", is_active=True)
        )
        await db.commit()
        miss = (
            (
                await db.execute(
                    sel(McpTool).where(
                        McpTool.name == "supabase____b_only",
                        McpTool.tenant_id == tenant_a.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert miss == []

    async def test_tool_permission_grant_contained_in_granting_tenant(self, db):
        from sqlalchemy import select as sel

        from app.db.models.identity import Role
        from app.db.models.mcp_hub import McpTool, ToolPermission

        tenant_a, tenant_b = await create_two_tenants(db)
        server_a = await _register_server(db, tenant_a.id, name="supabase-A5")
        server_b = await _register_server(db, tenant_b.id, name="supabase-B5")
        tool_a = McpTool(server_id=server_a.id, tenant_id=tenant_a.id,
                         name="supabase____query", original_name="query", is_active=True)
        tool_b = McpTool(server_id=server_b.id, tenant_id=tenant_b.id,
                         name="supabase____query", original_name="query", is_active=True)
        role_a = Role(name=f"tool-role-{uuid.uuid4().hex[:6]}", tenant_id=tenant_a.id)
        db.add_all([tool_a, tool_b, role_a])
        await db.flush()

        grant = ToolPermission(tool_id=tool_a.id, role_id=role_a.id)
        db.add(grant)
        await db.commit()

        # The grant authorizes tenant A's tool only.
        authorized = (
            (
                await db.execute(
                    sel(McpTool)
                    .join(ToolPermission, ToolPermission.tool_id == McpTool.id)
                    .where(
                        ToolPermission.role_id == role_a.id,
                        McpTool.tenant_id == tenant_a.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [t.id for t in authorized] == [tool_a.id]
        # Tenant B's same-named tool remains unauthorized for tenant A principals.
        b_authorized = (
            (
                await db.execute(
                    sel(McpTool)
                    .join(ToolPermission, ToolPermission.tool_id == McpTool.id)
                    .where(
                        ToolPermission.role_id == role_a.id,
                        McpTool.tenant_id == tenant_b.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert b_authorized == []
