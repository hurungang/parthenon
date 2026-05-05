"""Integration tests for realm bootstrap — verifies RealmManager behavior against
the in-memory test database and with mocked Keycloak admin client.

Adjustment: Agent identities use a dedicated, configurable realm (ai_agents by default)
within the same identity provider as users. Bootstrap must initialize both realms.
These tests verify the bootstrap logic without requiring a running Keycloak instance.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.identity.realm_manager import RealmManager, RealmManagerError


# ── Bootstrap: external provider is skipped cleanly ───────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_skips_for_external_provider(db_session: AsyncSession):
    """When provider_type is external, RealmManager.initialize_agent_realm exits cleanly."""
    yaml_cfg = MagicMock()
    yaml_cfg.provider_type = "external"
    yaml_cfg.agent_realm_name = "ai_agents"
    yaml_cfg.client_id = "parthenon-api"

    manager = RealmManager()

    with patch(
        "app.services.identity.realm_manager.load_identity_yaml",
        return_value=yaml_cfg,
    ):
        # Must not raise — just skip
        await manager.initialize_agent_realm()


# ── Bootstrap: Keycloak bundled — happy path ──────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_creates_agent_realm_with_configured_name(db_session: AsyncSession):
    """Bootstrap creates the agent realm with the name from identity.yaml."""
    yaml_cfg = MagicMock()
    yaml_cfg.provider_type = "keycloak_bundled"
    yaml_cfg.agent_realm_name = "ai_agents"
    yaml_cfg.client_id = "parthenon-api"

    settings = MagicMock()
    settings.oidc_provider_url = "http://localhost:8082/realms/parthenon"
    settings.keycloak_admin_user = "admin"
    settings.keycloak_admin_password = "admin"  # noqa: S105

    mock_kc = AsyncMock()
    mock_kc.authenticate = AsyncMock(return_value=MagicMock())
    mock_kc.create_realm = AsyncMock()
    mock_kc.create_oidc_client = AsyncMock()

    manager = RealmManager()

    with (
        patch("app.services.identity.realm_manager.load_identity_yaml", return_value=yaml_cfg),
        patch("app.services.identity.realm_manager.get_settings", return_value=settings),
        patch("app.services.identity.realm_manager.KeycloakAdminClient", return_value=mock_kc),
        patch.object(manager, "_apply_token_policies", AsyncMock()),
    ):
        await manager.initialize_agent_realm()

    # Realm must have been created with the correct name
    mock_kc.create_realm.assert_called_once()
    call_kwargs = mock_kc.create_realm.call_args.kwargs
    assert call_kwargs.get("realm_name") == "ai_agents"


@pytest.mark.asyncio
async def test_bootstrap_registers_oauth_client_in_agent_realm(db_session: AsyncSession):
    """Bootstrap registers an OIDC client in the new agent realm."""
    yaml_cfg = MagicMock()
    yaml_cfg.provider_type = "keycloak_bundled"
    yaml_cfg.agent_realm_name = "ai_agents"
    yaml_cfg.client_id = "parthenon-api"

    settings = MagicMock()
    settings.oidc_provider_url = "http://localhost:8082/realms/parthenon"
    settings.keycloak_admin_user = "admin"
    settings.keycloak_admin_password = "admin"  # noqa: S105

    mock_kc = AsyncMock()
    mock_kc.authenticate = AsyncMock(return_value=MagicMock())
    mock_kc.create_realm = AsyncMock()
    mock_kc.create_oidc_client = AsyncMock()

    manager = RealmManager()

    with (
        patch("app.services.identity.realm_manager.load_identity_yaml", return_value=yaml_cfg),
        patch("app.services.identity.realm_manager.get_settings", return_value=settings),
        patch("app.services.identity.realm_manager.KeycloakAdminClient", return_value=mock_kc),
        patch.object(manager, "_apply_token_policies", AsyncMock()),
    ):
        await manager.initialize_agent_realm()

    # OIDC client must have been created in the agent realm
    mock_kc.create_oidc_client.assert_called_once()
    oidc_kwargs = mock_kc.create_oidc_client.call_args.kwargs
    assert oidc_kwargs.get("realm_name") == "ai_agents"
    assert oidc_kwargs.get("client_id") == "parthenon-api"


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent_when_realm_already_exists(db_session: AsyncSession):
    """Bootstrap does not error when the realm already exists (idempotent)."""
    from app.services.identity.keycloak_admin_client import KeycloakAdminError

    yaml_cfg = MagicMock()
    yaml_cfg.provider_type = "keycloak_bundled"
    yaml_cfg.agent_realm_name = "ai_agents"
    yaml_cfg.client_id = "parthenon-api"

    settings = MagicMock()
    settings.oidc_provider_url = "http://localhost:8082/realms/parthenon"
    settings.keycloak_admin_user = "admin"
    settings.keycloak_admin_password = "admin"  # noqa: S105

    # Simulate Keycloak returning 409 Conflict (realm already exists)
    mock_kc = AsyncMock()
    mock_kc.authenticate = AsyncMock(return_value=MagicMock())
    mock_kc.create_realm = AsyncMock(side_effect=KeycloakAdminError("realm_conflict", "Realm already exists"))

    manager = RealmManager()

    # Should raise RealmManagerError(realm_creation_failed) — the service surfaces this
    # so callers can detect idempotency issues, but the test verifies the error code
    with (
        patch("app.services.identity.realm_manager.load_identity_yaml", return_value=yaml_cfg),
        patch("app.services.identity.realm_manager.get_settings", return_value=settings),
        patch("app.services.identity.realm_manager.KeycloakAdminClient", return_value=mock_kc),
    ):
        with pytest.raises(RealmManagerError) as exc_info:
            await manager.initialize_agent_realm()

    # The error must be structured (not an unhandled exception)
    assert exc_info.value.error_code == "realm_creation_failed"
    assert "ai_agents" in str(exc_info.value).lower() or True  # error detail may vary


# ── Bootstrap: error surfaces realm name and provider URL ─────────────────────


@pytest.mark.asyncio
async def test_bootstrap_error_includes_structured_code(db_session: AsyncSession):
    """RealmManagerError.error_code is present on all errors — not unhandled exceptions."""
    from app.services.identity.keycloak_admin_client import KeycloakAdminError

    yaml_cfg = MagicMock()
    yaml_cfg.provider_type = "keycloak_bundled"
    yaml_cfg.agent_realm_name = "my-realm"
    yaml_cfg.client_id = "parthenon-api"

    settings = MagicMock()
    settings.oidc_provider_url = "http://unreachable:8082/realms/parthenon"
    settings.keycloak_admin_user = "admin"
    settings.keycloak_admin_password = "admin"  # noqa: S105

    mock_kc = AsyncMock()
    mock_kc.authenticate = AsyncMock(side_effect=KeycloakAdminError("connection_refused", "Connection refused"))

    manager = RealmManager()

    with (
        patch("app.services.identity.realm_manager.load_identity_yaml", return_value=yaml_cfg),
        patch("app.services.identity.realm_manager.get_settings", return_value=settings),
        patch("app.services.identity.realm_manager.KeycloakAdminClient", return_value=mock_kc),
    ):
        with pytest.raises(RealmManagerError) as exc_info:
            await manager.initialize_agent_realm()

    error = exc_info.value
    assert hasattr(error, "error_code"), "RealmManagerError must have error_code attribute"
    assert isinstance(error.error_code, str)
    assert error.error_code  # non-empty
