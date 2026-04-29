"""
Test McpProxyEngine: session resolution, credential injection, tool result return.
"""
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


@pytest.mark.asyncio
async def test_proxy_engine_resolves_session_and_returns_result():
    """McpProxyEngine.call_tool() returns the JSON result from the remote server."""
    from app.services.mcp.proxy import McpProxyEngine
    from app.db.models.mcp_hub import McpSessionAuthType

    engine = McpProxyEngine()

    # Build mock tool + server + session
    mock_server = MagicMock()
    mock_server.base_url = "http://mcp-server"

    mock_session = MagicMock()
    mock_session.auth_type = McpSessionAuthType.api_key
    mock_session.encrypted_credentials = None  # no credentials for simplicity

    mock_tool = MagicMock()
    mock_tool.name = "my-server/toolA"
    mock_tool.original_name = "toolA"
    mock_tool.server_id = uuid.uuid4()
    mock_tool.server = mock_server

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_session))
    )

    expected_result = {"output": "hello from tool"}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_response = MagicMock()
        mock_response.json.return_value = expected_result
        mock_response.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_response)

        result = await engine.call_tool(mock_tool, {"x": 1}, mock_db)

    assert result == expected_result


@pytest.mark.asyncio
async def test_proxy_engine_raises_when_no_session():
    """McpProxyEngine.call_tool() raises McpProxyError when no active session exists."""
    from app.services.mcp.proxy import McpProxyEngine, McpProxyError

    engine = McpProxyEngine()
    mock_tool = MagicMock()
    mock_tool.server_id = uuid.uuid4()
    mock_tool.server = MagicMock()
    mock_tool.server.base_url = "http://mcp-server"

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    with pytest.raises(McpProxyError, match="No active session"):
        await engine.call_tool(mock_tool, {}, mock_db)
