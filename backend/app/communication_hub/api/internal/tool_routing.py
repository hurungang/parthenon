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

# Session-level cache of user JWTs for dual-identity tool calls
# Keyed by session_id, populated by WebSocket chat on user auth
_user_jwt_by_session: dict[str, str] = {}


def cache_user_jwt(session_id: str, user_jwt: str) -> None:
    """Store user JWT for a conversation session (called by WebSocket on auth)."""
    _user_jwt_by_session[session_id] = user_jwt
    logger.debug("Cached user JWT for session %s", session_id[:8])


def get_user_jwt(session_id: str) -> str | None:
    """Retrieve cached user JWT for a conversation session."""
    return _user_jwt_by_session.get(session_id)


def _allow_insecure_internal_fallback() -> bool:
    """Return True only for explicit development-mode insecure fallback opt-in."""
    environment = os.environ.get("ENVIRONMENT", "").strip().lower()
    opt_in = os.environ.get("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "").strip().lower()
    return environment == "development" and opt_in in {"1", "true", "yes", "on"}


def _build_control_center_auth(
    request: Request,
    cc_base: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build transport kwargs and headers for authenticated CH -> CC calls."""
    cert_manager = getattr(request.app.state, "certificate_manager", None)
    client_kwargs: dict[str, Any] = {
        "timeout": 60.0,
        "verify": get_ssl_context(),
    }
    headers: dict[str, str] = {}

    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if cc_base.startswith("https://"):
            client_kwargs["cert"] = (str(cert_manager.cert_path), str(cert_manager.key_path))
        else:
            from pathlib import Path

            cert_content = Path(cert_manager.cert_path).read_text()
            headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")
        return client_kwargs, headers

    if _allow_insecure_internal_fallback():
        logger.warning(
            "CH tool routing using insecure internal-call fallback because "
            "ALLOW_INSECURE_INTERNAL_CALL_FALLBACK is enabled in development"
        )
        return client_kwargs, headers

    raise HTTPException(
        status_code=503,
        detail=(
            "Communication Hub service certificate is required for Control Center internal calls"
        ),
    )


class ToolCallRequest(BaseModel):
    """Request to call a tool via Communication Hub."""

    tool_name: str
    tool_args: dict[str, Any]
    session_id: str
    agent_type_id: str
    user_jwt: str | None = None  # User identity JWT for dual-identity passthrough
    conv_session_id: str | None = None  # Parent conversation session ID for conversation-context interventions


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
    # Auto-populate user_jwt from session cache if not already provided
    if not body.user_jwt and body.session_id:
        body.user_jwt = get_user_jwt(body.session_id)
        if body.user_jwt:
            logger.debug("Populated user_jwt from session cache for session %s", body.session_id[:8])
    route_type = "system" if _is_system_tool(body.tool_name) else "mcp"
    logger.info(
        "Tool call request: tool=%s, session=%s, route_type=%s",
        body.tool_name,
        body.session_id,
        route_type,
        extra={
            "data": {
                "tool_name": body.tool_name,
                "session_id": body.session_id,
                "agent_type_id": body.agent_type_id,
                "route_type": route_type,
            }
        },
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
    if route_type == "system":
        return await _route_to_system_tool(body, request)

    # MCP tools route to Control Center MCP proxy
    return await _route_to_mcp_tool(body, request)


async def _route_to_system_tool(body: ToolCallRequest, request: Request) -> ToolCallResponse:
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

    logger.info(
        "Routing system tool '%s' (bare: %s) to Control Center",
        body.tool_name,
        bare_name,
        extra={
            "data": {
                "route_type": "system",
                "tool_name": body.tool_name,
                "normalized_tool_name": bare_name,
                "session_id": body.session_id,
                "agent_type_id": body.agent_type_id,
            }
        },
    )

    # Map bare tool name to Control Center endpoint
    cc_base = settings.control_center_url or "http://localhost:8000"
    endpoint_map = {
        "save_result": f"{cc_base}/api/v1/internal/system-tools/save-result",
        "send_notification": f"{cc_base}/api/v1/internal/system-tools/send-notification",
        "get_recipient_group": f"{cc_base}/api/v1/internal/system-tools/get-recipient-group",
        "human_intervene": f"{cc_base}/api/v1/internal/system-tools/human-intervene",
        "query_result": f"{cc_base}/api/v1/internal/system-tools/query-result",
    }

    endpoint = endpoint_map.get(bare_name)
    if not endpoint:
        logger.error("Unknown system tool: %s (bare: %s)", body.tool_name, bare_name)
        return ToolCallResponse(result={}, error=f"Unknown system tool: {body.tool_name}")

    logger.info(
        "System tool endpoint resolved: tool=%s endpoint=%s",
        bare_name,
        endpoint,
        extra={
            "data": {
                "route_type": "system",
                "normalized_tool_name": bare_name,
                "control_center_endpoint": endpoint,
            }
        },
    )

    # Validate required args locally so callers get actionable errors without
    # cross-service retries and masked 502 statuses.
    if bare_name == "send_notification":
        if not body.tool_args.get("group_slug") or not body.tool_args.get("body"):
            return ToolCallResponse(
                result={},
                error="Invalid send_notification args: group_slug and body are required",
            )
    if bare_name == "get_recipient_group":
        if not body.tool_args.get("group_slug"):
            return ToolCallResponse(
                result={},
                error="Invalid get_recipient_group args: group_slug is required",
            )

    # Call Control Center with mTLS certificate
    payload: dict[str, Any] = {
        "session_id": body.session_id,
        "tool_args": body.tool_args,
    }
    if body.conv_session_id:
        payload["conversation_session_id"] = body.conv_session_id

    try:
        cc_client_kwargs, headers = _build_control_center_auth(request, cc_base)
        async with httpx.AsyncClient(**cc_client_kwargs) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()

            logger.info(
                "System tool '%s' completed successfully",
                body.tool_name,
                extra={
                    "data": {
                        "route_type": "system",
                        "tool_name": body.tool_name,
                        "normalized_tool_name": bare_name,
                        "session_id": body.session_id,
                        "status_code": response.status_code,
                    }
                },
            )
            return ToolCallResponse(result=result)

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        detail = exc.response.text[:200]
        error_msg = f"Control Center system tool call failed: HTTP {status_code} - {detail}"
        logger.error(
            "%s",
            error_msg,
            extra={
                "data": {
                    "route_type": "system",
                    "tool_name": body.tool_name,
                    "normalized_tool_name": bare_name,
                    "session_id": body.session_id,
                    "status_code": status_code,
                }
            },
        )
        if 400 <= status_code < 500:
            return ToolCallResponse(result={}, error=error_msg)
        raise HTTPException(status_code=502, detail=error_msg)
    except Exception as exc:
        error_msg = f"System tool call error: {exc}"
        logger.exception(
            "System tool call failed for %s",
            body.tool_name,
            extra={
                "data": {
                    "route_type": "system",
                    "tool_name": body.tool_name,
                    "normalized_tool_name": bare_name,
                    "session_id": body.session_id,
                }
            },
        )
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
    logger.info(
        "Routing MCP tool '%s' to Control Center proxy",
        body.tool_name,
        extra={
            "data": {
                "route_type": "mcp",
                "tool_name": body.tool_name,
                "session_id": body.session_id,
                "agent_type_id": body.agent_type_id,
            }
        },
    )

    cc_base = settings.control_center_url or "http://localhost:8000"
    proxy_endpoint = f"{cc_base}/api/v1/internal/mcp/proxy-tool"

    payload = {
        "tool_name": body.tool_name,
        "tool_args": body.tool_args,
        "agent_type_id": body.agent_type_id,
        "agent_session_id": body.session_id,
        "user_jwt": body.user_jwt,
    }

    try:
        cc_client_kwargs, headers = _build_control_center_auth(request, cc_base)

        async with httpx.AsyncClient(**cc_client_kwargs) as client:
            response = await client.post(proxy_endpoint, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()

        logger.info(
            "MCP tool '%s' completed via Control Center proxy",
            body.tool_name,
            extra={
                "data": {
                    "route_type": "mcp",
                    "tool_name": body.tool_name,
                    "session_id": body.session_id,
                    "status_code": response.status_code,
                }
            },
        )
        return ToolCallResponse(result=result.get("result", {}))

    except httpx.HTTPStatusError as exc:
        error_msg = f"Control Center MCP proxy call failed: HTTP {exc.response.status_code}"
        logger.error(
            "%s - %s",
            error_msg,
            exc.response.text[:200],
            extra={
                "data": {
                    "route_type": "mcp",
                    "tool_name": body.tool_name,
                    "session_id": body.session_id,
                    "status_code": exc.response.status_code,
                }
            },
        )
        raise HTTPException(status_code=502, detail=error_msg)
    except Exception as exc:
        error_msg = f"MCP proxy call error: {exc}"
        logger.exception(
            "MCP proxy call failed for %s",
            body.tool_name,
            extra={
                "data": {
                    "route_type": "mcp",
                    "tool_name": body.tool_name,
                    "session_id": body.session_id,
                }
            },
        )
        raise HTTPException(status_code=502, detail=error_msg)
