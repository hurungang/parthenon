from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

# ── KeycloakClient ──────────────────────────────────────────────────────────


class KeycloakClient:
    """Encapsulates all Keycloak HTTP interactions for the demo app."""

    _TOKEN_BUFFER_SECS = 30
    _JWKS_TTL_SECS = 600  # 10 minutes

    def __init__(self, realm_name: str | None = None) -> None:
        self._realm_name: str | None = realm_name
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._jwks: dict[str, Any] | None = None
        self._jwks_fetched_at: float = 0.0

    @property
    def _realm(self) -> str:
        return self._realm_name or settings.KEYCLOAK_REALM

    @property
    def _token_url(self) -> str:
        return (
            f"{settings.KEYCLOAK_URL}/realms/{self._realm}"
            "/protocol/openid-connect/token"
        )

    @property
    def _jwks_url(self) -> str:
        return (
            f"{settings.KEYCLOAK_URL}/realms/{self._realm}"
            "/protocol/openid-connect/certs"
        )

    async def get_own_access_token(self) -> str:
        """Return a valid access token, refreshing if near expiry."""
        now = time.monotonic()
        if self._access_token and now < self._token_expires_at - self._TOKEN_BUFFER_SECS:
            return self._access_token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.KEYCLOAK_CLIENT_ID,
                    "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )
            response.raise_for_status()
            payload = response.json()

        self._access_token = payload["access_token"]
        expires_in: int = payload.get("expires_in", 300)
        self._token_expires_at = time.monotonic() + expires_in
        logger.info("Obtained new Keycloak access token (expires_in=%ds)", expires_in)
        return self._access_token

    async def get_jwks(self) -> dict[str, Any]:
        """Return the realm's JWKS, refreshing the 10-minute cache as needed."""
        now = time.monotonic()
        if self._jwks and now < self._jwks_fetched_at + self._JWKS_TTL_SECS:
            return self._jwks

        async with httpx.AsyncClient() as client:
            response = await client.get(self._jwks_url, timeout=10.0)
            response.raise_for_status()
            self._jwks = response.json()

        self._jwks_fetched_at = time.monotonic()
        logger.debug("Refreshed Keycloak JWKS")
        return self._jwks


# Module-level singleton — initialised in lifespan
keycloak_client: KeycloakClient = KeycloakClient()

# Second module-level singleton for user realm JWKS (independent cache)
_user_realm = settings.KEYCLOAK_USER_REALM or settings.KEYCLOAK_REALM
user_keycloak_client: KeycloakClient = KeycloakClient(realm_name=_user_realm)

# ── JWT validation ───────────────────────────────────────────────────────────


async def verify_agent_jwt(token: str) -> dict[str, Any]:
    """Validate a forwarded agent JWT using Keycloak JWKS.

    Returns the decoded claims dict on success.
    Raises HTTPException(401) on any validation failure.
    """
    expected_issuer = f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}"
    try:
        jwks = await keycloak_client.get_jwks()
        claims: dict[str, Any] = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        if claims.get("iss") != expected_issuer:
            raise JWTError(f"Unexpected issuer: {claims.get('iss')}")
        return claims
    except JWTError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    except Exception as exc:
        logger.error("Unexpected error during JWT validation: %s", exc)
        raise HTTPException(status_code=401, detail="Token validation error") from exc


async def get_agent_identity(request: Request) -> dict[str, Any]:
    """FastAPI dependency: extract and validate the Bearer token from the request."""
    auth_header: str = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        logger.warning("Agent identity: missing or malformed Authorization header")
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = auth_header[len("Bearer "):]
    claims = await verify_agent_jwt(token)
    logger.info(
        "Agent identity validated: sub=%s realm=%s mcp_role=%s",
        claims.get("sub"), claims.get("iss"), claims.get("mcp_role"),
    )
    return claims


# ── User identity validation (dual-realm) ──────────────────────────────────────


async def verify_user_jwt(token: str) -> dict[str, Any]:
    """Validate a forwarded user JWT using the user realm's Keycloak JWKS.

    Returns the decoded claims dict on success.
    Raises HTTPException(401) on any validation failure.

    Falls back to the agent realm when KEYCLOAK_USER_REALM is not configured.
    """
    user_realm = settings.KEYCLOAK_USER_REALM or settings.KEYCLOAK_REALM
    expected_issuer = f"{settings.KEYCLOAK_URL}/realms/{user_realm}"
    try:
        jwks = await user_keycloak_client.get_jwks()
        claims: dict[str, Any] = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        if claims.get("iss") != expected_issuer:
            raise JWTError(f"Unexpected issuer: {claims.get('iss')}")
        return claims
    except JWTError as exc:
        logger.warning("User JWT validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired user token") from exc
    except Exception as exc:
        logger.error("Unexpected error during user JWT validation: %s", exc)
        raise HTTPException(status_code=401, detail="User token validation error") from exc


async def get_user_identity(request: Request) -> dict[str, Any]:
    """FastAPI dependency: extract and validate the user JWT from X-User-Identity header."""
    user_header: str = request.headers.get("X-User-Identity", "")
    if not user_header.startswith("Bearer "):
        logger.warning("User identity: missing or malformed X-User-Identity header")
        raise HTTPException(status_code=401, detail="Missing or malformed X-User-Identity header")
    token = user_header[len("Bearer "):]
    claims = await verify_user_jwt(token)
    logger.info(
        "User identity validated: sub=%s realm=%s mcp_role=%s",
        claims.get("sub"), claims.get("iss"), claims.get("mcp_role"),
    )
    return claims
