"""FIX-20261101-014511 — integration::control_center entity-view permission.

The per-tenant Control Center MCP entity (slug ``cc``) is a protected
integration: only roles granted ``integration::control_center:read`` may SEE
it (MCP Hub list/detail, management toolset reads) and only
``integration::control_center:manage`` may define anything around it
(update/delete/sync, sessions, tool grants).

Non-cc servers keep behaving exactly as before (plain
``integration::mcp_hub`` rules).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.db.models.mcp_hub import McpSessionAuthType
from app.db.session import get_db
from app.middleware.auth import JWTAuthMiddleware
from app.core.resource_types import (
    RT_INTEGRATION_CONTROL_CENTER,
    ResourceTypeManifest,
    MODULE_GROUPS,
)

CC_SLUG = "cc"


# ── Manifest registration ──────────────────────────────────────────────────────


def test_manifest_registers_control_center():
    """The new RT is registered in the backend manifest with read+manage."""
    assert RT_INTEGRATION_CONTROL_CENTER == "integration::control_center"
    assert RT_INTEGRATION_CONTROL_CENTER in ResourceTypeManifest
    assert ResourceTypeManifest[RT_INTEGRATION_CONTROL_CENTER]["actions"] == [
        "read",
        "manage",
    ]


def test_manifest_control_center_in_integration_group():
    """Wildcard grants (integration::*) must cover the new RT."""
    assert RT_INTEGRATION_CONTROL_CENTER in MODULE_GROUPS["integration"]


# ── API test helpers (mock pattern of test_mcp_hub_api.py) ────────────────────


def _bypass_auth():
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "user-sub", "roles": ["user"]}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _mock_permissions(cc_allowed: bool):
    """Allow every integration::mcp_hub check; gate control_center by flag."""
    from app.services.permissions.permission_engine import AuthorizationResult

    async def mock_authorize(self, *args, **kwargs):
        module = kwargs.get("module") or (args[2] if len(args) > 2 else "")
        if module == RT_INTEGRATION_CONTROL_CENTER and not cc_allowed:
            return AuthorizationResult(allowed=False, reason="no grant")
        return AuthorizationResult(allowed=True, reason="ok")

    return patch(
        "app.services.permissions.permission_engine.PermissionEngine.authorize",
        mock_authorize,
    )


def _make_server(slug: str):
    now = datetime.now(timezone.utc)
    m = MagicMock()
    m.id = uuid.uuid4()
    m.name = slug
    m.slug = slug
    m.description = f"{slug} server"
    m.base_url = f"http://{slug}.test"
    m.oauth_config = None
    m.status = "active"
    m.last_synced_at = None
    m.sessions = []
    m.tenant_id = uuid.uuid4()
    m.created_at = now
    m.updated_at = now
    return m


def _make_tool(server):
    now = datetime.now(timezone.utc)
    m = MagicMock()
    m.id = uuid.uuid4()
    m.server_id = server.id
    m.name = f"{server.slug}____do_thing"
    m.original_name = "do_thing"
    m.description = "A tool"
    m.input_schema = {"type": "object"}
    m.is_active = True
    m.created_at = now
    m.updated_at = now
    m.server_slug = server.slug
    m.server_name = server.slug
    m.server = server
    return m


def _mock_db(servers=None, single=None):
    """Mock async DB session.

    ``execute`` results expose scalars().all() → servers (list queries) and a
    truthy scalar_one_or_none (PlatformUser identity lookups succeed).
    ``get`` returns ``single`` (or, for a two-element sequence, successive
    values — e.g. tool then parent server).
    """
    mock = AsyncMock()
    result = MagicMock()
    result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=list(servers or [])))
    )
    result.scalar_one_or_none = MagicMock(return_value=MagicMock())  # PlatformUser
    result.first = MagicMock(return_value=None)
    mock.execute = AsyncMock(return_value=result)
    if isinstance(single, (list, tuple)):
        mock.get = AsyncMock(side_effect=list(single))
    else:
        mock.get = AsyncMock(return_value=single)
    mock.add = MagicMock()
    mock.flush = AsyncMock()
    mock.refresh = AsyncMock()
    mock.delete = AsyncMock()

    async def dep():
        yield mock

    return mock, dep


async def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── MCP Hub REST ───────────────────────────────────────────────────────────────


class TestCcListAndDetail:
    @pytest.mark.asyncio
    async def test_list_without_read_filters_cc(self):
        cc = _make_server(CC_SLUG)
        normal = _make_server("supabase")
        mock_db, dep = _mock_db(servers=[cc, normal])
        app = create_app()
        app.dependency_overrides[get_db] = dep
        with _bypass_auth(), _mock_permissions(cc_allowed=False):
            async with await _client(app) as client:
                resp = await client.get("/api/v1/mcp/servers")
        assert resp.status_code == 200
        slugs = [s["slug"] for s in resp.json()]
        assert CC_SLUG not in slugs
        assert "supabase" in slugs

    @pytest.mark.asyncio
    async def test_list_with_read_includes_cc(self):
        cc = _make_server(CC_SLUG)
        normal = _make_server("supabase")
        mock_db, dep = _mock_db(servers=[cc, normal])
        app = create_app()
        app.dependency_overrides[get_db] = dep
        with _bypass_auth(), _mock_permissions(cc_allowed=True):
            async with await _client(app) as client:
                resp = await client.get("/api/v1/mcp/servers")
        assert resp.status_code == 200
        slugs = [s["slug"] for s in resp.json()]
        assert CC_SLUG in slugs

    @pytest.mark.asyncio
    async def test_get_cc_without_read_404_no_leak(self):
        cc = _make_server(CC_SLUG)
        mock_db, dep = _mock_db(single=cc)
        app = create_app()
        app.dependency_overrides[get_db] = dep
        with _bypass_auth(), _mock_permissions(cc_allowed=False):
            async with await _client(app) as client:
                resp = await client.get(f"/api/v1/mcp/servers/{cc.id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_cc_with_read_200(self):
        cc = _make_server(CC_SLUG)
        mock_db, dep = _mock_db(single=cc)
        app = create_app()
        app.dependency_overrides[get_db] = dep
        with _bypass_auth(), _mock_permissions(cc_allowed=True):
            async with await _client(app) as client:
                resp = await client.get(f"/api/v1/mcp/servers/{cc.id}")
        assert resp.status_code == 200
        assert resp.json()["slug"] == CC_SLUG


class TestCcMutations:
    async def _update(self, cc_allowed: bool):
        cc = _make_server(CC_SLUG)
        mock_db, dep = _mock_db(single=cc)
        app = create_app()
        app.dependency_overrides[get_db] = dep
        with _bypass_auth(), _mock_permissions(cc_allowed=cc_allowed):
            async with await _client(app) as client:
                resp = await client.put(
                    f"/api/v1/mcp/servers/{cc.id}", json={"description": "x"}
                )
        return resp

    @pytest.mark.asyncio
    async def test_update_cc_without_manage_403_structured(self):
        # FIX-20261101-090438: immutability is unconditional and checked
        # BEFORE the manage-permission gate, so even the permission denial
        # is replaced by the system-managed rejection.
        resp = await self._update(cc_allowed=False)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "system_managed_integration"

    @pytest.mark.asyncio
    async def test_update_cc_with_manage_rejected_system_managed(self):
        # FIX-20261101-090438: the cc entity is system-managed — even
        # integration::control_center:manage holders cannot mutate it.
        resp = await self._update(cc_allowed=True)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "system_managed_integration"

    @pytest.mark.asyncio
    async def test_delete_cc_without_manage_403(self):
        cc = _make_server(CC_SLUG)
        mock_db, dep = _mock_db(single=cc)
        app = create_app()
        app.dependency_overrides[get_db] = dep
        with _bypass_auth(), _mock_permissions(cc_allowed=False):
            async with await _client(app) as client:
                resp = await client.delete(f"/api/v1/mcp/servers/{cc.id}")
        assert resp.status_code == 403


# ── FIX-20261101-090438 — cc entity is SYSTEM-MANAGED and sessionless ──────────


class TestCcSystemManagedImmutable:
    """Nobody — not even manage holders or wildcards — may mutate the cc entity."""

    async def _call(self, method: str, path: str, cc_allowed: bool = True, **kw):
        cc = _make_server(CC_SLUG)
        mock_db, dep = _mock_db(single=cc)
        app = create_app()
        app.dependency_overrides[get_db] = dep
        with _bypass_auth(), _mock_permissions(cc_allowed=cc_allowed):
            async with await _client(app) as client:
                return await getattr(client, method)(path, **kw)

    @pytest.mark.asyncio
    async def test_delete_cc_with_manage_rejected(self):
        cc = _make_server(CC_SLUG)
        resp = await self._call("delete", f"/api/v1/mcp/servers/{cc.id}")
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "system_managed_integration"
        assert "system-managed" in resp.json()["detail"]["detail"]

    @pytest.mark.asyncio
    async def test_sync_cc_with_manage_rejected(self):
        cc = _make_server(CC_SLUG)
        resp = await self._call("post", f"/api/v1/mcp/servers/{cc.id}/sync")
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "system_managed_integration"

    @pytest.mark.asyncio
    async def test_oauth_authorize_cc_with_manage_rejected(self):
        cc = _make_server(CC_SLUG)
        resp = await self._call(
            "post", f"/api/v1/mcp/servers/{cc.id}/oauth/authorize", json=None
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "system_managed_integration"

    @pytest.mark.asyncio
    async def test_update_cc_wildcard_grant_rejected(self):
        """Wildcard grants (integration::*) do not unlock the cc entity either."""
        cc = _make_server(CC_SLUG)
        resp = await self._call(
            "put", f"/api/v1/mcp/servers/{cc.id}", json={"description": "x"}
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "system_managed_integration"

    @pytest.mark.asyncio
    async def test_create_session_on_cc_rejected(self):
        cc = _make_server(CC_SLUG)
        resp = await self._call(
            "post",
            f"/api/v1/mcp/servers/{cc.id}/sessions",
            json={"name": "s", "auth_type": "passthrough"},
        )
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == "system_managed_integration"
        assert "not supported" in detail["detail"]

    @pytest.mark.asyncio
    async def test_update_session_on_cc_rejected(self):
        cc = _make_server(CC_SLUG)
        resp = await self._call(
            "put",
            f"/api/v1/mcp/servers/{cc.id}/sessions/{uuid.uuid4()}",
            json={"description": "x"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "system_managed_integration"

    @pytest.mark.asyncio
    async def test_delete_session_on_cc_rejected(self):
        cc = _make_server(CC_SLUG)
        resp = await self._call(
            "delete", f"/api/v1/mcp/servers/{cc.id}/sessions/{uuid.uuid4()}"
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "system_managed_integration"

    @pytest.mark.asyncio
    async def test_list_cc_sessions_harmless(self):
        """Reading existing cc session rows stays allowed (may return empty)."""
        cc = _make_server(CC_SLUG)
        mock_db, dep = _mock_db(single=cc)
        empty = MagicMock()
        empty.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[]))
        )
        mock_db.execute = AsyncMock(return_value=empty)
        app = create_app()
        app.dependency_overrides[get_db] = dep
        with _bypass_auth(), _mock_permissions(cc_allowed=True):
            async with await _client(app) as client:
                resp = await client.get(f"/api/v1/mcp/servers/{cc.id}/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_non_cc_sessions_still_creatable(self):
        """Plain servers keep their normal session lifecycle."""
        normal = _make_server("supabase")
        mock_db, dep = _mock_db(single=normal)
        # Refresh populates ORM defaults (timestamps) for the created row.
        async def _populate(obj, *_a, **_k):
            from datetime import datetime, timezone as _tz
            now = datetime.now(_tz.utc)
            obj.id = uuid.uuid4()
            obj.created_at = now
            obj.updated_at = now
            obj.server_id = normal.id
            obj.name = "s"
            obj.auth_type = McpSessionAuthType.passthrough
            obj.identity_subject = None
            obj.identity_binding = None
            obj.credential_config = None
            obj.oauth_expires_at = None
            obj.oauth_refresh_expires_at = None
            obj.last_token_refresh_at = None
            obj.last_token_refresh_outcome = None
            obj.token_health_state = None
            obj.oauth_metadata = None
            obj.requires_reauth = False
            obj.last_refresh_error = None
            obj.is_active = True
            obj.is_default = True
        mock_db.refresh = _populate
        app = create_app()
        app.dependency_overrides[get_db] = dep
        with _bypass_auth(), _mock_permissions(cc_allowed=False), patch(
            "app.api.v1.mcp_hub.test_mcp_session_connection", new=AsyncMock()
        ):
            async with await _client(app) as client:
                resp = await client.post(
                    f"/api/v1/mcp/servers/{normal.id}/sessions",
                    json={"name": "s", "auth_type": "passthrough"},
                )
        # Passthrough path: created (mock DB) — NOT rejected as system-managed.
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_non_cc_server_unaffected_without_cc_grant(self):
        """A plain mcp_hub user keeps full power over ordinary servers."""
        normal = _make_server("supabase")
        mock_db, dep = _mock_db(single=normal)
        app = create_app()
        app.dependency_overrides[get_db] = dep
        with _bypass_auth(), _mock_permissions(cc_allowed=False):
            async with await _client(app) as client:
                resp = await client.put(
                    f"/api/v1/mcp/servers/{normal.id}", json={"description": "y"}
                )
        assert resp.status_code == 200


class TestCcToolGrants:
    @pytest.mark.asyncio
    async def test_grant_on_cc_tool_without_manage_403_structured(self):
        from app.schemas.mcp_hub import ToolPermissionCreate

        cc = _make_server(CC_SLUG)
        tool = _make_tool(cc)
        mock_db, dep = _mock_db(single=[tool, cc])
        app = create_app()
        app.dependency_overrides[get_db] = dep
        body = ToolPermissionCreate(role_id=str(uuid.uuid4())).model_dump(mode="json")
        with _bypass_auth(), _mock_permissions(cc_allowed=False):
            async with await _client(app) as client:
                resp = await client.post(
                    f"/api/v1/mcp/tools/{tool.id}/permissions", json=body
                )
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["required_permission"]["resource_type"] == RT_INTEGRATION_CONTROL_CENTER

    @pytest.mark.asyncio
    async def test_grant_on_cc_tool_with_manage_allowed(self):
        from app.schemas.mcp_hub import ToolPermissionCreate

        cc = _make_server(CC_SLUG)
        tool = _make_tool(cc)
        mock_db, dep = _mock_db(single=[tool, cc])
        # execute calls: 1) require_permission's PlatformUser lookup (truthy),
        # 2) identity_has_permission's PlatformUser lookup (truthy),
        # 3) duplicate-permission probe (None → no conflict)
        user_hit = MagicMock()
        user_hit.scalar_one_or_none = MagicMock(return_value=MagicMock())
        dup_hit = MagicMock()
        dup_hit.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute = AsyncMock(side_effect=[user_hit, user_hit, dup_hit])

        async def _populate(obj, *_a, **_k):
            obj.id = uuid.uuid4()
            from datetime import datetime, timezone as _tz

            now = datetime.now(_tz.utc)
            obj.created_at = now
            obj.updated_at = now
            obj.tool_id = tool.id
            obj.role_id = uuid.UUID(body["role_id"])

        mock_db.refresh = _populate
        app = create_app()
        app.dependency_overrides[get_db] = dep
        body = ToolPermissionCreate(role_id=str(uuid.uuid4())).model_dump(mode="json")
        with _bypass_auth(), _mock_permissions(cc_allowed=True):
            async with await _client(app) as client:
                resp = await client.post(
                    f"/api/v1/mcp/tools/{tool.id}/permissions", json=body
                )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_list_cc_tools_without_read_404(self):
        cc = _make_server(CC_SLUG)
        mock_db, dep = _mock_db(single=cc)
        app = create_app()
        app.dependency_overrides[get_db] = dep
        with _bypass_auth(), _mock_permissions(cc_allowed=False):
            async with await _client(app) as client:
                resp = await client.get(f"/api/v1/mcp/servers/{cc.id}/tools")
        assert resp.status_code == 404


# ── Management toolset (assistant reads) ───────────────────────────────────────


class TestManagementToolsetCc:
    @pytest.mark.asyncio
    async def test_list_mcp_servers_omits_cc_without_read(self):
        from app.api.v1.internal.management_tools import _list_resource, _cc_permitted

        cc = _make_server(CC_SLUG)
        normal = _make_server("supabase")

        db = AsyncMock()
        result = MagicMock()
        result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[cc, normal]))
        )
        db.execute = AsyncMock(return_value=result)

        async def fake_permitted(db_, sub, tenant_id, action):
            return False

        with patch(
            "app.api.v1.internal.management_tools._cc_permitted", fake_permitted
        ):
            out = await _list_resource(
                db, "mcp_servers", {}, "tenant-1", user_sub="user-sub"
            )
        slugs = [r["slug"] for r in out["records"]]
        assert CC_SLUG not in slugs
        assert "supabase" in slugs

    @pytest.mark.asyncio
    async def test_get_cc_without_read_404(self):
        from app.api.v1.internal.management_tools import _get_resource
        from fastapi import HTTPException

        cc = _make_server(CC_SLUG)
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=cc)
        db.execute = AsyncMock(return_value=result)

        async def fake_permitted(db_, sub, tenant_id, action):
            return False

        with patch(
            "app.api.v1.internal.management_tools._cc_permitted", fake_permitted
        ):
            with pytest.raises(HTTPException) as exc:
                await _get_resource(
                    db, "mcp_servers", {"name": "cc"}, "tenant-1", user_sub="u"
                )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_cc_with_read_returns_record(self):
        from app.api.v1.internal.management_tools import _get_resource

        cc = _make_server(CC_SLUG)
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=cc)
        db.execute = AsyncMock(return_value=result)

        async def fake_permitted(db_, sub, tenant_id, action):
            return True

        with patch(
            "app.api.v1.internal.management_tools._cc_permitted", fake_permitted
        ):
            out = await _get_resource(
                db, "mcp_servers", {"name": "cc"}, "tenant-1", user_sub="u"
            )
        assert out["record"]["slug"] == CC_SLUG


# ── FIX-20261101-090438 — system-managed flag in API responses + seeder ────────


class TestSystemManagedFlag:
    def test_read_schema_flags_cc_as_system_managed(self):
        from app.schemas.mcp_hub import McpServerRead

        now = datetime.now(timezone.utc)
        read = McpServerRead(
            id=uuid.uuid4(),
            name="Control Center",
            slug=CC_SLUG,
            description=None,
            base_url="",
            oauth_config=None,
            status="active",
            last_synced_at=None,
            session_count=0,
            created_at=now,
            updated_at=now,
        )
        assert read.is_system_managed is True

    def test_read_schema_flags_virtual_system_and_decision(self):
        from app.schemas.mcp_hub import McpServerRead

        now = datetime.now(timezone.utc)
        for slug in ("system", "decision"):
            read = McpServerRead(
                id=uuid.uuid4(),
                name=slug,
                slug=slug,
                description=None,
                base_url="",
                oauth_config=None,
                status="active",
                last_synced_at=None,
                session_count=0,
                created_at=now,
                updated_at=now,
            )
            assert read.is_system_managed is True, slug

    def test_read_schema_normal_servers_not_flagged(self):
        from app.schemas.mcp_hub import McpServerRead

        now = datetime.now(timezone.utc)
        read = McpServerRead(
            id=uuid.uuid4(),
            name="supabase",
            slug="supabase",
            description=None,
            base_url="http://x",
            oauth_config=None,
            status="active",
            last_synced_at=None,
            session_count=0,
            created_at=now,
            updated_at=now,
        )
        assert read.is_system_managed is False

    @pytest.mark.asyncio
    async def test_seeder_sets_and_refreshes_cc_entity(self):
        """The seeder keeps the cc McpServer canonical on every run (idempotent)."""
        from types import SimpleNamespace

        from app.services.agents.assistant_seeder import AssistantSeeder
        from app.services.agents.system_tool_registry import SystemToolRegistry

        tenant_id = uuid.uuid4()
        cc = SimpleNamespace(
            id=uuid.uuid5(uuid.NAMESPACE_OID, f"parthenon:cc-server:{tenant_id}"),
            tenant_id=tenant_id,
            name="Drifted Name",
            slug="cc",
            description="stale",
            base_url="http://accidentally-set.test",
            status="inactive",
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=cc)
        session.add = MagicMock()
        session.flush = AsyncMock()
        result = MagicMock()
        result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[]))
        )
        session.execute = AsyncMock(return_value=result)

        # No missing tools → only the parent-server refresh runs.
        with patch.object(
            SystemToolRegistry, "get_cc_mcp_hub_entries", return_value=[]
        ):
            await AssistantSeeder()._ensure_management_tool_rows(session, tenant_id)

        assert cc.slug == CC_SLUG
        assert cc.name == "Control Center"
        assert cc.status == "active"
        assert cc.base_url == ""
        session.add.assert_not_called()
