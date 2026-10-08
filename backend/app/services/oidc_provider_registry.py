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
# None tenant_id = the SHARED provider — the fallback slot for any
# tenant without its own config (FIX-20260929-221449).  Tenancy OFF
# resolves the ROOT tenant's (root_id, scope) slot instead (root only).
_CacheKey = tuple


class OIDCProviderRegistry:
    """In-memory registry of active OIDC provider configurations.

    Providers are cached by ``(tenant_id, scope)`` when multi-tenancy is
    on — per-tenant credentials take precedence inside their tenant —
    and by the ROOT tenant's ``(root_id, scope)`` slot when it is off
    (tenancy off = root only).

    SHARED providers (FIX-20260929-221449): a tenant-less (NULL
    ``tenant_id``) config is the SHARED provider — usable by the platform
    AND by any tenant whose login context resolves to it.  ROOT-slot
    fallback (FIX-20260930-075014): when neither the own nor the shared
    slot holds a config, the ROOT tenant's (``root_id``, scope) slot —
    the ADOPTED PLATFORM provider — resolves, for BOTH tenant-scoped and
    tenant-less lookups ("one provider serves the platform and all
    tenants").  The root tenant id is resolved with the same helper the
    adoption flow uses (``Tenant.is_system_tenant``) and cached with the
    same invalidation hooks as the provider map (initialize/reload).

    Full resolution order (multi-tenancy ON):

        own (tenant, scope) → shared (None, scope) → system (root_id, scope)

    A tenant with none of the three resolves ``None`` — fail-closed
    (sign-in not configured).

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

    def _key(self, scope: str, tenant_id: Any = None) -> tuple:
        """Cache key for a lookup: per-tenant only when tenancy is on.

        Tenancy OFF: the ROOT tenant's ``(root_id, scope)`` slot — the
        root tenant IS the default tenant.  When the root tenant is
        absent (empty DB pre-seed), the tenant-less ``(None, scope)``
        slot is the only one that can exist.
        """
        if not self._multi_tenancy_enabled:
            if self._root_tenant_id is not None:
                return (self._root_tenant_id, scope)
            return (None, scope)
        if tenant_id is None:
            return (None, scope)
        return (str(tenant_id), scope)

    def _resolve_cached(
        self,
        scope: str,
        tenant_id: Any = None,
        is_system_tenant: bool = False,
    ) -> Optional[_CachedProvider]:
        """Resolve the cached provider for (scope, tenant) — shared- and
        root-slot aware.

        Resolution order (multi-tenancy ON; FIX-20260930-075014):

        1. the tenant's OWN ``(tenant, scope)`` slot (per-tenant
           precedence — a tenant's own config always wins);
        2. the SHARED tenant-less ``(None, scope)`` slot;
        3. the ROOT tenant's ``(root_id, scope)`` slot — the adopted
           platform provider serving the platform and every tenant
           without own/shared config.

        Tenant-less lookups (``tenant_id=None`` — platform surfaces,
        ``/auth/tenant-memberships``) resolve shared → system.
        ``is_system_tenant`` is retained for API compatibility — the
        fallback no longer depends on it.

        Tenancy OFF: the ROOT tenant's ``(root_id, scope)`` slot only
        (``_key`` resolves there) — NULL-tenant and other tenants'
        rows never resolve (tenancy off = root only).
        """
        cached = self._providers.get(self._key(scope, tenant_id))
        if cached is not None:
            return cached
        if not self._multi_tenancy_enabled:
            return None  # tenancy OFF: ROOT-tenant slot only
        tenant_key = str(tenant_id) if tenant_id is not None else None
        if tenant_key is not None:
            # 2. shared slot
            cached = self._providers.get((None, scope))
            if cached is not None:
                return cached
        # 3. root-tenant slot (own slot already tried when tenant IS
        # the root tenant — skip the redundant lookup then)
        if (
            self._root_tenant_id
            and self._root_tenant_id != tenant_key
        ):
            cached = self._providers.get((self._root_tenant_id, scope))
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
        # Tenancy OFF: only the ROOT tenant's rows populate the map —
        # the root tenant IS the default tenant; NULL-tenant (shared)
        # and other tenants' rows never resolve.  When no root tenant
        # exists yet (empty DB pre-seed), the tenant-less seed rows
        # populate the (None, scope) slot, which ``_key`` resolves.
        off_tenant_key: Optional[str] = self._root_tenant_id
        for row in rows:
            if self._multi_tenancy_enabled:
                tenant_key: Optional[str] = (
                    str(row.tenant_id) if row.tenant_id is not None else None
                )
            else:
                row_key = str(row.tenant_id) if row.tenant_id is not None else None
                if row_key != off_tenant_key:
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
        # ``initialize``); tenant-less seed rows only when no root
        # tenant exists yet.
        off_tenant_key: Optional[str] = self._root_tenant_id
        for row in rows:
            if self._multi_tenancy_enabled:
                tenant_key: Optional[str] = (
                    str(row.tenant_id) if row.tenant_id is not None else None
                )
            else:
                row_key = str(row.tenant_id) if row.tenant_id is not None else None
                if row_key != off_tenant_key:
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

        With multi-tenancy on and a resolved tenant, the tenant's OWN
        provider wins and the SHARED (tenant-less) provider is the
        fallback; with neither, the result is ``None`` — fail-closed
        (sign-in not configured).
        """
        cached = self._resolve_cached(scope, tenant_id, is_system_tenant)
        return cached.config if cached else None

    def get_provider_candidates(
        self,
        scope: str,
        tenant_id: Any = None,
        is_system_tenant: bool = False,
    ) -> list[IdentityProviderConfig]:
        """Return the ordered, deduped candidate providers for (scope,
        tenant) — the full resolution chain, not just the first match
        (FIX-20261002-110000).

        Multi-tenancy ON — own (tenant, scope) slot (when a tenant
        context is resolved) → shared (None, scope) slot → root
        tenant's (root_id, scope) slot.  Tenant-less lookups: shared →
        root.  Multi-tenancy OFF: the single tenant-less (legacy
        global) slot only.  Missing slots are excluded; the chain may
        be empty (fail-closed).

        Token validation (``auth._try_oidc_token``) iterates these
        candidates and accepts the first that validates — a root-slot
        (adopted platform realm) token must validate on tenant-less
        paths even when the shared slot holds a DIFFERENT provider
        whose JWKS shadowed the root slot under first-match resolution.
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
            # tenancy OFF: ROOT-tenant slot only (tenant-less fallback
            # when no root tenant exists yet)
            _add(self._key(scope, tenant_id))
            return candidates
        if tenant_id is not None:
            _add((str(tenant_id), scope))  # 1. own slot
        _add((None, scope))  # 2. shared slot (tenant-less: first candidate)
        if self._root_tenant_id:  # 3. root-tenant slot
            _add((str(self._root_tenant_id), scope))
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
