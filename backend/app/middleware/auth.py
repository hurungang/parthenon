"""JWT authentication middleware — three-tier auth pipeline.

Pipeline priority:
1. **Super admin token** — Check for super-admin Bearer token, validate via
   ``SuperAdminAuthService`` (bypasses OIDC entirely).
2. **OIDC JWT** — Validate against active OIDC providers via
   ``OIDCProviderRegistry``.  Tries both user and agent providers.
3. **Public paths** — Skip authentication for whitelisted paths.
"""

import logging
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.oidc_client import OIDCClient, OIDCError, get_oidc_client

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
    "/api/v1/agents/identities/oauth/callback",  # OAuth redirect from IdP (no bearer token)
    # New public endpoints for super admin and provider discovery
    "/api/v1/auth/super-admin/login",
    "/api/v1/auth/super-admin/refresh",
    # Self-authenticating SSE endpoint — browser EventSource cannot set
    # Authorization headers, so the endpoint validates the ``?token=``
    # query param itself (same pattern as the Communication Hub chat
    # WebSocket) and enforces the same permission as the REST endpoint.
    "/api/v1/agents/runtime/topology/stream",
}

# Public path prefixes (for sub-resources like Swagger assets)
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/docs/",
    "/redoc/",
    "/api/v1/internal/",
)

# Dedicated header for super admin tokens (alternative to Bearer)
SUPER_ADMIN_HEADER = "X-Super-Admin-Token"


# ── Shared token-validation tiers ─────────────────────────────────────────────
#
# Extracted as module-level functions so self-authenticating endpoints (the
# SSE topology stream, which receives its JWT via the ``?token=`` query param
# because EventSource cannot set request headers) reuse the EXACT same
# validation pipeline as the middleware — no duplicated OIDC logic.


async def _try_super_admin_token(token: str) -> dict[str, Any] | None:
    """Tier 1 — validate the token as a super admin JWT (or None)."""
    try:
        from app.services.super_admin_auth_service import (
            SuperAdminAuthError,
            super_admin_enabled,
            validate_super_admin_token,
        )
    except ImportError:
        logger.debug("Auth: SuperAdminAuthService not available")
        return None

    if not super_admin_enabled():
        logger.debug("Auth: Super admin disabled")
        return None

    try:
        claims = validate_super_admin_token(token)
        logger.debug("Auth: Super admin token valid")
        return claims
    except SuperAdminAuthError as exc:
        logger.debug("Auth: Super admin token invalid: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Auth: Unexpected error validating super admin token: %s", exc)
        return None


async def _try_oidc_token(token: str) -> dict[str, Any] | None:
    """Tier 2 — validate the token against the OIDC registry / legacy client."""
    try:
        from app.main import _get_registry
    except ImportError:
        logger.debug("Auth: OIDCProviderRegistry not available")
        return None

    registry = _get_registry()
    if not registry.initialized:
        logger.debug("Auth: Provider registry not yet initialized")
        return None

    # Try user provider first, then agent provider
    for scope in ("user", "agent"):
        provider = registry.get_provider(scope)
        if provider is None:
            continue

        try:
            client = OIDCClient(
                issuer_url=provider.issuer_url,
                client_id=provider.client_id,
                claim_mappings=provider.claim_mappings or {},
                decrypted_client_secret=registry.get_decrypted_secret(scope),
            )
            claims = await client.validate_token(token)
            claims["_provider_scope"] = scope
            logger.debug("Auth: OIDC token valid for scope=%s", scope)
            return claims
        except OIDCError as exc:
            logger.debug("Auth: OIDC validation failed for scope=%s: %s", scope, exc)
        except Exception as exc:
            logger.warning("Auth: Unexpected OIDC error for scope=%s: %s", scope, exc)

    # Fallback: try legacy singleton if no providers in registry
    if not registry.has_any_provider():
        logger.debug("Auth: No providers in registry, trying legacy singleton")
        try:
            client = get_oidc_client()
            claims = await client.validate_token(token)
            claims["_provider_scope"] = "legacy"
            logger.debug("Auth: Legacy OIDC token valid")
            return claims
        except OIDCError as exc:
            logger.debug("Auth: Legacy OIDC validation failed: %s", exc)
        except Exception as exc:
            logger.warning("Auth: Unexpected legacy OIDC error: %s", exc)

    return None


async def validate_raw_token(token: str) -> tuple[dict[str, Any] | None, bool]:
    """Validate a raw JWT through the full auth-tier pipeline.

    Tier order matches the middleware pipeline: super-admin token first,
    then OIDC (provider registry with legacy-singleton fallback).

    Returns:
        ``(claims, is_super_admin)`` — ``(None, False)`` when every tier fails.
    """
    super_admin_claims = await _try_super_admin_token(token)
    if super_admin_claims is not None:
        return super_admin_claims, True

    oidc_claims = await _try_oidc_token(token)
    if oidc_claims is not None:
        return oidc_claims, False

    return None, False


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    Three-tier authentication middleware:

    1. **Super admin token** — highest priority.  Validates local JWT
       (HS256, signed with Control Center secret key) via
       ``SuperAdminAuthService``.  When super admin is disabled, this
       tier is skipped.
    2. **OIDC JWT** — extracts Bearer token, queries
       ``OIDCProviderRegistry`` for active user and agent providers,
       validates via per-provider ``OIDCClient``.
    3. **Public fallback** — paths in ``PUBLIC_PATHS`` or matching
       ``PUBLIC_PREFIXES`` skip all auth checks.

    After successful validation, upserts the ``PlatformUser`` record and
    maps IdP group claims to ``UserGroup`` memberships.  Both side effects
    are fire-and-log — failures produce a warning but do not fail the request.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        logger.debug("Auth middleware: %s %s", request.method, path)

        # Allow OPTIONS preflight and public paths
        if request.method == "OPTIONS" or self._is_public_request(request):
            logger.debug("Auth middleware: Allowing public path or OPTIONS: %s", path)
            return await call_next(request)

        # WebSocket connections pass token as query param
        if request.scope.get("type") == "websocket":
            token = request.query_params.get("token")
            logger.debug("Auth middleware: WebSocket connection, token from query param")
        else:
            authorization = request.headers.get("Authorization", "")
            super_admin_token = request.headers.get(SUPER_ADMIN_HEADER, "")

            logger.debug(
                "Auth middleware: Authorization header present: %s, super-admin header: %s",
                bool(authorization), bool(super_admin_token),
            )

            # Extract token from Authorization header
            if authorization.startswith("Bearer "):
                token = authorization[len("Bearer "):]
            elif super_admin_token:
                token = super_admin_token
            else:
                logger.warning(
                    "Auth middleware: Missing or invalid Authorization header for %s", path
                )
                return self._unauthorized(request, "Missing or invalid Authorization header")

            logger.debug("Auth middleware: Token extracted (length: %d)", len(token) if token else 0)

        # Store the raw token string for passthrough forwarding by API endpoints
        request.state.raw_token = token or ""

        if not token:
            logger.warning("Auth middleware: No token provided for %s", path)
            return self._unauthorized(request, "No token provided")

        # ── Tier 1 + 2: Super admin, then OIDC ─────────────────────────────
        claims, is_super_admin = await validate_raw_token(token)
        if claims is not None:
            request.state.identity = claims
            request.state.is_super_admin = is_super_admin
            logger.debug(
                "Auth middleware: Token valid for %s (sub: %s, super_admin=%s)",
                path, claims.get("sub", "unknown"), is_super_admin,
            )
            if not is_super_admin:
                # ── User cache upsert + group claim mapping ────────────────
                await self._sync_user_and_groups(request, claims)
            return await call_next(request)

        # ── Tier 3: Auth failed ────────────────────────────────────────────
        logger.warning(
            "Auth middleware: All auth tiers failed for %s (token len=%d)",
            path, len(token),
        )
        return self._unauthorized(request, "Authentication failed")

    # ── User cache sync ────────────────────────────────────────────────────

    async def _sync_user_and_groups(
        self, request: Request, claims: dict[str, Any]
    ) -> None:
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
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    user_cache = UserCacheService()
                    platform_user = await user_cache.upsert_user(
                        session, sub=sub, email=email, display_name=display_name
                    )
                    request.state.platform_user_id = platform_user.id

                    identity = await user_cache.upsert_identity(
                        session,
                        sub=sub,
                        display_name=display_name,
                        email=email or None,
                    )
                    # The Identity row is the canonical human-actor record —
                    # provenance columns (agent_jobs.triggered_by_user_id,
                    # conversation_sessions.triggered_by_user_id, …) FK to it.
                    request.state.identity_id = identity.id

                    group_claims: list[str] = claims.get("groups", [])
                    logger.info(
                        "_sync_user_and_groups sub=%s user_id=%s group_claims=%s has_groups=%s",
                        sub, platform_user.id, group_claims, bool(group_claims),
                    )
                    if group_claims:
                        mapper = GroupClaimMapper()
                        new_groups = await mapper.map_claims(session, platform_user.id, group_claims)
                        if new_groups:
                            logger.info(
                                "Auto-assigned user %s to %d group(s) via IdP claims",
                                platform_user.id,
                                len(new_groups),
                            )
                        else:
                            logger.info(
                                "_sync_user_and_groups user_id=%s group_claims_present BUT no matching groups found. claims=%s",
                                platform_user.id, group_claims,
                            )
        except Exception as exc:
            logger.warning("User cache/group mapping failed for sub=%s: %s", sub, exc)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _is_public(self, path: str) -> bool:
        """Check if the path is in the public allowlist."""
        if path in PUBLIC_PATHS:
            return True
        # Exact prefix checks for Swagger assets and internal service-to-service paths
        return path.startswith(PUBLIC_PREFIXES)

    def _is_public_request(self, request: Request) -> bool:
        """Check if the request should bypass auth (combines path + method rules)."""
        path = request.url.path
        # GET /system/identity-providers and /system/super-admin/status are public
        # for provider discovery by the login page. POST/PUT/DELETE require auth.
        get_only_public = {
            "/api/v1/system/identity-providers",
            "/api/v1/system/super-admin/status",
        }
        if path in get_only_public and request.method == "GET":
            return True
        return self._is_public(path)

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
