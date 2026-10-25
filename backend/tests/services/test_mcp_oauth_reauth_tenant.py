"""Regression tests: MCP OAuth re-authentication token mismatch.

Root cause: the OAuth callback always created a NEW McpSession with the
refreshed credentials, while the tool-call reader resolves sessions by
FIXED IDs (``AgentRoleMcpSession.mcp_session_id`` role assignments and the
``is_default`` flag).  Those fixed IDs kept pointing at the superseded
session, so tool calls kept using the stale, expired token even after a
successful re-authentication.

Fix: (1) when the flow is started for an existing session
(``reauth_session_id`` in the OAuth state), the callback updates that row
IN PLACE; (2) when a new session is created, prior active OAuth sessions
of the server are superseded — role assignments and the default flag are
migrated to the new row and the old rows are deactivated.

Tenant note: McpSession is parent-scoped (tenant-agnostic) — isolation is
inherited through the tenant-scoped McpServer parent join, so a
cross-tenant reauth_session_id resolves to None and the flow falls back
to creating a new session (never updates another tenant's row).
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.mcp_oauth_service import (
    handle_oauth_callback,
    initiate_oauth_flow,
    mcp_oauth_states,
)

from tests.services.test_mcp_oauth_service import (
    _mock_vault_ctx,
    _resp,
    _token_exchange_client,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _setup_reauth_state(
    server_id: str,
    reauth_session_id: str | None,
    state: str = "reauth-state",
) -> str:
    """Populate mcp_oauth_states with a pending re-auth flow entry."""
    mcp_oauth_states[state] = {
        "server_id": server_id,
        "client_id": "cb-client",
        "client_secret": "cb-secret",
        "token_url": "https://auth.example.com/token",
        "redirect_uri": "http://localhost:5173/oauth/callback",
        "code_verifier": "v" * 43,
        "session_name": None,
        "session_description": None,
        "reauth_session_id": reauth_session_id,
        "expires_at": (
            datetime.now(tz=timezone.utc) + timedelta(minutes=15)
        ).isoformat(),
    }
    return state


def _result(values=None, scalar=None, scalars_all=None):
    """Mock db.execute result with the accessors the callback uses."""
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=scalar)
    r.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=scalars_all or []))
    )
    if values is not None:
        r.all = MagicMock(return_value=values)
    return r


def _make_db(server, execute_results: list):
    """Mock AsyncSession: first execute returns the server, then queued results."""
    db = AsyncMock()
    calls = {"n": 0}

    async def _execute(stmt, *a, **kw):
        idx = calls["n"]
        calls["n"] += 1
        if idx == 0:
            return _result(scalar=server)
        if idx - 1 < len(execute_results):
            return execute_results[idx - 1]
        return _result()

    db.execute = AsyncMock(side_effect=_execute)

    async def _refresh(obj):
        obj.id = uuid.uuid4()

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


def _oauth2_session(
    session_id=None,
    is_active=True,
    is_default=False,
    expires_at=None,
):
    from app.db.models.mcp_hub import McpSessionAuthType

    s = MagicMock()
    s.id = session_id or uuid.uuid4()
    s.server_id = uuid.uuid4()
    s.auth_type = McpSessionAuthType.oauth2
    s.is_active = is_active
    s.is_default = is_default
    s.oauth_expires_at = expires_at
    s.encrypted_credentials = "old-encrypted-blob"
    return s


# ── 1. Re-auth updates the EXISTING session row in place ──────────────────────

@pytest.mark.asyncio
async def test_reauth_updates_existing_session_in_place():
    """State carries reauth_session_id → the existing row's credentials are
    updated; no duplicate session is created (db.add never called)."""
    from app.db.models.mcp_hub import McpSessionAuthType

    server = MagicMock()
    server.id = uuid.uuid4()
    server.base_url = "http://mcp.example.com"
    server.oauth_config = None

    existing = _oauth2_session(is_default=True)
    db = _make_db(server, execute_results=[_result(scalar=existing)])

    mcp_oauth_states.clear()
    state = _setup_reauth_state(str(server.id), str(existing.id))

    with _mock_vault_ctx(), \
         patch(
             "app.services.mcp_oauth_service.httpx.AsyncClient",
             return_value=_token_exchange_client(200, tokens={
                 "access_token": "acc-tok",
                 "refresh_token": "ref-tok",
                 "expires_in": 3600,
                 "refresh_expires_in": 86400,
             }),
         ), \
         patch("app.services.mcp_oauth_service._initialize_mcp_session",
               AsyncMock(return_value="fresh-upstream-id")), \
         patch("app.services.mcp.tool_sync.ToolSyncService"):
        result = await handle_oauth_callback(code="auth-code", state=state, db=db)

    assert result["success"] is True
    # The SAME session row is returned and updated in place
    assert result["session_id"] == str(existing.id)
    assert existing.encrypted_credentials == "encrypted-blob"
    assert existing.oauth_expires_at is not None
    assert existing.oauth_refresh_expires_at is not None
    assert existing.identity_binding == {"mcp_session_id": "fresh-upstream-id"}
    assert existing.is_active is True
    # No duplicate row created
    db.add.assert_not_called()
    # State consumed
    assert state not in mcp_oauth_states


@pytest.mark.asyncio
async def test_reauth_flow_stores_reauth_session_id_in_state():
    """initiate_oauth_flow(session_id=...) records reauth_session_id in state."""
    server = MagicMock()
    server.id = uuid.uuid4()
    server.oauth_config = {
        "authorization_url": "https://auth.example.com/authorize",
        "token_url": "https://auth.example.com/token",
        "client_id": "static-client",
    }
    db = AsyncMock()
    db.get = AsyncMock(return_value=server)

    mcp_oauth_states.clear()
    target = uuid.uuid4()
    await initiate_oauth_flow(server.id, db, session_id=target)

    stored = next(iter(mcp_oauth_states.values()))
    assert stored["reauth_session_id"] == str(target)


# ── 2. Tenant isolation: cross-tenant session id falls back to a new row ──────

@pytest.mark.asyncio
async def test_reauth_cross_tenant_session_id_creates_new_session():
    """A reauth_session_id from another tenant resolves to None through the
    tenant-scoped McpServer join → the flow falls back to creating a NEW
    session in the caller's tenant; the foreign row is never touched."""
    server = MagicMock()
    server.id = uuid.uuid4()
    server.base_url = "http://mcp.example.com"
    server.oauth_config = None

    foreign_session = _oauth2_session()
    # execute #1: reauth lookup → None (cross-tenant miss)
    db = _make_db(server, execute_results=[_result(scalar=None)])

    mcp_oauth_states.clear()
    state = _setup_reauth_state(str(server.id), str(foreign_session.id))

    with _mock_vault_ctx(), \
         patch(
             "app.services.mcp_oauth_service.httpx.AsyncClient",
             return_value=_token_exchange_client(200),
         ), \
         patch("app.services.mcp_oauth_service._initialize_mcp_session",
               AsyncMock(return_value="upstream-id")), \
         patch("app.services.mcp.tool_sync.ToolSyncService"):
        result = await handle_oauth_callback(code="auth-code", state=state, db=db)

    assert result["success"] is True
    # A NEW session was created — not the foreign one
    assert result["session_id"] != str(foreign_session.id)
    db.add.assert_called_once()
    # The foreign session object was never mutated
    assert foreign_session.encrypted_credentials == "old-encrypted-blob"


# ── 3. New session supersedes prior OAuth sessions (fixed-ID readers) ─────────

@pytest.mark.asyncio
async def test_new_session_supersedes_old_oauth_sessions_and_migrates_bindings():
    """Fresh auth creating a new session migrates AgentRoleMcpSession rows
    and the is_default flag to it, and deactivates the superseded sessions —
    so the role-based tool-call reader resolves the NEW credentials."""
    server = MagicMock()
    server.id = uuid.uuid4()
    server.base_url = "http://mcp.example.com"
    server.oauth_config = None

    old_default = _oauth2_session(is_default=True)
    old_other = _oauth2_session(is_default=False)
    assignment = MagicMock()
    assignment.mcp_session_id = old_default.id

    # execute #1: supersede select → old sessions; execute #2: assignments
    db = _make_db(
        server,
        execute_results=[
            _result(scalars_all=[old_default, old_other]),
            _result(scalars_all=[assignment]),
        ],
    )

    mcp_oauth_states.clear()
    state = _setup_reauth_state(str(server.id), None)

    with _mock_vault_ctx(), \
         patch(
             "app.services.mcp_oauth_service.httpx.AsyncClient",
             return_value=_token_exchange_client(200),
         ), \
         patch("app.services.mcp_oauth_service._initialize_mcp_session",
               AsyncMock(return_value="upstream-id")), \
         patch("app.services.mcp.tool_sync.ToolSyncService"):
        result = await handle_oauth_callback(code="auth-code", state=state, db=db)

    assert result["success"] is True
    new_session_id = uuid.UUID(result["session_id"])
    # Role assignment re-pointed to the new session
    assert assignment.mcp_session_id == new_session_id
    # Default flag transferred, old rows deactivated
    assert old_default.is_active is False
    assert old_other.is_active is False


# ── 4. Expired token → refresh updates the row the reader uses ────────────────

@pytest.mark.asyncio
async def test_expired_token_refresh_updates_credentials_used_by_tool_call():
    """McpProxyEngine.call_tool on an expired OAuth2 session triggers the
    refresh path; the refreshed credentials (not the stale ones) are sent
    as the Bearer token."""
    from app.services.mcp.proxy import McpProxyEngine
    from app.db.models.mcp_hub import McpSessionAuthType

    expired = datetime.now(tz=timezone.utc) - timedelta(minutes=10)

    mock_server = MagicMock()
    mock_server.base_url = "http://mcp-server"

    session = MagicMock()
    session.id = uuid.uuid4()
    session.auth_type = McpSessionAuthType.oauth2
    session.oauth_expires_at = expired
    session.identity_binding = None
    # Stale encrypted credentials; refresh replaces them
    session.encrypted_credentials = "stale-blob"

    tool = MagicMock()
    tool.name = "srv/toolA"
    tool.original_name = "toolA"
    tool.server_id = session.server_id
    tool.server = mock_server

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=session))
    )

    refresh_calls = {"n": 0}

    async def _fake_refresh(self, sess, db, buffer_minutes=5):
        refresh_calls["n"] += 1
        # Simulate the DB round-trip: the row now carries fresh credentials
        sess.encrypted_credentials = "fresh-blob"
        return True

    vault = MagicMock()
    vault.decrypt = MagicMock(
        side_effect=lambda blob: '{"access_token": "%s"}' % (
            "stale-token" if blob == "stale-blob" else "fresh-token"
        )
    )

    captured_headers = {}

    async def _post(url, json=None, headers=None):
        captured_headers.update(headers or {})
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"result": {"ok": True}}
        resp.raise_for_status = MagicMock()
        return resp

    with patch("app.services.mcp.oauth_refresh.OAuthRefreshService.check_and_refresh_if_needed",
               _fake_refresh), \
         patch("app.services.mcp.proxy.get_vault", return_value=vault), \
         patch("httpx.AsyncClient") as client_cls:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=_post)
        client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        engine = McpProxyEngine()
        result = await engine.call_tool(tool, {"x": 1}, db)

    assert result == {"ok": True}
    assert refresh_calls["n"] == 1
    # The post-refresh credential blob is what authenticated the call
    assert captured_headers["Authorization"] == "Bearer fresh-token"
