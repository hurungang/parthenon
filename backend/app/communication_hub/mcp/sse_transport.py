"""Server-Sent Events (SSE) transport for the MCP protocol server.

Provides a minimal, compatibility-focused SSE transport:

- ``GET /mcp/sse`` opens an event stream, announces the message endpoint, and
  keeps the stream open for streaming-capable clients.
- ``POST /mcp/sse/messages`` accepts JSON-RPC messages and returns the JSON-RPC
  response directly in the HTTP response body.

Both endpoints share the same protocol server and session manager as the
Streamable HTTP transport, so permission filtering and method semantics are
identical across transports.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.communication_hub.mcp.protocol_server import McpProtocolServer
from app.communication_hub.mcp.session_manager import McpSessionManager

logger = logging.getLogger(__name__)


def _is_api_key_authenticated(request: Request) -> bool:
    return getattr(request.state, "auth_method", None) == "api_key"


async def handle_sse_open(
    request: Request,
    manager: McpSessionManager,
) -> Response:
    """Open an SSE stream for the client and announce the message endpoint."""
    if not _is_api_key_authenticated(request):
        return JSONResponse(
            status_code=401,
            content={"detail": "API key authentication required"},
        )

    session = manager.create_session(
        identity_token=getattr(request.state, "identity_token", None),
        agent_identity_id=getattr(request.state, "api_key_agent_identity_id", None),
        agent_role_id=getattr(request.state, "api_key_agent_role_id", None),
        permissions=list(getattr(request.state, "api_key_permissions", []) or []),
        skills=list(getattr(request.state, "api_key_skills", []) or []),
        api_key_name=getattr(request.state, "api_key_name", None),
    )
    session_id = session.session_id

    async def event_stream() -> AsyncIterator[str]:
        endpoint = f"/mcp/sse/messages?sessionId={session_id}"
        yield f"event: endpoint\ndata: {endpoint}\n\n"
        # Keep the stream alive with periodic comments; the client drives the
        # protocol over the message endpoint.
        while True:
            try:
                await asyncio.sleep(30)
                yield ": keep-alive\n\n"
            except asyncio.CancelledError:
                manager.delete_session(session_id)
                return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


async def handle_sse_message(
    request: Request,
    manager: McpSessionManager,
    server: McpProtocolServer,
) -> Response:
    """Handle a JSON-RPC message posted to the SSE message endpoint."""
    if not _is_api_key_authenticated(request):
        return JSONResponse(
            status_code=401,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "API key authentication required"}},
        )

    try:
        body: Any = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(
            status_code=200,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
        )

    session_id = request.query_params.get("sessionId") or request.headers.get("mcp-session-id")
    session = manager.get_session(session_id) if session_id else None

    if session is None:
        # Fall back to creating a session from the auth context.
        session = manager.create_session(
            identity_token=getattr(request.state, "identity_token", None),
            agent_identity_id=getattr(request.state, "api_key_agent_identity_id", None),
            agent_role_id=getattr(request.state, "api_key_agent_role_id", None),
            permissions=list(getattr(request.state, "api_key_permissions", []) or []),
            skills=list(getattr(request.state, "api_key_skills", []) or []),
            api_key_name=getattr(request.state, "api_key_name", None),
        )

    response_msg = await server.handle(request, body, session)
    if response_msg is None:
        return Response(status_code=202)
    return JSONResponse(status_code=200, content=response_msg)
