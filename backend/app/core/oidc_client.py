"""OIDC client — multi-provider JWT validation with per-provider caching.

Each :class:`OIDCClient` instance is tied to a single OIDC provider (identified
by scope like ``user`` or ``agent``).  It fetches JWKS, validates JWT tokens,
and applies provider-specific claims mapping.  A backward-compatible singleton
is available for callers that haven't been migrated to multi-provider mode yet.

The module-level :func:`get_oidc_client` function returns the legacy singleton.
New code should use the :class:`OIDCProviderRegistry` to obtain configured
:class:`OIDCClient` instances.
"""

import logging
import time
from typing import Any, Optional

import httpx
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.ssl_context import get_ssl_context

logger = logging.getLogger(__name__)


class OIDCError(Exception):
    """Raised when OIDC validation fails."""


class OIDCClient:
    """Validates JWT tokens for a single OIDC provider.

    Each instance caches its own JWKS keys and discovery information.
    """

    def __init__(
        self,
        issuer_url: str,
        client_id: str = "",
        algorithm: str = "RS256",
        audience: Optional[str] = None,
        claim_mappings: Optional[dict] = None,
        decrypted_client_secret: Optional[str] = None,
    ) -> None:
        self._issuer_url = issuer_url.rstrip("/")
        self._client_id = client_id
        self._algorithm = algorithm
        self._audience = audience or client_id
        self._claim_mappings = claim_mappings or {}
        self._client_secret = decrypted_client_secret

        # Per-instance JWKS cache
        self._jwks_keys: dict[str, Any] = {}
        self._jwks_expiry: float = 0.0
        self._jwks_uri: Optional[str] = None
        self._discovery_cached: Optional[dict] = None
        self._discovery_expiry: float = 0.0

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def issuer_url(self) -> str:
        return self._issuer_url

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def algorithm(self) -> str:
        return self._algorithm

    # ── Discovery ─────────────────────────────────────────────────────────

    async def _get_jwks_uri(self) -> str:
        """Fetch JWKS URI from OIDC discovery endpoint."""
        now = time.monotonic()
        if self._jwks_uri and now < self._discovery_expiry:
            return self._jwks_uri

        discovery = await self._fetch_discovery()
        jwks_uri = discovery.get("jwks_uri", "")
        if not jwks_uri:
            raise OIDCError(f"Discovery document for {self._issuer_url} missing jwks_uri")

        self._jwks_uri = jwks_uri
        logger.debug("OIDC: JWKS URI discovered: %s", jwks_uri)
        return jwks_uri

    async def _fetch_discovery(self) -> dict[str, Any]:
        """Fetch .well-known/openid-configuration from the issuer."""
        now = time.monotonic()
        if self._discovery_cached and now < self._discovery_expiry:
            return self._discovery_cached

        discovery_url = f"{self._issuer_url}/.well-known/openid-configuration"
        logger.debug("OIDC: Fetching discovery document from %s", discovery_url)

        async with httpx.AsyncClient(timeout=10.0, verify=get_ssl_context()) as client:
            response = await client.get(discovery_url)
            response.raise_for_status()
            self._discovery_cached = response.json()
            self._discovery_expiry = now + 3600  # 1 hour TTL

        return self._discovery_cached

    # ── JWKS ──────────────────────────────────────────────────────────────

    async def _get_jwks(self) -> dict[str, Any]:
        """Fetch JWKS from the provider, with instance-level caching."""
        now = time.monotonic()
        if now < self._jwks_expiry and self._jwks_keys:
            return self._jwks_keys

        jwks_uri = await self._get_jwks_uri()
        logger.debug("OIDC: Fetching JWKS from %s", jwks_uri)

        async with httpx.AsyncClient(timeout=10.0, verify=get_ssl_context()) as client:
            response = await client.get(jwks_uri)
            response.raise_for_status()
            data: dict[str, Any] = response.json()

        # Build kid -> key mapping
        keys: dict[str, Any] = {}
        for jwk in data.get("keys", []):
            kid = jwk.get("kid", "default")
            keys[kid] = jwk

        self._jwks_keys = keys
        self._jwks_expiry = now + 300  # 5 minutes
        logger.debug("OIDC: JWKS refreshed from %s (%d keys)", jwks_uri, len(keys))
        return keys

    # ── Token validation ──────────────────────────────────────────────────

    async def validate_token(self, token: str) -> dict[str, Any]:
        """Validate a JWT token and return the decoded claims.

        Raises OIDCError if validation fails.
        """
        logger.debug("OIDC: Starting token validation (token length: %d)", len(token))
        try:
            # Decode header without verification to get kid
            header = jwt.get_unverified_header(token)
            logger.debug(
                "OIDC: JWT header decoded, kid=%s, alg=%s",
                header.get("kid"), header.get("alg"),
            )
        except JWTError as exc:
            logger.error("OIDC: Invalid JWT header: %s", exc)
            raise OIDCError(f"Invalid JWT header: {exc}") from exc

        kid = header.get("kid", "default")
        logger.debug("OIDC: Looking for key with kid=%s", kid)
        try:
            jwks = await self._get_jwks()
            logger.debug("OIDC: JWKS fetched, available kids: %s", list(jwks.keys()))
        except Exception as exc:
            logger.error("OIDC: Failed to fetch JWKS: %s", exc, exc_info=True)
            raise OIDCError(f"Failed to fetch JWKS: {exc}") from exc

        if kid not in jwks:
            logger.warning("OIDC: Key id %s not found in cache, refreshing JWKS", kid)
            # Try refreshing the cache once
            self._jwks_expiry = 0.0
            try:
                jwks = await self._get_jwks()
                logger.debug("OIDC: JWKS refreshed, available kids: %s", list(jwks.keys()))
            except Exception as exc:
                logger.error("OIDC: Failed to refresh JWKS: %s", exc, exc_info=True)
                raise OIDCError(f"Failed to refresh JWKS: {exc}") from exc

        if kid not in jwks:
            logger.error(
                "OIDC: Unknown key id: %s (available: %s)", kid, list(jwks.keys())
            )
            raise OIDCError(f"Unknown key id: {kid}")

        jwk = jwks[kid]
        logger.debug(
            "OIDC: Decoding token with kid=%s, algorithm=%s, audience=%s",
            kid, self._algorithm, self._audience,
        )
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                jwk,
                algorithms=[self._algorithm],
                audience=self._audience,
                options={"verify_aud": False},  # audience can be configured per env
            )
            logger.debug(
                "OIDC: Token decoded successfully, sub=%s, exp=%s",
                claims.get("sub"), claims.get("exp"),
            )
        except JWTError as exc:
            logger.error("OIDC: JWT validation failed: %s", exc, exc_info=True)
            raise OIDCError(f"JWT validation failed: {exc}") from exc

        # Verify expiry explicitly
        now_ts = time.time()
        exp = claims.get("exp", 0)
        if exp < now_ts:
            logger.warning(
                "OIDC: Token has expired (exp=%s, now=%s, diff=%s seconds)",
                exp, now_ts, now_ts - exp,
            )
            raise OIDCError("Token has expired")

        # Apply claims mapping if configured
        if self._claim_mappings:
            claims = self._apply_claims_mapping(claims)

        logger.debug("OIDC: Token validation successful for sub=%s", claims.get("sub"))
        return claims

    def _apply_claims_mapping(self, claims: dict[str, Any]) -> dict[str, Any]:
        """Apply configured claims mapping to the decoded claims.

        The *claim_mappings* dict maps OIDC claim names to platform field names.
        E.g. ``{"email": "email", "name": "display_name"}``.
        """
        if not self._claim_mappings:
            return claims

        mapped: dict[str, Any] = {}
        for platform_field, oidc_claim in self._claim_mappings.items():
            value = claims.get(oidc_claim)
            if value is not None:
                mapped[platform_field] = value

        # Always preserve original claims
        result = {**claims, **mapped}
        return result

    # ── Cache management ──────────────────────────────────────────────────

    def clear_cache(self) -> None:
        """Clear instance-level JWKS and discovery caches."""
        self._jwks_keys = {}
        self._jwks_expiry = 0.0
        self._jwks_uri = None
        self._discovery_cached = None
        self._discovery_expiry = 0.0


# ── Legacy singleton (backward-compatible) ───────────────────────────────—

_oidc_client: Optional[OIDCClient] = None


def get_oidc_client() -> OIDCClient:
    """Return the legacy singleton OIDC client.

    Reads configuration from :func:`get_settings`.  Prefer using
    :class:`OIDCProviderRegistry` to obtain per-provider clients for
    multi-provider deployments.
    """
    global _oidc_client
    if _oidc_client is None:
        settings = get_settings()
        _oidc_client = OIDCClient(
            issuer_url=settings.oidc_provider_url,
            client_id="",  # legacy singleton — not used for access control
            algorithm=settings.jwt_algorithm,
            audience=settings.jwt_audience,
        )
    return _oidc_client


def reset_singleton() -> None:
    """Clear the module-level OIDC client singleton."""
    global _oidc_client
    _oidc_client = None
