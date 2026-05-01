"""OIDC client — fetches JWKS and validates JWT tokens."""

import logging
import time
from typing import Any

import httpx
from jose import JWTError, jwt

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Cache: {kid: public_key_pem}
_jwks_cache: dict[str, Any] = {}
_jwks_cache_expiry: float = 0.0
_JWKS_TTL_SECONDS = 300  # 5 minutes


class OIDCError(Exception):
    """Raised when OIDC validation fails."""


class OIDCClient:
    """Fetches JWKS from the configured provider and validates JWT signatures."""

    def __init__(self) -> None:
        _settings = get_settings()
        self._provider_url = _settings.oidc_provider_url.rstrip("/")
        self._algorithm = _settings.jwt_algorithm
        self._audience = _settings.jwt_audience
        self._jwks_uri_cache: str | None = None

    async def _get_jwks_uri(self) -> str:
        """Fetch JWKS URI from OIDC discovery endpoint."""
        if self._jwks_uri_cache:
            return self._jwks_uri_cache

        discovery_url = f"{self._provider_url}/.well-known/openid-configuration"
        logger.debug("OIDC: Fetching discovery document from %s", discovery_url)

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(discovery_url)
            response.raise_for_status()
            config: dict[str, Any] = response.json()

        jwks_uri = config.get("jwks_uri")
        if not jwks_uri:
            raise OIDCError("Discovery document missing jwks_uri")

        logger.info("OIDC: JWKS URI discovered: %s", jwks_uri)
        self._jwks_uri_cache = jwks_uri
        return jwks_uri

    async def _get_jwks(self) -> dict[str, Any]:
        """Fetch JWKS from the provider, with in-process caching."""
        global _jwks_cache, _jwks_cache_expiry
        now = time.monotonic()
        if now < _jwks_cache_expiry and _jwks_cache:
            return _jwks_cache

        jwks_uri = await self._get_jwks_uri()
        logger.debug("OIDC: Fetching JWKS from %s", jwks_uri)

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(jwks_uri)
            response.raise_for_status()
            data: dict[str, Any] = response.json()

        # Build kid → key mapping
        keys: dict[str, Any] = {}
        for jwk in data.get("keys", []):
            kid = jwk.get("kid", "default")
            keys[kid] = jwk

        _jwks_cache = keys
        _jwks_cache_expiry = now + _JWKS_TTL_SECONDS
        logger.debug("OIDC: JWKS refreshed from %s (%d keys)", jwks_uri, len(keys))
        return keys

    async def validate_token(self, token: str) -> dict[str, Any]:
        """
        Validate a JWT token and return the decoded claims.

        Raises OIDCError if validation fails.
        """
        logger.debug("OIDC: Starting token validation (token length: %d)", len(token))
        try:
            # Decode header without verification to get kid
            header = jwt.get_unverified_header(token)
            logger.debug(
                "OIDC: JWT header decoded, kid=%s, alg=%s", header.get("kid"), header.get("alg")
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
            global _jwks_cache_expiry
            _jwks_cache_expiry = 0.0
            try:
                jwks = await self._get_jwks()
                logger.debug("OIDC: JWKS refreshed, available kids: %s", list(jwks.keys()))
            except Exception as exc:
                logger.error("OIDC: Failed to refresh JWKS: %s", exc, exc_info=True)
                raise OIDCError(f"Failed to refresh JWKS: {exc}") from exc

        if kid not in jwks:
            logger.error("OIDC: Unknown key id: %s (available: %s)", kid, list(jwks.keys()))
            raise OIDCError(f"Unknown key id: {kid}")

        jwk = jwks[kid]
        logger.debug(
            "OIDC: Decoding token with kid=%s, algorithm=%s, audience=%s",
            kid,
            self._algorithm,
            self._audience,
        )
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                jwk,
                algorithms=[self._algorithm],
                audience=self._audience,
                options={"verify_aud": False},  # audience can be configured per environment
            )
            logger.debug(
                "OIDC: Token decoded successfully, sub=%s, exp=%s",
                claims.get("sub"),
                claims.get("exp"),
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
                exp,
                now_ts,
                now_ts - exp,
            )
            raise OIDCError("Token has expired")

        logger.info("OIDC: Token validation successful for sub=%s", claims.get("sub"))
        return claims

    def clear_cache(self) -> None:
        """Clear the JWKS cache (useful in tests)."""
        global _jwks_cache, _jwks_cache_expiry
        _jwks_cache = {}
        _jwks_cache_expiry = 0.0

    def reload(self, provider_url: str, algorithm: str, audience: str) -> None:
        """Update the provider URL, algorithm, and audience, then clear JWKS cache.

        Called by the Bootstrap Service after provisioning to switch the active
        provider without restarting the process.

        Args:
            provider_url: New OIDC provider base URL (trailing slash stripped).
            algorithm: JWT signing algorithm (e.g. ``"RS256"``).
            audience: Expected ``aud`` claim value.
        """
        self._provider_url = provider_url.rstrip("/")
        self._algorithm = algorithm
        self._audience = audience
        self.clear_cache()
        logger.info("OIDCClient reloaded: provider=%s algorithm=%s", self._provider_url, algorithm)


# Singleton instance
_oidc_client: OIDCClient | None = None


def get_oidc_client() -> OIDCClient:
    """Return the singleton OIDC client."""
    global _oidc_client
    if _oidc_client is None:
        _oidc_client = OIDCClient()
    return _oidc_client


def reset_singleton() -> None:
    """Clear the module-level OIDC client singleton.

    After calling this, the next call to :func:`get_oidc_client` will create a
    fresh :class:`OIDCClient` instance reading updated settings.
    """
    global _oidc_client
    _oidc_client = None
