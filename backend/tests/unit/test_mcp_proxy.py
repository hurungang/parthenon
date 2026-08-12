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
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": expected_result}
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


# ── Passthrough auth header tests (Task 3.5) ──────────────────────────────────


def test_build_auth_headers_passthrough_injects_jwt():
    """_build_auth_headers() returns Bearer <jwt> for passthrough sessions."""
    from app.services.mcp.proxy import McpProxyEngine
    from app.db.models.mcp_hub import McpSessionAuthType

    engine = McpProxyEngine()

    mock_session = MagicMock()
    mock_session.id = uuid.uuid4()
    mock_session.auth_type = McpSessionAuthType.passthrough
    mock_session.encrypted_credentials = None

    headers = engine._build_auth_headers(mock_session, agent_jwt="my.agent.jwt")

    assert headers["Authorization"] == "Bearer my.agent.jwt"
    assert headers["Content-Type"] == "application/json"


def test_build_auth_headers_passthrough_raises_without_jwt():
    """_build_auth_headers() raises McpProxyError when passthrough session has no JWT."""
    from app.services.mcp.proxy import McpProxyEngine, McpProxyError
    from app.db.models.mcp_hub import McpSessionAuthType

    engine = McpProxyEngine()

    mock_session = MagicMock()
    mock_session.id = uuid.uuid4()
    mock_session.auth_type = McpSessionAuthType.passthrough
    mock_session.encrypted_credentials = None

    with pytest.raises(McpProxyError, match="Passthrough session requires a caller JWT"):
        engine._build_auth_headers(mock_session, agent_jwt=None)


def test_build_auth_headers_passthrough_raises_with_empty_jwt():
    """_build_auth_headers() raises McpProxyError when JWT is empty string."""
    from app.services.mcp.proxy import McpProxyEngine, McpProxyError
    from app.db.models.mcp_hub import McpSessionAuthType

    engine = McpProxyEngine()

    mock_session = MagicMock()
    mock_session.id = uuid.uuid4()
    mock_session.auth_type = McpSessionAuthType.passthrough
    mock_session.encrypted_credentials = None

    with pytest.raises(McpProxyError, match="Passthrough session requires a caller JWT"):
        engine._build_auth_headers(mock_session, agent_jwt="")

