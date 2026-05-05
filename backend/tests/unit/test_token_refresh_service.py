"""Unit tests for TokenRefreshService — proactive OAuth token refresh for agent identities.

Adjustment: Agent identities are users in a dedicated agent realm. Their OAuth tokens
(access + refresh) are stored AES-256 encrypted. This service proactively refreshes
tokens before expiry and marks the identity suspended if the refresh token is expired.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agents.token_refresh_service import (
    TokenRefreshError,
    TokenRefreshService,
    REFRESH_WINDOW_SECONDS,
)
from app.db.models.agents import AgentIdentity, AgentIdentityStatus


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_identity(
    identity_id: uuid.UUID | None = None,
    status: AgentIdentityStatus = AgentIdentityStatus.active,
    access_token: str | None = "enc:some-access-token",
    refresh_token: str | None = "enc:some-refresh-token",
    token_expires_at: datetime | None = None,
) -> MagicMock:
    identity = MagicMock(spec=AgentIdentity)
    identity.id = identity_id or uuid.uuid4()
    identity.status = status
    identity.access_token = access_token
    identity.refresh_token = refresh_token
    identity.token_expires_at = token_expires_at or (
        datetime.now(timezone.utc) + timedelta(seconds=60)
    )
    return identity


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.get = AsyncMock()
    db.execute = AsyncMock()
    return db


# ── refresh_token — happy path ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_token_updates_encrypted_tokens():
    """refresh_token calls the agent realm token endpoint and stores new encrypted tokens."""
    service = TokenRefreshService()
    identity_id = uuid.uuid4()
    identity = _make_identity(identity_id=identity_id)

    db = _mock_db()
    db.get = AsyncMock(return_value=identity)

    fake_token_response = {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "expires_in": 300,
    }

    mock_http_response = MagicMock()
    mock_http_response.status_code = 200
    mock_http_response.json.return_value = fake_token_response

    mock_vault = MagicMock()
    mock_vault.decrypt.return_value = "plain-refresh-token"
    mock_vault.encrypt.side_effect = lambda s: f"enc:{s}"

    with (
        patch(
            "app.services.agents.token_refresh_service._keycloak_base_url",
            return_value="http://localhost:8082",
        ),
        patch(
            "app.services.agents.token_refresh_service._agent_realm_name",
            return_value="ai_agents",
        ),
        patch(
            "app.services.agents.token_refresh_service._agent_realm_client_id",
            return_value="parthenon-api",
        ),
        patch(
            "app.services.agents.token_refresh_service.get_vault",
            return_value=mock_vault,
        ),
        patch("httpx.AsyncClient") as mock_http_client_cls,
    ):
        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_http_response)
        mock_http_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await service.refresh_token(identity_id, db)

    # New tokens must be encrypted and stored
    assert identity.access_token == "enc:new-access-token"
    assert identity.refresh_token == "enc:new-refresh-token"
    assert identity.token_expires_at is not None


@pytest.mark.asyncio
async def test_refresh_token_rotates_refresh_token():
    """When a new refresh_token is in the response, it replaces the old one."""
    service = TokenRefreshService()
    identity_id = uuid.uuid4()
    identity = _make_identity(identity_id=identity_id, refresh_token="enc:old-refresh")

    db = _mock_db()
    db.get = AsyncMock(return_value=identity)

    mock_http_response = MagicMock()
    mock_http_response.status_code = 200
    mock_http_response.json.return_value = {
        "access_token": "new-access",
        "refresh_token": "rotated-refresh",
        "expires_in": 300,
    }

    mock_vault = MagicMock()
    mock_vault.decrypt.return_value = "plain-old-refresh"
    mock_vault.encrypt.side_effect = lambda s: f"enc:{s}"

    with (
        patch("app.services.agents.token_refresh_service._keycloak_base_url", return_value="http://localhost:8082"),
        patch("app.services.agents.token_refresh_service._agent_realm_name", return_value="ai_agents"),
        patch("app.services.agents.token_refresh_service._agent_realm_client_id", return_value="parthenon-api"),
        patch("app.services.agents.token_refresh_service.get_vault", return_value=mock_vault),
        patch("httpx.AsyncClient") as mock_http_client_cls,
    ):
        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_http_response)
        mock_http_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        await service.refresh_token(identity_id, db)

    assert identity.refresh_token == "enc:rotated-refresh"


# ── refresh_token — error paths ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_token_marks_identity_suspended_when_refresh_token_expired():
    """When the IdP returns 400 (expired refresh token), identity is set to suspended."""
    service = TokenRefreshService()
    identity_id = uuid.uuid4()
    identity = _make_identity(identity_id=identity_id)

    db = _mock_db()
    db.get = AsyncMock(return_value=identity)

    mock_http_response = MagicMock()
    mock_http_response.status_code = 400
    mock_http_response.text = "Token is not active"

    mock_vault = MagicMock()
    mock_vault.decrypt.return_value = "plain-expired-refresh"

    with (
        patch("app.services.agents.token_refresh_service._keycloak_base_url", return_value="http://localhost:8082"),
        patch("app.services.agents.token_refresh_service._agent_realm_name", return_value="ai_agents"),
        patch("app.services.agents.token_refresh_service._agent_realm_client_id", return_value="parthenon-api"),
        patch("app.services.agents.token_refresh_service.get_vault", return_value=mock_vault),
        patch("httpx.AsyncClient") as mock_http_client_cls,
    ):
        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_http_response)
        mock_http_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(TokenRefreshError):
            await service.refresh_token(identity_id, db)

    # Identity must be marked suspended
    assert identity.status == AgentIdentityStatus.suspended


@pytest.mark.asyncio
async def test_refresh_token_raises_when_identity_has_no_refresh_token():
    """refresh_token raises TokenRefreshError immediately when no refresh token is stored."""
    service = TokenRefreshService()
    identity_id = uuid.uuid4()
    identity = _make_identity(identity_id=identity_id, refresh_token=None)

    db = _mock_db()
    db.get = AsyncMock(return_value=identity)

    with pytest.raises(TokenRefreshError, match="no stored refresh token"):
        await service.refresh_token(identity_id, db)


@pytest.mark.asyncio
async def test_refresh_token_raises_not_found_for_missing_identity():
    """refresh_token raises TokenRefreshError when identity_id does not exist."""
    service = TokenRefreshService()

    db = _mock_db()
    db.get = AsyncMock(return_value=None)

    with pytest.raises(TokenRefreshError, match="not found"):
        await service.refresh_token(uuid.uuid4(), db)


# ── refresh_expiring_soon — sweep ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_expiring_soon_returns_count_of_refreshed():
    """refresh_expiring_soon returns the number of successfully refreshed identities."""
    service = TokenRefreshService()

    id1 = uuid.uuid4()
    id2 = uuid.uuid4()
    identity1 = _make_identity(identity_id=id1)
    identity2 = _make_identity(identity_id=id2)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [identity1, identity2]

    db = _mock_db()
    db.execute = AsyncMock(return_value=mock_result)

    # Patch refresh_token to succeed for both
    service.refresh_token = AsyncMock(return_value=identity1)

    count = await service.refresh_expiring_soon(db)

    assert count == 2
    assert service.refresh_token.call_count == 2


@pytest.mark.asyncio
async def test_refresh_expiring_soon_skips_failed_and_continues():
    """refresh_expiring_soon logs failures per-identity and still returns count of successful ones."""
    service = TokenRefreshService()

    id1 = uuid.uuid4()
    id2 = uuid.uuid4()
    identity1 = _make_identity(identity_id=id1)
    identity2 = _make_identity(identity_id=id2)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [identity1, identity2]

    db = _mock_db()
    db.execute = AsyncMock(return_value=mock_result)

    # First identity fails, second succeeds
    service.refresh_token = AsyncMock(
        side_effect=[TokenRefreshError("network error"), identity2]
    )

    count = await service.refresh_expiring_soon(db)

    # Only one succeeded
    assert count == 1


@pytest.mark.asyncio
async def test_refresh_expiring_soon_returns_zero_when_no_identities_due():
    """refresh_expiring_soon returns 0 when no identities need refreshing."""
    service = TokenRefreshService()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    db = _mock_db()
    db.execute = AsyncMock(return_value=mock_result)

    count = await service.refresh_expiring_soon(db)

    assert count == 0
