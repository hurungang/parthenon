"""
Test ToolSyncService: idempotent upsert and tool deactivation on removal.
Tests McpProxyEngine session resolution via ToolSyncService.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, AsyncMock
import uuid


@pytest.mark.asyncio
async def test_toolsyncservice_adds_new_tools():
    """ToolSyncService.sync() adds new tools from the remote server."""
    from app.services.mcp.tool_sync import ToolSyncService
    from app.db.models.mcp_hub import McpServerStatus

    mock_server = MagicMock()
    mock_server.id = uuid.uuid4()
    mock_server.slug = "my-server"
    mock_server.base_url = "http://mcp-server"
    mock_server.status = McpServerStatus.active

    mock_db = AsyncMock()
    # No existing tools found (first sync)
    mock_db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # tool lookup
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),  # deactivation query
        ]
    )

    service = ToolSyncService()

    remote_tools = [{"name": "toolA", "description": "Tool A"}]
    # JSON-RPC 2.0 response format (tools/list)
    jsonrpc_response = {"jsonrpc": "2.0", "id": 1, "result": {"tools": remote_tools}}
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_response = MagicMock()
        mock_response.json.return_value = jsonrpc_response
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await service.sync(mock_server, mock_db)

    assert result["added"] == 1
    assert result["deactivated"] == 0
    mock_db.add.assert_called_once()


@pytest.mark.asyncio
async def test_toolsyncservice_deactivates_removed_tools():
    """ToolSyncService.sync() marks tools inactive when they disappear from remote."""
    from app.services.mcp.tool_sync import ToolSyncService
    from app.db.models.mcp_hub import McpServerStatus, McpTool

    mock_server = MagicMock()
    mock_server.id = uuid.uuid4()
    mock_server.slug = "my-server"
    mock_server.base_url = "http://mcp-server"
    mock_server.status = McpServerStatus.active

    # An existing tool that won't be in the remote response
    stale_tool = MagicMock(spec=McpTool)
    stale_tool.name = "my-server/toolA"
    stale_tool.is_active = True

    mock_db = AsyncMock()
    # Remote returns empty → stale_tool should be deactivated
    mock_db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[stale_tool])))
        )
    )

    service = ToolSyncService()
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_response = MagicMock()
        # JSON-RPC 2.0 response with empty tools list
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await service.sync(mock_server, mock_db)

    assert stale_tool.is_active is False
    assert result["deactivated"] == 1


@pytest.mark.asyncio
async def test_toolsyncservice_uses_oauth2_session_credentials():
    """ToolSyncService.sync() adds Authorization: Bearer header when oauth2 session is provided."""
    from app.services.mcp.tool_sync import ToolSyncService
    from app.db.models.mcp_hub import McpServerStatus, McpSessionAuthType

    mock_server = MagicMock()
    mock_server.id = uuid.uuid4()
    mock_server.slug = "supabase-mcp"
    mock_server.base_url = "https://mcp.supabase.com"
    mock_server.status = McpServerStatus.active

    mock_session = MagicMock()
    mock_session.name = "oauth-session"
    mock_session.auth_type = McpSessionAuthType.oauth2
    mock_session.encrypted_credentials = "encrypted-blob"
    mock_session.oauth_expires_at = None  # prevent datetime comparison TypeError

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # tool lookup
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )

    service = ToolSyncService()
    jsonrpc_response = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "list_tables", "description": "List tables"}]}}

    captured_headers = {}

    with patch("httpx.AsyncClient") as mock_client_cls, \
         patch("app.services.mcp.tool_sync.get_vault") as mock_get_vault:
        # Mock vault decryption to return JSON with access_token
        mock_vault = MagicMock()
        mock_vault.decrypt.return_value = '{"access_token": "test-oauth-token-xyz"}'
        mock_get_vault.return_value = mock_vault

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        async def capture_post(url, *, json=None, headers=None, **kwargs):
            captured_headers.update(headers or {})
            resp = MagicMock()
            resp.json.return_value = jsonrpc_response
            resp.raise_for_status = MagicMock()
            return resp

        mock_client.post = capture_post

        result = await service.sync(mock_server, mock_db, session=mock_session)

    assert result["added"] == 1
    assert "Authorization" in captured_headers
    assert captured_headers["Authorization"] == "Bearer test-oauth-token-xyz"
    mock_vault.decrypt.assert_called_once_with("encrypted-blob")


@pytest.mark.asyncio
async def test_toolsyncservice_uses_bearer_token_session():
    """ToolSyncService.sync() adds Authorization: Bearer header when bearer_token session is provided."""
    from app.services.mcp.tool_sync import ToolSyncService
    from app.db.models.mcp_hub import McpServerStatus, McpSessionAuthType

    mock_server = MagicMock()
    mock_server.id = uuid.uuid4()
    mock_server.slug = "test-server"
    mock_server.base_url = "http://mcp-server"
    mock_server.status = McpServerStatus.active

    mock_session = MagicMock()
    mock_session.name = "bearer-session"
    mock_session.auth_type = McpSessionAuthType.bearer_token
    mock_session.encrypted_credentials = "encrypted-blob"

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )

    service = ToolSyncService()
    jsonrpc_response = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    captured_headers = {}

    with patch("httpx.AsyncClient") as mock_client_cls, \
         patch("app.services.mcp.tool_sync.get_vault") as mock_get_vault:
        mock_vault = MagicMock()
        mock_vault.decrypt.return_value = '{"token": "my-bearer-token"}'
        mock_get_vault.return_value = mock_vault

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        async def capture_post(url, *, json=None, headers=None, **kwargs):
            captured_headers.update(headers or {})
            resp = MagicMock()
            resp.json.return_value = jsonrpc_response
            resp.raise_for_status = MagicMock()
            return resp

        mock_client.post = capture_post

        result = await service.sync(mock_server, mock_db, session=mock_session)

    assert captured_headers.get("Authorization") == "Bearer my-bearer-token"


@pytest.mark.asyncio
async def test_toolsyncservice_uses_api_key_session():
    """ToolSyncService.sync() adds X-API-Key header when api_key session is provided."""
    from app.services.mcp.tool_sync import ToolSyncService
    from app.db.models.mcp_hub import McpServerStatus, McpSessionAuthType

    mock_server = MagicMock()
    mock_server.id = uuid.uuid4()
    mock_server.slug = "test-server"
    mock_server.base_url = "http://mcp-server"
    mock_server.status = McpServerStatus.active

    mock_session = MagicMock()
    mock_session.name = "api-key-session"
    mock_session.auth_type = McpSessionAuthType.api_key
    mock_session.encrypted_credentials = "encrypted-blob"

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )

    service = ToolSyncService()
    jsonrpc_response = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    captured_headers = {}

    with patch("httpx.AsyncClient") as mock_client_cls, \
         patch("app.services.mcp.tool_sync.get_vault") as mock_get_vault:
        mock_vault = MagicMock()
        mock_vault.decrypt.return_value = '{"api_key": "sk-secret-key"}'
        mock_get_vault.return_value = mock_vault

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        async def capture_post(url, *, json=None, headers=None, **kwargs):
            captured_headers.update(headers or {})
            resp = MagicMock()
            resp.json.return_value = jsonrpc_response
            resp.raise_for_status = MagicMock()
            return resp

        mock_client.post = capture_post

        result = await service.sync(mock_server, mock_db, session=mock_session)

    assert captured_headers.get("X-API-Key") == "sk-secret-key"
    assert "Authorization" not in captured_headers


@pytest.mark.asyncio
async def test_toolsyncservice_no_auth_headers_without_session():
    """ToolSyncService.sync() sends no auth headers when no session is provided."""
    from app.services.mcp.tool_sync import ToolSyncService
    from app.db.models.mcp_hub import McpServerStatus

    mock_server = MagicMock()
    mock_server.id = uuid.uuid4()
    mock_server.slug = "open-server"
    mock_server.base_url = "http://mcp-server"
    mock_server.status = McpServerStatus.active

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )

    service = ToolSyncService()
    jsonrpc_response = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    captured_headers = {}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        async def capture_post(url, *, json=None, headers=None, **kwargs):
            captured_headers.update(headers or {})
            resp = MagicMock()
            resp.json.return_value = jsonrpc_response
            resp.raise_for_status = MagicMock()
            return resp

        mock_client.post = capture_post

        result = await service.sync(mock_server, mock_db, session=None)

    assert "Authorization" not in captured_headers
    assert "X-API-Key" not in captured_headers


@pytest.mark.asyncio
async def test_toolsyncservice_gracefully_handles_vault_decrypt_failure():
    """ToolSyncService.sync() continues without auth if vault decryption fails."""
    from app.services.mcp.tool_sync import ToolSyncService
    from app.db.models.mcp_hub import McpServerStatus, McpSessionAuthType

    mock_server = MagicMock()
    mock_server.id = uuid.uuid4()
    mock_server.slug = "test-server"
    mock_server.base_url = "http://mcp-server"
    mock_server.status = McpServerStatus.active

    mock_session = MagicMock()
    mock_session.name = "failing-session"
    mock_session.auth_type = McpSessionAuthType.oauth2
    mock_session.encrypted_credentials = "corrupted-blob"
    mock_session.oauth_expires_at = None  # prevent datetime comparison TypeError

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
    )

    service = ToolSyncService()
    jsonrpc_response = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    captured_headers = {}

    with patch("httpx.AsyncClient") as mock_client_cls, \
         patch("app.services.mcp.tool_sync.get_vault") as mock_get_vault:
        mock_vault = MagicMock()
        mock_vault.decrypt.side_effect = Exception("Decryption failed")
        mock_get_vault.return_value = mock_vault

        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        async def capture_post(url, *, json=None, headers=None, **kwargs):
            captured_headers.update(headers or {})
            resp = MagicMock()
            resp.json.return_value = jsonrpc_response
            resp.raise_for_status = MagicMock()
            return resp

        mock_client.post = capture_post

        # Should NOT raise — graceful degradation
        result = await service.sync(mock_server, mock_db, session=mock_session)

    # Sync still completes, just without auth headers
    assert "Authorization" not in captured_headers
