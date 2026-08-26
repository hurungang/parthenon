"""Unit tests for app.communication_hub.mcp.sse_transport.

Covers the SSE ``endpoint`` announcement event and the JSON-RPC message path,
using a lightweight fake ``Request``/state (no FastAPI stack, no DB).
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.communication_hub.mcp.protocol_server import McpProtocolServer
from app.communication_hub.mcp.session_manager import McpSessionManager
from app.communication_hub.mcp.sse_transport import handle_sse_message, handle_sse_open


class FakeRequest:
    def __init__(
        self,
        body: Any,
        state: Any,
        headers: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
    ) -> None:
        self._body = body
        self.state = state
        self.headers = headers if headers is not None else {}
        self.query_params = query_params if query_params is not None else {}

    async def json(self) -> Any:
        return self._body


def _authed_state() -> SimpleNamespace:
    return SimpleNamespace(
        auth_method="api_key",
        identity_token="server-side-token",
        api_key_agent_identity_id=None,
        api_key_agent_role_id="role-1",
        api_key_permissions=[],
        api_key_skills=[],
        api_key_name="test-key",
    )


async def test_handle_sse_open_produces_endpoint_event() -> None:
    manager = McpSessionManager()
    req = FakeRequest(body=None, state=_authed_state())

    response = await handle_sse_open(req, manager)

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    stream = response.body_iterator
    first_chunk = await stream.__anext__()
    assert "event: endpoint" in first_chunk
    assert "/mcp/sse/messages?sessionId=" in first_chunk


async def test_handle_sse_message_returns_jsonrpc_response() -> None:
    manager = McpSessionManager()
    server = McpProtocolServer()
    req = FakeRequest(body={"id": 2, "method": "ping"}, state=_authed_state())

    response = await handle_sse_message(req, manager, server)

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 2
    assert body["result"] == {}


async def test_handle_sse_message_missing_auth_returns_401() -> None:
    manager = McpSessionManager()
    server = McpProtocolServer()
    req = FakeRequest(
        body={"id": 2, "method": "ping"},
        state=SimpleNamespace(auth_method="none"),
    )

    response = await handle_sse_message(req, manager, server)

    assert response.status_code == 401
