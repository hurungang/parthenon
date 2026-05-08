"""API tests for MCP Hub — Sessions and Tool Repository endpoints.

Tests cover the enhance-mcp-hub-skills-sops change:
- Session create/read/update with identity_binding and credential_config
- Credential exclusion: encrypted_credentials absent from all responses
- GET /mcp/tools returns all active tools
- GET /mcp/tools/{id}/skills returns skills bound to a tool
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.db.session import get_db
from app.middleware.auth import JWTAuthMiddleware


# ── Auth/DB helpers ─────────────────────────────────────────────────────────────


def _bypass_auth():
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "admin-sub", "roles": ["admin"]}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _mock_permission_allow():
    from app.services.permissions.permission_engine import AuthorizationResult

    async def mock_authorize(*args, **kwargs):
        return AuthorizationResult(allowed=True, reason="Test override")

    return patch(
        "app.services.permissions.permission_engine.PermissionEngine.authorize",
        mock_authorize,
    )


def _server_id():
    return uuid.uuid4()


def _session_id():
    return uuid.uuid4()


def _make_server(server_id=None):
    sid = server_id or _server_id()
    now = datetime.now(timezone.utc)
    m = MagicMock()
    m.id = sid
    m.name = "Test Server"
    m.slug = "test-server"
    m.description = "A test MCP server"
    m.base_url = "http://mcp.test"
    m.status = "active"
    m.last_synced_at = None
    m.created_at = now
    m.updated_at = now
    return m


def _make_session(server_id=None, session_id=None):
    sid = session_id or _session_id()
    svid = server_id or _server_id()
    now = datetime.now(timezone.utc)
    m = MagicMock()
    m.id = sid
    m.server_id = svid
    m.name = "Primary Session"
    m.description = "Primary binding"
    m.auth_type = "api_key"
    m.identity_subject = "agent-001"
    m.identity_binding = {"agent_id": "agent-001", "realm": "parthenon"}
    m.credential_config = {"required_keys": ["api_key"]}
    m.is_active = True
    m.created_at = now
    m.updated_at = now
    m.connection_test = None
    # encrypted_credentials is present on the model but must not appear in responses
    m.encrypted_credentials = "ENCRYPTED:xyz"
    return m


def _make_tool(server_id=None, tool_id=None):
    tid = tool_id or uuid.uuid4()
    svid = server_id or _server_id()
    now = datetime.now(timezone.utc)
    m = MagicMock()
    m.id = tid
    m.server_id = svid
    m.name = "search"
    m.original_name = "search"
    m.description = "Searches the web"
    m.input_schema = {"type": "object"}
    m.is_active = True
    m.created_at = now
    m.updated_at = now
    # server relationship
    server = MagicMock()
    server.slug = "test-server"
    server.name = "Test Server"
    m.server = server
    # McpToolRead.model_validate reads these directly from the tool object
    m.server_slug = "test-server"
    m.server_name = "Test Server"
    return m


def _db_returning(return_value=None, scalar_all=None):
    """Create a mock DB session returning specified scalars."""
    mock_session = AsyncMock()

    def make_execute_result(val):
        res = MagicMock()
        res.scalar_one_or_none = MagicMock(return_value=val)
        res.scalar_one = MagicMock(return_value=val)
        res.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=scalar_all or []))
        )
        return res

    mock_session.execute = AsyncMock(return_value=make_execute_result(return_value))
    mock_session.get = AsyncMock(return_value=return_value)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.delete = AsyncMock()

    async def override():
        yield mock_session

    return mock_session, override


# ── Session List ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_sessions_returns_200_with_identity_binding():
    """GET /mcp/servers/{id}/sessions returns sessions with identity_binding."""
    server_id = _server_id()
    session = _make_session(server_id=server_id)
    mock_db, db_dep = _db_returning(return_value=MagicMock(), scalar_all=[session])
    # server.get() must return the server
    mock_db.get = AsyncMock(return_value=_make_server(server_id=server_id))

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/mcp/servers/{server_id}/sessions")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["identity_binding"] == {"agent_id": "agent-001", "realm": "parthenon"}
    assert body[0]["credential_config"] == {"required_keys": ["api_key"]}


@pytest.mark.asyncio
async def test_list_sessions_excludes_encrypted_credentials():
    """GET /mcp/servers/{id}/sessions must not return encrypted_credentials."""
    server_id = _server_id()
    session = _make_session(server_id=server_id)
    # return_value=MagicMock() ensures the PlatformUser lookup in require_permission succeeds
    mock_db, db_dep = _db_returning(return_value=MagicMock(), scalar_all=[session])
    mock_db.get = AsyncMock(return_value=_make_server(server_id=server_id))

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/mcp/servers/{server_id}/sessions")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    # encrypted_credentials must never appear in API response
    assert "encrypted_credentials" not in body[0]


# ── Session Create ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_session_with_identity_binding_returns_201():
    """POST /mcp/servers/{id}/sessions with identity_binding returns 201."""
    server_id = _server_id()
    created_session = _make_session(server_id=server_id)
    mock_db, db_dep = _db_returning(return_value=created_session)
    mock_db.get = AsyncMock(return_value=_make_server(server_id=server_id))
    _now = datetime.now(timezone.utc)

    async def _populate_new_session(s):
        s.id = created_session.id
        s.created_at = _now
        s.updated_at = _now
        s.is_active = True

    mock_db.refresh = AsyncMock(side_effect=_populate_new_session)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {
        "name": "Primary Session",
        "auth_type": "api_key",
        "identity_binding": {"agent_id": "agent-001", "realm": "parthenon"},
        "credential_config": {"required_keys": ["api_key"]},
    }

    with _bypass_auth(), _mock_permission_allow():
        with patch("app.core.credential_vault.get_vault") as mock_vault:
            mock_vault.return_value.encrypt = MagicMock(return_value="ENCRYPTED:mock")
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    f"/api/v1/mcp/servers/{server_id}/sessions", json=payload
                )

    assert resp.status_code == 201
    body = resp.json()
    assert body["identity_binding"] == {"agent_id": "agent-001", "realm": "parthenon"}
    assert body["credential_config"] == {"required_keys": ["api_key"]}
    assert "encrypted_credentials" not in body


@pytest.mark.asyncio
async def test_create_session_with_credentials_does_not_return_them():
    """POST /mcp/servers/{id}/sessions: response must not include credentials."""
    server_id = _server_id()
    created_session = _make_session(server_id=server_id)
    mock_db, db_dep = _db_returning(return_value=created_session)
    mock_db.get = AsyncMock(return_value=_make_server(server_id=server_id))
    _now2 = datetime.now(timezone.utc)

    async def _populate_cred_session(s):
        s.id = created_session.id
        s.created_at = _now2
        s.updated_at = _now2
        s.is_active = True

    mock_db.refresh = AsyncMock(side_effect=_populate_cred_session)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {
        "name": "Session With Creds",
        "auth_type": "api_key",
        "credentials": {"api_key": "super-secret-key"},
    }

    with _bypass_auth(), _mock_permission_allow():
        with patch("app.core.credential_vault.get_vault") as mock_vault:
            mock_vault.return_value.encrypt = MagicMock(return_value="ENCRYPTED:mock")
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    f"/api/v1/mcp/servers/{server_id}/sessions", json=payload
                )

    assert resp.status_code == 201
    body = resp.json()
    assert "encrypted_credentials" not in body
    assert "credentials" not in body


# ── Session Update ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_session_with_identity_binding_returns_200():
    """PUT /mcp/servers/{id}/sessions/{sid} with identity_binding update returns 200."""
    server_id = _server_id()
    session_id = _session_id()
    session = _make_session(server_id=server_id, session_id=session_id)
    session.identity_binding = {"agent_id": "updated-agent", "realm": "parthenon"}

    mock_db, db_dep = _db_returning(return_value=session)
    mock_db.refresh = AsyncMock()

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {"identity_binding": {"agent_id": "updated-agent", "realm": "parthenon"}}

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/mcp/servers/{server_id}/sessions/{session_id}", json=payload
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["identity_binding"]["agent_id"] == "updated-agent"
    assert "encrypted_credentials" not in body


# ── Tool Repository ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_all_tools_returns_200():
    """GET /mcp/tools returns 200 with list of active tools."""
    tool = _make_tool()

    mock_db = AsyncMock()
    scalars_result = MagicMock()
    scalars_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[tool]))
    )
    mock_db.execute = AsyncMock(return_value=scalars_result)

    async def db_dep():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/mcp/tools")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)


@pytest.mark.asyncio
async def test_list_all_tools_returns_empty_when_no_active_tools():
    """GET /mcp/tools returns empty list when no active tools exist."""
    mock_db = AsyncMock()
    scalars_result = MagicMock()
    scalars_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    mock_db.execute = AsyncMock(return_value=scalars_result)

    async def db_dep():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/mcp/tools")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_tool_skills_returns_empty_list_for_tool_with_no_bindings():
    """GET /mcp/tools/{id}/skills returns [] for tool with no skill bindings (not 404)."""
    tool_id = uuid.uuid4()
    tool = _make_tool(tool_id=tool_id)

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=tool)
    scalars_result = MagicMock()
    scalars_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    mock_db.execute = AsyncMock(return_value=scalars_result)

    async def db_dep():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/mcp/tools/{tool_id}/skills")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_tool_skills_returns_404_for_unknown_tool():
    """GET /mcp/tools/{id}/skills returns 404 for unknown tool."""
    tool_id = uuid.uuid4()

    mock_db = AsyncMock()
    # Provide a proper execute result so the PlatformUser lookup in require_permission succeeds
    _user_result = MagicMock()
    _user_result.scalar_one_or_none = MagicMock(return_value=MagicMock())
    mock_db.execute = AsyncMock(return_value=_user_result)
    mock_db.get = AsyncMock(return_value=None)

    async def db_dep():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/mcp/tools/{tool_id}/skills")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_request_to_tools_is_rejected():
    """GET /mcp/tools without auth returns 401 or 403."""
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/mcp/tools")

    assert resp.status_code in (401, 403)


# ── OAuth Config CRUD ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_server_with_oauth_config_returns_201():
    """POST /mcp/servers creates a server and returns 201 (oauth_config is set via PUT)."""
    server_id = _server_id()
    now = datetime.now(timezone.utc)

    # require_permission does: execute(select(PlatformUser)...) → user lookup
    # create_mcp_server does:  execute(select(McpServer).where(slug==...)) → slug check
    # These must return different values: truthy user, then None (no slug conflict).
    call_count = [0]

    def _make_execute_result():
        call_count[0] += 1
        result = MagicMock()
        if call_count[0] == 1:
            # First call: user lookup for require_permission — must return a user
            result.scalar_one_or_none = MagicMock(return_value=MagicMock())
        else:
            # Second call: slug uniqueness check — no conflict
            result.scalar_one_or_none = MagicMock(return_value=None)
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        return result

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=lambda *a, **kw: _make_execute_result())
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.delete = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)

    def _populate_server(s):
        s.id = server_id
        s.oauth_config = None
        s.last_synced_at = None
        s.created_at = now
        s.updated_at = now
        s.status = "active"

    mock_db.refresh = AsyncMock(side_effect=lambda s: _populate_server(s))

    async def db_dep():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {
        "name": "OAuth Server",
        "slug": "oauth-server",
        "base_url": "http://mcp.oauth.example.com",
    }

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/mcp/servers", json=payload)

    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_update_server_oauth_config_returns_200():
    """PUT /mcp/servers/{id} with oauth_config saves and returns the config."""
    server_id = _server_id()
    server = _make_server(server_id=server_id)
    server.oauth_config = None

    oauth_cfg = {
        "authorization_url": "https://auth.example.com/oauth/authorize",
        "token_url": "https://auth.example.com/oauth/token",
        "client_id": "mcp-client-id",
        "client_secret": "mcp-client-secret",
        "scope": "read write",
        "redirect_uri": "http://localhost:5173/oauth/callback",
    }

    mock_db, db_dep = _db_returning(return_value=server)
    mock_db.get = AsyncMock(return_value=server)

    def _apply_oauth(s):
        s.oauth_config = oauth_cfg

    mock_db.refresh = AsyncMock(side_effect=lambda s: _apply_oauth(s))

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {"oauth_config": oauth_cfg}

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(f"/api/v1/mcp/servers/{server_id}", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["oauth_config"]["client_id"] == "mcp-client-id"
    assert body["oauth_config"]["authorization_url"] == "https://auth.example.com/oauth/authorize"


@pytest.mark.asyncio
async def test_read_server_returns_oauth_config():
    """GET /mcp/servers/{id} returns oauth_config field in response."""
    server_id = _server_id()
    server = _make_server(server_id=server_id)
    server.oauth_config = {
        "authorization_url": "https://auth.example.com/oauth/authorize",
        "client_id": "mcp-client-id",
        "token_url": "https://auth.example.com/oauth/token",
    }

    mock_db, db_dep = _db_returning(return_value=server)
    mock_db.get = AsyncMock(return_value=server)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/mcp/servers/{server_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert "oauth_config" in body
    assert body["oauth_config"]["client_id"] == "mcp-client-id"


@pytest.mark.asyncio
async def test_read_server_without_oauth_config_returns_null():
    """GET /mcp/servers/{id} returns null for oauth_config when not configured."""
    server_id = _server_id()
    server = _make_server(server_id=server_id)
    server.oauth_config = None

    mock_db, db_dep = _db_returning(return_value=server)
    mock_db.get = AsyncMock(return_value=server)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/mcp/servers/{server_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert "oauth_config" in body
    assert body["oauth_config"] is None


# ── OAuth Authorize Endpoint ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oauth_authorize_with_valid_config_returns_authorization_url():
    """GET /mcp/servers/{id}/oauth/authorize returns authorization_url when fully configured."""
    server_id = _server_id()
    server = _make_server(server_id=server_id)
    server.oauth_config = {
        "authorization_url": "https://auth.example.com/oauth/authorize",
        "token_url": "https://auth.example.com/oauth/token",
        "client_id": "mcp-client-id",
        "client_secret": "mcp-client-secret",
        "scope": "read write",
        "redirect_uri": "http://localhost:5173/oauth/callback",
    }

    mock_db, db_dep = _db_returning(return_value=server)
    mock_db.get = AsyncMock(return_value=server)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/mcp/servers/{server_id}/oauth/authorize")

    assert resp.status_code == 200
    body = resp.json()
    assert "authorization_url" in body
    assert "https://auth.example.com/oauth/authorize" in body["authorization_url"]
    assert "client_id=mcp-client-id" in body["authorization_url"]
    assert "response_type=code" in body["authorization_url"]
    assert "state=" in body["authorization_url"]


@pytest.mark.asyncio
async def test_oauth_authorize_without_config_returns_400():
    """GET /mcp/servers/{id}/oauth/authorize returns 400 when no oauth_config."""
    server_id = _server_id()
    server = _make_server(server_id=server_id)
    server.oauth_config = None

    mock_db, db_dep = _db_returning(return_value=server)
    mock_db.get = AsyncMock(return_value=server)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/mcp/servers/{server_id}/oauth/authorize")

    assert resp.status_code == 400
    assert "OAuth not configured" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_oauth_authorize_with_incomplete_config_returns_400():
    """GET /mcp/servers/{id}/oauth/authorize returns 400 when oauth_config missing required fields."""
    server_id = _server_id()
    server = _make_server(server_id=server_id)
    # Missing token_url and client_secret — but also missing client_id triggers 400
    server.oauth_config = {
        "authorization_url": "https://auth.example.com/oauth/authorize",
        # Missing client_id
    }

    mock_db, db_dep = _db_returning(return_value=server)
    mock_db.get = AsyncMock(return_value=server)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/mcp/servers/{server_id}/oauth/authorize")

    assert resp.status_code == 400
    assert "Incomplete OAuth configuration" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_oauth_authorize_returns_unique_state_per_request():
    """Each call to oauth/authorize generates a unique state token."""
    server_id = _server_id()
    server = _make_server(server_id=server_id)
    server.oauth_config = {
        "authorization_url": "https://auth.example.com/oauth/authorize",
        "token_url": "https://auth.example.com/oauth/token",
        "client_id": "mcp-client-id",
        "client_secret": "mcp-client-secret",
    }

    mock_db, db_dep = _db_returning(return_value=server)
    mock_db.get = AsyncMock(return_value=server)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp1 = await client.get(f"/api/v1/mcp/servers/{server_id}/oauth/authorize")
            resp2 = await client.get(f"/api/v1/mcp/servers/{server_id}/oauth/authorize")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    url1 = resp1.json()["authorization_url"]
    url2 = resp2.json()["authorization_url"]
    # State tokens must differ
    state1 = dict(p.split("=") for p in url1.split("?")[1].split("&"))["state"]
    state2 = dict(p.split("=") for p in url2.split("?")[1].split("&"))["state"]
    assert state1 != state2


@pytest.mark.asyncio
async def test_oauth_authorize_includes_scope_when_configured():
    """GET oauth/authorize includes scope param in URL when scope is set in oauth_config."""
    server_id = _server_id()
    server = _make_server(server_id=server_id)
    server.oauth_config = {
        "authorization_url": "https://auth.example.com/oauth/authorize",
        "token_url": "https://auth.example.com/oauth/token",
        "client_id": "mcp-client-id",
        "client_secret": "mcp-client-secret",
        "scope": "read write tools",
    }

    mock_db, db_dep = _db_returning(return_value=server)
    mock_db.get = AsyncMock(return_value=server)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/mcp/servers/{server_id}/oauth/authorize")

    assert resp.status_code == 200
    assert "scope=" in resp.json()["authorization_url"]


# ── OAuth Callback Endpoint ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oauth_callback_with_valid_code_creates_session():
    """GET /mcp/oauth/callback with valid code+state creates MCP session with oauth2 auth_type."""
    from app.api.v1.mcp_hub import _mcp_oauth_states

    server_id = _server_id()
    state = "test-state-token-abc123"

    # Pre-populate state as if authorize endpoint was called
    _mcp_oauth_states[state] = {
        "server_id": str(server_id),
        "client_id": "mcp-client-id",
        "client_secret": "mcp-client-secret",
        "token_url": "https://auth.example.com/oauth/token",
        "redirect_uri": "http://localhost:5173/oauth/callback",
    }

    created_session = _make_session(server_id=server_id)
    created_session.auth_type = "oauth2"
    now = datetime.now(timezone.utc)
    created_session.created_at = now
    created_session.updated_at = now

    mock_db, db_dep = _db_returning(return_value=created_session)

    async def _populate_oauth_session(s):
        s.id = created_session.id
        s.created_at = now
        s.updated_at = now
        s.is_active = True
        s.auth_type = "oauth2"
        s.name = created_session.name
        s.server_id = server_id
        s.description = "Auto-created via OAuth flow"
        s.identity_subject = None
        s.identity_binding = None
        s.credential_config = None

    mock_db.refresh = AsyncMock(side_effect=_populate_oauth_session)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    mock_token_response = {
        "access_token": "access-token-abc",
        "refresh_token": "refresh-token-xyz",
        "token_type": "Bearer",
        "expires_in": 3600,
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=mock_token_response)
        mock_post.return_value = mock_response

        with patch("app.core.credential_vault.get_vault") as mock_vault:
            mock_vault.return_value.encrypt = MagicMock(return_value="ENCRYPTED:tokens")
            with _bypass_auth():
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.get(
                        "/api/v1/mcp/oauth/callback",
                        params={"code": "auth-code-123", "state": state},
                    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "session_id" in body


@pytest.mark.asyncio
async def test_oauth_callback_with_invalid_state_returns_400():
    """GET /mcp/oauth/callback with unknown state returns 400."""
    app = create_app()

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/mcp/oauth/callback",
                params={"code": "some-code", "state": "nonexistent-state-xyz"},
            )

    assert resp.status_code == 400
    assert "Invalid or expired OAuth state" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_oauth_callback_state_is_consumed_after_use():
    """OAuth state token is consumed on first use — replay returns 400."""
    from app.api.v1.mcp_hub import _mcp_oauth_states

    server_id = _server_id()
    state = "one-time-state-token-xyz"

    _mcp_oauth_states[state] = {
        "server_id": str(server_id),
        "client_id": "mcp-client-id",
        "client_secret": "mcp-client-secret",
        "token_url": "https://auth.example.com/oauth/token",
        "redirect_uri": "http://localhost:5173/oauth/callback",
    }

    created_session = _make_session(server_id=server_id)
    now = datetime.now(timezone.utc)

    async def _populate(s):
        s.id = created_session.id
        s.created_at = now
        s.updated_at = now
        s.is_active = True
        s.auth_type = "oauth2"
        s.name = "OAuth Session"
        s.server_id = server_id
        s.description = "Auto-created via OAuth flow"
        s.identity_subject = None
        s.identity_binding = None
        s.credential_config = None

    mock_db, db_dep = _db_returning(return_value=created_session)
    mock_db.refresh = AsyncMock(side_effect=_populate)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    mock_token_response = {"access_token": "tok", "token_type": "Bearer"}

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=mock_token_response)
        mock_post.return_value = mock_response

        with patch("app.core.credential_vault.get_vault") as mock_vault:
            mock_vault.return_value.encrypt = MagicMock(return_value="ENCRYPTED:tokens")
            with _bypass_auth():
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    # First use succeeds
                    resp1 = await client.get(
                        "/api/v1/mcp/oauth/callback",
                        params={"code": "auth-code-first", "state": state},
                    )
                    # Replay with same state must fail
                    resp2 = await client.get(
                        "/api/v1/mcp/oauth/callback",
                        params={"code": "auth-code-replay", "state": state},
                    )

    assert resp1.status_code == 200
    assert resp2.status_code == 400


@pytest.mark.asyncio
async def test_oauth_callback_encrypts_tokens_before_storing():
    """OAuth callback stores encrypted tokens — vault encrypt is called."""
    from app.api.v1.mcp_hub import _mcp_oauth_states

    server_id = _server_id()
    state = "encrypt-test-state"

    _mcp_oauth_states[state] = {
        "server_id": str(server_id),
        "client_id": "mcp-client-id",
        "client_secret": "mcp-secret",
        "token_url": "https://auth.example.com/oauth/token",
        "redirect_uri": "http://localhost:5173/oauth/callback",
    }

    created_session = _make_session(server_id=server_id)
    now = datetime.now(timezone.utc)

    async def _populate(s):
        s.id = created_session.id
        s.created_at = now
        s.updated_at = now
        s.is_active = True
        s.auth_type = "oauth2"
        s.name = "OAuth Session"
        s.server_id = server_id
        s.description = "Auto-created via OAuth flow"
        s.identity_subject = None
        s.identity_binding = None
        s.credential_config = None

    mock_db, db_dep = _db_returning(return_value=created_session)
    mock_db.refresh = AsyncMock(side_effect=_populate)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"access_token": "tok", "token_type": "Bearer"})
        mock_post.return_value = mock_response

        with patch("app.api.v1.mcp_hub.get_vault") as mock_vault:
            mock_encrypt = MagicMock(return_value="ENCRYPTED:tokens")
            mock_vault.return_value.encrypt = mock_encrypt

            with _bypass_auth():
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.get(
                        "/api/v1/mcp/oauth/callback",
                        params={"code": "auth-code", "state": state},
                    )

    assert resp.status_code == 200
    # Vault encrypt must have been called to store tokens securely
    mock_encrypt.assert_called_once()
