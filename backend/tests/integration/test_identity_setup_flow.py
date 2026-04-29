"""Integration tests for the full identity setup API flow.

These tests exercise the real service + DB layer (SQLite in-memory) while
mocking only the external Keycloak HTTP calls via ``respx``.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
import pytest_asyncio
import respx
from httpx import Response
from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models.identity_provider_config import IdentityProviderConfig
from app.db.models.identity_provider_setup_state import IdentityProviderSetupState

# ---------------------------------------------------------------------------
# Cleanup fixture — clear DB tables and reset settings cache before each test
# so a previous developer run (which may have written identity.yaml) doesn't
# pollute the test results.
# ---------------------------------------------------------------------------

_PATCH_RELOAD = (
    "app.services.identity.bootstrap_service.IdentityBootstrapService._reload_oidc_client"
)
_PATCH_YAML = "app.services.identity.bootstrap_service.write_identity_yaml"


@pytest_asyncio.fixture(autouse=True)
async def clean_identity_tables(db_session):
    """Truncate identity setup tables and force-reset cached settings.

    The ``IDENTITY_SETUP_COMPLETE`` env var overrides the on-disk
    ``identity.yaml`` value so tests always start from NOT_CONFIGURED.
    """
    # Override YAML-sourced setting via env var (env vars beat YAML in pydantic-settings)
    old_val = os.environ.get("IDENTITY_SETUP_COMPLETE")
    os.environ["IDENTITY_SETUP_COMPLETE"] = "false"
    get_settings.cache_clear()

    await db_session.execute(delete(IdentityProviderConfig))
    await db_session.execute(delete(IdentityProviderSetupState))
    await db_session.commit()

    yield

    # Restore env state and clear cache so later tests aren't affected
    if old_val is None:
        os.environ.pop("IDENTITY_SETUP_COMPLETE", None)
    else:
        os.environ["IDENTITY_SETUP_COMPLETE"] = old_val
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Shared payloads
# ---------------------------------------------------------------------------

EXTERNAL_OIDC_PAYLOAD = {
    "provider_type": "azure_entraid",
    "oidc_discovery_url": (
        "https://login.microsoftonline.com/tenant/.well-known/openid-configuration"
    ),
    "client_id": "my-client",
    "client_secret": "my-secret",
    "force_reconfigure": False,
}

KEYCLOAK_PAYLOAD = {
    "provider_type": "keycloak_bundled",
    "keycloak_url": "http://keycloak.local:8080",
    "realm_name": "parthenon",
    "client_id": "parthenon-api",
    "admin_user": "admin",
    "admin_password": "admin-password",
    "initial_admin_password": "first-login-password",
    "force_reconfigure": False,
}

# ---------------------------------------------------------------------------
# GET /setup/identity-status — full DB round-trip
# ---------------------------------------------------------------------------


class TestIdentityStatusIntegration:
    """Full DB integration for GET /setup/identity-status."""

    @pytest.mark.asyncio
    async def test_fresh_db_returns_not_configured(self, async_client) -> None:
        """On a fresh DB (no rows), the status must be NOT_CONFIGURED."""
        response = await async_client.get("/api/v1/setup/identity-status")
        assert response.status_code == 200
        data = response.json()
        assert data["setup_state"] == "NOT_CONFIGURED"
        assert data["provider_type"] is None

    @pytest.mark.asyncio
    async def test_after_setup_rows_created_returns_configured(
        self, db_session, async_client
    ) -> None:
        """After inserting setup state + config rows, status must be CONFIGURED."""
        state_row = IdentityProviderSetupState(is_setup_complete=True)
        db_session.add(state_row)
        await db_session.commit()

        config_row = IdentityProviderConfig(
            provider_type="keycloak_bundled",
            oidc_provider_url="http://keycloak.local:8080/realms/parthenon",
            client_id="parthenon-api",
            is_setup_complete=True,
        )
        db_session.add(config_row)
        await db_session.commit()

        response = await async_client.get("/api/v1/setup/identity-status")
        assert response.status_code == 200
        data = response.json()
        assert data["setup_state"] == "CONFIGURED"
        assert data["provider_type"] == "keycloak_bundled"

    @pytest.mark.asyncio
    async def test_status_endpoint_is_public(self, async_client) -> None:
        """Status endpoint must respond 200 without an Authorization header."""
        response = await async_client.get("/api/v1/setup/identity-status")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /setup/identity — external OIDC (no Keycloak HTTP calls needed)
# ---------------------------------------------------------------------------


class TestProvisionExternalOidcIntegration:
    """Integration tests for external OIDC / Azure EntraID provisioning."""

    @pytest.mark.asyncio
    async def test_provision_external_oidc_success(self, async_client) -> None:
        """POST /setup/identity with azure_entraid returns 200 with success=true."""
        discovery_url = (
            "https://login.microsoftonline.com/tenant/.well-known/openid-configuration"
        )
        discovery_doc = {
            "issuer": "https://login.microsoftonline.com/tenant/v2.0",
            "authorization_endpoint": "https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
            "token_endpoint": "https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
            "jwks_uri": "https://login.microsoftonline.com/tenant/discovery/v2.0/keys",
        }
        with (
            respx.mock(assert_all_called=False) as mock_http,
            patch(_PATCH_YAML),
            patch(_PATCH_RELOAD),
        ):
            mock_http.get(discovery_url).mock(
                return_value=Response(200, json=discovery_doc)
            )
            response = await async_client.post(
                "/api/v1/setup/identity", json=EXTERNAL_OIDC_PAYLOAD
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["provider_type"] == "azure_entraid"

    @pytest.mark.asyncio
    async def test_provision_returns_409_when_already_configured(
        self, db_session, async_client
    ) -> None:
        """Returns 409 when DB already has a setup state row and force_reconfigure=False."""
        state_row = IdentityProviderSetupState(is_setup_complete=True)
        db_session.add(state_row)
        await db_session.commit()

        response = await async_client.post(
            "/api/v1/setup/identity", json=EXTERNAL_OIDC_PAYLOAD
        )
        assert response.status_code == 409
        assert "already configured" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_provision_endpoint_is_public(self, async_client) -> None:
        """POST /setup/identity must not require an Authorization header."""
        discovery_url = (
            "https://login.microsoftonline.com/tenant/.well-known/openid-configuration"
        )
        with (
            respx.mock(assert_all_called=False) as mock_http,
            patch(_PATCH_YAML),
            patch(_PATCH_RELOAD),
        ):
            mock_http.get(discovery_url).mock(
                return_value=Response(200, json={"issuer": "https://example.com"})
            )
            response = await async_client.post(
                "/api/v1/setup/identity", json=EXTERNAL_OIDC_PAYLOAD
            )
        assert response.status_code not in (401, 403)


# ---------------------------------------------------------------------------
# POST /setup/identity — bundled Keycloak (mocks httpx calls via respx)
# ---------------------------------------------------------------------------


class TestProvisionBundledKeycloakIntegration:
    """Integration tests for bundled Keycloak provisioning with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_provision_bundled_keycloak_success(self, async_client) -> None:
        """Full flow with mocked Keycloak HTTP responses returns 200 success."""
        with (
            respx.mock(assert_all_called=False) as mock_kc,
            patch(_PATCH_YAML),
            patch(_PATCH_RELOAD),
        ):
            # Health check
            mock_kc.get("http://keycloak.local:8080/health/ready").mock(
                return_value=Response(200, json={"status": "UP"})
            )
            # Admin token
            mock_kc.post(
                "http://keycloak.local:8080/realms/master/protocol/openid-connect/token"
            ).mock(return_value=Response(200, json={"access_token": "test-token"}))
            # realm_exists check (GET returns 404 = doesn't exist)
            mock_kc.get("http://keycloak.local:8080/admin/realms/parthenon").mock(
                return_value=Response(404)
            )
            # Create realm
            mock_kc.post("http://keycloak.local:8080/admin/realms").mock(
                return_value=Response(201)
            )
            # client_exists check for api client
            mock_kc.get(
                "http://keycloak.local:8080/admin/realms/parthenon/clients",
                params={"clientId": "parthenon-api"},
            ).mock(return_value=Response(200, json=[]))
            # Create api client
            mock_kc.post(
                "http://keycloak.local:8080/admin/realms/parthenon/clients"
            ).mock(
                return_value=Response(
                    201,
                    headers={
                        "Location": "http://keycloak.local:8080/admin/realms/parthenon/clients/abc"
                    },
                )
            )
            # Get api client secret
            mock_kc.get(
                "http://keycloak.local:8080/admin/realms/parthenon/clients/abc/client-secret"
            ).mock(return_value=Response(200, json={"value": "generated-secret"}))
            # client_exists check for ui client
            mock_kc.get(
                "http://keycloak.local:8080/admin/realms/parthenon/clients",
                params={"clientId": "parthenon-api-ui"},
            ).mock(return_value=Response(200, json=[]))
            # Create ui client (public, no secret)
            mock_kc.post(
                "http://keycloak.local:8080/admin/realms/parthenon/clients"
            ).mock(return_value=Response(201))
            # Create initial admin user
            mock_kc.post(
                "http://keycloak.local:8080/admin/realms/parthenon/users"
            ).mock(return_value=Response(201))

            response = await async_client.post(
                "/api/v1/setup/identity", json=KEYCLOAK_PAYLOAD
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["provider_type"] == "keycloak_bundled"
        assert data["realm_name"] == "parthenon"

    @pytest.mark.asyncio
    async def test_provision_bundled_keycloak_502_on_connection_error(
        self, async_client
    ) -> None:
        """Returns 502 when Keycloak health check fails with ConnectError."""
        import httpx as _httpx

        with respx.mock(assert_all_called=False) as mock_kc:
            mock_kc.get("http://keycloak.local:8080/health/ready").mock(
                side_effect=_httpx.ConnectError("Connection refused")
            )

            response = await async_client.post(
                "/api/v1/setup/identity", json=KEYCLOAK_PAYLOAD
            )

        assert response.status_code == 502
