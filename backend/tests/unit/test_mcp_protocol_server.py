"""Unit tests for app.communication_hub.mcp.protocol_server.

Covers JSON-RPC method dispatch, the initialize handshake, protocol ordering
(``tools/list`` before a session), notification handling, method-not-found, and
``tools/call`` parameter validation — all without any Control Center or database.
"""
from __future__ import annotations

import pytest

from app.communication_hub.mcp.protocol_server import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    JSONRPC,
    METHOD_NOT_FOUND,
    SERVER_INFO,
    McpProtocolServer,
)
from app.communication_hub.mcp.session_manager import MCP_PROTOCOL_VERSION, McpSession


@pytest.fixture
def server() -> McpProtocolServer:
    return McpProtocolServer()


async def test_initialize_result(server: McpProtocolServer) -> None:
    result = await server.handle(
        None, {"id": 1, "method": "initialize", "params": {}}, None
    )
    assert result["jsonrpc"] == JSONRPC
    assert result["id"] == 1
    assert result["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert result["result"]["capabilities"] == {"tools": {}}
    assert result["result"]["serverInfo"] == SERVER_INFO


async def test_ping_returns_empty_result(server: McpProtocolServer) -> None:
    result = await server.handle(None, {"id": 2, "method": "ping"}, None)
    assert result["result"] == {}


async def test_tools_list_requires_session(server: McpProtocolServer) -> None:
    result = await server.handle(None, {"id": 3, "method": "tools/list"}, None)
    assert result["error"]["code"] == INVALID_REQUEST
    assert "Session not initialized" in result["error"]["message"]


async def test_tools_call_before_session_requires_session(server: McpProtocolServer) -> None:
    result = await server.handle(
        None,
        {"id": 4, "method": "tools/call", "params": {"name": "load_skills"}},
        None,
    )
    assert result["error"]["code"] == INVALID_REQUEST


async def test_notification_returns_none(server: McpProtocolServer) -> None:
    result = await server.handle(
        None, {"method": "notifications/initialized", "params": {}}, None
    )
    assert result is None


async def test_method_not_found(server: McpProtocolServer) -> None:
    session = McpSession(session_id="session-1")
    result = await server.handle(
        None, {"id": 5, "method": "bogus/method"}, session
    )
    assert result["error"]["code"] == METHOD_NOT_FOUND
    assert "bogus/method" in result["error"]["message"]


async def test_tools_call_missing_name(server: McpProtocolServer) -> None:
    session = McpSession(session_id="session-1", permissions=["system____save_data"])
    result = await server.handle(
        None, {"id": 6, "method": "tools/call", "params": {}}, session
    )
    assert result["error"]["code"] == INVALID_PARAMS
    assert "Missing tool name" in result["error"]["message"]


async def test_tools_list_returns_catalog(server: McpProtocolServer) -> None:
    session = McpSession(
        session_id="session-1",
        permissions=["system____save_data"],
        skills=[],
    )
    result = await server.handle(
        None, {"id": 7, "method": "tools/list"}, session
    )
    names = [t["name"] for t in result["result"]["tools"]]
    assert "load_skills" in names
    assert "system____save_data" in names
