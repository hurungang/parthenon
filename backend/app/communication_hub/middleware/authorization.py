"""Communication Hub Certificate Authorization Middleware.

Validates agent client certificates and checks permissions with Control Center
before every tool call execution.

Authorization flow per tool call:
1. Extract client certificate PEM from request (X-Client-Certificate header or TLS)
2. Validate certificate via Control Center /internal/certificates/validate
3. If invalid → 403 Forbidden with reason
4. Call Control Center /internal/authorize/tool-call for permission check + identity token
5. If unauthorized → 403 Forbidden (permissions) or 503 (token refresh failed)
6. Execute tool with Control Center-provided identity token
7. Log all authorization decisions for audit trail

Security guarantees:
- Agent Runtime NEVER provides identity tokens
- All tokens come from Control Center on-demand
- Certificate revocation takes effect immediately (checked on every call)
- No caching of authorization decisions
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

import httpx
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

_TOOL_CALL_PATH_PREFIX = "/tools/"


def _get_control_center_url() -> str:
    return os.environ.get("CONTROL_CENTER_URL", "").rstrip("/")


# ── Core functions ────────────────────────────────────────────────────────────


def extract_client_certificate(request: Request) -> str | None:
    """Extract client certificate PEM from the request.

    Checks:
    1. X-Client-Certificate header (for reverse-proxy setups where the proxy
       terminates TLS and forwards the cert as a header)
    2. request.state.client_certificate (set by TLS layer if available)

    Args:
        request: FastAPI/Starlette request.

    Returns:
        PEM-encoded certificate string, or None if not present.
    """
    # Check header first (reverse proxy / nginx $ssl_client_cert forwarding)
    header_cert = request.headers.get("X-Client-Certificate")
    if header_cert:
        # nginx encodes percent-escapes; decode if necessary
        try:
            from urllib.parse import unquote
            return unquote(header_cert)
        except Exception:
            return header_cert

    # Check request state (set by TLS middleware if present)
    return getattr(request.state, "client_certificate", None)


async def validate_certificate_with_control_center(
    cert_pem: str,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Call Control Center certificate validation API.

    Args:
        cert_pem: PEM-encoded certificate to validate.
        tool_name: Operation being authorized (for audit log).

    Returns:
        Validation response dict with 'valid', 'serial_number', 'reason', etc.
    """
    control_center_url = _get_control_center_url()
    if not control_center_url:
        return {"valid": False, "reason": "control_center_url_not_configured"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{control_center_url}/api/v1/internal/certificates/validate",
                json={
                    "certificate_pem": cert_pem,
                    "requested_operation": tool_name,
                },
            )
        return response.json()
    except Exception as exc:
        logger.error("Failed to contact Control Center for cert validation: %s", exc)
        return {"valid": False, "reason": f"control_center_unavailable: {exc}"}


async def authorize_tool_call(
    cert_serial_number: str,
    tool_name: str,
    tool_params: dict | None = None,
) -> dict[str, Any]:
    """Call Control Center tool call authorization API.

    Args:
        cert_serial_number: Agent certificate serial number.
        tool_name: Tool being called.
        tool_params: Tool parameters (for audit logging only).

    Returns:
        Authorization response dict with 'authorized', 'identity_token', 'reason', etc.
    """
    control_center_url = _get_control_center_url()
    if not control_center_url:
        return {"authorized": False, "reason": "control_center_url_not_configured"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{control_center_url}/api/v1/internal/authorize/tool-call",
                json={
                    "certificate_serial_number": cert_serial_number,
                    "tool_name": tool_name,
                    "tool_params": tool_params,
                },
            )
        return response.json()
    except Exception as exc:
        logger.error("Failed to contact Control Center for authorization: %s", exc)
        return {"authorized": False, "reason": f"control_center_unavailable: {exc}"}


async def execute_tool_with_identity(
    tool_name: str,
    params: dict,
    identity_token: str,
    tool_executor: Callable,
) -> Any:
    """Execute a tool using the Control Center-provided identity token.

    The identity_token is injected into the execution context and is NEVER
    transmitted back to the Agent Runtime.

    Args:
        tool_name: Tool to execute.
        params: Tool parameters from the agent request.
        identity_token: Access token from Control Center (decrypted).
        tool_executor: Callable that executes the tool.

    Returns:
        Tool execution result.
    """
    return await tool_executor(tool_name, params, identity_token)


def log_authorization_decision(
    cert_serial: str | None,
    cert_cn: str | None,
    tool_name: str,
    outcome: str,
    reason: str | None,
) -> None:
    """Log authorization decision for audit trail."""
    logger.info(
        "Authorization decision: cert_serial=%s cert_cn=%s tool=%s outcome=%s reason=%s",
        cert_serial,
        cert_cn,
        tool_name,
        outcome,
        reason,
    )


# ── Middleware Class ──────────────────────────────────────────────────────────


class CertificateAuthorizationMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware that validates agent certificates on tool calls.

    Applies to requests matching /tools/{tool_name}.  Other paths pass through
    without certificate validation (they use standard JWT auth from JWTAuthMiddleware).

    Authorization errors:
    - Invalid certificate: 403 with message "Invalid certificate: {reason}"
    - Insufficient permissions: 403 with message "Insufficient permissions: ..."
    - Token refresh failed: 503 with message "Identity token refresh failed: ..."

    The validated identity_token from Control Center is attached to request.state
    for downstream tool executors to use.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Only apply to tool call paths
        path = request.url.path
        if not path.startswith(_TOOL_CALL_PATH_PREFIX):
            return await call_next(request)

        # Extract tool name from path
        tool_name = path[len(_TOOL_CALL_PATH_PREFIX):].split("/")[0]

        # 1. Extract client certificate
        cert_pem = extract_client_certificate(request)
        if not cert_pem:
            log_authorization_decision(None, None, tool_name, "rejected", "no_client_certificate")
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid certificate: no client certificate provided"},
            )

        # 2. Validate certificate with Control Center
        validation = await validate_certificate_with_control_center(cert_pem, tool_name)
        cert_serial = validation.get("serial_number")
        cert_cn = None  # Extracted from validation response if available

        if not validation.get("valid", False):
            reason = validation.get("reason", "unknown")
            log_authorization_decision(cert_serial, cert_cn, tool_name, "rejected", reason)
            return JSONResponse(
                status_code=403,
                content={"detail": f"Invalid certificate: {reason}"},
            )

        # 3. Authorize tool call (permission check + token)
        authorization = await authorize_tool_call(
            cert_serial_number=cert_serial,
            tool_name=tool_name,
        )

        if not authorization.get("authorized", False):
            reason = authorization.get("reason", "unknown")
            agent_type = authorization.get("agent_type", "unknown")
            required = authorization.get("required_permission")

            log_authorization_decision(cert_serial, cert_cn, tool_name, "denied", reason)

            # Distinguish between permission denied and token refresh failure
            if "token_refresh_failed" in reason:
                return JSONResponse(
                    status_code=503,
                    content={"detail": f"Identity token refresh failed: {reason}"},
                )

            if required:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            f"Insufficient permissions: tool '{tool_name}' "
                            f"not allowed for agent type '{agent_type}'"
                        ),
                        "certificate_serial": cert_serial,
                        "required_permission": required,
                    },
                )

            return JSONResponse(
                status_code=403,
                content={
                    "detail": f"Authorization denied: {reason}",
                    "certificate_serial": cert_serial,
                },
            )

        # 4. Attach identity token to request state for tool executor
        #    The token is used internally and is NEVER returned to the agent.
        identity_token = authorization.get("identity_token")
        request.state.identity_token = identity_token
        request.state.authorized_agent_type_id = authorization.get("agent_type_id")
        request.state.authorized_identity_id = authorization.get("identity_id")

        log_authorization_decision(cert_serial, cert_cn, tool_name, "authorized", None)

        # 5. Execute tool
        return await call_next(request)
