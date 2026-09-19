"""FastAPI router + registration for the MCP protocol server.

Mounts the MCP protocol endpoints on the Communication Hub. Registration is
gated on ``CH_MCP_PROTOCOL_SERVER_ENABLED`` (default off) so the endpoint is
opt-in and the existing REST ``/mcp/tools/load_skills`` and internal mTLS paths
remain available exactly as before when the flag is off.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from app.communication_hub.mcp.protocol_server import McpProtocolServer
from app.communication_hub.mcp.session_manager import McpSessionManager
from app.communication_hub.mcp.sse_transport import handle_sse_message, handle_sse_open
from app.communication_hub.mcp.streamable_http import handle_streamable_http

logger = logging.getLogger(__name__)

mcp_protocol_router = APIRouter(prefix="/mcp", tags=["MCP - Protocol Server"])

#: Module-level singletons, initialized lazily on first registration.
_session_manager: McpSessionManager | None = None
_protocol_server: McpProtocolServer | None = None


def _get_session_manager() -> McpSessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = McpSessionManager()
    return _session_manager


def _get_protocol_server() -> McpProtocolServer:
    global _protocol_server
    if _protocol_server is None:
        _protocol_server = McpProtocolServer()
    return _protocol_server


@mcp_protocol_router.post("")
async def mcp_streamable_http_endpoint(request: Request) -> Any:
    """MCP Streamable HTTP endpoint (JSON-RPC over POST)."""
    return await handle_streamable_http(
        request, _get_session_manager(), _get_protocol_server()
    )


@mcp_protocol_router.get("/sse")
async def mcp_sse_endpoint(request: Request) -> Any:
    """MCP Server-Sent Events stream endpoint."""
    return await handle_sse_open(request, _get_session_manager())


@mcp_protocol_router.post("/sse/messages")
async def mcp_sse_messages_endpoint(request: Request) -> Any:
    """MCP SSE message endpoint (JSON-RPC posted by the client)."""
    return await handle_sse_message(
        request, _get_session_manager(), _get_protocol_server()
    )


def register_mcp_protocol_server(app: Any, enabled: bool) -> None:
    """Register the MCP protocol router on the CH app when enabled."""
    if not enabled:
        logger.info("MCP protocol server disabled (CH_MCP_PROTOCOL_SERVER_ENABLED=false)")
        return
    app.include_router(mcp_protocol_router)
    logger.info("MCP protocol server enabled and registered (CH_MCP_PROTOCOL_SERVER_ENABLED=true)")
