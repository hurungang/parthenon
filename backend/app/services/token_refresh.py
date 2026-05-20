"""Token Refresh Service — automatic OAuth token lifecycle management for agent identities.

This service integrates with permission resolution to transparently refresh expired tokens
before they are returned for tool execution.  All refresh attempts are logged to the
``token_refresh_logs`` audit table.

Key behavior:
- Checks token expiration before every permission resolution
- Refreshes via OAuth provider refresh_token grant
- Exponential backoff: 1s, 5s, 15s (max 3 attempts)
- Respects HTTP 429 rate limit responses from OAuth provider
- Sets ``token_status=refresh_failed`` on the AgentIdentity when max retries are exceeded
- Logs every attempt with outcome, retry number, and error message
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.credential_vault import get_vault
from app.core.ssl_context import get_ssl_context
from app.core.yaml_config import load_identity_yaml
from app.db.models.agent_security import TokenRefreshLog, TokenRefreshOutcome
from app.db.models.agents import AgentIdentity, AgentTokenStatus

logger = logging.getLogger(__name__)

# Token is considered "expiring soon" if it expires within this window
_EXPIRY_WINDOW_SECONDS = 300  # 5 minutes

# Exponential back-off delays between retry attempts (seconds)
_RETRY_DELAYS = [1, 5, 15]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── Exceptions ────────────────────────────────────────────────────────────────


class TokenRefreshError(Exception):
    """Raised when token refresh ultimately fails after all retries."""

    def __init__(self, message: str, is_rate_limited: bool = False) -> None:
        super().__init__(message)
        self.is_rate_limited = is_rate_limited


# ── Result type ───────────────────────────────────────────────────────────────


class TokenRefreshResult(NamedTuple):
    """Result of a token refresh operation."""

    access_token: str
    expires_at: datetime


# ── Internal helpers ──────────────────────────────────────────────────────────


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


# ── Core functions ────────────────────────────────────────────────────────────


async def check_token_expiration(identity_id: uuid.UUID, db: AsyncSession) -> bool:
    """Return True if the identity token is expired or expires within 5 minutes.

    Args:
        identity_id: UUID of the AgentIdentity to check.
        db: Active async database session.

    Returns:
        True if token needs refresh, False if token is still valid.
    """
    identity = await db.get(AgentIdentity, identity_id)
    if identity is None:
        return True  # Non-existent identity is treated as needing refresh

    expires_at = identity.token_expires_at
    if expires_at is None:
        return True  # No expiry recorded → treat as expired

    threshold = _now_utc() + timedelta(seconds=_EXPIRY_WINDOW_SECONDS)
    return expires_at <= threshold


async def refresh_oauth_token(
    identity_id: uuid.UUID,
    db: AsyncSession,
) -> TokenRefreshResult:
    """Refresh OAuth tokens for an agent identity using the stored refresh token.

    Calls the OAuth provider token endpoint with ``grant_type=refresh_token``.
    Implements exponential backoff with up to 3 attempts.

    On success: updates access_token, expires_at, last_token_refresh_at, token_status=active.
    On failure: sets token_status=refresh_failed and raises TokenRefreshError.

    All attempts are logged in the ``token_refresh_logs`` table.

    Args:
        identity_id: UUID of the AgentIdentity to refresh.
        db: Active async database session.

    Returns:
        TokenRefreshResult with the new access token and expiration timestamp.

    Raises:
        TokenRefreshError: If refresh fails after all retry attempts.
    """
    identity = await db.get(AgentIdentity, identity_id)
    if identity is None:
        raise TokenRefreshError(f"AgentIdentity {identity_id} not found")

    # Prefer the dedicated encrypted_refresh_token field; fall back to legacy refresh_token
    encrypted_rt = identity.encrypted_refresh_token or identity.refresh_token
    if not encrypted_rt:
        raise TokenRefreshError(
            f"AgentIdentity {identity_id} has no stored refresh token"
        )

    logger.debug(
        "Auto-refresh for identity %s: using encrypted_refresh_token=%s, refresh_token=%s",
        identity_id,
        identity.encrypted_refresh_token is not None,
        identity.refresh_token is not None,
    )

    vault = get_vault()
    try:
        refresh_token_plain = vault.decrypt(encrypted_rt)
    except Exception as exc:
        raise TokenRefreshError(
            f"Failed to decrypt refresh token for identity {identity_id}: {exc}"
        ) from exc

    keycloak_base = _keycloak_base_url()
    realm = _agent_realm_name()
    client_id = _agent_realm_client_id()
    token_url = f"{keycloak_base}/realms/{realm}/protocol/openid-connect/token"

    last_error: str = "unknown"
    is_rate_limited = False

    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            async with httpx.AsyncClient(
                timeout=30.0, verify=get_ssl_context()
            ) as http_client:
                response = await http_client.post(
                    token_url,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": client_id,
                        "refresh_token": refresh_token_plain,
                    },
                )

            if response.status_code == 429:
                # Rate limited — log and back off
                retry_after = int(response.headers.get("Retry-After", delay * 3))
                last_error = f"rate_limited (Retry-After: {retry_after}s)"
                is_rate_limited = True
                next_retry = _now_utc() + timedelta(seconds=retry_after)
                await _log_refresh(
                    identity_id,
                    TokenRefreshOutcome.rate_limited,
                    attempt,
                    last_error,
                    next_retry,
                    db,
                )
                if attempt < len(_RETRY_DELAYS):
                    await asyncio.sleep(retry_after)
                continue

            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                outcome = TokenRefreshOutcome.failure
                next_retry = (
                    _now_utc() + timedelta(seconds=_RETRY_DELAYS[attempt - 1])
                    if attempt < len(_RETRY_DELAYS)
                    else None
                )
                await _log_refresh(
                    identity_id, outcome, attempt, last_error, next_retry, db
                )
                if attempt < len(_RETRY_DELAYS):
                    await asyncio.sleep(_RETRY_DELAYS[attempt - 1])
                continue

            # Success
            token_data = response.json()
            new_access_token: str = token_data["access_token"]
            new_refresh_token: str | None = token_data.get("refresh_token")
            expires_in: int = int(token_data.get("expires_in", 300))
            new_expires_at = _now_utc() + timedelta(seconds=expires_in)

            await store_refreshed_token(
                identity_id, new_access_token, new_expires_at,
                new_refresh_token, db,
            )
            await _log_refresh(identity_id, TokenRefreshOutcome.success, attempt, None, None, db)

            logger.info(
                "Refreshed tokens for identity %s on attempt %d; expires=%s",
                identity_id,
                attempt,
                new_expires_at,
            )
            return TokenRefreshResult(access_token=new_access_token, expires_at=new_expires_at)

        except httpx.RequestError as exc:
            last_error = f"Network error: {exc}"
            next_retry = (
                _now_utc() + timedelta(seconds=_RETRY_DELAYS[attempt - 1])
                if attempt < len(_RETRY_DELAYS)
                else None
            )
            await _log_refresh(
                identity_id, TokenRefreshOutcome.failure, attempt, last_error, next_retry, db
            )
            if attempt < len(_RETRY_DELAYS):
                await asyncio.sleep(_RETRY_DELAYS[attempt - 1])

    # All attempts failed — mark identity token_status
    identity = await db.get(AgentIdentity, identity_id)
    if identity is not None:
        identity.token_status = AgentTokenStatus.refresh_failed
        await db.flush()

    logger.error(
        "Token refresh failed for identity %s after %d attempts: %s",
        identity_id,
        len(_RETRY_DELAYS),
        last_error,
    )
    raise TokenRefreshError(last_error, is_rate_limited=is_rate_limited)


async def store_refreshed_token(
    identity_id: uuid.UUID,
    access_token: str,
    expires_at: datetime,
    new_refresh_token: str | None,
    db: AsyncSession,
) -> None:
    """Persist refreshed tokens to the agent_identity record.

    Encrypts the access token and optionally the new refresh token before storage.

    Args:
        identity_id: UUID of the AgentIdentity.
        access_token: Plain-text new access token.
        expires_at: New expiration timestamp.
        new_refresh_token: New refresh token (if provider issued one).
        db: Active async database session.
    """
    identity = await db.get(AgentIdentity, identity_id)
    if identity is None:
        return

    vault = get_vault()
    identity.access_token = vault.encrypt(access_token)
    identity.token_expires_at = expires_at
    identity.last_token_refresh_at = _now_utc()
    identity.token_status = AgentTokenStatus.active

    if new_refresh_token:
        encrypted_rt = vault.encrypt(new_refresh_token)
        identity.encrypted_refresh_token = encrypted_rt
        identity.refresh_token = encrypted_rt  # Keep legacy field in sync

    await db.flush()


async def _log_refresh(
    identity_id: uuid.UUID,
    outcome: TokenRefreshOutcome,
    retry_attempt: int,
    error_message: str | None,
    next_retry_at: datetime | None,
    db: AsyncSession,
) -> None:
    """Insert a token refresh audit log entry."""
    entry = TokenRefreshLog(
        agent_identity_id=identity_id,
        attempted_at=_now_utc(),
        outcome=outcome,
        error_message=error_message,
        retry_attempt=retry_attempt,
        next_retry_at=next_retry_at,
    )
    db.add(entry)
    await db.flush()


async def log_refresh_attempt(
    identity_id: uuid.UUID,
    outcome: TokenRefreshOutcome,
    error: str | None,
    db: AsyncSession,
    retry_attempt: int = 1,
) -> None:
    """Public wrapper for logging a single refresh attempt."""
    await _log_refresh(identity_id, outcome, retry_attempt, error, None, db)


# ── Main Service Class ────────────────────────────────────────────────────────


class TokenRefreshServiceV2:
    """Security-segregation token refresh service with full audit logging.

    Named V2 to distinguish from the background-sweep TokenRefreshService in
    ``app.services.agents.token_refresh_service``.  This service is called
    inline during permission resolution for on-demand token refresh.
    """

    async def check_expiration(
        self, identity_id: uuid.UUID, db: AsyncSession
    ) -> bool:
        return await check_token_expiration(identity_id, db)

    async def refresh(
        self, identity_id: uuid.UUID, db: AsyncSession
    ) -> TokenRefreshResult:
        return await refresh_oauth_token(identity_id, db)

    async def store_tokens(
        self,
        identity_id: uuid.UUID,
        access_token: str,
        expires_at: datetime,
        refresh_token: str | None,
        db: AsyncSession,
    ) -> None:
        await store_refreshed_token(identity_id, access_token, expires_at, refresh_token, db)

    async def log_attempt(
        self,
        identity_id: uuid.UUID,
        outcome: TokenRefreshOutcome,
        error: str | None,
        db: AsyncSession,
        retry_attempt: int = 1,
    ) -> None:
        await log_refresh_attempt(identity_id, outcome, error, db, retry_attempt)
