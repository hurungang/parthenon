"""Communication Hub — API Key Authentication Middleware for External Agents.

Detects API key authentication on incoming MCP requests, validates keys via
Control Center's internal API over mTLS, and enriches the request context with
resolved identity tokens and permissions.

Coexists with existing mTLS certificate auth — API key auth is additive.
Certificate-based auth path is unchanged.

Detection order:
1. ``Authorization: Bearer <api_key>`` header
2. ``?apiKey=<api_key>`` query parameter (only if no Bearer header)

The raw key is SHA-256 hashed before being sent to Control Center — the raw
key is never transmitted across services, even under mTLS.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.ssl_context import get_ssl_context

logger = logging.getLogger(__name__)

# MCP endpoints that support API key auth (external agent paths)
_MCP_PATH_PREFIX = "/mcp"

# Headers to extract key from
_BEARER_PREFIX = "Bearer "
_QUERY_PARAM_NAME = "apiKey"


def _get_control_center_url() -> str:
    return os.environ.get("CONTROL_CENTER_URL", "").rstrip("/")


def _hash_api_key(raw_key: str) -> str:
    """SHA-256 hash a raw API key for secure transmission."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _extract_api_key(request: Request) -> str | None:
    """Extract API key from request headers or query parameters.

    Checks:
    1. ``Authorization: Bearer <value>`` header
    2. ``?apiKey=<value>`` query parameter (fallback)
    """
    # Check Bearer token header first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith(_BEARER_PREFIX):
        raw_key = auth_header[len(_BEARER_PREFIX):].strip()
        if raw_key:
            return raw_key

    # Fallback to query parameter
    query_key = request.query_params.get(_QUERY_PARAM_NAME)
    if query_key:
        return query_key

    return None


def _build_mtls_client(request: Request) -> tuple[dict[str, Any], dict[str, str]]:
    """Build authenticated HTTP client config for CH -> CC internal calls."""
    cert_manager = getattr(request.app.state, "certificate_manager", None)
    control_center_url = _get_control_center_url()

    client_kwargs: dict[str, Any] = {
        "timeout": 10.0,
        "verify": get_ssl_context(),
    }
    headers: dict[str, str] = {}

    if cert_manager and cert_manager.cert_path and cert_manager.key_path:
        if control_center_url.startswith("https://"):
            client_kwargs["cert"] = (str(cert_manager.cert_path), str(cert_manager.key_path))
        else:
            cert_content = Path(cert_manager.cert_path).read_text()
            headers["X-Client-Certificate"] = cert_content.replace("\n", "\\n")
        return client_kwargs, headers

    # Development fallback
    environment = os.environ.get("ENVIRONMENT", "").strip().lower()
    opt_in = os.environ.get("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "").strip().lower()
    if environment == "development" and opt_in in {"1", "true", "yes", "on"}:
        logger.warning(
            "API key middleware using insecure internal fallback (development only)"
        )
        return client_kwargs, headers

    raise RuntimeError("Communication Hub service certificate is required for API key validation")


async def _validate_api_key_with_cc(
    request: Request,
    key_hash: str,
) -> dict[str, Any]:
    """Call Control Center internal API key validation endpoint.

    Sends the hashed key over mTLS — raw key never leaves the CH.
    """
    control_center_url = _get_control_center_url()
    if not control_center_url:
        return {"valid": False, "reason": "control_center_url_not_configured"}

    try:
        client_kwargs, headers = _build_mtls_client(request)
        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.post(
                f"{control_center_url}/api/v1/internal/auth/validate-api-key",
                json={"key_hash": key_hash},
                headers=headers,
            )
        if response.status_code == 200:
            return response.json()
        else:
            detail = "Unknown error"
            try:
                detail = response.json().get("detail", detail)
            except Exception:
                detail = response.text or detail
            return {"valid": False, "reason": detail, "status_code": response.status_code}
    except Exception as exc:
        logger.error("Failed to contact Control Center for API key validation: %s", exc)
        return {"valid": False, "reason": f"control_center_unavailable: {exc}"}


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """Middleware detecting API key auth on MCP paths and routing to CC validation.

    Applies to paths matching ``/mcp*``.  Other paths pass through without
    modification (they use standard JWT auth or existing cert auth).

    On successful validation, the resolved identity token and permission set are
    stored on ``request.state`` for downstream handlers.  Identity tokens are
    held exclusively by CH — never returned to external agents.

    Coexists with ``CertificateAuthorizationMiddleware`` — API key auth is
    additive.  Certificate-based paths (``/tools/*``) are not affected.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Only apply to MCP paths (external agent endpoints)
        if not path.startswith(_MCP_PATH_PREFIX):
            return await call_next(request)

        # Try to extract API key
        raw_key = _extract_api_key(request)
        if raw_key is None:
            # No API key — let the request proceed (may be handled by other auth)
            return await call_next(request)

        # Hash the key for secure transmission to CC
        key_hash = _hash_api_key(raw_key)

        # Validate with Control Center
        validation = await _validate_api_key_with_cc(request, key_hash)

        if not validation.get("valid", False):
            reason = validation.get("reason", "Invalid API key")
            status_code = validation.get("status_code", 401)
            logger.warning(
                "API key auth rejected: path=%s reason=%s",
                path,
                reason,
            )
            return JSONResponse(
                status_code=status_code,
                content={
                    "detail": f"Authentication failed: {reason}",
                    "auth_type": "api_key",
                },
            )

        # Store resolved identity token and permissions on request state
        request.state.identity_token = validation.get("identity_token")
        request.state.api_key_agent_identity_id = validation.get("agent_identity_id")
        request.state.api_key_agent_role_id = validation.get("agent_role_id")
        request.state.api_key_permissions = validation.get("permissions", [])
        request.state.api_key_skills = validation.get("skills", [])
        request.state.api_key_name = validation.get("api_key_name")
        request.state.auth_method = "api_key"

        logger.info(
            "API key auth succeeded: key_name=%s path=%s",
            validation.get("api_key_name"),
            path,
        )

        return await call_next(request)
