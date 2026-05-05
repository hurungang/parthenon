"""TokenRefreshService — proactively refreshes stored agent OAuth access tokens.

Background behavior:
  - refresh_expiring_soon(db): queries all AgentIdentity records whose
    token_expires_at is within the next REFRESH_WINDOW_SECONDS and refreshes
    each one using the stored refresh token.
  - refresh_token(identity_id, db): refreshes a single identity's tokens.

Tokens are stored AES-256 encrypted; this service decrypts to call the IdP
and re-encrypts the returned token pair.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.credential_vault import get_vault
from app.core.yaml_config import load_identity_yaml
from app.db.models.agents import AgentIdentity, AgentIdentityStatus

logger = logging.getLogger(__name__)

# How far in advance to refresh tokens (5 minutes)
REFRESH_WINDOW_SECONDS = 300


def _keycloak_base_url() -> str:
    settings = get_settings()
    url = settings.oidc_provider_url.rstrip("/")
    if "/realms/" in url:
        return url.split("/realms/")[0]
    return url


def _agent_realm_name() -> str:
    yaml_cfg = load_identity_yaml()
    return getattr(yaml_cfg, "agent_realm_name", None) or "ai_agents"


def _agent_realm_client_id() -> str:
    settings = get_settings()
    return settings.jwt_audience or "parthenon-api"


class TokenRefreshError(Exception):
    """Raised when a token refresh call fails."""


class TokenRefreshService:
    """Background service for proactive agent OAuth token refresh.

    Intended to be called periodically (e.g., every 60 seconds) from a
    background task in the application startup lifecycle.
    """

    async def refresh_token(self, identity_id: uuid.UUID, db: AsyncSession) -> AgentIdentity:
        """Refresh the OAuth tokens for a single AgentIdentity.

        Reads the stored encrypted refresh token, calls the agent realm token
        endpoint, and updates the identity record with newly encrypted tokens.

        Args:
            identity_id: UUID of the AgentIdentity to refresh.
            db: Active async database session.

        Returns:
            Updated AgentIdentity with new token_expires_at.

        Raises:
            TokenRefreshError: If the identity has no refresh token, or if the
                IdP token endpoint returns an error.
        """
        identity = await db.get(AgentIdentity, identity_id)
        if identity is None:
            raise TokenRefreshError(f"AgentIdentity {identity_id} not found")

        if not identity.refresh_token:
            raise TokenRefreshError(
                f"AgentIdentity {identity_id} has no stored refresh token"
            )

        vault = get_vault()
        try:
            refresh_token_plain = vault.decrypt(identity.refresh_token)
        except Exception as exc:
            raise TokenRefreshError(
                f"Failed to decrypt refresh token for identity {identity_id}: {exc}"
            ) from exc

        keycloak_base = _keycloak_base_url()
        realm = _agent_realm_name()
        client_id = _agent_realm_client_id()
        token_url = f"{keycloak_base}/realms/{realm}/protocol/openid-connect/token"

        async with httpx.AsyncClient(timeout=30.0) as http_client:
            response = await http_client.post(
                token_url,
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": refresh_token_plain,
                },
            )

        if response.status_code != 200:
            logger.error(
                "Token refresh failed for identity %s: HTTP %s — %s",
                identity_id,
                response.status_code,
                response.text[:200],
            )
            # Mark the identity as needing re-authorization
            identity.status = AgentIdentityStatus.suspended
            await db.flush()
            raise TokenRefreshError(
                f"Token refresh failed (HTTP {response.status_code}): {response.text[:200]}"
            )

        token_data = response.json()
        new_access_token: str = token_data["access_token"]
        new_refresh_token: str | None = token_data.get("refresh_token")
        expires_in: int = int(token_data.get("expires_in", 300))

        identity.access_token = vault.encrypt(new_access_token)
        if new_refresh_token:
            identity.refresh_token = vault.encrypt(new_refresh_token)
        identity.token_expires_at = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + expires_in, tz=timezone.utc
        )

        await db.flush()
        await db.refresh(identity)
        logger.info(
            "Refreshed tokens for identity %s; new token_expires_at=%s",
            identity_id,
            identity.token_expires_at,
        )
        return identity

    async def refresh_expiring_soon(self, db: AsyncSession) -> int:
        """Refresh tokens for all identities expiring within REFRESH_WINDOW_SECONDS.

        Queries all AgentIdentity records with a refresh token whose access
        token is approaching expiry, and refreshes each one.

        Args:
            db: Active async database session.

        Returns:
            Number of identities successfully refreshed.
        """
        threshold = datetime.now(timezone.utc) + timedelta(seconds=REFRESH_WINDOW_SECONDS)

        result = await db.execute(
            select(AgentIdentity).where(
                AgentIdentity.refresh_token.is_not(None),
                AgentIdentity.token_expires_at.is_not(None),
                AgentIdentity.token_expires_at <= threshold,
                AgentIdentity.status == AgentIdentityStatus.active,
            )
        )
        identities = list(result.scalars().all())

        if not identities:
            return 0

        refreshed = 0
        for identity in identities:
            try:
                await self.refresh_token(identity.id, db)
                refreshed += 1
            except TokenRefreshError as exc:
                logger.warning(
                    "Failed to refresh tokens for identity %s: %s",
                    identity.id,
                    exc,
                )

        logger.info(
            "Token refresh sweep complete: %d/%d identities refreshed",
            refreshed,
            len(identities),
        )
        return refreshed
