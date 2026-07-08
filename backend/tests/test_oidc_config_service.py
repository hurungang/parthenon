"""Unit tests for OIDCConfigService — CRUD, encryption, discovery validation, audit."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.oidc_config_service import OIDCConfigError, OIDCConfigService
from app.db.models.identity_provider_config import IdentityProviderConfig
from app.db.models.identity_provider_config_audit import IdentityProviderConfigAudit


@pytest.fixture
def service() -> OIDCConfigService:
    return OIDCConfigService()


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _mock_discovery_response():
    return {
        "issuer": "https://auth.example.com",
        "jwks_uri": "https://auth.example.com/jwks",
        "authorization_endpoint": "https://auth.example.com/auth",
        "token_endpoint": "https://auth.example.com/token",
    }


@pytest.mark.asyncio
class TestCreateProvider:
    async def test_create_user_provider_success(self, service, mock_db):
        """Should create a user provider with encrypted secret and audit entry."""
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        with patch("app.services.oidc_config_service._fetch_discovery",
                   AsyncMock(return_value=_mock_discovery_response())):
            with patch("app.services.oidc_config_service.get_vault") as mock_vault:
                mock_vault.return_value.encrypt.return_value = "encrypted-secret-value"

                config = await service.create_provider(
                    mock_db,
                    provider_scope="user",
                    provider_type="oidc_generic",
                    display_name="Test OIDC",
                    issuer_url="https://auth.example.com",
                    client_id="my-client-id",
                    client_secret="my-secret",
                    scopes="openid profile",
                    changed_by="test_user",
                )

        assert config.provider_scope == "user"
        assert config.provider_type == "oidc_generic"
        assert config.issuer_url == "https://auth.example.com"
        assert config.client_id == "my-client-id"
        assert config.encrypted_client_secret == "encrypted-secret-value"
        assert mock_db.add.call_count >= 2  # config row + audit + setup state

    async def test_reject_duplicate_scope(self, service, mock_db):
        """Should reject creating a provider for an already-configured scope."""
        existing = MagicMock(spec=IdentityProviderConfig)
        existing.provider_scope = "user"
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=existing)
        ))

        with pytest.raises(OIDCConfigError, match="already exists"):
            await service.create_provider(
                mock_db,
                provider_scope="user",
                provider_type="keycloak",
                display_name="Test",
                issuer_url="https://auth.example.com",
                client_id="id",
            )

    async def test_reject_invalid_scope(self, service, mock_db):
        """Should reject invalid provider_scope."""
        with pytest.raises(OIDCConfigError, match="Invalid provider_scope"):
            await service.create_provider(
                mock_db,
                provider_scope="invalid",
                provider_type="oidc_generic",
                display_name="Test",
                issuer_url="https://auth.example.com",
                client_id="id",
            )


@pytest.mark.asyncio
class TestUpdateProvider:
    async def test_update_partial_fields(self, service, mock_db):
        """Should update only provided fields and write audit."""
        existing = MagicMock(spec=IdentityProviderConfig)
        existing.id = uuid.uuid4()
        existing.provider_scope = "user"
        existing.provider_type = "oidc_generic"
        existing.display_name = "Old Name"
        existing.issuer_url = "https://old.example.com"
        existing.client_id = "old-client"
        existing.encrypted_client_secret = "old-secret"
        existing.scopes = "openid"
        existing.claim_mappings = None
        existing.is_enabled = True

        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=existing)
        ))

        config = await service.update_provider(
            mock_db,
            "user",
            display_name="New Name",
            changed_by="test_user",
        )

        assert config.display_name == "New Name"
        assert config.provider_type == "oidc_generic"  # unchanged

    async def test_update_nonexistent_scope(self, service, mock_db):
        """Should raise when updating a non-existent scope."""
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        ))

        with pytest.raises(OIDCConfigError, match="No provider config exists"):
            await service.update_provider(mock_db, "agent", display_name="Test")


@pytest.mark.asyncio
class TestDeleteProvider:
    async def test_delete_success(self, service, mock_db):
        """Should delete and write audit entry."""
        existing = MagicMock(spec=IdentityProviderConfig)
        existing.id = uuid.uuid4()
        existing.provider_scope = "user"
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=existing)
        ))

        await service.delete_provider(mock_db, "user", changed_by="test_user")
        mock_db.delete.assert_called_once()


@pytest.mark.asyncio
class TestToggleProvider:
    async def test_toggle_success(self, service, mock_db):
        """Should toggle is_enabled and write audit."""
        existing = MagicMock(spec=IdentityProviderConfig)
        existing.id = uuid.uuid4()
        existing.provider_scope = "user"
        existing.is_enabled = True
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=existing)
        ))

        config = await service.toggle_provider(mock_db, "user", False, changed_by="test_user")
        assert config.is_enabled is False


@pytest.mark.asyncio
class TestTestConnection:
    async def test_successful_connection(self, service):
        """Should return success for a reachable issuer."""
        with patch("app.services.oidc_config_service._fetch_discovery",
                   AsyncMock(return_value=_mock_discovery_response())):
            with patch("app.services.oidc_config_service.httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__.return_value.get.return_value = (
                    MagicMock(status_code=200, raise_for_status=MagicMock(),
                              json=MagicMock(return_value={"keys": [{"kid": "k1"}]}))
                )
                result = await service.test_connection(
                    issuer_url="https://auth.example.com",
                    client_id="test-client",
                )

        assert result["success"] is True
        assert len(result["steps"]) >= 3
        assert all(s["status"] == "passed" for s in result["steps"] if s["status"] != "skipped")

    async def test_unreachable_issuer(self, service):
        """Should return failure for unreachable issuer."""
        with patch("app.services.oidc_config_service._fetch_discovery",
                   AsyncMock(side_effect=OIDCConfigError("Cannot reach issuer"))):
            result = await service.test_connection(issuer_url="https://unreachable.example.com")

        assert result["success"] is False
        assert result["steps"][0]["status"] == "failed"
