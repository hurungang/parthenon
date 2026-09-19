"""Streamable HTTP transport for the MCP protocol server.

Implements the MCP Streamable HTTP transport over a single ``POST /mcp``
endpoint: the client sends a JSON-RPC message, the server replies with a
newline-delimited JSON response and a ``mcp-session-id`` header used to resume
the session on subsequent requests.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.communication_hub.mcp.protocol_server import McpProtocolServer
from app.communication_hub.mcp.session_manager import McpSession, McpSessionManager

logger = logging.getLogger(__name__)

_SESSION_HEADERS = ("mcp-session-id", "x-session-id")


def _session_from_request(request: Request, manager: McpSessionManager) -> McpSession:
    """Create an MCP session seeded from the API-key auth context on ``request.state``."""
    return manager.create_session(
        identity_token=getattr(request.state, "identity_token", None),
        agent_identity_id=getattr(request.state, "api_key_agent_identity_id", None),
        agent_role_id=getattr(request.state, "api_key_agent_role_id", None),
        permissions=list(getattr(request.state, "api_key_permissions", []) or []),
        skills=list(getattr(request.state, "api_key_skills", []) or []),
        api_key_name=getattr(request.state, "api_key_name", None),
    )


def _is_api_key_authenticated(request: Request) -> bool:
    return getattr(request.state, "auth_method", None) == "api_key"


async def handle_streamable_http(
    request: Request,
    manager: McpSessionManager,
    server: McpProtocolServer,
) -> Response:
    """Handle a ``POST /mcp`` Streamable HTTP request."""
    if not _is_api_key_authenticated(request):
        return JSONResponse(
            status_code=401,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "API key authentication required"}},
        )

    try:
        body: Any = await request.json()
    except Exception as exc:  # noqa: BLE001
        return _jsonrpc_error_response(None, -32700, "Parse error", None)

    session_id = request.headers.get("mcp-session-id") or request.headers.get("x-session-id")
    session = manager.get_session(session_id) if session_id else None
    if session is None:
        session = _session_from_request(request, manager)

    response_msg = await server.handle(request, body, session)

    headers = {"mcp-session-id": session.session_id, "Cache-Control": "no-cache"}
    if response_msg is None:
        # Notification (e.g. notifications/initialized) — 202 with no body.
        return Response(status_code=202, headers=headers)

    return Response(
        content=json.dumps(response_msg) + "\n",
        media_type="application/json",
        headers=headers,
    )


def _jsonrpc_error_response(request_id: Any, code: int, message: str, session_id: str | None) -> Response:
    payload = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    headers = {"Cache-Control": "no-cache"}
    if session_id:
        headers["mcp-session-id"] = session_id
    return JSONResponse(status_code=200, content=payload, headers=headers)
