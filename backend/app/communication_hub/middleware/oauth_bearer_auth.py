"""Communication Hub — OAuth/OIDC Bearer-token auth middleware for the MCP server.

Adds an OAuth/OIDC auth path on the MCP protocol server (``/mcp*``), parallel
to :class:`ApiKeyAuthMiddleware`: a client presents the *user's* OIDC Bearer
token (a JWT), the middleware validates it against the identity provider, then
resolves the user's identity, tenant and permission scope (the set of
management tools the user may invoke) from Control Center.  The resolved
context is seeded into the MCP session; the identity token itself is held
server-side only and never returned to the client.

Coexistence: API keys are opaque ``phn_sk_*`` strings; OAuth tokens are JWTs.
This middleware only acts on JWT-looking tokens and lets everything else fall
through to the existing API-key path unchanged.  An invalid/expired JWT is
rejected with 401 (fail closed); a missing token falls through so the transport
can apply its own 401.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.communication_hub.mcp.cc_client import build_cc_client, get_control_center_url
from app.core.internal_http import internal_httpx_client
from app.core.oidc_client import OIDCError, get_oidc_client

logger = logging.getLogger(__name__)

_MCP_PATH_PREFIX = "/mcp"
_BEARER_PREFIX = "Bearer "
_RESOLVE_PATH = "/api/v1/internal/management-tools/resolve"


def _extract_bearer(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith(_BEARER_PREFIX):
        return None
    raw = auth_header[len(_BEARER_PREFIX):].strip()
    return raw or None


def _looks_like_jwt(token: str) -> bool:
    """Return True when *token* is a JWT (three dot-separated segments).

    API keys are opaque ``phn_sk_*`` strings — never treated as OAuth tokens.
    """
    if token.count(".") != 2:
        return False
    try:
        from jose import jwt

        header = jwt.get_unverified_header(token)
        return "alg" in header
    except Exception:
        return False


async def _validate_token(token: str) -> dict[str, Any] | None:
    """Validate an OIDC token; fall back to a platform-account JWT."""
    try:
        return await get_oidc_client().validate_token(token)
    except OIDCError:
        pass
    except Exception:  # noqa: BLE001
        logger.warning("OAuth middleware: unexpected OIDC error", exc_info=True)
    try:
        from app.services.tenancy.platform_account_auth_service import (
            validate_platform_account_token,
        )

        return validate_platform_account_token(token)
    except Exception:
        logger.warning("OAuth middleware: platform token validation failed", exc_info=True)
        return None


class OAuthBearerAuthMiddleware(BaseHTTPMiddleware):
    """Validate the user's OIDC Bearer token on ``/mcp*`` and seed the session.

    Runs before :class:`ApiKeyAuthMiddleware` (registered later → outermost):
    JWT tokens are handled here; opaque API keys fall through untouched.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        if not path.startswith(_MCP_PATH_PREFIX):
            return await call_next(request)

        token = _extract_bearer(request)
        if token is None or not _looks_like_jwt(token):
            # Not an OAuth token — leave it to the API-key middleware / transport.
            return await call_next(request)

        claims = await _validate_token(token)
        if claims is None:
            logger.warning("OAuth middleware: invalid user token on %s", path)
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authentication failed: invalid or expired OAuth token",
                    "auth_type": "oauth",
                },
            )

        sub = claims.get("sub")
        if not sub:
            logger.warning("OAuth middleware: token missing sub claim on %s", path)
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication failed: missing subject", "auth_type": "oauth"},
            )

        tenant_slug = claims.get("tenant")
        resolved = await self._resolve_with_cc(
            request, sub, tenant_slug if isinstance(tenant_slug, str) else None
        )
        if resolved is None:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authentication failed: user not resolvable",
                    "auth_type": "oauth",
                },
            )

        # Seed the request state for the transports (identity held server-side).
        request.state.auth_method = "oauth"
        request.state.user_sub = sub
        request.state.platform_user_id = resolved.get("platform_user_id")
        request.state.permissions = list(resolved.get("permitted_tools") or [])
        request.state.tenant_id = resolved.get("tenant_id")

        tenant_headers = resolved.get("tenant_headers")
        if tenant_headers:
            from app.core.tenant_signature import bind_forwarded_tenant_headers

            bind_forwarded_tenant_headers(dict(tenant_headers))
            logger.info(
                "OAuth middleware: bound tenant %s for user %s",
                resolved.get("tenant_id"), sub,
            )

        logger.info("OAuth middleware: authenticated user %s on %s", sub, path)
        return await call_next(request)

    async def _resolve_with_cc(
        self, request: Request, sub: str, tenant_slug: str | None
    ) -> dict[str, Any] | None:
        """Resolve the user's identity, tenant and permitted tools from CC."""
        cc_base = get_control_center_url()
        if not cc_base:
            logger.error("OAuth middleware: Control Center URL not configured")
            return None
        try:
            client_kwargs, headers = build_cc_client(request, cc_base)
            payload: dict[str, Any] = {"sub": sub}
            if tenant_slug:
                payload["tenant"] = tenant_slug
            async with internal_httpx_client(**client_kwargs) as client:
                response = await client.post(
                    f"{cc_base}{_RESOLVE_PATH}", json=payload, headers=headers
                )
            if response.status_code == 200:
                return response.json()
            logger.warning(
                "OAuth middleware: CC resolve returned HTTP %d for sub %s",
                response.status_code, sub,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error("OAuth middleware: failed to resolve user via CC: %s", exc)
            return None
