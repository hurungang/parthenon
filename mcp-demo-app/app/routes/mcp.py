from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.auth import get_agent_identity
from app.config import settings
from app.tools import TOOL_MANIFEST, tool_registry

logger = logging.getLogger(__name__)

mcp_router = APIRouter()

_SERVER_INFO = {
    "name": "MCP Demo App",
    "version": "0.1.0",
}

_PROTOCOL_VERSION = "2024-11-05"


def _ok(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


@mcp_router.post("/mcp")
async def mcp_endpoint(request: Request) -> JSONResponse:
    body: dict[str, Any] = await request.json()
    method: str = body.get("method", "")
    request_id: Any = body.get("id")
    params: dict[str, Any] = body.get("params") or {}

    if method == "initialize":
        result = {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": _SERVER_INFO,
        }
        return JSONResponse(_ok(request_id, result))

    if method == "tools/list":
        return JSONResponse(_ok(request_id, {"tools": TOOL_MANIFEST}))

    if method == "tools/call":
        tool_name: str = params.get("name", "")
        handler = tool_registry.get(tool_name)
        if handler is None:
            return JSONResponse(_error(request_id, -32601, f"Unknown tool: {tool_name}"))

        # Validate the agent identity for tool calls
        agent_identity = await get_agent_identity(request)
        tool_result = handler(agent_identity)
        return JSONResponse(
            _ok(
                request_id,
                {
                    "content": [{"type": "text", "text": str(tool_result)}],
                    "result": tool_result,
                },
            )
        )

    return JSONResponse(_error(request_id, -32601, f"Method not found: {method}"))
