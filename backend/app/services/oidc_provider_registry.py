"""OIDC Provider Registry — in-memory cache of OIDC provider configs.

Maintains a hot-reloadable cache of all enabled ``IdentityProviderConfig`` rows
loaded from the database, along with per-provider JWKS keys and OIDC Discovery
documents.  Acts as the single source of truth for auth middleware and token
validation consumers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_vault import get_vault
from app.core.ssl_context import get_ssl_context
from app.db.models.identity_provider_config import IdentityProviderConfig

logger = logging.getLogger(__name__)

# Default TTL for JWKS and discovery caches (seconds)
DEFAULT_JWKS_TTL = 300  # 5 minutes
DEFAULT_DISCOVERY_TTL = 3600  # 1 hour


@dataclass
class _CachedProvider:
    """Internal dataclass for a cached provider configuration."""

    config: IdentityProviderConfig
    decrypted_secret: Optional[str] = None
    jwks_keys: dict[str, Any] = field(default_factory=dict)
    jwks_expiry: float = 0.0
    discovery_doc: Optional[dict] = None
    discovery_expiry: float = 0.0


# Cache key: (tenant_id or None, provider_scope).
# Tenancy ON: the tenant's OWN (tenant, scope) slot only — there is no
# shared fallback slot (retired).  Tenancy OFF resolves the ROOT
# tenant's (root_id, scope) slot instead (root only); the tenant-less
# (None, scope) key is used only for the empty-DB pre-seed (no root
# tenant yet).
_CacheKey = tuple


class OIDCProviderRegistry:
    """In-memory registry of active OIDC provider configurations.

    Providers are cached by ``(tenant_id, scope)`` when multi-tenancy is
    on — each tenant resolves ONLY its own slot — and by the ROOT
    tenant's ``(root_id, scope)`` slot when it is off (tenancy off =
    root only).

    Every tenant uses ONLY its own identity provider.  There is NO
    shared provider and NO candidate chain: a tenant without its own
    enabled provider for a scope simply has no OIDC login for that
    scope.  NULL-tenant (shared) rows are ignored on load — they are
    inert legacy data.

    Full resolution (multi-tenancy ON): the single own
    ``(tenant, scope)`` slot, or nothing (fail-closed).

    Usage::

        registry = OIDCProviderRegistry()
        await registry.initialize(db_session)   # on startup
        provider = registry.get_user_provider()  # fast in-memory lookup
    """

    def __init__(self) -> None:
        self._providers: dict[_CacheKey, _CachedProvider] = {}
        self._initialized: bool = False
        # Mirrors the platform tenancy switch; refreshed on
        # initialize/reload (the settings toggle triggers a reload).
        self._multi_tenancy_enabled: bool = False
        # The ROOT tenant's id (the implicit tenant that adopts
        # pre-existing data — ``Tenant.is_system_tenant``), cached with
        # the same invalidation hooks as the provider map
        # (FIX-20260930-075014).
        self._root_tenant_id: Optional[str] = None

    # ── Tenancy mode ──────────────────────────────────────────────────────

    @property
    def multi_tenancy_enabled(self) -> bool:
        """Whether the registry caches providers per tenant."""
        return self._multi_tenancy_enabled

    def set_tenancy_enabled(self, enabled: bool) -> None:
        """Update the tenancy mode (call from the settings toggle path)."""
        self._multi_tenancy_enabled = bool(enabled)

    def _default_key(self, scope: str) -> tuple:
        """Cache key of the DEFAULT (root) provider slot for *scope*.

        Tenancy OFF: the ROOT tenant's ``(root_id, scope)`` slot — the
        root tenant IS the default tenant.  When the root tenant is
        absent (empty DB pre-seed), the tenant-less ``(None, scope)``
        slot is the only one that can exist.
        """
        if self._root_tenant_id is not None:
            return (self._root_tenant_id, scope)
        return (None, scope)

    def _key(self, scope: str, tenant_id: Any = None) -> tuple:
        """Cache key for a lookup: per-tenant only when tenancy is on.

        Tenancy OFF the caller must use :meth:`get_default_provider` —
        ``_resolve_cached`` rejects tenant-addressed tenancy-off lookups
        before this method is reached, so ``tenant_id`` is irrelevant
        here when the switch is off (the default key is returned).
        """
        if not self._multi_tenancy_enabled:
            return self._default_key(scope)
        if tenant_id is None:
            # No tenant resolved → no slot addressed; use a key that can
            # never be present (distinct per call) so the lookup is a
            # guaranteed miss.
            return (object(), scope)
        return (str(tenant_id), scope)

    def _resolve_cached(
        self,
        scope: str,
        tenant_id: Any = None,
        is_system_tenant: bool = False,
    ) -> Optional[_CachedProvider]:
        """Resolve the cached provider for (scope, tenant) — OWN slot only.

        Multi-tenancy ON: the tenant's OWN ``(tenant, scope)`` slot ONLY.
        There is no shared or root fallback chain — a tenant without its
        own provider resolves ``None`` (fail-closed).  Tenant-less
        lookups (``tenant_id=None``) resolve nothing.
        ``is_system_tenant`` is retained for API compatibility.

        Tenancy OFF: tenant-addressed lookups are REJECTED — the ONLY
        tenancy-off lookup is :meth:`get_default_provider` (the ROOT
        slot).  NULL-tenant and other tenants' rows never resolve
        (tenancy off = root only, explicitly).
        """
        if not self._multi_tenancy_enabled and tenant_id is not None:
            raise ValueError(
                "tenancy is disabled: use get_default_provider(scope) — "
                "a tenant-addressed provider lookup is not valid when "
                "multi-tenancy is off (the root tenant is THE default "
                "tenant)"
            )
        cached = self._providers.get(self._key(scope, tenant_id))
        return cached

    async def _load_root_tenant_id(self, db: AsyncSession) -> None:
        """Cache the ROOT tenant's id (the adoption anchor tenant)."""
        from app.db.models.tenant import Tenant

        result = await db.execute(
            select(Tenant.id).where(Tenant.is_system_tenant.is_(True))
        )
        root_id = result.scalar_one_or_none()
        self._root_tenant_id = str(root_id) if root_id is not None else None

    # ── Initialization / hot-reload ───────────────────────────────────────

    @property
    def initialized(self) -> bool:
        """Whether the registry has been loaded at least once."""
        return self._initialized

    async def initialize(self, db: AsyncSession) -> None:
        """Load all tenants' enabled providers from the database."""
        from app.services.tenancy.platform_settings_service import (
            get_platform_settings_service,
        )

        self._multi_tenancy_enabled = (
            await get_platform_settings_service().is_multi_tenancy_enabled(db)
        )
        await self._load_root_tenant_id(db)
        result = await db.execute(
            select(IdentityProviderConfig).where(
                IdentityProviderConfig.is_enabled.is_(True)
            )
        )
        rows = result.scalars().all()
        self._providers.clear()
        # NULL-tenant (shared) rows are RETIRED — never loaded.  They
        # remain inert in the database (no cleanup migration applied).
        null_tenant_rows = [r for r in rows if r.tenant_id is None]
        if null_tenant_rows:
            logger.warning(
                "OIDCProviderRegistry: ignoring %d legacy NULL-tenant "
                "(shared-slot) provider row(s) — the shared slot is retired",
                len(null_tenant_rows),
            )
        # Tenancy OFF: only the ROOT tenant's rows populate the map —
        # the root tenant IS the default tenant; NULL-tenant (shared)
        # and other tenants' rows never resolve.  When no root tenant
        # exists yet (empty DB pre-seed), the tenant-less seed rows
        # populate the (None, scope) slot, which ``_key`` resolves.
        off_tenant_key: Optional[str] = self._root_tenant_id
        for row in rows:
            if row.tenant_id is None:
                if not (not self._multi_tenancy_enabled and off_tenant_key is None):
                    continue
                tenant_key: Optional[str] = None
            elif self._multi_tenancy_enabled:
                tenant_key = str(row.tenant_id)
            else:
                if str(row.tenant_id) != off_tenant_key:
                    continue
                tenant_key = off_tenant_key
            self._providers[(tenant_key, row.provider_scope)] = _CachedProvider(
                config=row,
                decrypted_secret=_decrypt_if_present(row.encrypted_client_secret),
            )
        self._initialized = True
        logger.info(
            "OIDCProviderRegistry initialized with %d provider(s) "
            "(multi_tenancy=%s): %s",
            len(self._providers),
            self._multi_tenancy_enabled,
            sorted(f"{k[0] or 'global'}::{k[1]}" for k in self._providers),
        )

    async def reload(self, db: AsyncSession) -> None:
        """Hot-reload: invalidate and reload all configs from the database."""
        logger.info("OIDCProviderRegistry: hot-reload triggered")
        self._providers.clear()
        await self.initialize(db)

    async def reload_single(self, db: AsyncSession, scope: str) -> None:
        """Reload every provider of *scope* (all tenants) from the database."""
        logger.info("OIDCProviderRegistry: hot-reload triggered for scope=%s", scope)
        for key in [k for k in self._providers if k[1] == scope]:
            del self._providers[key]
        # The root tenant id participates in resolution (FIX-20260930-
        # 075014) — refresh it with the same invalidation hooks.
        await self._load_root_tenant_id(db)
        result = await db.execute(
            select(IdentityProviderConfig).where(
                IdentityProviderConfig.provider_scope == scope,
                IdentityProviderConfig.is_enabled.is_(True),
            )
        )
        rows = result.scalars().all()
        if not rows:
            logger.info(
                "OIDCProviderRegistry: removed provider scope=%s", scope
            )
        # Tenancy OFF: only the ROOT tenant's rows (same rule as
        # ``initialize``); NULL-tenant (shared) rows are RETIRED and
        # never loaded, except the empty-DB pre-seed case (no root
        # tenant yet) where tenant-less seed rows are the only ones.
        off_tenant_key: Optional[str] = self._root_tenant_id
        for row in rows:
            if row.tenant_id is None:
                if not (not self._multi_tenancy_enabled and off_tenant_key is None):
                    continue
                tenant_key: Optional[str] = None
            elif self._multi_tenancy_enabled:
                tenant_key = str(row.tenant_id)
            else:
                if str(row.tenant_id) != off_tenant_key:
                    continue
                tenant_key = off_tenant_key
            self._providers[(tenant_key, scope)] = _CachedProvider(
                config=row,
                decrypted_secret=_decrypt_if_present(row.encrypted_client_secret),
            )
            logger.info(
                "OIDCProviderRegistry: reloaded provider scope=%s tenant=%s",
                scope,
                tenant_key or "global",
            )

    # ── Provider resolution ───────────────────────────────────────────────

    def get_default_provider(
        self, scope: str
    ) -> Optional[IdentityProviderConfig]:
        """Return the DEFAULT (root-tenant) provider config for *scope*.

        THE tenancy-off lookup: with the switch off the root workspace
        IS the default tenant, so the ROOT tenant's ``(root_id, scope)``
        slot is the only provider that exists.  When the root tenant
        does not exist yet (empty-DB pre-seed), the tenant-less
        ``(None, scope)`` seed slot resolves.  Takes no ``tenant_id`` —
        there is nothing to address when tenancy is off.
        """
        cached = self._providers.get(self._default_key(scope))
        return cached.config if cached else None

    def get_user_provider(
        self, tenant_id: Any = None, is_system_tenant: bool = False
    ) -> Optional[IdentityProviderConfig]:
        """Return the active user identity provider config, or ``None``."""
        return self.get_provider("user", tenant_id, is_system_tenant)

    def get_agent_provider(
        self, tenant_id: Any = None, is_system_tenant: bool = False
    ) -> Optional[IdentityProviderConfig]:
        """Return the active agent identity provider config, or ``None``."""
        return self.get_provider("agent", tenant_id, is_system_tenant)

    def get_provider(
        self,
        scope: str,
        tenant_id: Any = None,
        is_system_tenant: bool = False,
    ) -> Optional[IdentityProviderConfig]:
        """Return the active provider config for the given scope, or ``None``.

        With multi-tenancy on and a resolved tenant, ONLY the tenant's
        OWN provider resolves; with no tenant or no own provider, the
        result is ``None`` — fail-closed (sign-in not configured).

        With multi-tenancy OFF, ``tenant_id`` MUST be ``None``: the
        lookup resolves the DEFAULT (root) provider via
        :meth:`get_default_provider`.  Passing a ``tenant_id`` raises
        ``ValueError`` — under tenancy off there is exactly one tenant
        (root) and exactly one lookup; there is no hidden fallback.
        """
        if not self._multi_tenancy_enabled:
            if tenant_id is not None:
                raise ValueError(
                    "tenancy is disabled: use get_default_provider(scope) — "
                    "get_provider(scope, tenant_id) is not a valid "
                    "tenancy-off lookup"
                )
            return self.get_default_provider(scope)
        cached = self._resolve_cached(scope, tenant_id, is_system_tenant)
        return cached.config if cached else None

    def get_provider_candidates(
        self,
        scope: str,
        tenant_id: Any = None,
        is_system_tenant: bool = False,
    ) -> list[IdentityProviderConfig]:
        """Return the candidate providers for (scope, tenant) — a SINGLE
        candidate (the own slot), or an empty list.

        Multi-tenancy ON: the tenant's OWN ``(tenant, scope)`` slot only
        (when a tenant context is resolved).  There is no shared or root
        fallback — a tenant without its own provider has no candidates
        (fail-closed).  Tenant-less lookups: empty.

        Multi-tenancy OFF: ``tenant_id`` MUST be ``None``; the single
        DEFAULT (root-tenant) candidate is returned.  A tenant-addressed
        tenancy-off call raises ``ValueError`` — use
        :meth:`get_default_provider` instead.
        """
        candidates: list[IdentityProviderConfig] = []
        seen: set[tuple] = set()

        def _add(key: tuple) -> None:
            if key in seen:
                return
            cached = self._providers.get(key)
            if cached is not None:
                seen.add(key)
                candidates.append(cached.config)

        if not self._multi_tenancy_enabled:
            if tenant_id is not None:
                raise ValueError(
                    "tenancy is disabled: use get_default_provider(scope) — "
                    "get_provider_candidates(scope, tenant_id) is not a "
                    "valid tenancy-off lookup"
                )
            # tenancy OFF: the DEFAULT (root-tenant) slot only (tenant-less
            # seed slot when no root tenant exists yet)
            _add(self._default_key(scope))
            return candidates
        if tenant_id is not None:
            _add((str(tenant_id), scope))  # own slot only — no chain
        return candidates

    def get_bootstrap_candidates(
        self, scope: str
    ) -> list[IdentityProviderConfig]:
        """Return ALL loaded tenant providers for a scope — login-bootstrap
        candidates for requests with NO resolved tenant context yet
        (e.g. ``/auth/tenant-memberships`` before a workspace is chosen).

        Strict containment is unaffected: validating a token against all
        providers only proves WHICH tenant realm issued it (issuers are
        distinct); authorization still derives from the token subject's
        memberships, never from the provider slot.  Tenant-less legacy
        rows are never included (the shared slot is retired).
        """
        if not self._multi_tenancy_enabled:
            default = self.get_default_provider(scope)
            return [default] if default is not None else []
        candidates: list[IdentityProviderConfig] = []
        seen: set[str] = set()
        for (tenant_key, provider_scope), cached in self._providers.items():
            if provider_scope != scope or tenant_key is None:
                continue
            if tenant_key in seen:
                continue
            seen.add(tenant_key)
            candidates.append(cached.config)
        return candidates

    def get_decrypted_secret_for(
        self, config: IdentityProviderConfig
    ) -> Optional[str]:
        """Return the decrypted client secret for a SPECIFIC cached provider
        config (candidate iteration — the first-match secret resolver would
        pair a candidate with the wrong slot's credential)."""
        for cached in self._providers.values():
            if cached.config is config:
                return cached.decrypted_secret
        return None

    def get_decrypted_secret(
        self,
        scope: str,
        tenant_id: Any = None,
        is_system_tenant: bool = False,
    ) -> Optional[str]:
        """Return the decrypted client secret for a provider scope."""
        cached = self._resolve_cached(scope, tenant_id, is_system_tenant)
        return cached.decrypted_secret if cached else None

    def list_providers(self) -> list[IdentityProviderConfig]:
        """Return all active provider configs."""
        return [c.config for c in self._providers.values()]

    def has_any_provider(self) -> bool:
        """Return ``True`` if at least one provider is configured and enabled."""
        return len(self._providers) > 0

    def has_user_provider(
        self, tenant_id: Any = None, is_system_tenant: bool = False
    ) -> bool:
        """Return ``True`` if a user provider is active for the tenant."""
        return self.get_provider("user", tenant_id, is_system_tenant) is not None

    def has_agent_provider(
        self, tenant_id: Any = None, is_system_tenant: bool = False
    ) -> bool:
        """Return ``True`` if an agent provider is active for the tenant."""
        return self.get_provider("agent", tenant_id, is_system_tenant) is not None

    # ── JWKS key cache ────────────────────────────────────────────────────

    async def get_jwks(
        self, scope: str, tenant_id: Any = None, is_system_tenant: bool = False
    ) -> dict[str, Any]:
        """Return the JWKS key map for *scope*, fetching and caching if needed.

        Returns ``{kid: jwk}`` mapping.
        """
        cached = self._resolve_cached(scope, tenant_id, is_system_tenant)
        if cached is None:
            return {}

        now = time.monotonic()
        if now < cached.jwks_expiry and cached.jwks_keys:
            return cached.jwks_keys

        # Fetch fresh JWKS
        jwks_uri = await self._get_jwks_uri(scope, tenant_id, is_system_tenant)
        if not jwks_uri:
            return {}

        try:
            async with httpx.AsyncClient(
                timeout=10.0, verify=get_ssl_context()
            ) as http_client:
                resp = await http_client.get(jwks_uri)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.error(
                "OIDCProviderRegistry: failed to fetch JWKS for scope=%s tenant=%s: %s",
                scope, tenant_id, exc,
            )
            # Return expired cache if available, else empty
            return cached.jwks_keys

        keys: dict[str, Any] = {}
        for jwk in data.get("keys", []):
            kid = jwk.get("kid", "default")
            keys[kid] = jwk

        cached.jwks_keys = keys
        cached.jwks_expiry = now + DEFAULT_JWKS_TTL
        logger.debug(
            "OIDCProviderRegistry: JWKS refreshed for scope=%s tenant=%s (%d keys)",
            scope, tenant_id, len(keys),
        )
        return keys

    async def invalidate_jwks(
        self, scope: str, tenant_id: Any = None, is_system_tenant: bool = False
    ) -> None:
        """Force a JWKS re-fetch on the next call to :meth:`get_jwks`."""
        cached = self._resolve_cached(scope, tenant_id, is_system_tenant)
        if cached:
            cached.jwks_expiry = 0.0

    # ── OIDC Discovery cache ──────────────────────────────────────────────

    async def get_discovery(
        self, scope: str, tenant_id: Any = None, is_system_tenant: bool = False
    ) -> Optional[dict]:
        """Return the OIDC Discovery document for *scope*, cached."""
        cached = self._resolve_cached(scope, tenant_id, is_system_tenant)
        if cached is None:
            return None

        now = time.monotonic()
        if now < cached.discovery_expiry and cached.discovery_doc is not None:
            return cached.discovery_doc

        issuer_url = cached.config.issuer_url.rstrip("/")
        discovery_url = f"{issuer_url}/.well-known/openid-configuration"
        try:
            async with httpx.AsyncClient(
                timeout=15.0, verify=get_ssl_context()
            ) as http_client:
                resp = await http_client.get(discovery_url)
                resp.raise_for_status()
                cached.discovery_doc = resp.json()
                cached.discovery_expiry = now + DEFAULT_DISCOVERY_TTL
        except Exception as exc:
            logger.error(
                "OIDCProviderRegistry: failed to fetch discovery for scope=%s tenant=%s: %s",
                scope, tenant_id, exc,
            )
            return cached.discovery_doc  # may be None or stale

        return cached.discovery_doc

    async def invalidate_discovery(
        self, scope: str, tenant_id: Any = None, is_system_tenant: bool = False
    ) -> None:
        """Force a discovery re-fetch on the next call."""
        cached = self._resolve_cached(scope, tenant_id, is_system_tenant)
        if cached:
            cached.discovery_expiry = 0.0

    # ── JWKS URI resolution ───────────────────────────────────────────────

    async def _get_jwks_uri(
        self, scope: str, tenant_id: Any = None, is_system_tenant: bool = False
    ) -> Optional[str]:
        """Resolve the JWKS URI from discovery, or from cached config."""
        discovery = await self.get_discovery(scope, tenant_id, is_system_tenant)
        if discovery:
            return discovery.get("jwks_uri")
        return None


# ── Helpers ────────────────────────────────────────────────────────────────


def _decrypt_if_present(encrypted: Optional[str]) -> Optional[str]:
    """Decrypt a stored secret, returning ``None`` if the value is ``None``."""
    if not encrypted:
        return None
    return get_vault().decrypt(encrypted)
