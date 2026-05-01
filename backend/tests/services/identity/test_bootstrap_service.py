"""Unit tests for IdentityBootstrapService."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set required env vars before importing app modules
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.schemas.identity_bootstrap import ProviderSetupRequest, ProviderType, SetupState
from app.services.identity.bootstrap_service import IdentityBootstrapService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_session() -> AsyncMock:
    """Return a fully mocked AsyncSession."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _make_execute_result(scalar_value: object) -> MagicMock:
    """Return a mock execute result whose scalar_one_or_none() returns *scalar_value*."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    return result


def _make_state_row(is_setup_complete: bool) -> MagicMock:
    """Return a mock IdentityProviderSetupState row."""
    row = MagicMock()
    row.is_setup_complete = is_setup_complete
    return row


# ---------------------------------------------------------------------------
# check_setup_state
# ---------------------------------------------------------------------------


class TestCheckSetupState:
    """Tests for IdentityBootstrapService.check_setup_state."""

    @pytest.mark.asyncio
    async def test_returns_not_configured_when_no_db_row_and_flag_false(self) -> None:
        """NOT_CONFIGURED when DB has no row and identity_setup_complete=False."""
        db = _make_db_session()
        db.execute.return_value = _make_execute_result(None)  # no DB row

        with patch("app.services.identity.bootstrap_service.get_settings") as mock_settings_fn:
            mock_settings = MagicMock()
            mock_settings.identity_setup_complete = False
            mock_settings_fn.return_value = mock_settings

            service = IdentityBootstrapService()
            state = await service.check_setup_state(db)

        assert state == SetupState.NOT_CONFIGURED

    @pytest.mark.asyncio
    async def test_returns_configured_when_db_row_is_complete(self) -> None:
        """CONFIGURED when DB has a row with is_setup_complete=True."""
        db = _make_db_session()
        db.execute.return_value = _make_execute_result(_make_state_row(is_setup_complete=True))

        service = IdentityBootstrapService()
        state = await service.check_setup_state(db)

        assert state == SetupState.CONFIGURED

    @pytest.mark.asyncio
    async def test_returns_not_configured_when_db_row_is_incomplete(self) -> None:
        """NOT_CONFIGURED when DB has a row with is_setup_complete=False."""
        db = _make_db_session()
        db.execute.return_value = _make_execute_result(_make_state_row(is_setup_complete=False))

        service = IdentityBootstrapService()
        state = await service.check_setup_state(db)

        assert state == SetupState.NOT_CONFIGURED


# ---------------------------------------------------------------------------
# provision_bundled_keycloak
# ---------------------------------------------------------------------------


class TestProvisionBundledKeycloak:
    """Tests for IdentityBootstrapService.provision_bundled_keycloak."""

    @pytest.mark.asyncio
    async def test_returns_error_when_keycloak_url_missing(self) -> None:
        """Returns error result with error_code='missing_keycloak_url' when keycloak_url is None."""
        db = _make_db_session()
        request = ProviderSetupRequest(
            provider_type=ProviderType.KEYCLOAK_BUNDLED,
            keycloak_url=None,
        )

        service = IdentityBootstrapService()
        result = await service.provision_bundled_keycloak(db, request)

        assert result.success is False
        assert result.error_code == "missing_keycloak_url"

    @pytest.mark.asyncio
    async def test_returns_error_when_keycloak_unreachable(self) -> None:
        """Returns error result with error_code='keycloak_unreachable' when HTTP connect fails."""
        import httpx

        db = _make_db_session()
        request = ProviderSetupRequest(
            provider_type=ProviderType.KEYCLOAK_BUNDLED,
            keycloak_url="http://unreachable-kc.example.com",
            realm_name="parthenon",
            client_id="parthenon-api",
            admin_user="admin",
            admin_password="secret",
        )

        # Build a mock AsyncClient context manager that raises ConnectError on get()
        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "app.services.identity.bootstrap_service.httpx.AsyncClient", return_value=mock_cm
        ):
            service = IdentityBootstrapService()
            result = await service.provision_bundled_keycloak(db, request)

        assert result.success is False
        assert result.error_code == "keycloak_unreachable"


# ---------------------------------------------------------------------------
# provision_external_oidc
# ---------------------------------------------------------------------------


class TestProvisionExternalOidc:
    """Tests for IdentityBootstrapService.provision_external_oidc."""

    @pytest.mark.asyncio
    async def test_returns_error_when_client_id_missing(self) -> None:
        """Returns error result with error_code='missing_client_id' when client_id is None."""
        db = _make_db_session()
        request = ProviderSetupRequest(
            provider_type=ProviderType.KEYCLOAK_EXTERNAL,
            oidc_discovery_url="https://idp.example.com/.well-known/openid-configuration",
            client_id=None,
        )

        service = IdentityBootstrapService()
        result = await service.provision_external_oidc(db, request)

        assert result.success is False
        assert result.error_code == "missing_client_id"
