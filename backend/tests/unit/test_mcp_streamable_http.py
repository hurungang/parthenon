"""Unit tests for app.communication_hub.mcp.streamable_http.

Exercises ``handle_streamable_http`` with a lightweight fake ``Request``/state
(no FastAPI stack, no DB): JSON-RPC response + ``mcp-session-id`` header, and a
401 for missing API-key authentication.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.communication_hub.mcp.protocol_server import McpProtocolServer
from app.communication_hub.mcp.session_manager import McpSessionManager
from app.communication_hub.mcp.streamable_http import handle_streamable_http


class FakeRequest:
    """Minimal stand-in for ``fastapi.Request`` used by the transport handlers."""

    def __init__(
        self,
        body: Any,
        state: Any,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = body
        self.state = state
        self.headers = headers if headers is not None else {}

    async def json(self) -> Any:
        return self._body


def _authed_state(**overrides: Any) -> SimpleNamespace:
    state = SimpleNamespace(
        auth_method="api_key",
        identity_token="server-side-token",
        api_key_agent_identity_id="identity-1",
        api_key_agent_role_id="role-1",
        api_key_permissions=["system____save_data"],
        api_key_skills=[],
        api_key_name="test-key",
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


async def test_returns_jsonrpc_response_with_session_header() -> None:
    manager = McpSessionManager()
    server = McpProtocolServer()
    req = FakeRequest(
        body={"id": 1, "method": "initialize", "params": {}},
        state=_authed_state(),
    )

    response = await handle_streamable_http(req, manager, server)

    assert response.status_code == 200
    assert response.headers.get("mcp-session-id")
    body = json.loads(response.body.decode().strip())
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    assert body["result"]["protocolVersion"] == "2024-11-05"


async def test_session_resumed_via_header() -> None:
    manager = McpSessionManager()
    server = McpProtocolServer()
    # First request creates a session.
    first = FakeRequest(
        body={"id": 1, "method": "initialize", "params": {}},
        state=_authed_state(),
    )
    response = await handle_streamable_http(first, manager, server)
    session_id = response.headers["mcp-session-id"]

    # Second request carries the session header and resolves the same session.
    second = FakeRequest(
        body={"id": 2, "method": "tools/list"},
        state=_authed_state(),
        headers={"mcp-session-id": session_id},
    )
    response2 = await handle_streamable_http(second, manager, server)
    assert response2.headers["mcp-session-id"] == session_id
    body = json.loads(response2.body.decode().strip())
    tools = body["result"]["tools"]
    names = [t["name"] for t in tools]
    assert "load_skills" in names


async def test_missing_auth_returns_401() -> None:
    manager = McpSessionManager()
    server = McpProtocolServer()
    req = FakeRequest(
        body={"id": 1, "method": "initialize"},
        state=SimpleNamespace(auth_method="none"),
    )

    response = await handle_streamable_http(req, manager, server)

    assert response.status_code == 401
    body = json.loads(response.body)
    assert body["error"]["code"] == -32001
