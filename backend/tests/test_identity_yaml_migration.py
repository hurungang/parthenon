"""Unit tests for IdentityYamlMigration — one-time migration from identity.yaml to DB."""
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.identity_yaml_migration import IdentityYamlMigration


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _write_temp_yaml(data: dict) -> Path:
    """Write a temporary identity.yaml file and return its path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    yaml.dump(data, tmp)
    tmp.close()
    return Path(tmp.name)


@pytest.mark.asyncio
class TestIdentityYamlMigration:
    async def test_migration_keycloak_bundled(self, mock_db):
        """Should migrate a bundled Keycloak config from YAML."""
        yaml_data = {
            "provider_type": "keycloak_bundled",
            "oidc_provider_url": "http://localhost:8080/realms/parthenon",
            "client_id": "parthenon-api",
            "client_secret": "some-secret",
            "realm_name": "parthenon",
            "setup_complete": True,
        }
        yaml_path = _write_temp_yaml(yaml_data)
        try:
            migration = IdentityYamlMigration(yaml_path=yaml_path)

            # Mock that no user provider exists in DB
            mock_db.execute = AsyncMock(return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=None)
            ))

            with patch("app.services.identity_yaml_migration.OIDCConfigService") as mock_service_cls:
                mock_service = MagicMock()
                mock_service.create_provider = AsyncMock(return_value=MagicMock())
                mock_service_cls.return_value = mock_service

                result = await migration.run(mock_db)
                assert result is True
                mock_service.create_provider.assert_called_once()
                # Verify the call uses the new provider_type
                call_args = mock_service.create_provider.call_args
                assert call_args.kwargs["provider_type"] == "keycloak"
        finally:
            os.unlink(yaml_path)

    async def test_skip_when_db_has_config(self, mock_db):
        """Should skip migration when DB already has a user provider."""
        yaml_path = _write_temp_yaml({"provider_type": "keycloak", "oidc_provider_url": "http://example.com"})
        try:
            migration = IdentityYamlMigration(yaml_path=yaml_path)

            # Mock that user provider exists
            mock_db.execute = AsyncMock(return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=MagicMock())
            ))

            result = await migration.run(mock_db)
            assert result is False  # skipped
        finally:
            os.unlink(yaml_path)

    async def test_skip_when_yaml_not_found(self, mock_db):
        """Should skip when YAML file doesn't exist."""
        migration = IdentityYamlMigration(yaml_path=Path("/nonexistent/path.yaml"))
        result = await migration.run(mock_db)
        assert result is False

    async def test_malformed_yaml_handled(self, mock_db):
        """Should handle malformed YAML gracefully."""
        yaml_path = _write_temp_yaml("not a dict: just a string")  # type: ignore[arg-type]
        try:
            migration = IdentityYamlMigration(yaml_path=yaml_path)

            mock_db.execute = AsyncMock(return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=None)
            ))

            result = await migration.run(mock_db)
            # Should not crash — returns False or handles the error
            assert result is False
        finally:
            os.unlink(yaml_path)

    async def test_missing_key_fields(self, mock_db):
        """Should skip when YAML is missing key fields."""
        yaml_data = {
            # Missing oidc_provider_url
            "provider_type": "keycloak",
        }
        yaml_path = _write_temp_yaml(yaml_data)
        try:
            migration = IdentityYamlMigration(yaml_path=yaml_path)

            mock_db.execute = AsyncMock(return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=None)
            ))

            result = await migration.run(mock_db)
            assert result is False
        finally:
            os.unlink(yaml_path)
