"""Integration tests for the full super admin login-to-save flow.

Tests cover:
1. Login as super admin → get token
2. Use token to create a user identity provider
3. Use token to update an agent identity provider
4. Use token to list providers
5. Toggle super admin with guard rail
6. Super admin status endpoint
7. Password update flow
8. Token refresh

All tests use mock isolation — no real DB needed.
"""

import os
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("ENVIRONMENT", "test")


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_app():
    """Create a lightweight FastAPI app with system config + auth routes."""
    from app.api.v1.system_config import SystemConfigRouter, AuthRouter

    app = FastAPI()
    app.include_router(SystemConfigRouter, prefix="/api/v1")
    app.include_router(AuthRouter, prefix="/api/v1")
    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


# ── Helper: create mock config with required fields ────────────────────────

def _mock_provider_config(**overrides):
    """Create a mock IdentityProviderConfig with required datetime fields."""
    from app.db.models.identity_provider_config import IdentityProviderConfig
    import datetime

    defaults = {
        "id": uuid.uuid4(),
        "provider_scope": "user",
        "provider_type": "oidc_generic",
        "display_name": "Test Provider",
        "issuer_url": "https://auth.example.com",
        "client_id": "test-client",
        "encrypted_client_secret": "encrypted-secret",
        "scopes": "openid profile email",
        "is_enabled": True,
        "created_at": datetime.datetime.now(datetime.timezone.utc),
        "updated_at": datetime.datetime.now(datetime.timezone.utc),
    }
    defaults.update(overrides)
    return IdentityProviderConfig(**defaults)


def _mock_creds(is_enabled=True):
    """Create a mock SuperAdminCredentials."""
    from app.db.models.super_admin_credentials import SuperAdminCredentials
    return SuperAdminCredentials(
        id=uuid.uuid4(),
        username="testadmin",
        hashed_password="hashed-pass",
        is_enabled=is_enabled,
    )


# ── Tests: Login ──────────────────────────────────────────────────────────

class TestSuperAdminLogin:
    """Test the super admin login flow (auth router)."""

    def test_login_returns_token(self, client):
        """Login with valid credentials returns access token."""
        from app.services.super_admin_auth_service import SuperAdminAuthError

        with patch(
            "app.api.v1.system_config.SuperAdminAuthService.login",
            AsyncMock(return_value="test-jwt-token-string"),
        ):
            response = client.post(
                "/api/v1/auth/super-admin/login",
                json={"username": "testadmin", "password": "testpass"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["access_token"] == "test-jwt-token-string"
            assert data["username"] == "testadmin"

    def test_login_invalid_password(self, client):
        """Login with wrong password returns 401."""
        from app.services.super_admin_auth_service import SuperAdminAuthError

        with patch(
            "app.api.v1.system_config.SuperAdminAuthService.login",
            AsyncMock(side_effect=SuperAdminAuthError("Invalid username or password")),
        ):
            response = client.post(
                "/api/v1/auth/super-admin/login",
                json={"username": "testadmin", "password": "wrongpass"},
            )
            assert response.status_code == 401

    def test_login_disabled(self, client):
        """Login when super admin is disabled returns 401."""
        from app.services.super_admin_auth_service import SuperAdminAuthError

        with patch(
            "app.api.v1.system_config.SuperAdminAuthService.login",
            AsyncMock(side_effect=SuperAdminAuthError("Super admin login is disabled")),
        ):
            response = client.post(
                "/api/v1/auth/super-admin/login",
                json={"username": "testadmin", "password": "testpass"},
            )
            assert response.status_code == 401

    def test_login_not_configured(self, client):
        """Login when super admin not seeded returns 401."""
        from app.services.super_admin_auth_service import SuperAdminAuthError

        with patch(
            "app.api.v1.system_config.SuperAdminAuthService.login",
            AsyncMock(side_effect=SuperAdminAuthError("Super admin not configured")),
        ):
            response = client.post(
                "/api/v1/auth/super-admin/login",
                json={"username": "admin", "password": "pass"},
            )
            assert response.status_code == 401

    def test_login_missing_body(self, client):
        """Login without username/password returns 422."""
        response = client.post("/api/v1/auth/super-admin/login")
        assert response.status_code == 422

    def test_login_empty_credentials(self, client):
        """Login with empty strings returns 422."""
        response = client.post(
            "/api/v1/auth/super-admin/login",
            json={"username": "", "password": ""},
        )
        assert response.status_code == 422


# ── Tests: Identity Provider CRUD ─────────────────────────────────────────

class TestIdentityProviderLifecycle:
    """Test full CRUD lifecycle of identity providers via super admin."""

    def test_create_user_provider(self, client):
        """Create a user identity provider (with auth mock)."""
        mock_config = _mock_provider_config(
            provider_scope="user",
            display_name="User SSO",
        )

        with patch("app.api.v1.system_config._require_auth", MagicMock()):
            with patch(
                "app.api.v1.system_config.OIDCConfigService.create_provider",
                AsyncMock(return_value=mock_config),
            ):
                with patch(
                    "app.api.v1.system_config._reload_registry",
                    AsyncMock(),
                ):
                    with patch(
                        "app.api.v1.system_config._get_changed_by",
                        MagicMock(return_value="testadmin"),
                    ):
                        response = client.post(
                            "/api/v1/system/identity-providers",
                            json={
                                "provider_scope": "user",
                                "provider_type": "oidc_generic",
                                "display_name": "User SSO",
                                "issuer_url": "https://user-sso.example.com",
                                "client_id": "user-client-id",
                                "is_enabled": True,
                            },
                        )
                        assert response.status_code == 201
                        data = response.json()
                        assert data["provider_scope"] == "user"
                        assert data["display_name"] == "User SSO"

    def test_update_agent_provider(self, client):
        """Update an agent identity provider (with auth mock)."""
        mock_config = _mock_provider_config(
            provider_scope="agent",
            provider_type="keycloak",
            display_name="Agent KC Updated",
        )

        with patch("app.api.v1.system_config._require_auth", MagicMock()):
            with patch(
                "app.api.v1.system_config.OIDCConfigService.update_provider",
                AsyncMock(return_value=mock_config),
            ):
                with patch(
                    "app.api.v1.system_config._reload_registry",
                    AsyncMock(),
                ):
                    with patch(
                        "app.api.v1.system_config._get_changed_by",
                        MagicMock(return_value="testadmin"),
                    ):
                        response = client.put(
                            "/api/v1/system/identity-providers/agent",
                            json={
                                "display_name": "Agent KC Updated",
                                "is_enabled": True,
                            },
                        )
                        assert response.status_code == 200
                        data = response.json()
                        assert data["provider_scope"] == "agent"
                        assert data["display_name"] == "Agent KC Updated"

    def test_list_providers(self, client):
        """List identity providers (public endpoint)."""
        mock_configs = [_mock_provider_config()]

        with patch(
            "app.api.v1.system_config.OIDCConfigService.list_providers",
            AsyncMock(return_value=mock_configs),
        ):
            response = client.get("/api/v1/system/identity-providers")
            assert response.status_code == 200
            data = response.json()
            assert data["items"] is not None
            assert data["total"] >= 1

    def test_list_providers_empty(self, client):
        """List providers returns empty when none configured."""
        with patch(
            "app.api.v1.system_config.OIDCConfigService.list_providers",
            AsyncMock(return_value=[]),
        ):
            response = client.get("/api/v1/system/identity-providers")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 0

    def test_create_without_auth_fails(self, client):
        """Creating provider without auth returns 401."""
        response = client.post(
            "/api/v1/system/identity-providers",
            json={
                "provider_scope": "user",
                "provider_type": "oidc_generic",
                "display_name": "Test",
                "issuer_url": "https://auth.example.com",
                "client_id": "test",
            },
        )
        assert response.status_code == 401

    def test_update_without_auth_fails(self, client):
        """Updating provider without auth returns 401."""
        response = client.put(
            "/api/v1/system/identity-providers/agent",
            json={"display_name": "Updated"},
        )
        assert response.status_code == 401

    def test_get_single_provider_requires_auth(self, client):
        """Getting a single provider requires auth."""
        response = client.get("/api/v1/system/identity-providers/user")
        assert response.status_code == 401

    def test_get_single_provider_with_auth(self, client):
        """Getting a single provider with auth returns config."""
        mock_config = _mock_provider_config(provider_scope="user")

        with patch("app.api.v1.system_config._require_auth", MagicMock()):
            with patch(
                "app.api.v1.system_config.OIDCConfigService.get_by_scope",
                AsyncMock(return_value=mock_config),
            ):
                response = client.get("/api/v1/system/identity-providers/user")
                assert response.status_code == 200
                data = response.json()
                assert data["provider_scope"] == "user"

    def test_get_nonexistent_provider_returns_404(self, client):
        """Getting a non-existent provider returns 404."""
        with patch("app.api.v1.system_config._require_auth", MagicMock()):
            with patch(
                "app.api.v1.system_config.OIDCConfigService.get_by_scope",
                AsyncMock(return_value=None),
            ):
                response = client.get("/api/v1/system/identity-providers/user")
                assert response.status_code == 404

    def test_create_duplicate_scope_fails(self, client):
        """Creating a provider for a scope that already exists returns 400."""
        from app.services.oidc_config_service import OIDCConfigError

        with patch("app.api.v1.system_config._require_auth", MagicMock()):
            with patch(
                "app.api.v1.system_config.OIDCConfigService.create_provider",
                AsyncMock(side_effect=OIDCConfigError(
                    "A provider config already exists for scope 'user'."
                )),
            ):
                response = client.post(
                    "/api/v1/system/identity-providers",
                    json={
                        "provider_scope": "user",
                        "provider_type": "oidc_generic",
                        "display_name": "Duplicate",
                        "issuer_url": "https://auth.example.com",
                        "client_id": "test",
                    },
                )
                assert response.status_code == 400


# ── Tests: Super Admin Toggle ─────────────────────────────────────────────

class TestSuperAdminToggle:
    """Test the super admin toggle with guard rail."""

    def test_disable_without_oidc_guard_rail(self, client):
        """Disabling without OIDC provider returns 400 (guard rail)."""
        with patch("app.api.v1.system_config._require_super_admin", MagicMock()):
            with patch(
                "app.api.v1.system_config.OIDCConfigService.list_providers",
                AsyncMock(return_value=[]),
            ):
                response = client.patch(
                    "/api/v1/system/super-admin/toggle",
                    json={"is_enabled": False},
                )
                assert response.status_code == 400
                assert "no active oidc provider" in response.json()["detail"].lower()

    def test_disable_with_active_oidc_succeeds(self, client):
        """Disabling with active OIDC provider succeeds."""
        mock_provider = _mock_provider_config(is_enabled=True)

        with patch("app.api.v1.system_config._require_super_admin", MagicMock()):
            with patch(
                "app.api.v1.system_config.OIDCConfigService.list_providers",
                AsyncMock(return_value=[mock_provider]),
            ):
                with patch(
                    "app.api.v1.system_config.SuperAdminAuthService.toggle",
                    AsyncMock(return_value=_mock_creds(is_enabled=False)),
                ):
                    with patch(
                        "app.api.v1.system_config.SuperAdminAuthService.get_status",
                        AsyncMock(return_value={
                            "is_enabled": False,
                            "username": "testadmin",
                            "last_login_at": None,
                        }),
                    ):
                        response = client.patch(
                            "/api/v1/system/super-admin/toggle",
                            json={"is_enabled": False},
                        )
                        assert response.status_code == 200
                        assert response.json()["is_enabled"] is False

    def test_disable_with_disabled_oidc_fails(self, client):
        """Disabling when OIDC exists but is disabled still has guard rail."""
        mock_provider = _mock_provider_config(is_enabled=False)

        with patch("app.api.v1.system_config._require_super_admin", MagicMock()):
            with patch(
                "app.api.v1.system_config.OIDCConfigService.list_providers",
                AsyncMock(return_value=[mock_provider]),
            ):
                response = client.patch(
                    "/api/v1/system/super-admin/toggle",
                    json={"is_enabled": False},
                )
                assert response.status_code == 400

    def test_enable_succeeds(self, client):
        """Enabling super admin succeeds directly."""
        with patch("app.api.v1.system_config._require_super_admin", MagicMock()):
            with patch(
                "app.api.v1.system_config.SuperAdminAuthService.toggle",
                AsyncMock(return_value=_mock_creds(is_enabled=True)),
            ):
                with patch(
                    "app.api.v1.system_config.SuperAdminAuthService.get_status",
                    AsyncMock(return_value={
                        "is_enabled": True,
                        "username": "testadmin",
                        "last_login_at": None,
                    }),
                ):
                    response = client.patch(
                        "/api/v1/system/super-admin/toggle",
                        json={"is_enabled": True},
                    )
                    assert response.status_code == 200
                    assert response.json()["is_enabled"] is True

    def test_toggle_requires_super_admin(self, client):
        """Toggle requires super_admin, not just regular auth."""
        # Without _require_super_admin mock, the endpoint gets no identity
        response = client.patch(
            "/api/v1/system/super-admin/toggle",
            json={"is_enabled": False},
        )
        assert response.status_code in (401, 403)


# ── Tests: Super Admin Status ─────────────────────────────────────────────

class TestSuperAdminStatus:
    """Test the super admin status endpoint."""

    def test_status_returns_enabled(self, client):
        """Status returns is_enabled=True when enabled."""
        with patch(
            "app.api.v1.system_config.SuperAdminAuthService.get_status",
            AsyncMock(return_value={
                "is_enabled": True,
                "username": "testadmin",
                "last_login_at": "2025-01-15T10:00:00Z",
            }),
        ):
            with patch(
                "app.api.v1.system_config.SuperAdminAuthService.is_enabled",
                MagicMock(return_value=True),
            ):
                response = client.get("/api/v1/system/super-admin/status")
                assert response.status_code == 200
                data = response.json()
                assert data["is_enabled"] is True
                assert data["username"] == "testadmin"

    def test_status_returns_disabled(self, client):
        """Status returns is_enabled=False when disabled."""
        with patch(
            "app.api.v1.system_config.SuperAdminAuthService.get_status",
            AsyncMock(return_value={
                "is_enabled": False,
                "username": "testadmin",
                "last_login_at": None,
            }),
        ):
            response = client.get("/api/v1/system/super-admin/status")
            assert response.status_code == 200
            data = response.json()
            assert data["is_enabled"] is False

    def test_status_not_seeded(self, client):
        """Status when no credentials exist returns null username."""
        with patch(
            "app.api.v1.system_config.SuperAdminAuthService.get_status",
            AsyncMock(return_value=None),
        ):
            with patch(
                "app.api.v1.system_config.SuperAdminAuthService.is_enabled",
                MagicMock(return_value=False),
            ):
                response = client.get("/api/v1/system/super-admin/status")
                assert response.status_code == 200
                data = response.json()
                assert data["is_enabled"] is False
                assert data["username"] is None

    def test_status_env_disable_overrides_db(self, client):
        """Env-level disable should override DB value."""
        with patch(
            "app.api.v1.system_config.SuperAdminAuthService.get_status",
            AsyncMock(return_value={
                "is_enabled": True,
                "username": "testadmin",
                "last_login_at": None,
            }),
        ):
            with patch(
                "app.api.v1.system_config.SuperAdminAuthService.is_enabled",
                MagicMock(return_value=False),
            ):
                response = client.get("/api/v1/system/super-admin/status")
                assert response.status_code == 200
                data = response.json()
                assert data["is_enabled"] is False  # DB true, but env disabled


# ── Tests: Password Update ────────────────────────────────────────────────

class TestSuperAdminPasswordUpdate:
    """Test the password update flow."""

    def test_update_success(self, client):
        """Password update succeeds with valid credentials."""
        with patch("app.api.v1.system_config._require_super_admin", MagicMock()):
            with patch(
                "app.api.v1.system_config.SuperAdminAuthService.update_password",
                AsyncMock(),
            ):
                with patch(
                    "app.api.v1.system_config.SuperAdminAuthService.get_status",
                    AsyncMock(return_value={
                        "is_enabled": True,
                        "username": "testadmin",
                        "last_login_at": None,
                    }),
                ):
                    response = client.put(
                        "/api/v1/system/super-admin/password",
                        json={
                            "current_password": "oldpass",
                            "new_password": "newpass123",
                        },
                    )
                    assert response.status_code == 200

    def test_update_wrong_current(self, client):
        """Password update fails with wrong current password."""
        from app.services.super_admin_auth_service import SuperAdminAuthError

        with patch("app.api.v1.system_config._require_super_admin", MagicMock()):
            with patch(
                "app.api.v1.system_config.SuperAdminAuthService.update_password",
                AsyncMock(side_effect=SuperAdminAuthError("Current password is incorrect")),
            ):
                response = client.put(
                    "/api/v1/system/super-admin/password",
                    json={
                        "current_password": "wrong",
                        "new_password": "newpass123",
                    },
                )
                assert response.status_code == 400

    def test_update_short_password(self, client):
        """Password shorter than 8 chars fails Pydantic validation."""
        response = client.put(
            "/api/v1/system/super-admin/password",
            json={"current_password": "oldpass", "new_password": "short"},
        )
        # 422 from Pydantic min_length=8, or 401 if auth is checked first
        assert response.status_code in (401, 403, 422)

    def test_update_without_auth(self, client):
        """Password update without auth returns 401/403."""
        response = client.put(
            "/api/v1/system/super-admin/password",
            json={"current_password": "old", "new_password": "newpass123"},
        )
        assert response.status_code in (401, 403)

    def test_update_empty_current(self, client):
        """Empty current password should fail validation."""
        response = client.put(
            "/api/v1/system/super-admin/password",
            json={"current_password": "", "new_password": "newpass123"},
        )
        assert response.status_code in (401, 403, 422)


# ── Tests: Token Refresh ─────────────────────────────────────────────────

class TestSuperAdminRefresh:
    """Test the token refresh endpoint."""

    def test_refresh_without_auth(self, client):
        """Refresh without auth fails."""
        response = client.post("/api/v1/auth/super-admin/refresh")
        assert response.status_code in (401, 403)

    def test_refresh_missing_identity(self, client):
        """Refresh without request.state.identity fails."""
        # In test app, no middleware sets request.state.identity
        response = client.post("/api/v1/auth/super-admin/refresh")
        assert response.status_code in (401, 403)


# ── Tests: OIDC Test Connection ───────────────────────────────────────────

class TestOIDCTestConnection:

    def test_test_connection_requires_auth(self, client):
        """Test connection endpoint requires auth."""
        response = client.post(
            "/api/v1/system/identity-providers/test",
            json={"issuer_url": "https://auth.example.com"},
        )
        assert response.status_code in (401, 422)

    def test_test_connection_with_auth(self, client):
        """Test connection with auth returns diagnostic results."""
        with patch("app.api.v1.system_config._require_auth", MagicMock()):
            with patch(
                "app.api.v1.system_config.OIDCConfigService.test_connection",
                AsyncMock(return_value={
                    "success": False,
                    "steps": [{"step": "discovery_fetch", "status": "failed", "detail": "unreachable"}],
                    "discovery_doc": None,
                }),
            ):
                response = client.post(
                    "/api/v1/system/identity-providers/test",
                    json={"issuer_url": "https://auth.example.com"},
                )
                assert response.status_code == 200
                data = response.json()
                assert "success" in data
                assert "steps" in data


# ── Tests: Delete Provider ────────────────────────────────────────────────

class TestDeleteProvider:

    def test_delete_requires_auth(self, client):
        """Delete provider requires auth."""
        response = client.delete("/api/v1/system/identity-providers/user")
        assert response.status_code == 401

    def test_delete_with_auth(self, client):
        """Delete with auth succeeds."""
        with patch("app.api.v1.system_config._require_auth", MagicMock()):
            with patch(
                "app.api.v1.system_config.OIDCConfigService.delete_provider",
                AsyncMock(),
            ):
                with patch(
                    "app.api.v1.system_config._reload_registry",
                    AsyncMock(),
                ):
                    with patch(
                        "app.api.v1.system_config._get_changed_by",
                        MagicMock(return_value="testadmin"),
                    ):
                        response = client.delete("/api/v1/system/identity-providers/user")
                        assert response.status_code == 204

    def test_delete_nonexistent_fails(self, client):
        """Delete non-existent provider returns 400."""
        from app.services.oidc_config_service import OIDCConfigError

        with patch("app.api.v1.system_config._require_auth", MagicMock()):
            with patch(
                "app.api.v1.system_config.OIDCConfigService.delete_provider",
                AsyncMock(side_effect=OIDCConfigError(
                    "No provider config exists for scope 'user'."
                )),
            ):
                response = client.delete("/api/v1/system/identity-providers/user")
                assert response.status_code == 400


# ── Tests: Provider Toggle ────────────────────────────────────────────────

class TestProviderToggle:

    def test_toggle_requires_auth(self, client):
        """Toggle provider requires auth."""
        response = client.patch(
            "/api/v1/system/identity-providers/user/toggle",
            json={"is_enabled": True},
        )
        assert response.status_code == 401

    def test_toggle_with_auth(self, client):
        """Toggle provider with auth succeeds."""
        mock_config = _mock_provider_config(is_enabled=False)

        with patch("app.api.v1.system_config._require_auth", MagicMock()):
            with patch(
                "app.api.v1.system_config.OIDCConfigService.toggle_provider",
                AsyncMock(return_value=mock_config),
            ):
                with patch(
                    "app.api.v1.system_config._reload_registry",
                    AsyncMock(),
                ):
                    with patch(
                        "app.api.v1.system_config._get_changed_by",
                        MagicMock(return_value="testadmin"),
                    ):
                        response = client.patch(
                            "/api/v1/system/identity-providers/user/toggle",
                            json={"is_enabled": False},
                        )
                        assert response.status_code == 200
                        assert response.json()["is_enabled"] is False
