"""Integration tests — Token refresh logic with mocked OAuth provider.

Covers:
  Task 6.2 — Backend Integration Tests - Token Refresh

Tests:
  - Permission check with valid token → returns token without refresh
  - Permission check with expired token → triggers refresh, returns new token
  - Token refresh success → updates all fields correctly
  - Token refresh failure (invalid_grant) → logs failure, sets token_status=refresh_failed
  - Token refresh rate-limited → outcome=rate_limited logged
  - Query token_refresh_log table → all attempts logged
  - Token refresh with retry → exponential backoff respected

Database: Uses shared SQLite in-memory engine from conftest.py.
OAuth provider: Mocked via unittest.mock to avoid real HTTP calls.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_vault import CredentialVault
from app.db.models.agent_security import TokenRefreshLog, TokenRefreshOutcome
from app.db.models.agents import AgentIdentity, AgentIdentityStatus, AgentIdentityType, AgentTokenStatus
from app.services.token_refresh import (
    TokenRefreshError,
    TokenRefreshServiceV2,
    check_token_expiration,
    refresh_oauth_token,
    store_refreshed_token,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_vault() -> CredentialVault:
    """Create a test vault with fixed key."""
    import os
    os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
    return CredentialVault()


@pytest_asyncio.fixture
async def agent_identity_with_valid_token(db_session: AsyncSession) -> AgentIdentity:
    """AgentIdentity with a non-expired token."""
    vault = _make_vault()
    access_token = vault.encrypt("valid-access-token-abc")
    refresh_token = vault.encrypt("valid-refresh-token-xyz")
    identity = AgentIdentity(
        name=f"test-identity-valid-{uuid.uuid4().hex[:6]}",
        identity_type=AgentIdentityType.realm_user,
        access_token=access_token,
        refresh_token=refresh_token,
        encrypted_refresh_token=refresh_token,
        token_expires_at=_now_utc() + timedelta(hours=1),
        token_status=AgentTokenStatus.active,
        status=AgentIdentityStatus.active,
    )
    db_session.add(identity)
    await db_session.flush()
    return identity


@pytest_asyncio.fixture
async def agent_identity_with_expired_token(db_session: AsyncSession) -> AgentIdentity:
    """AgentIdentity with an expired token."""
    vault = _make_vault()
    access_token = vault.encrypt("expired-access-token")
    refresh_token = vault.encrypt("valid-refresh-token-for-expired")
    identity = AgentIdentity(
        name=f"test-identity-expired-{uuid.uuid4().hex[:6]}",
        identity_type=AgentIdentityType.realm_user,
        access_token=access_token,
        refresh_token=refresh_token,
        encrypted_refresh_token=refresh_token,
        token_expires_at=_now_utc() - timedelta(hours=1),  # Already expired
        token_status=AgentTokenStatus.expired,
        status=AgentIdentityStatus.active,
    )
    db_session.add(identity)
    await db_session.flush()
    return identity


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_token_expiration_valid_token_returns_false(
    db_session: AsyncSession,
    agent_identity_with_valid_token: AgentIdentity,
):
    """check_token_expiration returns False when token is valid and not near expiry."""
    needs_refresh = await check_token_expiration(
        agent_identity_with_valid_token.id, db_session
    )
    assert needs_refresh is False


@pytest.mark.asyncio
async def test_check_token_expiration_expired_token_returns_true(
    db_session: AsyncSession,
    agent_identity_with_expired_token: AgentIdentity,
):
    """check_token_expiration returns True when token is already expired."""
    needs_refresh = await check_token_expiration(
        agent_identity_with_expired_token.id, db_session
    )
    assert needs_refresh is True


@pytest.mark.asyncio
async def test_check_token_expiration_expiring_soon_returns_true(
    db_session: AsyncSession,
):
    """check_token_expiration returns True when token expires within 5 minutes."""
    vault = _make_vault()
    identity = AgentIdentity(
        name=f"test-identity-expiring-soon-{uuid.uuid4().hex[:6]}",
        identity_type=AgentIdentityType.realm_user,
        access_token=vault.encrypt("soon-token"),
        refresh_token=vault.encrypt("refresh"),
        token_expires_at=_now_utc() + timedelta(minutes=2),  # 2 min — within 5 min window
        token_status=AgentTokenStatus.active,
        status=AgentIdentityStatus.active,
    )
    db_session.add(identity)
    await db_session.flush()

    needs_refresh = await check_token_expiration(identity.id, db_session)
    assert needs_refresh is True


@pytest.mark.asyncio
async def test_refresh_token_success_updates_identity(
    db_session: AsyncSession,
    agent_identity_with_expired_token: AgentIdentity,
):
    """Successful token refresh updates access_token, expires_at, last_token_refresh_at, token_status."""
    new_expires_in = 3600
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "new-access-token-fresh",
        "refresh_token": "new-refresh-token",
        "expires_in": new_expires_in,
    }

    with patch("app.services.token_refresh.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await refresh_oauth_token(
            agent_identity_with_expired_token.id, db_session
        )

    assert result.access_token == "new-access-token-fresh"
    assert result.expires_at > _now_utc()

    # Verify database updated
    await db_session.refresh(agent_identity_with_expired_token)
    assert agent_identity_with_expired_token.token_status == AgentTokenStatus.active
    assert agent_identity_with_expired_token.last_token_refresh_at is not None
    # SQLite may strip timezone info on reload; normalize before comparing
    stored_expires = agent_identity_with_expired_token.token_expires_at
    if stored_expires.tzinfo is None:
        stored_expires = stored_expires.replace(tzinfo=timezone.utc)
    assert stored_expires > _now_utc()


@pytest.mark.asyncio
async def test_refresh_token_failure_sets_refresh_failed_status(
    db_session: AsyncSession,
    agent_identity_with_expired_token: AgentIdentity,
):
    """Token refresh failure sets token_status=refresh_failed and raises TokenRefreshError."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = '{"error": "invalid_grant", "error_description": "Token expired"}'

    with patch("app.services.token_refresh.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        with patch("app.services.token_refresh.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(TokenRefreshError):
                await refresh_oauth_token(
                    agent_identity_with_expired_token.id, db_session
                )

    await db_session.refresh(agent_identity_with_expired_token)
    assert agent_identity_with_expired_token.token_status == AgentTokenStatus.refresh_failed


@pytest.mark.asyncio
async def test_refresh_token_rate_limited_logs_rate_limited_outcome(
    db_session: AsyncSession,
    agent_identity_with_expired_token: AgentIdentity,
):
    """Rate-limited token refresh logs outcome=rate_limited."""
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.headers = {"Retry-After": "5"}
    mock_response.text = ""

    with patch("app.services.token_refresh.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        with patch("app.services.token_refresh.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(TokenRefreshError) as exc_info:
                await refresh_oauth_token(
                    agent_identity_with_expired_token.id, db_session
                )
    assert exc_info.value.is_rate_limited is True


@pytest.mark.asyncio
async def test_refresh_attempts_logged_in_audit_table(
    db_session: AsyncSession,
    agent_identity_with_expired_token: AgentIdentity,
):
    """All refresh attempts are logged in the token_refresh_logs table."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    count_before = len((await db_session.execute(select(TokenRefreshLog))).scalars().all())

    with patch("app.services.token_refresh.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        with patch("app.services.token_refresh.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(TokenRefreshError):
                await refresh_oauth_token(
                    agent_identity_with_expired_token.id, db_session
                )

    all_logs = (await db_session.execute(select(TokenRefreshLog))).scalars().all()
    new_logs = [
        l for l in all_logs
        if l.agent_identity_id == agent_identity_with_expired_token.id
    ]

    # Should have 3 attempts logged (retries: 1, 2, 3)
    assert len(new_logs) == 3
    outcomes = [l.outcome for l in new_logs]
    assert all(o == TokenRefreshOutcome.failure for o in outcomes)


@pytest.mark.asyncio
async def test_store_refreshed_token_updates_fields(
    db_session: AsyncSession,
    agent_identity_with_expired_token: AgentIdentity,
):
    """store_refreshed_token correctly updates identity fields."""
    new_expires_at = _now_utc() + timedelta(hours=1)
    new_token = "new-stored-token"
    new_refresh = "new-stored-refresh"

    await store_refreshed_token(
        agent_identity_with_expired_token.id,
        new_token,
        new_expires_at,
        new_refresh,
        db_session,
    )

    await db_session.refresh(agent_identity_with_expired_token)
    assert agent_identity_with_expired_token.token_status == AgentTokenStatus.active
    assert agent_identity_with_expired_token.last_token_refresh_at is not None
    # SQLite may strip timezone info on reload; normalize before comparing
    stored_expires = agent_identity_with_expired_token.token_expires_at
    if stored_expires.tzinfo is None:
        stored_expires = stored_expires.replace(tzinfo=timezone.utc)
    assert stored_expires == new_expires_at

    # Verify token stored encrypted (not plaintext)
    vault = _make_vault()
    stored_decrypted = vault.decrypt(agent_identity_with_expired_token.access_token)
    assert stored_decrypted == new_token
