"""Unit tests for KeycloakAdminClient."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set required env vars before importing app modules
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.services.identity.keycloak_admin_client import (
    AdminToken,
    KeycloakAdminClient,
    KeycloakAdminError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_URL = "http://keycloak.example.com"
_TOKEN = AdminToken(access_token="test-access-token", token_type="Bearer")


def _make_mock_response(status_code: int, json_data: dict | None = None, text: str = "") -> MagicMock:
    """Create a mock httpx.Response."""
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.headers = {}
    if json_data is not None:
        response.json.return_value = json_data
    return response


def _make_mock_async_client(response: MagicMock) -> MagicMock:
    """Create a mock httpx.AsyncClient that returns *response* for any request call."""
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=response)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return mock_cm


_PATCH_TARGET = "app.services.identity.keycloak_admin_client.httpx.AsyncClient"


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------


class TestAuthenticate:
    """Tests for KeycloakAdminClient.authenticate."""

    @pytest.mark.asyncio
    async def test_returns_admin_token_on_200(self) -> None:
        """authenticate() returns AdminToken on HTTP 200 with valid JSON."""
        json_data = {"access_token": "my-token", "token_type": "Bearer"}
        mock_cm = _make_mock_async_client(_make_mock_response(200, json_data))

        with patch(_PATCH_TARGET, return_value=mock_cm):
            client = KeycloakAdminClient(_BASE_URL)
            token = await client.authenticate("admin", "secret")

        assert token.access_token == "my-token"
        assert token.token_type == "Bearer"

    @pytest.mark.asyncio
    async def test_raises_on_401(self) -> None:
        """authenticate() raises KeycloakAdminError with error_code='auth_failed' on HTTP 401."""
        mock_cm = _make_mock_async_client(_make_mock_response(401, text="Unauthorized"))

        with patch(_PATCH_TARGET, return_value=mock_cm):
            client = KeycloakAdminClient(_BASE_URL)
            with pytest.raises(KeycloakAdminError) as exc_info:
                await client.authenticate("admin", "wrong-password")

        assert exc_info.value.error_code == "auth_failed"


# ---------------------------------------------------------------------------
# realm_exists
# ---------------------------------------------------------------------------


class TestRealmExists:
    """Tests for KeycloakAdminClient.realm_exists."""

    @pytest.mark.asyncio
    async def test_returns_true_on_200(self) -> None:
        """realm_exists() returns True when GET returns 200."""
        mock_cm = _make_mock_async_client(_make_mock_response(200, {}))

        with patch(_PATCH_TARGET, return_value=mock_cm):
            client = KeycloakAdminClient(_BASE_URL)
            exists = await client.realm_exists(_TOKEN, "my-realm")

        assert exists is True

    @pytest.mark.asyncio
    async def test_returns_false_on_404(self) -> None:
        """realm_exists() returns False when GET returns 404."""
        mock_cm = _make_mock_async_client(_make_mock_response(404, text="Not Found"))

        with patch(_PATCH_TARGET, return_value=mock_cm):
            client = KeycloakAdminClient(_BASE_URL)
            exists = await client.realm_exists(_TOKEN, "missing-realm")

        assert exists is False


# ---------------------------------------------------------------------------
# create_realm (idempotency)
# ---------------------------------------------------------------------------


class TestCreateRealm:
    """Tests for KeycloakAdminClient.create_realm."""

    @pytest.mark.asyncio
    async def test_skips_creation_when_realm_already_exists(self) -> None:
        """create_realm() is idempotent: skips POST when realm already exists (GET 200)."""
        # realm_exists → GET 200 (realm exists)
        mock_cm = _make_mock_async_client(_make_mock_response(200, {}))

        with patch(_PATCH_TARGET, return_value=mock_cm) as mock_cls:
            client = KeycloakAdminClient(_BASE_URL)
            await client.create_realm(_TOKEN, "existing-realm")

            # Only one HTTP call should be made (the GET for realm_exists)
            # No POST to create the realm
            mock_inner_client = mock_cm.__aenter__.return_value
            calls = mock_inner_client.request.call_args_list
            assert len(calls) == 1
            assert calls[0].args[0].upper() == "GET"


# ---------------------------------------------------------------------------
# create_oidc_client (idempotency)
# ---------------------------------------------------------------------------


class TestCreateOidcClient:
    """Tests for KeycloakAdminClient.create_oidc_client."""

    @pytest.mark.asyncio
    async def test_skips_creation_when_client_already_exists(self) -> None:
        """create_oidc_client() is idempotent: skips POST when client already exists."""
        # client_exists → GET /clients?clientId=... returns list with matching client
        existing_client = [{"clientId": "parthenon-api", "id": "some-uuid"}]
        mock_cm = _make_mock_async_client(_make_mock_response(200, existing_client))

        with patch(_PATCH_TARGET, return_value=mock_cm):
            client = KeycloakAdminClient(_BASE_URL)
            result = await client.create_oidc_client(_TOKEN, "my-realm", "parthenon-api")

        # Should return None when client already exists
        assert result is None

        # Only one HTTP call should be made (GET for client_exists)
        mock_inner_client = mock_cm.__aenter__.return_value
        calls = mock_inner_client.request.call_args_list
        assert len(calls) == 1
        assert calls[0].args[0].upper() == "GET"


# ---------------------------------------------------------------------------
# create_group_membership_mapper
# ---------------------------------------------------------------------------


class TestCreateGroupMembershipMapper:
    """Tests for KeycloakAdminClient.create_group_membership_mapper."""

    @pytest.mark.asyncio
    async def test_skips_when_mapper_already_exists(self) -> None:
        """create_group_membership_mapper() is idempotent: skips POST when mapper exists."""
        client_uuid = "test-client-uuid"

        def request_side_effect(method: str, url: str, **kwargs: object) -> MagicMock:
            if method == "GET" and "protocol-mappers" in url:
                # Mapper already exists
                return _make_mock_response(
                    200,
                    [{"name": "group_membership", "id": "existing-mapper-id"}],
                )
            # Client lookup
            return _make_mock_response(
                200,
                [{"clientId": "parthenon-api-ui", "id": client_uuid}],
            )

        mock_inner = AsyncMock()
        mock_inner.request = AsyncMock(side_effect=request_side_effect)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_inner)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch(_PATCH_TARGET, return_value=mock_cm):
            client = KeycloakAdminClient(_BASE_URL)
            await client.create_group_membership_mapper(
                _TOKEN, "my-realm", "parthenon-api-ui"
            )

        # Two calls: client lookup + mappers list (no POST)
        calls = mock_inner.request.call_args_list
        assert len(calls) == 2
        assert calls[0].args[0].upper() == "GET"  # client lookup
        assert calls[1].args[0].upper() == "GET"  # mappers list
        # Verify no POST was made
        post_calls = [c for c in calls if c.args[0].upper() == "POST"]
        assert len(post_calls) == 0

    @pytest.mark.asyncio
    async def test_creates_mapper_when_not_exists(self) -> None:
        """create_group_membership_mapper() creates the mapper when it doesn't exist yet."""
        client_uuid = "test-client-uuid"

        def request_side_effect(method: str, url: str, **kwargs: object) -> MagicMock:
            if method == "GET" and "protocol-mappers" in url:
                # No existing mappers
                return _make_mock_response(200, [])
            elif method == "POST" and "protocol-mappers" in url:
                return _make_mock_response(201)
            # Client lookup
            return _make_mock_response(
                200,
                [{"clientId": "parthenon-api-ui", "id": client_uuid}],
            )

        mock_inner = AsyncMock()
        mock_inner.request = AsyncMock(side_effect=request_side_effect)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_inner)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch(_PATCH_TARGET, return_value=mock_cm):
            client = KeycloakAdminClient(_BASE_URL)
            await client.create_group_membership_mapper(
                _TOKEN, "my-realm", "parthenon-api-ui"
            )

        # Three calls: client lookup + mappers list + create
        calls = mock_inner.request.call_args_list
        assert len(calls) == 3
        assert calls[0].args[0].upper() == "GET"  # client lookup
        assert calls[1].args[0].upper() == "GET"  # mappers list
        assert calls[2].args[0].upper() == "POST"  # create mapper

        # Verify correct mapper config in POST payload
        post_call = calls[2]
        post_json = post_call.kwargs.get("json", {})
        assert post_json.get("name") == "group_membership"
        assert post_json.get("protocolMapper") == "oidc-group-membership-mapper"
        assert post_json.get("config", {}).get("claim.name") == "groups"
        assert post_json.get("config", {}).get("full.path") == "false"
        assert post_json.get("config", {}).get("access.token.claim") == "true"

    @pytest.mark.asyncio
    async def test_raises_when_client_not_found(self) -> None:
        """create_group_membership_mapper() raises when client doesn't exist."""
        mock_cm = _make_mock_async_client(_make_mock_response(200, []))

        with patch(_PATCH_TARGET, return_value=mock_cm):
            client = KeycloakAdminClient(_BASE_URL)
            with pytest.raises(KeycloakAdminError) as exc_info:
                await client.create_group_membership_mapper(
                    _TOKEN, "my-realm", "nonexistent-client"
                )

        assert exc_info.value.error_code == "client_not_found"

    @pytest.mark.asyncio
    async def test_raises_on_mapper_creation_failure(self) -> None:
        """create_group_membership_mapper() raises when mapper creation returns non-2xx."""
        client_uuid = "test-client-uuid"

        def request_side_effect(method: str, url: str, **kwargs: object) -> MagicMock:
            if method == "GET" and "protocol-mappers" in url:
                return _make_mock_response(200, [])
            elif method == "POST" and "protocol-mappers" in url:
                return _make_mock_response(500, text="Internal Server Error")
            return _make_mock_response(
                200,
                [{"clientId": "parthenon-api-ui", "id": client_uuid}],
            )

        mock_inner = AsyncMock()
        mock_inner.request = AsyncMock(side_effect=request_side_effect)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_inner)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch(_PATCH_TARGET, return_value=mock_cm):
            client = KeycloakAdminClient(_BASE_URL)
            with pytest.raises(KeycloakAdminError) as exc_info:
                await client.create_group_membership_mapper(
                    _TOKEN, "my-realm", "parthenon-api-ui"
                )

        assert exc_info.value.error_code == "mapper_creation_failed"
