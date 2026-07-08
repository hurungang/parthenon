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


class OIDCProviderRegistry:
    """In-memory registry of active OIDC provider configurations.

    Usage::

        registry = OIDCProviderRegistry()
        await registry.initialize(db_session)   # on startup
        provider = registry.get_user_provider()  # fast in-memory lookup
    """

    def __init__(self) -> None:
        self._providers: dict[str, _CachedProvider] = {}
        self._initialized: bool = False

    # ── Initialization / hot-reload ───────────────────────────────────────

    @property
    def initialized(self) -> bool:
        """Whether the registry has been loaded at least once."""
        return self._initialized

    async def initialize(self, db: AsyncSession) -> None:
        """Load all enabled providers from the database."""
        result = await db.execute(
            select(IdentityProviderConfig).where(
                IdentityProviderConfig.is_enabled.is_(True)
            )
        )
        rows = result.scalars().all()
        self._providers.clear()
        for row in rows:
            self._providers[row.provider_scope] = _CachedProvider(
                config=row,
                decrypted_secret=_decrypt_if_present(row.encrypted_client_secret),
            )
        self._initialized = True
        logger.info(
            "OIDCProviderRegistry initialized with %d provider(s): %s",
            len(self._providers),
            list(self._providers.keys()),
        )

    async def reload(self, db: AsyncSession) -> None:
        """Hot-reload: invalidate and reload all configs from the database."""
        logger.info("OIDCProviderRegistry: hot-reload triggered")
        self._providers.clear()
        await self.initialize(db)

    async def reload_single(self, db: AsyncSession, scope: str) -> None:
        """Reload a single provider scope from the database."""
        result = await db.execute(
            select(IdentityProviderConfig).where(
                IdentityProviderConfig.provider_scope == scope,
                IdentityProviderConfig.is_enabled.is_(True),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            self._providers.pop(scope, None)
            logger.info(
                "OIDCProviderRegistry: removed provider scope=%s", scope
            )
        else:
            self._providers[scope] = _CachedProvider(
                config=row,
                decrypted_secret=_decrypt_if_present(row.encrypted_client_secret),
            )
            logger.info(
                "OIDCProviderRegistry: reloaded provider scope=%s", scope
            )

    # ── Provider resolution ───────────────────────────────────────────────

    def get_user_provider(self) -> Optional[IdentityProviderConfig]:
        """Return the active user identity provider config, or ``None``."""
        cached = self._providers.get("user")
        return cached.config if cached else None

    def get_agent_provider(self) -> Optional[IdentityProviderConfig]:
        """Return the active agent identity provider config, or ``None``."""
        cached = self._providers.get("agent")
        return cached.config if cached else None

    def get_provider(self, scope: str) -> Optional[IdentityProviderConfig]:
        """Return the active provider config for the given scope, or ``None``."""
        cached = self._providers.get(scope)
        return cached.config if cached else None

    def get_decrypted_secret(self, scope: str) -> Optional[str]:
        """Return the decrypted client secret for a provider scope."""
        cached = self._providers.get(scope)
        return cached.decrypted_secret if cached else None

    def list_providers(self) -> list[IdentityProviderConfig]:
        """Return all active provider configs."""
        return [c.config for c in self._providers.values()]

    def has_any_provider(self) -> bool:
        """Return ``True`` if at least one provider is configured and enabled."""
        return len(self._providers) > 0

    def has_user_provider(self) -> bool:
        """Return ``True`` if a user provider is active."""
        return "user" in self._providers

    def has_agent_provider(self) -> bool:
        """Return ``True`` if an agent provider is active."""
        return "agent" in self._providers

    # ── JWKS key cache ────────────────────────────────────────────────────

    async def get_jwks(self, scope: str) -> dict[str, Any]:
        """Return the JWKS key map for *scope*, fetching and caching if needed.

        Returns ``{kid: jwk}`` mapping.
        """
        cached = self._providers.get(scope)
        if cached is None:
            return {}

        now = time.monotonic()
        if now < cached.jwks_expiry and cached.jwks_keys:
            return cached.jwks_keys

        # Fetch fresh JWKS
        jwks_uri = await self._get_jwks_uri(scope)
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
                "OIDCProviderRegistry: failed to fetch JWKS for scope=%s: %s",
                scope, exc,
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
            "OIDCProviderRegistry: JWKS refreshed for scope=%s (%d keys)",
            scope, len(keys),
        )
        return keys

    async def invalidate_jwks(self, scope: str) -> None:
        """Force a JWKS re-fetch on the next call to :meth:`get_jwks`."""
        cached = self._providers.get(scope)
        if cached:
            cached.jwks_expiry = 0.0

    # ── OIDC Discovery cache ──────────────────────────────────────────────

    async def get_discovery(self, scope: str) -> Optional[dict]:
        """Return the OIDC Discovery document for *scope*, cached."""
        cached = self._providers.get(scope)
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
                "OIDCProviderRegistry: failed to fetch discovery for scope=%s: %s",
                scope, exc,
            )
            return cached.discovery_doc  # may be None or stale

        return cached.discovery_doc

    async def invalidate_discovery(self, scope: str) -> None:
        """Force a discovery re-fetch on the next call."""
        cached = self._providers.get(scope)
        if cached:
            cached.discovery_expiry = 0.0

    # ── JWKS URI resolution ───────────────────────────────────────────────

    async def _get_jwks_uri(self, scope: str) -> Optional[str]:
        """Resolve the JWKS URI from discovery, or from cached config."""
        discovery = await self.get_discovery(scope)
        if discovery:
            return discovery.get("jwks_uri")
        return None


# ── Helpers ────────────────────────────────────────────────────────────────


def _decrypt_if_present(encrypted: Optional[str]) -> Optional[str]:
    """Decrypt a stored secret, returning ``None`` if the value is ``None``."""
    if not encrypted:
        return None
    return get_vault().decrypt(encrypted)
