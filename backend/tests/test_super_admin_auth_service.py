"""Unit tests for SuperAdminAuthService — seeding, login, JWT issuance, toggle."""
import os
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.super_admin_auth_service import (
    SuperAdminAuthError,
    SuperAdminAuthService,
    _hash_plaintext,
    _verify_password,
)
from app.db.models.super_admin_credentials import SuperAdminCredentials


@pytest.fixture
def service() -> SuperAdminAuthService:
    return SuperAdminAuthService()


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def credentials() -> SuperAdminCredentials:
    return SuperAdminCredentials(
        id=uuid.uuid4(),
        username="admin",
        hashed_password=_hash_plaintext("testpass"),
        is_enabled=True,
        last_login_at=None,
    )


# ── Seeding ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSeedCredentials:
    async def test_seed_first_launch(self, service, mock_db):
        """Should create credentials when none exist."""
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        ))

        with patch.dict(os.environ, {
            "SUPER_ADMIN_USERNAME": "admin",
            "SUPER_ADMIN_PASSWORD_HASH": _hash_plaintext("admin123"),
        }):
            await service.seed_credentials(mock_db)

        assert mock_db.add.call_count >= 1

    async def test_seed_skips_when_no_env_var(self, service, mock_db):
        """Should skip seeding when SUPER_ADMIN_USERNAME is not set."""
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        ))

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SUPER_ADMIN_USERNAME", None)
            os.environ.pop("SUPER_ADMIN_PASSWORD_HASH", None)
            await service.seed_credentials(mock_db)

        mock_db.add.assert_not_called()

    async def test_seed_idempotent(self, service, mock_db, credentials):
        """Should not create duplicate when credentials already exist."""
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=credentials)
        ))

        with patch.dict(os.environ, {
            "SUPER_ADMIN_USERNAME": "admin",
        }):
            await service.seed_credentials(mock_db)

        # Should not add new credentials
        add_calls = [c for c in mock_db.add.call_args_list if isinstance(c.args[0], SuperAdminCredentials)]
        assert len(add_calls) == 0


# ── Login ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestLogin:
    async def test_successful_login(self, service, mock_db, credentials):
        """Should return a valid JWT on successful login."""
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=credentials)
        ))

        token = await service.login(mock_db, "admin", "testpass")
        assert token is not None
        assert len(token) > 0

        # Validate token
        payload = service.validate_token(token)
        assert payload["is_super_admin"] is True
        assert payload["username"] == "admin"

    async def test_invalid_password(self, service, mock_db, credentials):
        """Should raise when password is wrong."""
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=credentials)
        ))

        with pytest.raises(SuperAdminAuthError, match="Invalid username or password"):
            await service.login(mock_db, "admin", "wrongpass")

    async def test_login_when_disabled(self, service, mock_db, credentials):
        """Should raise when super admin is disabled."""
        credentials.is_enabled = False
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=credentials)
        ))

        with pytest.raises(SuperAdminAuthError, match="disabled"):
            await service.login(mock_db, "admin", "testpass")

    async def test_login_when_not_seeded(self, service, mock_db):
        """Should raise when no credentials exist."""
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        ))

        with pytest.raises(SuperAdminAuthError, match="not configured"):
            await service.login(mock_db, "admin", "pass")


# ── Token validation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestValidateToken:
    async def test_valid_token(self, service, mock_db, credentials):
        """Should validate a legitimately issued token."""
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=credentials)
        ))

        token = await service.login(mock_db, "admin", "testpass")
        payload = service.validate_token(token)
        assert payload["is_super_admin"] is True
        assert payload["username"] == "admin"

    def test_invalid_token(self, service):
        """Should raise for a garbage token."""
        with pytest.raises(SuperAdminAuthError):
            service.validate_token("invalid-token")

    def test_non_super_admin_token(self, service):
        """Should raise for a token that is not a super admin token."""
        from jose import jwt as jose_jwt
        token = jose_jwt.encode({"sub": "user"}, "secret", algorithm="HS256")
        with pytest.raises(SuperAdminAuthError):
            service.validate_token(token)


# ── Toggle ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestToggle:
    async def test_disable(self, service, mock_db, credentials):
        """Should disable the super admin."""
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=credentials)
        ))

        result = await service.toggle(mock_db, False)
        assert result.is_enabled is False

    async def test_enable(self, service, mock_db, credentials):
        """Should enable the super admin."""
        credentials.is_enabled = False
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=credentials)
        ))

        result = await service.toggle(mock_db, True)
        assert result.is_enabled is True


# ── Password update ──────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestUpdatePassword:
    async def test_successful_update(self, service, mock_db, credentials):
        """Should update password after verifying current one."""
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=credentials)
        ))

        await service.update_password(mock_db, "testpass", "newpass123")
        assert credentials.hashed_password != _hash_plaintext("testpass")

    async def test_wrong_current_password(self, service, mock_db, credentials):
        """Should raise when current password is wrong."""
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=credentials)
        ))

        with pytest.raises(SuperAdminAuthError, match="Current password is incorrect"):
            await service.update_password(mock_db, "wrongpass", "newpass")
