"""JWT authentication middleware."""

import logging
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.oidc_client import OIDCError, get_oidc_client

logger = logging.getLogger(__name__)

# Paths that bypass authentication
PUBLIC_PATHS: set[str] = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/setup/init",
    "/api/v1/setup/identity-status",
    "/api/v1/setup/identity",
    "/api/v1/ping",
    "/api/v1/telemetry/config",
}


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    Extract bearer token from the Authorization header, validate via OIDCClient,
    and attach identity claims to request.state.identity.

    After successful validation, upserts the PlatformUser record and maps
    IdP group claims to UserGroup memberships. Both side effects are fire-and-log
    — failures produce a warning but do not fail the request.

    Public paths are excluded from authentication.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        logger.debug("Auth middleware: %s %s", request.method, path)

        # Allow OPTIONS preflight and public paths
        if request.method == "OPTIONS" or self._is_public(path):
            logger.debug("Auth middleware: Allowing public path or OPTIONS: %s", path)
            return await call_next(request)

        # WebSocket connections pass token as query param
        if request.scope.get("type") == "websocket":
            token = request.query_params.get("token")
            logger.debug("Auth middleware: WebSocket connection, token from query param")
        else:
            authorization = request.headers.get("Authorization", "")
            logger.debug("Auth middleware: Authorization header present: %s", bool(authorization))
            if not authorization.startswith("Bearer "):
                logger.warning(
                    "Auth middleware: Missing or invalid Authorization header for %s", path
                )
                return self._unauthorized(request, "Missing or invalid Authorization header")
            token = authorization[len("Bearer ") :]
            logger.debug("Auth middleware: Token extracted (length: %d)", len(token))

        if not token:
            logger.warning("Auth middleware: No token provided for %s", path)
            return self._unauthorized(request, "No token provided")

        try:
            client = get_oidc_client()
            logger.debug("Auth middleware: Validating token for %s", path)
            claims: dict[str, Any] = await client.validate_token(token)
            request.state.identity = claims
            logger.info(
                "Auth middleware: Token validated successfully for %s (sub: %s)",
                path,
                claims.get("sub", "unknown"),
            )
        except OIDCError as exc:
            logger.warning("JWT validation failed for %s: %s", path, exc)
            logger.debug("JWT validation error details: %s", exc, exc_info=True)
            return self._unauthorized(request, str(exc))
        except Exception as exc:
            logger.error("Unexpected auth error for %s: %s", path, exc, exc_info=True)
            return self._unauthorized(request, "Authentication error")

        # ── User cache upsert + group claim mapping ────────────────────────────
        # Both are fire-and-log: failures must not block the request.
        await self._sync_user_and_groups(request, claims)
        # ──────────────────────────────────────────────────────────────────────

        return await call_next(request)

    async def _sync_user_and_groups(self, request: Request, claims: dict[str, Any]) -> None:
        """Upsert PlatformUser and map IdP group claims. Errors are logged only."""
        # Lazy imports to avoid startup circular dependencies
        try:
            from app.db.session import AsyncSessionLocal
            from app.services.permissions.group_claim_mapper import GroupClaimMapper
            from app.services.permissions.user_cache_service import UserCacheService
        except ImportError:
            return

        sub = claims.get("sub", "")
        email = claims.get("email", "") or ""
        display_name = claims.get("name") or claims.get("preferred_username", "") or sub

        try:
            async with AsyncSessionLocal() as session, session.begin():
                user_cache = UserCacheService()
                platform_user = await user_cache.upsert_user(
                    session, sub=sub, email=email, display_name=display_name
                )
                request.state.platform_user_id = platform_user.id

                group_claims: list[str] = claims.get("groups", [])
                if group_claims:
                    mapper = GroupClaimMapper()
                    new_groups = await mapper.map_claims(session, platform_user.id, group_claims)
                    if new_groups:
                        logger.info(
                            "Auto-assigned user %s to %d group(s) via IdP claims",
                            platform_user.id,
                            len(new_groups),
                        )
        except Exception as exc:
            logger.warning("User cache/group mapping failed for sub=%s: %s", sub, exc)

    def _is_public(self, path: str) -> bool:
        """Check if the path is in the public allowlist."""
        if path in PUBLIC_PATHS:
            return True
        # Exact prefix checks for Swagger assets
        return path.startswith("/docs/") or path.startswith("/redoc/")

    def _unauthorized(self, request: Request, detail: str) -> JSONResponse:
        """Return 401 response with CORS headers to prevent browser CORS errors."""
        response = JSONResponse(status_code=401, content={"detail": detail})

        # Add CORS headers for allowed origins to prevent browser CORS errors
        origin = request.headers.get("origin", "")
        allowed_origins = [
            "http://localhost:5173",
            "http://localhost:4173",
            "http://localhost:3000",
        ]

        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"

        return response
