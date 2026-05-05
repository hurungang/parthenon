"""Unit tests for mcp_oauth_service — discovery, DCR, flow initiation, and OAuth callback."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.services.mcp_oauth_service import (
    discover_oauth_config,
    handle_oauth_callback,
    initiate_oauth_flow,
    mcp_oauth_states,
    register_dynamic_client,
)
from app.schemas.mcp_oauth import OAuthDiscoveryResult


# ── Response / client helpers ─────────────────────────────────────────────────

def _resp(status_code: int, json_data=None, headers=None, text=""):
    """Build a mock httpx response."""
    r = MagicMock()
    r.status_code = status_code
    r.headers = dict(headers or {})
    r.text = text
    if json_data is not None:
        r.json = MagicMock(return_value=json_data)
    else:
        r.json = MagicMock(side_effect=ValueError("no JSON body"))
    return r


def _make_client(*get_side_effects, post_response=None):
    """Create a mock async httpx.AsyncClient context manager.

    Args:
        get_side_effects: Responses returned in order for successive GET calls.
        post_response: Response for POST calls (DCR).
    """
    client = AsyncMock()
    client.get = AsyncMock(side_effect=list(get_side_effects))
    if post_response is not None:
        client.post = AsyncMock(return_value=post_response)

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _mock_server(oauth_config=None, base_url="http://mcp.example.com"):
    server = MagicMock()
    server.id = uuid4()
    server.base_url = base_url
    server.oauth_config = oauth_config
    return server


def _mock_db(server=None):
    db = AsyncMock()
    db.get = AsyncMock(return_value=server)
    return db


# ── discover_oauth_config ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_discover_via_www_authenticate_direct_params():
    """Method 1: 401 with WWW-Authenticate containing direct authorization_uri."""
    mock_client = _make_client(
        _resp(
            401,
            headers={
                "WWW-Authenticate": (
                    'Bearer authorization_uri="https://auth.example.com/authorize",'
                    ' token_uri="https://auth.example.com/token",'
                    ' client_id="my-client"'
                )
            },
        )
    )

    with patch("app.services.mcp_oauth_service.httpx.AsyncClient", return_value=mock_client):
        result = await discover_oauth_config(
            "http://mcp.example.com", "http://localhost:5173/oauth/callback"
        )

    assert result.authorization_url == "https://auth.example.com/authorize"
    assert result.token_url == "https://auth.example.com/token"
    assert result.client_id == "my-client"
    assert result.redirect_uri == "http://localhost:5173/oauth/callback"


@pytest.mark.asyncio
async def test_discover_via_www_authenticate_resource_metadata():
    """Method 1: 401 with resource_metadata URL that resolves authorization_servers."""
    resource_meta = {
        "authorization_servers": ["https://as.example.com"],
        "scopes_supported": ["read", "write"],
    }
    as_meta = {
        "authorization_endpoint": "https://as.example.com/authorize",
        "token_endpoint": "https://as.example.com/token",
        "registration_endpoint": "https://as.example.com/register",
    }

    # GET calls in order: base URL (401), resource_metadata fetch, AS metadata fetch
    mock_client = _make_client(
        _resp(
            401,
            headers={
                "WWW-Authenticate": (
                    'Bearer resource_metadata="https://mcp.example.com/.well-known/resource"'
                )
            },
        ),
        _resp(200, json_data=resource_meta),   # resource_metadata fetch
        _resp(200, json_data=as_meta),          # AS .well-known fetch
    )

    with patch("app.services.mcp_oauth_service.httpx.AsyncClient", return_value=mock_client):
        result = await discover_oauth_config(
            "http://mcp.example.com", "http://localhost:5173/oauth/callback"
        )

    assert result.authorization_url == "https://as.example.com/authorize"
    assert result.token_url == "https://as.example.com/token"
    assert result.registration_endpoint == "https://as.example.com/register"
    assert result.scope == "read write"


@pytest.mark.asyncio
async def test_discover_via_well_known():
    """Method 2: .well-known/oauth-authorization-server returns metadata."""
    well_known_json = {
        "authorization_endpoint": "https://auth.example.com/authorize",
        "token_endpoint": "https://auth.example.com/token",
        "client_id": "wk-client",
        "scopes_supported": ["openid", "profile"],
        "registration_endpoint": "https://auth.example.com/register",
    }

    # GET calls: base URL (200, skip method 1), well-known (200 with JSON)
    mock_client = _make_client(
        _resp(200),                            # base URL, not 401 — skip method 1
        _resp(200, json_data=well_known_json), # well-known — method 2 succeeds
    )

    with patch("app.services.mcp_oauth_service.httpx.AsyncClient", return_value=mock_client):
        result = await discover_oauth_config(
            "http://mcp.example.com", "http://localhost:5173/oauth/callback"
        )

    assert result.authorization_url == "https://auth.example.com/authorize"
    assert result.token_url == "https://auth.example.com/token"
    assert result.client_id == "wk-client"
    assert result.scope == "openid profile"
    assert result.registration_endpoint == "https://auth.example.com/register"


@pytest.mark.asyncio
async def test_discover_via_mcp_metadata():
    """Method 3: /oauth/metadata returns config when well-known fails."""
    meta_json = {
        "authorization_url": "https://auth.example.com/authorize",
        "token_url": "https://auth.example.com/token",
        "client_id": "meta-client",
        "scope": "mcp:read",
    }

    mock_client = _make_client(
        _resp(200),                         # base URL (not 401) — skip method 1
        _resp(404),                         # well-known — method 2 fails
        _resp(200, json_data=meta_json),    # /oauth/metadata — method 3 succeeds
    )

    with patch("app.services.mcp_oauth_service.httpx.AsyncClient", return_value=mock_client):
        result = await discover_oauth_config(
            "http://mcp.example.com", "http://localhost:5173/oauth/callback"
        )

    assert result.authorization_url == "https://auth.example.com/authorize"
    assert result.client_id == "meta-client"
    assert result.scope == "mcp:read"


@pytest.mark.asyncio
async def test_discover_all_methods_fail_raises_value_error():
    """All three discovery methods fail → ValueError."""
    mock_client = _make_client(
        _resp(200),   # base URL (not 401)
        _resp(404),   # well-known — method 2 fails
        _resp(404),   # /oauth/metadata — method 3 fails
    )

    with patch("app.services.mcp_oauth_service.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="Could not discover OAuth configuration"):
            await discover_oauth_config(
                "http://mcp.example.com", "http://localhost:5173/oauth/callback"
            )


# ── register_dynamic_client ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_dynamic_client_success():
    dcr_resp = _resp(201, json_data={"client_id": "dyn-client-123", "client_secret": "super-secret"})
    mock_client = _make_client(post_response=dcr_resp)

    with patch("app.services.mcp_oauth_service.httpx.AsyncClient", return_value=mock_client):
        client_id, client_secret = await register_dynamic_client(
            registration_endpoint="https://auth.example.com/register",
            redirect_uri="http://localhost:5173/oauth/callback",
        )

    assert client_id == "dyn-client-123"
    assert client_secret == "super-secret"


@pytest.mark.asyncio
async def test_register_dynamic_client_public_client_no_secret():
    """Public clients may return no client_secret."""
    dcr_resp = _resp(201, json_data={"client_id": "pub-client-456"})
    mock_client = _make_client(post_response=dcr_resp)

    with patch("app.services.mcp_oauth_service.httpx.AsyncClient", return_value=mock_client):
        client_id, client_secret = await register_dynamic_client(
            registration_endpoint="https://auth.example.com/register",
            redirect_uri="http://localhost:5173/oauth/callback",
        )

    assert client_id == "pub-client-456"
    assert client_secret is None


@pytest.mark.asyncio
async def test_register_dynamic_client_failure_raises():
    dcr_resp = _resp(400, text="invalid_redirect_uri")
    mock_client = _make_client(post_response=dcr_resp)

    with patch("app.services.mcp_oauth_service.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ValueError, match="Dynamic client registration failed"):
            await register_dynamic_client(
                registration_endpoint="https://auth.example.com/register",
                redirect_uri="http://localhost:5173/oauth/callback",
            )


# ── initiate_oauth_flow ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_initiate_oauth_flow_uses_preconfigured_oauth_config():
    """Server with complete oauth_config skips discovery."""
    server = _mock_server(
        oauth_config={
            "authorization_url": "https://auth.example.com/authorize",
            "token_url": "https://auth.example.com/token",
            "client_id": "static-client",
            "client_secret": "static-secret",
            "scope": "read",
        }
    )
    db = _mock_db(server)

    mcp_oauth_states.clear()
    # No httpx calls should be made — discovery is skipped
    result = await initiate_oauth_flow(server.id, db)

    assert "authorization_url" in result
    assert "static-client" in result["authorization_url"]
    assert len(mcp_oauth_states) == 1

    stored = next(iter(mcp_oauth_states.values()))
    assert stored["client_id"] == "static-client"
    assert stored["client_secret"] == "static-secret"


@pytest.mark.asyncio
async def test_initiate_oauth_flow_auto_discovers_when_no_config():
    """Server with no oauth_config triggers auto-discovery via well-known."""
    server = _mock_server(oauth_config=None)
    db = _mock_db(server)

    wk_json = {
        "authorization_endpoint": "https://auth.example.com/authorize",
        "token_endpoint": "https://auth.example.com/token",
        "client_id": "discovered-client",
    }
    mock_client = _make_client(
        _resp(200),                    # base URL (not 401)
        _resp(200, json_data=wk_json), # well-known — discovery succeeds
    )

    with patch("app.services.mcp_oauth_service.httpx.AsyncClient", return_value=mock_client):
        mcp_oauth_states.clear()
        result = await initiate_oauth_flow(server.id, db)

    assert "discovered-client" in result["authorization_url"]


@pytest.mark.asyncio
async def test_initiate_oauth_flow_performs_dcr_when_no_client_id():
    """Discovery succeeds but returns no client_id → DCR is performed."""
    server = _mock_server(oauth_config=None)
    db = _mock_db(server)

    wk_json = {
        "authorization_endpoint": "https://auth.example.com/authorize",
        "token_endpoint": "https://auth.example.com/token",
        "client_id": "",  # Empty — triggers DCR
        "registration_endpoint": "https://auth.example.com/register",
    }
    # Discovery uses one AsyncClient; DCR uses a second AsyncClient
    discovery_client = _make_client(
        _resp(200),
        _resp(200, json_data=wk_json),
    )
    dcr_client = _make_client(
        post_response=_resp(
            201, json_data={"client_id": "dyn-123", "client_secret": "dyn-secret"}
        ),
    )

    call_count = 0

    def client_factory(**_kwargs):
        nonlocal call_count
        call_count += 1
        return discovery_client if call_count == 1 else dcr_client

    with patch(
        "app.services.mcp_oauth_service.httpx.AsyncClient",
        side_effect=client_factory,
    ):
        mcp_oauth_states.clear()
        result = await initiate_oauth_flow(server.id, db)

    assert "dyn-123" in result["authorization_url"]
    stored = next(iter(mcp_oauth_states.values()))
    assert stored["client_id"] == "dyn-123"
    assert stored["client_secret"] == "dyn-secret"


@pytest.mark.asyncio
async def test_initiate_oauth_flow_server_not_found_raises_404():
    db = _mock_db(server=None)

    with pytest.raises(HTTPException) as exc_info:
        await initiate_oauth_flow(uuid4(), db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_initiate_oauth_flow_discovery_failure_raises_400():
    server = _mock_server(oauth_config=None)
    db = _mock_db(server)

    mock_client = _make_client(
        _resp(200),   # base URL (not 401)
        _resp(404),   # well-known fails
        _resp(404),   # /oauth/metadata fails
    )

    with patch("app.services.mcp_oauth_service.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(HTTPException) as exc_info:
            await initiate_oauth_flow(server.id, db)

    assert exc_info.value.status_code == 400
    assert "Could not discover" in exc_info.value.detail


# ── handle_oauth_callback ──────────────────────────────────────────────────────

# Helpers for callback tests

_DEFAULT_TOKENS = {"access_token": "acc-tok", "refresh_token": "ref-tok", "expires_in": 3600}
_DEFAULT_STATE = "cb-test-state"
_DEFAULT_TOKEN_URL = "https://auth.example.com/token"


def _setup_callback_state(
    state: str = _DEFAULT_STATE,
    server_id: str | None = None,
    client_id: str = "cb-client",
    client_secret: str | None = "cb-secret",
    token_url: str = _DEFAULT_TOKEN_URL,
    redirect_uri: str = "http://localhost:5173/oauth/callback",
    expired: bool = False,
) -> str:
    """Populate mcp_oauth_states with a pending OAuth flow entry. Returns state key."""
    sid = server_id or str(uuid4())
    ttl = timedelta(minutes=-1) if expired else timedelta(minutes=15)
    mcp_oauth_states[state] = {
        "server_id": sid,
        "client_id": client_id,
        "client_secret": client_secret,
        "token_url": token_url,
        "redirect_uri": redirect_uri,
        "expires_at": (datetime.now(tz=timezone.utc) + ttl).isoformat(),
    }
    return state


def _token_exchange_client(status_code: int, tokens: dict | None = None):
    """Mock async httpx client whose POST returns the given status and token JSON."""
    resp = _resp(status_code, json_data=tokens if tokens is not None else _DEFAULT_TOKENS)
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _callback_db(server=None):
    """Mock AsyncSession for handle_oauth_callback (no real DB calls)."""
    db = AsyncMock()

    async def _fake_refresh(obj):
        obj.id = uuid4()

    db.refresh = AsyncMock(side_effect=_fake_refresh)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=server)
    db.execute = AsyncMock(return_value=mock_result)
    return db


def _mock_vault_ctx():
    """Patch context for get_vault that returns a stub encryptor."""
    vault = MagicMock()
    vault.encrypt = MagicMock(return_value="encrypted-blob")
    return patch("app.core.credential_vault.get_vault", return_value=vault)


# --- State validation ---

@pytest.mark.asyncio
async def test_callback_invalid_state_raises_400():
    """Missing state key → HTTPException 400."""
    mcp_oauth_states.clear()
    with pytest.raises(HTTPException) as exc_info:
        await handle_oauth_callback(code="abc", state="no-such-state", db=AsyncMock())
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_callback_expired_state_raises_400():
    """State with past expiry → HTTPException 400, state entry cleaned up."""
    mcp_oauth_states.clear()
    state = _setup_callback_state(expired=True)
    with pytest.raises(HTTPException) as exc_info:
        await handle_oauth_callback(code="abc", state=state, db=AsyncMock())
    assert exc_info.value.status_code == 400
    assert state not in mcp_oauth_states


# --- Bug Fix 1: Token exchange accepts any 2xx status code ---

@pytest.mark.asyncio
async def test_callback_token_exchange_200_succeeds():
    """Token exchange returning HTTP 200 → session created successfully."""
    mcp_oauth_states.clear()
    state = _setup_callback_state()
    db = _callback_db(server=MagicMock())

    with _mock_vault_ctx(), \
         patch("app.services.mcp_oauth_service.httpx.AsyncClient",
               return_value=_token_exchange_client(200)), \
         patch("app.services.mcp.tool_sync.ToolSyncService"):
        result = await handle_oauth_callback(code="auth-code", state=state, db=db)

    assert result["success"] is True
    assert "session_id" in result


@pytest.mark.asyncio
async def test_callback_token_exchange_201_succeeds():
    """Token exchange returning HTTP 201 → authentication succeeds (2xx fix)."""
    mcp_oauth_states.clear()
    state = _setup_callback_state()
    db = _callback_db(server=MagicMock())

    with _mock_vault_ctx(), \
         patch("app.services.mcp_oauth_service.httpx.AsyncClient",
               return_value=_token_exchange_client(201)), \
         patch("app.services.mcp.tool_sync.ToolSyncService"):
        result = await handle_oauth_callback(code="auth-code", state=state, db=db)

    assert result["success"] is True
    assert "session_id" in result


@pytest.mark.asyncio
async def test_callback_token_exchange_204_succeeds():
    """Token exchange returning HTTP 204 → authentication succeeds (2xx fix)."""
    mcp_oauth_states.clear()
    state = _setup_callback_state()
    db = _callback_db(server=MagicMock())

    with _mock_vault_ctx(), \
         patch("app.services.mcp_oauth_service.httpx.AsyncClient",
               return_value=_token_exchange_client(204)), \
         patch("app.services.mcp.tool_sync.ToolSyncService"):
        result = await handle_oauth_callback(code="auth-code", state=state, db=db)

    assert result["success"] is True


@pytest.mark.asyncio
async def test_callback_token_exchange_400_raises_400():
    """Token exchange returning HTTP 400 → HTTPException 400."""
    mcp_oauth_states.clear()
    state = _setup_callback_state()

    with patch("app.services.mcp_oauth_service.httpx.AsyncClient",
               return_value=_token_exchange_client(400)):
        with pytest.raises(HTTPException) as exc_info:
            await handle_oauth_callback(code="auth-code", state=state, db=AsyncMock())

    assert exc_info.value.status_code == 400
    assert "Token exchange failed" in exc_info.value.detail


@pytest.mark.asyncio
async def test_callback_token_exchange_401_raises_400():
    """Token exchange returning HTTP 401 → HTTPException 400."""
    mcp_oauth_states.clear()
    state = _setup_callback_state()

    with patch("app.services.mcp_oauth_service.httpx.AsyncClient",
               return_value=_token_exchange_client(401)):
        with pytest.raises(HTTPException) as exc_info:
            await handle_oauth_callback(code="auth-code", state=state, db=AsyncMock())

    assert exc_info.value.status_code == 400
    assert "Token exchange failed" in exc_info.value.detail


@pytest.mark.asyncio
async def test_callback_token_exchange_500_raises_400():
    """Token exchange returning HTTP 500 → HTTPException 400."""
    mcp_oauth_states.clear()
    state = _setup_callback_state()

    with patch("app.services.mcp_oauth_service.httpx.AsyncClient",
               return_value=_token_exchange_client(500)):
        with pytest.raises(HTTPException) as exc_info:
            await handle_oauth_callback(code="auth-code", state=state, db=AsyncMock())

    assert exc_info.value.status_code == 400
    assert "Token exchange failed" in exc_info.value.detail


# --- Bug Fix 2: Automatic tool sync after OAuth ---

@pytest.mark.asyncio
async def test_callback_tool_sync_success_returns_counts():
    """Successful OAuth → tool sync runs and added/updated/deactivated counts returned."""
    mcp_oauth_states.clear()
    state = _setup_callback_state()
    server = MagicMock()
    db = _callback_db(server=server)

    mock_sync_instance = AsyncMock()
    mock_sync_instance.sync = AsyncMock(
        return_value={"added": 5, "updated": 2, "deactivated": 1}
    )
    mock_sync_class = MagicMock(return_value=mock_sync_instance)

    with _mock_vault_ctx(), \
         patch("app.services.mcp_oauth_service.httpx.AsyncClient",
               return_value=_token_exchange_client(200)), \
         patch("app.services.mcp.tool_sync.ToolSyncService", mock_sync_class):
        result = await handle_oauth_callback(code="auth-code", state=state, db=db)

    assert result["success"] is True
    assert result["tools_synced"] == {"added": 5, "updated": 2, "deactivated": 1}
    mock_sync_instance.sync.assert_called_once_with(server, db)


@pytest.mark.asyncio
async def test_callback_tool_sync_failure_handled_gracefully():
    """Tool sync exception → session still created, error not propagated."""
    mcp_oauth_states.clear()
    state = _setup_callback_state()
    server = MagicMock()
    db = _callback_db(server=server)

    mock_sync_instance = AsyncMock()
    mock_sync_instance.sync = AsyncMock(side_effect=RuntimeError("connection refused"))
    mock_sync_class = MagicMock(return_value=mock_sync_instance)

    with _mock_vault_ctx(), \
         patch("app.services.mcp_oauth_service.httpx.AsyncClient",
               return_value=_token_exchange_client(200)), \
         patch("app.services.mcp.tool_sync.ToolSyncService", mock_sync_class):
        result = await handle_oauth_callback(code="auth-code", state=state, db=db)

    assert result["success"] is True
    assert "session_id" in result
    assert result["tools_synced"] == {"added": 0, "updated": 0, "deactivated": 0}


@pytest.mark.asyncio
async def test_callback_tool_sync_skipped_when_server_not_found():
    """Server record missing after session creation → tool sync skipped gracefully."""
    mcp_oauth_states.clear()
    state = _setup_callback_state()
    db = _callback_db(server=None)  # scalar_one_or_none returns None

    mock_sync_class = MagicMock()

    with _mock_vault_ctx(), \
         patch("app.services.mcp_oauth_service.httpx.AsyncClient",
               return_value=_token_exchange_client(200)), \
         patch("app.services.mcp.tool_sync.ToolSyncService", mock_sync_class):
        result = await handle_oauth_callback(code="auth-code", state=state, db=db)

    assert result["success"] is True
    assert result["tools_synced"] == {"added": 0, "updated": 0, "deactivated": 0}
    mock_sync_class.assert_not_called()
