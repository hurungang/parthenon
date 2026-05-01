"""Unit tests for the Setup Identity API endpoints."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# Set required env vars before importing app modules
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.main import create_app
from app.schemas.identity_bootstrap import (
    SetupState,
)
from app.services.identity.keycloak_admin_client import KeycloakAdminError

_SERVICE_PATH = "app.api.v1.setup.IdentityBootstrapService"


def _make_db_override() -> tuple[AsyncMock, object]:
    """Return a mock DB session and the override dependency callable."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    async def override_get_db():  # type: ignore[return]
        yield mock_session

    return mock_session, override_get_db


# ---------------------------------------------------------------------------
# GET /api/v1/setup/identity-status
# ---------------------------------------------------------------------------


class TestGetIdentityStatus:
    """Tests for GET /api/v1/setup/identity-status."""

    @pytest.mark.asyncio
    async def test_returns_not_configured(self) -> None:
        """Returns 200 with setup_state='NOT_CONFIGURED' when service returns NOT_CONFIGURED."""
        app = create_app()
        _, override = _make_db_override()

        from app.db.session import get_db

        app.dependency_overrides[get_db] = override

        with patch(_SERVICE_PATH) as MockService:
            mock_instance = MockService.return_value
            mock_instance.check_setup_state = AsyncMock(return_value=SetupState.NOT_CONFIGURED)
            mock_instance.get_current_config = AsyncMock(return_value=None)

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/setup/identity-status")

        assert response.status_code == 200
        data = response.json()
        assert data["setup_state"] == "NOT_CONFIGURED"
        assert data["provider_type"] is None
        assert data["oidc_provider_url"] is None

    @pytest.mark.asyncio
    async def test_returns_configured_with_provider_fields(self) -> None:
        """Returns 200 with setup_state='CONFIGURED' and provider fields when service returns CONFIGURED."""
        app = create_app()
        _, override = _make_db_override()

        from app.db.session import get_db

        app.dependency_overrides[get_db] = override

        mock_config = MagicMock()
        mock_config.provider_type = "keycloak_bundled"
        mock_config.oidc_provider_url = "http://keycloak.example.com/realms/parthenon"

        with patch(_SERVICE_PATH) as MockService:
            mock_instance = MockService.return_value
            mock_instance.check_setup_state = AsyncMock(return_value=SetupState.CONFIGURED)
            mock_instance.get_current_config = AsyncMock(return_value=mock_config)

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/setup/identity-status")

        assert response.status_code == 200
        data = response.json()
        assert data["setup_state"] == "CONFIGURED"
        assert data["provider_type"] == "keycloak_bundled"
        assert data["oidc_provider_url"] == "http://keycloak.example.com/realms/parthenon"


# ---------------------------------------------------------------------------
# POST /api/v1/setup/identity
# ---------------------------------------------------------------------------


class TestProvisionIdentity:
    """Tests for POST /api/v1/setup/identity."""

    @pytest.mark.asyncio
    async def test_returns_409_when_already_configured_and_no_force(self) -> None:
        """Returns 409 when setup is already CONFIGURED and force_reconfigure=false."""
        app = create_app()
        _, override = _make_db_override()

        from app.db.session import get_db

        app.dependency_overrides[get_db] = override

        with patch(_SERVICE_PATH) as MockService:
            mock_instance = MockService.return_value
            mock_instance.check_setup_state = AsyncMock(return_value=SetupState.CONFIGURED)

            payload = {
                "provider_type": "keycloak_bundled",
                "force_reconfigure": False,
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/api/v1/setup/identity", json=payload)

        assert response.status_code == 409
        assert "already configured" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_returns_502_when_keycloak_admin_error_raised(self) -> None:
        """Returns 502 when KeycloakAdminError is raised by the service."""
        app = create_app()
        _, override = _make_db_override()

        from app.db.session import get_db

        app.dependency_overrides[get_db] = override

        with patch(_SERVICE_PATH) as MockService:
            mock_instance = MockService.return_value
            mock_instance.check_setup_state = AsyncMock(return_value=SetupState.NOT_CONFIGURED)
            mock_instance.provision_bundled_keycloak = AsyncMock(
                side_effect=KeycloakAdminError(
                    error_code="auth_failed",
                    detail="Keycloak admin authentication failed",
                )
            )

            payload = {
                "provider_type": "keycloak_bundled",
                "keycloak_url": "http://keycloak.example.com",
                "realm_name": "parthenon",
                "client_id": "parthenon-api",
                "admin_user": "admin",
                "admin_password": "secret",
                "force_reconfigure": False,
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/api/v1/setup/identity", json=payload)

        assert response.status_code == 502
        detail = response.json()["detail"]
        assert detail["error_code"] == "auth_failed"
