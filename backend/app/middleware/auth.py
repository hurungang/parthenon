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
    # Self-serve registration + platform-password sign-in (public,
    # switch-gated, throttled — Phase 10)
    "/api/v1/auth/register",
    "/api/v1/auth/login-password",
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


async def _try_platform_account_token(token: str) -> dict[str, Any] | None:
    """Tier 1b — validate the token as a platform-account JWT (or None).

    Platform-issued (self-serve, Phase 10) accounts authenticate against
    Control Center itself — outside the per-tenant OIDC registry.  Their
    tokens are HS256 platform JWTs carrying ``tenant`` (slug) so the
    tenant-claim middleware binds them exactly like OIDC tokens.
    """
    try:
        from app.services.tenancy.platform_account_auth_service import (
            validate_platform_account_token,
        )
    except ImportError:
        logger.debug("Auth: platform account auth service not available")
        return None
    try:
        claims = validate_platform_account_token(token)
        if claims is not None:
            logger.debug("Auth: platform account token valid")
        return claims
    except Exception as exc:
        logger.warning("Auth: Unexpected error validating platform account token: %s", exc)
        return None


def _inject_tenant_claim(
    claims: dict[str, Any],
    registry: Any,
    scope: str,
    tenant_id: Any,
    slug: Any,
) -> None:
    """Stamp the ``tenant`` claim on a token validated for the RESOLVED
    login context (validation-time claim injection — FIX-20260929-043443,
    shared-provider semantics FIX-20260929-221449).

    External / tenant-scoped OIDC providers (Azure EntraID, per-tenant
    Keycloak realms, …) issue tokens with standard identity claims only —
    the platform ``tenant`` claim is never embedded — so
    :meth:`JWTAuthMiddleware._check_tenant_claim` rejected EVERY request
    from an OIDC session in multi-tenant mode (401 → the frontend
    interceptor bounced the user back to /login mid-load).

    The backend therefore injects the claim post-validation instead of
    depending on provider-side claim-mapper configuration.  The injection
    happens whenever a provider is resolvable for the resolved tenant —
    the tenant's OWN registry slot, or the SHARED (tenant-less) slot
    when the tenant has no own config (FIX-20260929-221449).

    Why injecting from the RESOLVED CONTEXT is legitimate under the
    shared-provider model (FIX-20260929-221449): the shared provider no
    longer PROVES tenancy — the claim source is the resolved LOGIN
    CONTEXT (the tenant whose registry slot validated the token; a
    foreign token cannot validate against another tenant's own slot, and
    the shared slot is shared by design).  Cross-tenant safety is
    enforced where it belongs: membership gates (``authorize_identity``
    denies ``no_access_to_workspace`` without an ACTIVE membership) plus
    the row-level scoped data plane — a user without membership gets
    403s, never data.

    Security semantics (preserved):

    - The claim source is the **provider registry slot that validated the
      token** — never the request's ``X-Tenant`` header (the header only
      selects WHICH login context resolves; without a resolvable provider
      no claims and no injection are produced).
    - The existing ``_check_tenant_claim`` still runs afterwards and
      compares the (injected or native) claim against the
      request-resolved tenant — mismatch rejection is untouched.
    - Single-tenant mode (no tenant context) and platform-password /
      super-admin tokens are untouched.
    """
    if tenant_id is None or slug is None or not str(slug).strip():
        return  # single-tenant mode / platform surface — unchanged
    # Inject ONLY when a provider is resolvable for the resolved tenant
    # (own slot first, SHARED slot as fallback).  No resolvable provider
    # → no validation happened for this context → no injection.
    if registry.get_provider(scope, tenant_id, False) is None:
        return
    claims["tenant"] = str(slug)


async def _try_oidc_token(
    token: str,
    tenant_context: Any = None,
) -> dict[str, Any] | None:
    """Tier 2 — validate the token against the OIDC registry / legacy client.

    When a resolved *tenant_context* is provided (multi-tenancy on), the
    token is validated against the provider resolvable for THAT login
    context: the tenant's OWN provider config when configured, ELSE the
    SHARED (tenant-less) provider (FIX-20260929-221449) — a credential
    that validates against no provider resolvable for the context fails.
    A token validated against any provider resolvable for the resolved
    tenant has the ``tenant`` claim (slug) injected from the RESOLVED
    LOGIN CONTEXT (:func:`_inject_tenant_claim`), which
    ``JWTAuthMiddleware._check_tenant_claim`` then enforces against the
    resolved tenant (tokens carrying a native claim are overridden — the
    authoritative binding is the login context that validated the token).
    Cross-tenant safety under the shared-provider model comes from
    membership gates + the scoped data plane, not from provider binding.
    """
    try:
        from app.main import _get_registry
    except ImportError:
        logger.debug("Auth: OIDCProviderRegistry not available")
        return None

    registry = _get_registry()
    if not registry.initialized:
        logger.debug("Auth: Provider registry not yet initialized")
        return None

    tenant_id = getattr(tenant_context, "tenant_id", None)
    is_system_tenant = bool(getattr(tenant_context, "is_system_tenant", False))

    # Try user provider first, then agent provider.  Within a scope,
    # iterate ALL candidate providers (own → shared → root slot —
    # FIX-20261002-110000): the first provider whose JWKS validates the
    # token wins; a root-slot (adopted platform realm) token must not be
    # shadowed by a different provider in the shared slot.
    for scope in ("user", "agent"):
        for provider in registry.get_provider_candidates(scope, tenant_id, is_system_tenant):
            try:
                client = OIDCClient(
                    issuer_url=provider.issuer_url,
                    client_id=provider.client_id,
                    claim_mappings=provider.claim_mappings or {},
                    decrypted_client_secret=registry.get_decrypted_secret_for(provider),
                )
                claims = await client.validate_token(token)
                claims["_provider_scope"] = scope
                # FIX-20260929-043443: provision the tenant claim the claim
                # check requires (see _inject_tenant_claim for the security
                # semantics — binding derives from the provider slot, never
                # from the request's X-Tenant header).
                _inject_tenant_claim(claims, registry, scope, tenant_id, getattr(tenant_context, "slug", None))
                logger.debug(
                    "Auth: OIDC token valid for scope=%s tenant=%s issuer=%s",
                    scope, tenant_id, provider.issuer_url,
                )
                return claims
            except OIDCError as exc:
                logger.debug(
                    "Auth: OIDC validation failed for scope=%s issuer=%s: %s",
                    scope, provider.issuer_url, exc,
                )
            except Exception as exc:
                logger.warning(
                    "Auth: Unexpected OIDC error for scope=%s issuer=%s: %s",
                    scope, provider.issuer_url, exc,
                )

    # Fallback: try legacy singleton if no providers in registry — only
    # when no tenant context is active (single-tenant mode unchanged).
    if tenant_context is not None:
        return None
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


async def validate_raw_token(
    token: str,
    tenant_context: Any = None,
) -> tuple[dict[str, Any] | None, bool]:
    """Validate a raw JWT through the full auth-tier pipeline.

    Tier order matches the middleware pipeline: super-admin token first,
    then OIDC (provider registry with legacy-singleton fallback).  With
    multi-tenancy on, *tenant_context* (the resolved TenantContext)
    restricts token validation to the resolved tenant's provider.

    Returns:
        ``(claims, is_super_admin)`` — ``(None, False)`` when every tier fails.
    """
    super_admin_claims = await _try_super_admin_token(token)
    if super_admin_claims is not None:
        return super_admin_claims, True

    platform_account_claims = await _try_platform_account_token(token)
    if platform_account_claims is not None:
        return platform_account_claims, False

    oidc_claims = await _try_oidc_token(token, tenant_context)
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
        from app.core.tenant_context import get_tenant_context, is_tenancy_enabled

        # Phase 11: when the tenancy switch is OFF the bound context is
        # the ROOT default — validation must behave exactly as the legacy
        # context-less path (no per-tenant provider selection, no claim
        # injection), so the context is discarded for this request.
        token_tenant_context = (
            get_tenant_context(request)
            if is_tenancy_enabled(request)
            else None
        )
        claims, is_super_admin = await validate_raw_token(
            token, token_tenant_context
        )
        if claims is not None:
            # ── Tenant claim binding (multi-tenant mode only) ─────────────
            # A validated token whose tenant claim differs from the
            # resolved tenant (or that lacks the claim in multi-tenant
            # mode) is rejected BEFORE any user sync occurs.
            claim_error = await self._check_tenant_claim(request, claims, is_super_admin)
            if claim_error is not None:
                return self._unauthorized(request, claim_error)

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

    # ── Tenant claim binding ───────────────────────────────────────────────

    async def _check_tenant_claim(
        self, request: Request, claims: dict[str, Any], is_super_admin: bool
    ) -> str | None:
        """Validate the token's tenant claim against the resolved tenant.

        Returns an error detail string when the request must be rejected
        with 401, or None when it may proceed.

        Behaviour:
        - No resolved tenant context (switch off or bypassed path): the
          check is inert — single-tenant behaviour is unchanged.
        - Super admin tokens are platform-scoped (``tenant_access:
          platform_only``): valid across tenants for platform
          administration surfaces (tenant metadata only), so a request
          resolved INTO a tenant workspace is rejected — the super admin
          never operates on tenant business data.
        - Otherwise the token MUST carry a ``tenant`` claim (slug, or the
          tenant UUID) that equals the resolved tenant; anything else is a
          security-relevant cross-tenant rejection.
        """
        from app.core.tenant_context import get_tenant_context, is_tenancy_enabled

        context = get_tenant_context(request)
        if not context.is_set:
            return None  # no resolved context — inert
        if not is_tenancy_enabled(request):
            return None  # tenancy OFF: root-default context, no claim checks
        if is_super_admin:
            # Platform-only principal: no tenant workspace access.
            logger.warning(
                "Auth middleware: super admin rejected for tenant-scoped "
                "request %s (resolved=%s) — platform administration only",
                request.url.path,
                context.slug,
            )
            await self._audit_claim_mismatch(
                request,
                context.slug,
                reason="super_admin_platform_only",
                token_tenant=None,
            )
            return "Super admin cannot access tenant workspaces"

        token_tenant = claims.get("tenant")
        if token_tenant is None or str(token_tenant).strip() == "":
            logger.warning(
                "Auth middleware: token lacks tenant claim in multi-tenant "
                "mode for %s (resolved=%s)",
                request.url.path,
                context.slug,
            )
            await self._audit_claim_mismatch(
                request, context.slug, reason="missing_claim", token_tenant=None
            )
            return "Token is not valid for this tenant"

        normalized = str(token_tenant).strip()
        if normalized != context.slug and normalized != str(context.tenant_id):
            logger.warning(
                "Auth middleware: tenant claim mismatch for %s "
                "(token=%s resolved=%s)",
                request.url.path,
                normalized,
                context.slug,
            )
            await self._audit_claim_mismatch(
                request, context.slug, reason="mismatch", token_tenant=normalized
            )
            return "Token is not valid for this tenant"

        return None

    async def _audit_claim_mismatch(
        self,
        request: Request,
        resolved_slug: str,
        *,
        reason: str,
        token_tenant: str | None,
    ) -> None:
        """Record a security-relevant audit event for the rejection.

        Fire-and-forget-safe: audit failures never mask the 401.
        """
        try:
            from sqlalchemy import select

            from app.db.models.tenant import Tenant
            from app.db.models.tenant_audit_event import (
                TenantAuditActorType,
                TenantAuditEventType,
            )
            from app.db.session import AsyncSessionLocal
            from app.services.tenancy.tenant_audit_service import TenantAuditService

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Tenant.id).where(Tenant.slug == resolved_slug)
                )
                tenant_id = result.scalar_one_or_none()
                await TenantAuditService().record_safe(
                    db,
                    TenantAuditEventType.cross_tenant_access_denied,
                    tenant_id=tenant_id,
                    actor_type=TenantAuditActorType.system,
                    actor_ip=request.client.host if request.client else None,
                    target_resource=f"{request.method} {request.url.path}",
                    detail={
                        "reason": reason,
                        "resolved_tenant": resolved_slug,
                        "token_tenant": token_tenant,
                    },
                    is_security_relevant=True,
                )
                await db.commit()
        except Exception:
            logger.exception("Failed to audit tenant claim mismatch")

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

                    # JIT default tenant role (FIX-20260930-075014):
                    # first OIDC sign-in to a resolved tenant via a
                    # provider whose default_tenant_role is set admits
                    # the user (membership + preset role grant).
                    await self._maybe_jit_default_role(
                        session, platform_user, claims, request
                    )
        except Exception as exc:
            logger.warning("User cache/group mapping failed for sub=%s: %s", sub, exc)

    # ── JIT default tenant role (FIX-20260930-075014) ─────────────────────

    async def _maybe_jit_default_role(
        self,
        session: Any,
        platform_user: Any,
        claims: dict[str, Any],
        request: Request,
    ) -> None:
        """Admit a first-time OIDC sign-in with the provider's default role.

        Gated on ALL of:

        - the token is an OIDC token validated through the registry
          (``_provider_scope`` claim present) — platform-password and
          super-admin tokens NEVER JIT;
        - multi-tenancy is ON and a tenant context is RESOLVED for the
          request (single-tenant mode unchanged);
        - the provider that validated the token — the slot resolvable for
          the resolved tenant (own → shared → system-slot fallback) — has
          ``default_tenant_role`` configured;
        - the user holds NO active membership in the tenant (idempotent:
          an existing membership means nothing happens).

        Unset default → no JIT → the request later hits the existing
        ``no_access_to_workspace`` 403 in ``authorize_identity``
        (unchanged).  Errors are logged, never fatal (fire-and-log, like
        the rest of the sync).
        """
        try:
            from app.core.tenant_context import (
                get_tenant_context,
                is_tenancy_enabled,
            )
            from app.db.models.tenant_audit_event import (
                TenantAuditActorType,
                TenantAuditEventType,
            )
            from app.services.tenancy.default_tenant_roles import (
                jit_membership_with_default_role,
            )
            from app.services.tenancy.tenant_audit_service import TenantAuditService

            scope = claims.get("_provider_scope")
            if scope not in ("user", "agent"):
                return  # platform-password / legacy tokens — NO JIT

            context = get_tenant_context(request)
            if (
                not context.is_set
                or getattr(context, "tenant_id", None) is None
                or not is_tenancy_enabled(request)
            ):
                return  # gated: multi-tenancy ON + resolved tenant context

            from app.main import _get_registry

            registry = _get_registry()
            provider = registry.get_provider(
                scope, context.tenant_id, context.is_system_tenant
            )
            role_key = getattr(provider, "default_tenant_role", None)
            if provider is None or role_key is None:
                return  # no configured default → no JIT (403 path unchanged)

            created = await jit_membership_with_default_role(
                session,
                tenant_id=context.tenant_id,
                user_id=platform_user.id,
                role_key=role_key,
            )
            if created:
                await TenantAuditService().record_safe(
                    session,
                    TenantAuditEventType.self_serve_registration,
                    tenant_id=context.tenant_id,
                    actor_type=TenantAuditActorType.system,
                    target_resource=f"platform_user:{platform_user.id}",
                    detail={
                        "reason": "jit_default_role_assigned",
                        "role_key": str(role_key),
                        "provider_scope": scope,
                        "tenant_slug": context.slug,
                    },
                    is_security_relevant=False,
                )
        except Exception as exc:
            logger.warning(
                "JIT default-role assignment failed for sub=%s: %s",
                claims.get("sub", ""), exc,
            )

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
        # GET /auth/tenant is the public multi-tenant discovery endpoint.
        get_only_public = {
            "/api/v1/system/identity-providers",
            "/api/v1/system/super-admin/status",
            "/api/v1/auth/tenant",
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
