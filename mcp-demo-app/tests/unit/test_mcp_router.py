"""Unit tests for the MCP JSON-RPC router (app/routes/mcp.py).

Tests all method dispatch paths — initialize, tools/list, tools/call, and
unknown methods — without triggering the app lifespan (no real Keycloak/Hub
calls are made). External dependencies (get_agent_identity) are mocked where
authentication is exercised.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.routes.health import health_router
from app.routes.mcp import mcp_router


# ── Test-app fixture (no lifespan) ───────────────────────────────────────────


@pytest.fixture
def test_app():
    """Minimal FastAPI app with the MCP + health routers; no startup lifespan."""
    app = FastAPI()
    app.include_router(health_router)
    app.include_router(mcp_router)
    return app


@pytest.fixture
async def client(test_app):
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as c:
        yield c


_FAKE_IDENTITY = {"sub": "agent-abc", "iss": "http://keycloak:8082/realms/ai_agents"}


# ── initialize ────────────────────────────────────────────────────────────────


async def test_initialize_returns_200(client):
    """Scenario 3.6: initialize succeeds."""
    response = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "0.0.1"},
            },
        },
    )
    assert response.status_code == 200


async def test_initialize_response_structure(client):
    """initialize result must contain serverInfo, capabilities, protocolVersion."""
    body = (
        await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    ).json()
    result = body["result"]
    assert "serverInfo" in result
    assert "capabilities" in result
    assert "protocolVersion" in result


async def test_initialize_no_auth_required(client):
    """Scenario 3.6: initialize must not require Authorization header."""
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
    )
    assert response.status_code == 200


async def test_initialize_echoes_request_id(client):
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 42, "method": "initialize", "params": {}},
    )
    assert response.json()["id"] == 42


# ── tools/list ────────────────────────────────────────────────────────────────


async def test_tools_list_returns_200(client):
    """Scenario 3.7: tools/list succeeds."""
    response = await client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert response.status_code == 200


async def test_tools_list_returns_one_tool(client):
    """Scenario 3.7 + AC-6: exactly one tool in manifest."""
    body = (
        await client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
    ).json()
    tools = body["result"]["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "helloWorld"


async def test_tools_list_no_auth_required(client):
    """Scenario 3.7: tools/list must not require Authorization header."""
    response = await client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert response.status_code == 200


async def test_tools_list_tool_has_input_schema(client):
    body = (
        await client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
    ).json()
    tool = body["result"]["tools"][0]
    assert "inputSchema" in tool
    assert "description" in tool


# ── tools/call ────────────────────────────────────────────────────────────────


async def test_tools_call_no_auth_returns_401(client):
    """Scenario 3.8: tools/call without Authorization → 401."""
    response = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "helloWorld"},
        },
    )
    assert response.status_code == 401


async def test_tools_call_invalid_jwt_returns_401(client):
    """Scenario 3.8: tools/call with invalid JWT → 401."""
    with patch(
        "app.routes.mcp.get_agent_identity",
        new=AsyncMock(side_effect=HTTPException(status_code=401, detail="Invalid token")),
    ):
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "helloWorld"},
            },
            headers={"Authorization": "Bearer invalid.token.here"},
        )
    assert response.status_code == 401


async def test_tools_call_valid_identity_returns_greeting(client):
    """Scenario 3.8: valid agent JWT → greeting with agent_sub in response."""
    with patch(
        "app.routes.mcp.get_agent_identity",
        new=AsyncMock(return_value=_FAKE_IDENTITY),
    ):
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "helloWorld"},
            },
            headers={"Authorization": "Bearer fake.jwt.token"},
        )

    assert response.status_code == 200
    body = response.json()
    result = body["result"]["result"]
    assert result["message"] == "Hello from MCP Demo App!"
    assert result["agent_sub"] == "agent-abc"


async def test_tools_call_agent_claims_in_response(client):
    """AC-3: agent_claims must be accessible in the tool response."""
    with patch(
        "app.routes.mcp.get_agent_identity",
        new=AsyncMock(return_value=_FAKE_IDENTITY),
    ):
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "helloWorld"},
            },
            headers={"Authorization": "Bearer fake.jwt.token"},
        )

    result = response.json()["result"]["result"]
    assert "agent_claims" in result
    assert result["agent_claims"]["sub"] == "agent-abc"


async def test_tools_call_unknown_tool_returns_rpc_error(client):
    """Scenario 3.8 / Edge case: unknown tool name → JSON-RPC error -32601."""
    with patch(
        "app.routes.mcp.get_agent_identity",
        new=AsyncMock(return_value=_FAKE_IDENTITY),
    ):
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "nonExistentTool"},
            },
            headers={"Authorization": "Bearer fake.jwt.token"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == -32601


# ── Unknown method ────────────────────────────────────────────────────────────


async def test_unknown_method_returns_rpc_error(client):
    """Scenario 3.9: unrecognised method → JSON-RPC error -32601."""
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 99, "method": "notAMethod", "params": {}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == -32601


async def test_unknown_method_echoes_request_id(client):
    """Scenario 3.9: request id must be echoed back in error response."""
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 77, "method": "notAMethod", "params": {}},
    )
    assert response.json()["id"] == 77


# ── id handling ───────────────────────────────────────────────────────────────


async def test_missing_id_echoed_as_null(client):
    """Edge case (JSON-RPC spec): omitted id must produce null id in response."""
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "initialize", "params": {}},
    )
    assert response.json()["id"] is None


async def test_string_id_echoed_correctly(client):
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": "req-abc", "method": "tools/list"},
    )
    assert response.json()["id"] == "req-abc"
