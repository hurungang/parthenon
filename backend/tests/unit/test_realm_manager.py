"""Unit tests for RealmManager — agent realm initialization in the OIDC provider.

Adjustment: Agent identities use a separate, configurable realm (e.g. ai_agents)
within the same identity provider as users. RealmManager initializes this realm,
mirroring the user realm setup.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.identity.realm_manager import RealmManager, RealmManagerError


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_settings(
    oidc_provider_url: str = "http://localhost:8082/realms/parthenon",
    identity_provider_type: str = "keycloak_bundled",
    agent_realm_name: str = "ai_agents",
    jwt_audience: str = "parthenon-api",
    keycloak_admin_user: str = "admin",
    keycloak_admin_password: str = "admin",
) -> MagicMock:
    settings = MagicMock()
    settings.oidc_provider_url = oidc_provider_url
    settings.identity_provider_type = identity_provider_type
    settings.agent_realm_name = agent_realm_name
    settings.jwt_audience = jwt_audience
    settings.keycloak_admin_user = keycloak_admin_user
    settings.keycloak_admin_password = keycloak_admin_password
    return settings


# ── External / unconfigured provider — skip gracefully ────────────────────────


@pytest.mark.asyncio
async def test_initialize_agent_realm_skips_for_external_provider():
    manager = RealmManager()
    with patch(
        "app.services.identity.realm_manager.get_settings",
        return_value=_make_settings(identity_provider_type="external"),
    ):
        await manager.initialize_agent_realm(realm_name="ai_agents")


@pytest.mark.asyncio
async def test_initialize_agent_realm_skips_for_unconfigured_provider():
    manager = RealmManager()
    with patch(
        "app.services.identity.realm_manager.get_settings",
        return_value=_make_settings(identity_provider_type="unconfigured"),
    ):
        await manager.initialize_agent_realm(realm_name="ai_agents")


# ── keycloak_bundled — realm name resolution ──────────────────────────────────


@pytest.mark.asyncio
async def test_initialize_uses_explicit_realm_name():
    manager = RealmManager()
    mock_kc = AsyncMock()
    mock_kc.authenticate = AsyncMock(return_value=MagicMock())
    mock_kc.create_realm = AsyncMock()
    mock_kc.create_oidc_client = AsyncMock()
    mock_kc.realm_exists = AsyncMock(return_value=False)

    with (
        patch(
            "app.services.identity.realm_manager.get_settings",
            return_value=_make_settings(agent_realm_name="default-realm"),
        ),
        patch("app.services.identity.realm_manager.KeycloakAdminClient", return_value=mock_kc),
        patch.object(manager, "_apply_token_policies", AsyncMock()),
    ):
        await manager.initialize_agent_realm(realm_name="custom-realm")

    create_realm_calls = mock_kc.create_realm.call_args_list
    assert len(create_realm_calls) == 1
    realm_name_used = create_realm_calls[0].kwargs.get("realm_name") or create_realm_calls[0].args[1]
    assert realm_name_used == "custom-realm"


@pytest.mark.asyncio
async def test_initialize_falls_back_to_settings_realm_name():
    manager = RealmManager()
    mock_kc = AsyncMock()
    mock_kc.authenticate = AsyncMock(return_value=MagicMock())
    mock_kc.create_realm = AsyncMock()
    mock_kc.create_oidc_client = AsyncMock()
    mock_kc.realm_exists = AsyncMock(return_value=False)

    with (
        patch(
            "app.services.identity.realm_manager.get_settings",
            return_value=_make_settings(agent_realm_name="ai_agents"),
        ),
        patch("app.services.identity.realm_manager.KeycloakAdminClient", return_value=mock_kc),
        patch.object(manager, "_apply_token_policies", AsyncMock()),
    ):
        await manager.initialize_agent_realm()

    create_realm_calls = mock_kc.create_realm.call_args_list
    assert len(create_realm_calls) == 1
    realm_name_used = create_realm_calls[0].kwargs.get("realm_name") or create_realm_calls[0].args[1]
    assert realm_name_used == "ai_agents"


@pytest.mark.asyncio
async def test_initialize_falls_back_to_ai_agents_default():
    manager = RealmManager()
    mock_kc = AsyncMock()
    mock_kc.authenticate = AsyncMock(return_value=MagicMock())
    mock_kc.create_realm = AsyncMock()
    mock_kc.create_oidc_client = AsyncMock()
    mock_kc.realm_exists = AsyncMock(return_value=False)

    with (
        patch(
            "app.services.identity.realm_manager.get_settings",
            return_value=_make_settings(agent_realm_name=None),
        ),
        patch("app.services.identity.realm_manager.KeycloakAdminClient", return_value=mock_kc),
        patch.object(manager, "_apply_token_policies", AsyncMock()),
    ):
        await manager.initialize_agent_realm()

    create_realm_calls = mock_kc.create_realm.call_args_list
    realm_name_used = create_realm_calls[0].kwargs.get("realm_name") or create_realm_calls[0].args[1]
    assert realm_name_used == "ai_agents"


# ── keycloak_bundled — error when Keycloak unreachable ────────────────────────


@pytest.mark.asyncio
async def test_initialize_raises_structured_error_when_keycloak_unreachable():
    from app.services.identity.keycloak_admin_client import KeycloakAdminError

    manager = RealmManager()
    mock_kc = AsyncMock()
    mock_kc.authenticate = AsyncMock(
        side_effect=KeycloakAdminError("connection_refused", "Connection refused")
    )

    with (
        patch("app.services.identity.realm_manager.get_settings", return_value=_make_settings()),
        patch("app.services.identity.realm_manager.KeycloakAdminClient", return_value=mock_kc),
    ):
        with pytest.raises(RealmManagerError) as exc_info:
            await manager.initialize_agent_realm(realm_name="ai_agents")

    assert exc_info.value.error_code == "keycloak_auth_failed"


@pytest.mark.asyncio
async def test_initialize_raises_when_realm_creation_fails():
    from app.services.identity.keycloak_admin_client import KeycloakAdminError

    manager = RealmManager()
    mock_kc = AsyncMock()
    mock_kc.authenticate = AsyncMock(return_value=MagicMock())
    mock_kc.create_realm = AsyncMock(side_effect=KeycloakAdminError("realm_conflict", "Realm already exists"))
    mock_kc.realm_exists = AsyncMock(return_value=False)

    with (
        patch("app.services.identity.realm_manager.get_settings", return_value=_make_settings()),
        patch("app.services.identity.realm_manager.KeycloakAdminClient", return_value=mock_kc),
    ):
        with pytest.raises(RealmManagerError) as exc_info:
            await manager.initialize_agent_realm(realm_name="ai_agents")

    assert exc_info.value.error_code == "realm_creation_failed"


# ── realm_exists helper ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_realm_exists_returns_true_when_realm_present():
    manager = RealmManager()
    mock_kc = AsyncMock()
    mock_kc.authenticate = AsyncMock(return_value=MagicMock())
    mock_kc.realm_exists = AsyncMock(return_value=True)

    with (
        patch("app.services.identity.realm_manager.get_settings", return_value=_make_settings()),
        patch("app.services.identity.realm_manager.KeycloakAdminClient", return_value=mock_kc),
    ):
        result = await manager.realm_exists("ai_agents")

    assert result is True


@pytest.mark.asyncio
async def test_realm_exists_returns_false_when_keycloak_unreachable():
    from app.services.identity.keycloak_admin_client import KeycloakAdminError

    manager = RealmManager()
    mock_kc = AsyncMock()
    mock_kc.authenticate = AsyncMock(side_effect=KeycloakAdminError("timeout", "Connection timed out"))

    with (
        patch("app.services.identity.realm_manager.get_settings", return_value=_make_settings()),
        patch("app.services.identity.realm_manager.KeycloakAdminClient", return_value=mock_kc),
    ):
        result = await manager.realm_exists("ai_agents")

    assert result is False
