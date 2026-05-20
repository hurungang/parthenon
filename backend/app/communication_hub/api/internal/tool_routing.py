"""Tool routing endpoint for Communication Hub.

Routes ALL tool calls from Agent Runtime to:
- External MCP servers (via MCP Proxy)
- Control Center system tools (system____save_result, system____send_notification,
  system____get_recipient_group)

All requests require valid agent certificate (mTLS).
All data (credentials, permissions) fetched from Control Center.
NO direct database access.
"""
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.ssl_context import get_ssl_context
from app.services.agents.tool_naming import is_system_tool as _is_system_tool, get_bare_tool_name

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/internal/tools", tags=["Internal - Tool Routing"])


class ToolCallRequest(BaseModel):
    """Request to call a tool via Communication Hub."""

    tool_name: str
    tool_args: dict[str, Any]
    session_id: str
    agent_type_id: str


class ToolCallResponse(BaseModel):
    """Response from tool execution."""

    result: dict[str, Any]
    error: str | None = None


@router.post("/call", response_model=ToolCallResponse)
async def route_tool_call(
    body: ToolCallRequest,
    request: Request,
) -> ToolCallResponse:
    """Route a tool call from Agent Runtime to the appropriate destination.

    Flow:
    1. Validate agent certificate (mTLS) - extract agent identity
    2. Call Control Center to validate permissions for tool
    3. If system tool (system____*) → route to CC system tool endpoints
    4. If MCP tool → get session credentials from CC, call MCP server
    5. Return result to Agent Runtime

    Args:
        body: Tool call request with tool name, args, session ID
        request: FastAPI request (contains certificate in TLS context)

    Returns:
        Tool execution result or error

    Raises:
        HTTPException: 401 if certificate invalid, 403 if permission denied, 502 if tool call fails
    """
    logger.info(
        "Tool call request: tool=%s, session=%s",
        body.tool_name,
        body.session_id,
    )

    # Extract and validate certificate
    # TODO: Implement proper certificate validation using existing middleware
    # For now, check if we're in development mode
    if settings.environment != "development":
        # In production, certificate validation is required
        # This will be handled by the certificate authorization middleware
        pass

    # System tools are identified by the canonical system____ prefix.
    # Also accept legacy bare names for backward compatibility (is_system_tool handles both).
    if _is_system_tool(body.tool_name):
        return await _route_to_system_tool(body)

    # MCP tools route to Control Center MCP proxy
    return await _route_to_mcp_tool(body, request)


async def _route_to_system_tool(body: ToolCallRequest) -> ToolCallResponse:
    """Route system tool call to Control Center internal endpoints.

    Accepts canonical ``system____*`` names, legacy bare names, and old
    ``system/*`` display names.

    Args:
        body: Tool call request

    Returns:
        Tool execution result

    Raises:
        HTTPException: If Control Center call fails
    """
    # Resolve to bare handler name (e.g. "save_result")
    try:
        bare_name = get_bare_tool_name(body.tool_name)
    except ValueError:
        # Fallback for legacy bare names that get_bare_tool_name can't parse
        bare_name = body.tool_name.split("/")[-1] if "/" in body.tool_name else body.tool_name

    logger.info("Routing system tool '%s' (bare: %s) to Control Center", body.tool_name, bare_name)

    # Map bare tool name to Control Center endpoint
    cc_base = settings.control_center_url or "http://localhost:8000"
    endpoint_map = {
        "save_result": f"{cc_base}/api/v1/internal/system-tools/save-result",
        "send_notification": f"{cc_base}/api/v1/internal/system-tools/send-notification",
        "get_recipient_group": f"{cc_base}/api/v1/internal/system-tools/get-recipient-group",
    }

    endpoint = endpoint_map.get(bare_name)
    if not endpoint:
        logger.error("Unknown system tool: %s (bare: %s)", body.tool_name, bare_name)
        return ToolCallResponse(result={}, error=f"Unknown system tool: {body.tool_name}")

    # Call Control Center with mTLS certificate
    payload = {
        "session_id": body.session_id,
        "tool_args": body.tool_args,
    }

    try:
        # TODO: Add mTLS certificate for authentication
        async with httpx.AsyncClient(timeout=30.0, verify=get_ssl_context()) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            result = response.json()

            logger.info("System tool '%s' completed successfully", body.tool_name)
            return ToolCallResponse(result=result)

    except httpx.HTTPStatusError as exc:
        error_msg = f"Control Center system tool call failed: HTTP {exc.response.status_code}"
        logger.error("%s - %s", error_msg, exc.response.text[:200])
        raise HTTPException(status_code=502, detail=error_msg)
    except Exception as exc:
        error_msg = f"System tool call error: {exc}"
        logger.exception("System tool call failed for %s", body.tool_name)
        raise HTTPException(status_code=502, detail=error_msg)


async def _route_to_mcp_tool(body: ToolCallRequest, request: Request) -> ToolCallResponse:
    """Route MCP tool call to Control Center MCP proxy endpoint.

    Delegates to Control Center /internal/mcp/proxy-tool which uses
    McpProxyEngine (handles session resolution, OAuth refresh,
    Mcp-Session-Id header, and JSON-RPC protocol).

    Args:
        body: Tool call request
        request: FastAPI request (for accessing app state/certificate manager)

    Returns:
        Tool execution result

    Raises:
        HTTPException: If proxy call fails
    """
    logger.info("Routing MCP tool '%s' to Control Center proxy", body.tool_name)

    cc_base = settings.control_center_url or "http://localhost:8000"
    proxy_endpoint = f"{cc_base}/api/v1/internal/mcp/proxy-tool"

    payload = {
        "tool_name": body.tool_name,
        "tool_args": body.tool_args,
        "agent_type_id": body.agent_type_id,
        "agent_session_id": body.session_id,
    }

    try:
        cert_manager = getattr(request.app.state, "certificate_manager", None)

        cc_client_kwargs: dict = {
            "timeout": 60.0,
            "verify": get_ssl_context(),
        }
        headers: dict[str, str] = {}

        if cert_manager and cert_manager.cert_path and cert_manager.key_path:
            if cc_base.startswith("https://"):
                cc_client_kwargs["cert"] = (str(cert_manager.cert_path), str(cert_manager.key_path))
                logger.info("Using mTLS certificate for Control Center MCP proxy call")
            else:
                from pathlib import Path
                cert_content = Path(cert_manager.cert_path).read_text()
                headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")
                logger.info("Using X-Client-Certificate header for Control Center MCP proxy call")
        else:
            logger.warning("No certificate manager — Control Center MCP proxy call may fail authentication")

        async with httpx.AsyncClient(**cc_client_kwargs) as client:
            response = await client.post(proxy_endpoint, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()

        logger.info("MCP tool '%s' completed via Control Center proxy", body.tool_name)
        return ToolCallResponse(result=result.get("result", {}))

    except httpx.HTTPStatusError as exc:
        error_msg = f"Control Center MCP proxy call failed: HTTP {exc.response.status_code}"
        logger.error("%s - %s", error_msg, exc.response.text[:200])
        raise HTTPException(status_code=502, detail=error_msg)
    except Exception as exc:
        error_msg = f"MCP proxy call error: {exc}"
        logger.exception("MCP proxy call failed for %s", body.tool_name)
        raise HTTPException(status_code=502, detail=error_msg)
