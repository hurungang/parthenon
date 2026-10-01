"""Tenant Resolution Service — slug/header to active tenant, fail-closed.

Single resolution point per request: Control Center's
``TenantResolutionMiddleware`` asks this service to resolve a tenant from
the ``X-Tenant`` header (API/MCP clients) or the subdomain of the Host
header (browser tenants).  Only tenant metadata (id, slug, name, status,
system flag) is ever read — never business data.

Fail-closed semantics (only enforced when the tenancy switch is on — the
middleware never calls this service when it is off): unknown slugs,
suspended tenants, deleted tenants, and unresolvable requests all raise
:class:`TenantResolutionError`.

Resolved active tenants are cached with a short TTL to keep the hot path
off the database; *rejections are never cached* so suspend/delete take
effect immediately.
"""
from __future__ import annotations

import enum
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Final

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.tenant_context import TenantContext
from app.db.models.tenant import Tenant, TenantStatus

logger = logging.getLogger(__name__)

#: Explicit tenant header for API/MCP clients — carries the tenant slug.
#: Resolution precedence: this header first, then the Host subdomain.
TENANT_HEADER: Final[str] = "X-Tenant"

#: Reserved subdomains that can never be tenant slugs.
_RESERVED_SLUGS: Final[frozenset[str]] = frozenset(
    {"www", "api", "app", "admin", "platform", "static", "cdn", "mail"}
)


class TenantResolutionError(Exception):
    """Raised when a request's tenant cannot be resolved (fail-closed)."""

    def __init__(self, reason: str, slug: str | None = None) -> None:
        self.reason = reason
        self.slug = slug
        super().__init__(reason)


class ResolutionSource(str, enum.Enum):
    """Where the candidate slug came from (for logs/audit attribution)."""

    header = "header"
    host = "host"
    none = "none"


@dataclass(frozen=True, slots=True)
class SlugCandidate:
    """Candidate tenant slug extracted from a request."""

    slug: str
    source: ResolutionSource


def _get_header(request: Request, name: str) -> str:
    """Case-insensitive header read.

    Starlette's ``Headers`` is already case-insensitive; the explicit
    fallback keeps the helper testable with plain dicts.
    """
    try:
        value = request.headers[name]
        if value:
            return value
    except KeyError:
        pass
    lowered = name.lower()
    for key, value in request.headers.items():
        if key.lower() == lowered:
            return value
    return ""


def extract_slug_candidate(request: Request) -> SlugCandidate | None:
    """Extract the candidate tenant slug from a request (no DB access).

    Precedence: explicit ``X-Tenant`` header, then the Host-header label
    immediately left of ``TENANT_ADDRESS_BASE_DOMAIN`` (when configured).
    Returns None when neither source yields a plausible slug.
    """
    header_value = _get_header(request, TENANT_HEADER).strip().lower()
    if header_value:
        return SlugCandidate(slug=header_value, source=ResolutionSource.header)

    host = _get_header(request, "host").split(":", 1)[0].strip().lower()
    base_domain = (get_settings().tenant_address_base_domain or "").strip().lower()
    if not host or not base_domain:
        return None
    if host == base_domain or not host.endswith("." + base_domain):
        return None
    label = host[: -(len(base_domain) + 1)]
    # Only the leftmost label is a tenant address (acme.base.com); deeper
    # names (a.b.base.com) are not tenant slugs.
    if "." in label:
        return None
    return SlugCandidate(slug=label, source=ResolutionSource.host)


class TenantResolutionService:
    """Resolves a request's candidate slug to an active tenant context."""

    def __init__(self, cache_ttl_seconds: float | None = None) -> None:
        self._ttl = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else get_settings().tenant_resolution_cache_ttl_seconds
        )
        # slug -> (TenantContext, cached_at_monotonic) — successes only.
        self._cache: dict[str, tuple[TenantContext, float]] = {}

    # ── resolution ───────────────────────────────────────────────────────────

    async def resolve(
        self, db: AsyncSession, request: Request
    ) -> tuple[TenantContext, ResolutionSource]:
        """Resolve the request's tenant context; raise when unresolvable.

        Fail-closed by contract: the middleware only calls this when the
        tenancy switch is on, and any failure here rejects the request.
        """
        candidate = extract_slug_candidate(request)
        if candidate is None:
            raise TenantResolutionError("unresolvable")

        if candidate.slug in _RESERVED_SLUGS:
            raise TenantResolutionError("unknown", candidate.slug)

        context = await self.resolve_slug(db, candidate.slug)
        return context, candidate.source

    async def resolve_slug(self, db: AsyncSession, slug: str) -> TenantContext:
        """Resolve a slug to an active tenant; raises on any failure.

        Unknown, suspended and deleted tenants are all treated as
        unresolvable — rejections are never cached.
        """
        normalized = slug.strip().lower()
        cached = self._cache.get(normalized)
        if cached is not None and time.monotonic() - cached[1] < self._ttl:
            return cached[0]

        result = await db.execute(
            select(
                Tenant.id,
                Tenant.slug,
                Tenant.name,
                Tenant.status,
                Tenant.is_system_tenant,
            ).where(Tenant.slug == normalized)
        )
        row = result.first()
        if row is None:
            raise TenantResolutionError("unknown", normalized)
        tenant_id, tenant_slug, tenant_name, status, is_system_tenant = row
        if status == TenantStatus.suspended:
            raise TenantResolutionError("suspended", normalized)
        if status == TenantStatus.deleted:
            raise TenantResolutionError("deleted", normalized)
        if status != TenantStatus.active:
            raise TenantResolutionError("unknown", normalized)

        context = TenantContext(
            tenant_id=uuid.UUID(str(tenant_id)),
            slug=tenant_slug,
            name=tenant_name,
            is_system_tenant=bool(is_system_tenant),
        )
        self._cache[normalized] = (context, time.monotonic())
        return context

    async def invalidate(self, slug: str | None = None) -> None:
        """Drop one slug (or the whole resolution cache).

        Called by the tenant lifecycle service after suspend/resume/delete
        so lifecycle changes take effect immediately.
        """
        if slug is None:
            self._cache.clear()
        else:
            self._cache.pop(slug.strip().lower(), None)


_service: TenantResolutionService | None = None


def get_tenant_resolution_service() -> TenantResolutionService:
    """Return the module-level TenantResolutionService singleton.

    Shared process-wide so the lifecycle cache invalidations apply to
    every request handler in this worker.
    """
    global _service
    if _service is None:
        _service = TenantResolutionService()
    return _service
