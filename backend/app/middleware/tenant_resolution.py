"""Tenant Resolution Middleware — Control Center only.

Runs BEFORE ``JWTAuthMiddleware`` in ``create_app()`` (last-registered
middleware executes first in Starlette) and establishes the immutable
tenant context exactly once per request.

Behaviour:
- **Switch off (default)** — completely inert: the cached tenancy flag is
  read, nothing else happens, and the request passes through untouched
  (byte-for-byte single-tenant behaviour).
- **Switch on** — fail-closed: the tenant must resolve from the
  ``X-Tenant`` header or the Host subdomain; anything else (no address,
  unknown slug, suspended/deleted tenant) is rejected with 403 before any
  feature logic or authentication runs.  Rejections are logged and
  audited as security-relevant ``TenantAuditEvent`` records.

Public health/setup paths, internal service-to-service paths (they carry
their own signed tenant context, verified per Phase 8), and the platform
admin surface (metadata-only, base-domain hosted) are bypassed.
"""
from __future__ import annotations

import logging

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

#: Exact paths that skip tenant resolution (health/docs/setup + public auth).
BYPASS_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/ping",
        "/docs",
        "/redoc",
        "/openapi.json",
        # First-run setup endpoints (public, pre-tenancy)
        "/api/v1/setup/init",
        "/api/v1/setup/identity-status",
        "/api/v1/setup/identity",
        "/api/v1/ping",
        "/api/v1/telemetry/config",
        # Public auth endpoints: sign-in discovery/selection happens before
        # a tenant-bound session exists.
        "/api/v1/auth/tenant",  # public tenant discovery by host (Phase 5)
        "/api/v1/auth/tenant-memberships",  # the caller's own org list
        "/api/v1/auth/super-admin/login",
        "/api/v1/auth/super-admin/refresh",
        "/api/v1/auth/register",  # self-serve account-first registration (Phase 10)
        "/api/v1/auth/login-password",  # platform-password sign-in (Phase 10)
        "/api/v1/invitations/accept",  # public token-based acceptance
    }
)

#: Path prefixes that skip tenant resolution.
#: - Swagger/OpenAPI assets
#: - /api/v1/internal/* — service-to-service; carries its own signed
#:   tenant context verified by the internal endpoints (Phase 8).
#: - /api/v1/platform/* — platform admin console: metadata-only, hosted at
#:   the base domain (no tenant address by design); guarded by
#:   platform:: resource types instead.
BYPASS_PREFIXES: tuple[str, ...] = (
    "/docs/",
    "/redoc/",
    "/api/v1/internal/",
    "/api/v1/platform/",
)

#: Login-page bootstrap probes — PUBLIC pre-auth READ endpoints
#: (backend/app/api/v1/system_config.py).  The login page calls these
#: BEFORE any authentication or tenant context exists, so in multi-tenant
#: mode they must pass tenant resolution (FIX-20260929-121120 / Defect A).
#: METHOD-AWARE by design: only safe reads bypass — identity-provider
#: WRITES (POST/PUT/DELETE) on the same paths are tenant-scoped and stay
#: fail-closed.  Never widen this into a blanket path bypass.
BYPASS_GET_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/system/identity-providers",
        "/api/v1/system/super-admin/status",
    }
)

#: Methods considered safe reads for ``BYPASS_GET_PATHS`` (HEAD is a
#: harmless read-only companion of GET).
_BYPASS_GET_METHODS: frozenset[str] = frozenset({"GET", "HEAD"})

#: Paths that are static assets/docs only — never feature logic.
_DOC_PREFIXES: tuple[str, ...] = ("/docs/", "/redoc/")


def _is_bypassed(path: str, method: str | None = None) -> bool:
    """Whether ``path`` skips tenant resolution.

    ``method`` selects the method-aware GET-only bypass; when it is
    unknown (``None``) the GET-only paths are NOT bypassed — fail-closed,
    consistent with the middleware's rejection semantics.
    """
    if path in BYPASS_PATHS:
        return True
    if (
        path in BYPASS_GET_PATHS
        and method is not None
        and method in _BYPASS_GET_METHODS
    ):
        return True
    return path.startswith(BYPASS_PREFIXES)


class TenantResolutionMiddleware(BaseHTTPMiddleware):
    """Resolve and bind the request tenant once; fail-closed when on."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        if request.method == "OPTIONS":
            return await call_next(request)

        # ── Read the cached tenancy switch ────────────────────────────────
        from app.db.session import AsyncSessionLocal
        from app.services.tenancy.platform_settings_service import (
            get_platform_settings_service,
        )

        try:
            async with AsyncSessionLocal() as db:
                multi_tenancy_enabled = (
                    await get_platform_settings_service().is_multi_tenancy_enabled(db)
                )
        except Exception:
            # Cannot even read the switch — fail safe to OFF: single-tenant
            # behaviour is the safe default (inert, nothing enabled).
            logger.exception(
                "Tenant resolution: failed to read tenancy switch; "
                "treating as disabled for this request"
            )
            multi_tenancy_enabled = False

        if not multi_tenancy_enabled:
            # Inert: no tenant logic executes with the switch off (no
            # tenant span attributes either).
            return await call_next(request)

        from app.core.tenant_context import (
            set_current_tenant_context,
            set_tenant_context,
            set_tenant_span_attributes,
        )

        if _is_bypassed(path, request.method):
            # FIX-20261001-010107: a bypassed public GET carrying a VALID
            # X-Tenant (workspace-scoped read of the login-probe endpoints)
            # still binds the tenant context so the response is scoped to
            # shared + own-tenant data.  An INVALID slug degrades to the
            # context-less shared-only view — a public READ is never
            # rejected for an unresolvable address (fail-safe, not
            # fail-open: less data is exposed, never more).  Writes on
            # these paths are NOT bypassed (method-aware rules above) and
            # keep the fail-closed resolution below.
            if path in BYPASS_GET_PATHS and request.headers.get("x-tenant"):
                try:
                    from app.services.tenancy.tenant_resolution_service import (
                        get_tenant_resolution_service,
                    )

                    async with AsyncSessionLocal() as db:
                        context, _source = await get_tenant_resolution_service().resolve(
                            db, request
                        )
                except Exception:
                    context = None
                if context is not None:
                    set_tenant_context(request, context)
                    set_current_tenant_context(context)
                    set_tenant_span_attributes(context, tenancy_active=True)
                    return await call_next(request)
            # Platform surface / public path — platform sentinel attribution.
            set_tenant_span_attributes(None, tenancy_active=True)
            return await call_next(request)

        # ── Fail-closed resolution ─────────────────────────────────────────
        from app.services.tenancy.tenant_resolution_service import (
            TenantResolutionError,
            get_tenant_resolution_service,
        )

        try:
            async with AsyncSessionLocal() as db:
                context, source = await get_tenant_resolution_service().resolve(
                    db, request
                )
        except TenantResolutionError as exc:
            logger.warning(
                "Tenant resolution rejected %s %s: reason=%s slug=%s",
                request.method,
                path,
                exc.reason,
                exc.slug,
            )
            set_tenant_span_attributes(None, tenancy_active=True)
            await self._audit_rejection(request, exc.reason, exc.slug)
            return JSONResponse(
                status_code=403,
                content={"detail": "Tenant could not be resolved"},
            )
        except Exception:
            logger.exception("Tenant resolution failed unexpectedly for %s", path)
            set_tenant_span_attributes(None, tenancy_active=True)
            return JSONResponse(
                status_code=403,
                content={"detail": "Tenant could not be resolved"},
            )

        # Bind the immutable context — exactly once per request.
        set_tenant_context(request, context)
        set_current_tenant_context(context)
        set_tenant_span_attributes(context, tenancy_active=True)
        logger.debug(
            "Tenant resolved (%s): slug=%s id=%s for %s %s",
            source.value,
            context.slug,
            context.tenant_id,
            request.method,
            path,
        )
        return await call_next(request)

    async def _audit_rejection(self, request: Request, reason: str, slug: str | None) -> None:
        """Record a security-relevant audit event for the rejection.

        Fire-and-forget-safe: an audit failure must never mask the 403.
        """
        try:
            from app.db.models.tenant_audit_event import (
                TenantAuditActorType,
                TenantAuditEventType,
            )
            from app.db.session import AsyncSessionLocal
            from app.services.tenancy.tenant_audit_service import TenantAuditService

            async with AsyncSessionLocal() as db:
                await TenantAuditService().record_safe(
                    db,
                    TenantAuditEventType.tenant_boundary_violation,
                    tenant_id=None,  # no tenant could be resolved
                    actor_type=TenantAuditActorType.system,
                    actor_ip=request.client.host if request.client else None,
                    target_resource=f"{request.method} {request.url.path}",
                    detail={"reason": reason, "slug": slug},
                    is_security_relevant=True,
                )
                await db.commit()
        except Exception:
            logger.exception("Failed to audit tenant resolution rejection")
