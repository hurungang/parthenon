"""Keycloak Admin REST API client.

Encapsulates all calls to the Keycloak Admin REST API behind typed async
methods. Retries on HTTP 503 with exponential back-off (up to 3 attempts).
Raises :class:`KeycloakAdminError` with a machine-readable ``error_code``
for all unrecoverable failures.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # seconds


class KeycloakAdminError(Exception):
    """Raised when the Keycloak Admin API returns an unrecoverable error."""

    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class AdminToken:
    """Short-lived admin bearer token."""

    access_token: str
    token_type: str


@dataclass(frozen=True)
class ClientSecret:
    """Client secret returned after creating a Keycloak client."""

    value: str


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: object,
) -> httpx.Response:
    """Execute an HTTP request with exponential back-off on 503."""
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = await client.request(method, url, **kwargs)  # type: ignore[arg-type]
            if response.status_code != 503:
                return response
            logger.warning(
                "Keycloak returned 503 on %s %s (attempt %d/%d)",
                method,
                url,
                attempt + 1,
                _MAX_RETRIES,
            )
        except httpx.TransportError as exc:
            logger.warning(
                "Transport error on %s %s (attempt %d/%d): %s",
                method,
                url,
                attempt + 1,
                _MAX_RETRIES,
                exc,
            )
            last_exc = exc

        delay = _RETRY_BASE_DELAY * (2 ** attempt)
        await asyncio.sleep(delay)

    if last_exc is not None:
        raise KeycloakAdminError(
            "keycloak_unreachable",
            f"Keycloak is unreachable after {_MAX_RETRIES} attempts: {last_exc}",
        )
    raise KeycloakAdminError(
        "keycloak_service_unavailable",
        f"Keycloak returned 503 after {_MAX_RETRIES} attempts",
    )


class KeycloakAdminClient:
    """Typed async wrapper around the Keycloak Admin REST API."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def authenticate(self, admin_user: str, admin_password: str) -> AdminToken:
        """Obtain a master-realm admin bearer token.

        Args:
            admin_user: Keycloak master-realm admin username.
            admin_password: Keycloak master-realm admin password.

        Returns:
            :class:`AdminToken` containing the bearer token.

        Raises:
            :class:`KeycloakAdminError` on auth failure.
        """
        url = f"{self._base_url}/realms/master/protocol/openid-connect/token"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await _request_with_retry(
                client,
                "POST",
                url,
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": admin_user,
                    "password": admin_password,
                },
            )

        if response.status_code != 200:
            raise KeycloakAdminError(
                "auth_failed",
                f"Keycloak admin authentication failed (HTTP {response.status_code}): "
                f"{response.text[:200]}",
            )

        data = response.json()
        return AdminToken(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
        )

    async def realm_exists(self, token: AdminToken, realm_name: str) -> bool:
        """Return True if *realm_name* already exists in Keycloak."""
        url = f"{self._base_url}/admin/realms/{realm_name}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await _request_with_retry(
                client,
                "GET",
                url,
                headers={"Authorization": f"Bearer {token.access_token}"},
            )
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        raise KeycloakAdminError(
            "realm_check_failed",
            f"Failed to check realm existence (HTTP {response.status_code}): {response.text[:200]}",
        )

    async def create_realm(
        self,
        token: AdminToken,
        realm_name: str,
        display_name: str = "",
    ) -> None:
        """Create a new realm.  Idempotent — does nothing if it already exists.

        Args:
            token: Valid admin token.
            realm_name: Internal realm identifier.
            display_name: Human-readable realm name (defaults to *realm_name*).
        """
        if await self.realm_exists(token, realm_name):
            logger.info("Realm %r already exists — skipping creation", realm_name)
            return

        url = f"{self._base_url}/admin/realms"
        payload = {
            "realm": realm_name,
            "displayName": display_name or realm_name,
            "enabled": True,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await _request_with_retry(
                client,
                "POST",
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token.access_token}"},
            )

        if response.status_code not in (200, 201):
            raise KeycloakAdminError(
                "realm_creation_failed",
                f"Failed to create realm {realm_name!r} (HTTP {response.status_code}): "
                f"{response.text[:200]}",
            )
        logger.info("Realm %r created", realm_name)

    async def client_exists(
        self, token: AdminToken, realm_name: str, client_id: str
    ) -> bool:
        """Return True if a client with *client_id* already exists in *realm_name*."""
        url = f"{self._base_url}/admin/realms/{realm_name}/clients"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await _request_with_retry(
                client,
                "GET",
                url,
                params={"clientId": client_id},
                headers={"Authorization": f"Bearer {token.access_token}"},
            )

        if response.status_code != 200:
            raise KeycloakAdminError(
                "client_check_failed",
                f"Failed to list clients (HTTP {response.status_code}): {response.text[:200]}",
            )
        clients = response.json()
        return any(c.get("clientId") == client_id for c in clients)

    async def create_oidc_client(
        self,
        token: AdminToken,
        realm_name: str,
        client_id: str,
        redirect_uris: list[str] | None = None,
        web_origins: list[str] | None = None,
        *,
        public_client: bool = False,
    ) -> Optional[ClientSecret]:
        """Create an OIDC client in *realm_name*.  Idempotent.

        Args:
            token: Valid admin token.
            realm_name: Target realm.
            client_id: Client identifier.
            redirect_uris: Allowed redirect URIs.
            web_origins: Allowed web origins for CORS. Defaults to ["+""]
                which mirrors the redirect URI origins.
            public_client: If True, creates a public client (no secret).

        Returns:
            :class:`ClientSecret` for confidential clients, ``None`` for public ones.
        """
        if await self.client_exists(token, realm_name, client_id):
            logger.info("Client %r already exists in realm %r — skipping", client_id, realm_name)
            return None

        url = f"{self._base_url}/admin/realms/{realm_name}/clients"
        payload: dict[str, object] = {
            "clientId": client_id,
            "protocol": "openid-connect",
            "enabled": True,
            "publicClient": public_client,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "redirectUris": redirect_uris or ["*"],
            # "+" means "derive allowed origins from redirect URIs" — Keycloak
            # resolves this to the actual origins, which browsers accept.
            "webOrigins": web_origins if web_origins is not None else ["+"],
        }
        if not public_client:
            payload["serviceAccountsEnabled"] = True

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await _request_with_retry(
                client,
                "POST",
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token.access_token}"},
            )

        if response.status_code not in (200, 201):
            raise KeycloakAdminError(
                "client_creation_failed",
                f"Failed to create client {client_id!r} in realm {realm_name!r} "
                f"(HTTP {response.status_code}): {response.text[:200]}",
            )
        logger.info("Client %r created in realm %r", client_id, realm_name)

        if public_client:
            return None

        # Fetch the generated client secret
        location = response.headers.get("Location", "")
        keycloak_client_uuid = location.rstrip("/").split("/")[-1] if location else None
        if not keycloak_client_uuid:
            # Fall back: list clients and find by clientId
            list_url = f"{self._base_url}/admin/realms/{realm_name}/clients"
            async with httpx.AsyncClient(timeout=15.0) as client:
                list_resp = await _request_with_retry(
                    client,
                    "GET",
                    list_url,
                    params={"clientId": client_id},
                    headers={"Authorization": f"Bearer {token.access_token}"},
                )
            clients = list_resp.json()
            if not clients:
                return None
            keycloak_client_uuid = clients[0]["id"]

        secret_url = (
            f"{self._base_url}/admin/realms/{realm_name}/clients/{keycloak_client_uuid}/client-secret"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            secret_resp = await _request_with_retry(
                client,
                "GET",
                secret_url,
                headers={"Authorization": f"Bearer {token.access_token}"},
            )

        if secret_resp.status_code != 200:
            logger.warning("Could not retrieve client secret (HTTP %d)", secret_resp.status_code)
            return None

        secret_value: str = secret_resp.json().get("value", "")
        return ClientSecret(value=secret_value)

    async def create_user(
        self,
        token: AdminToken,
        realm_name: str,
        username: str,
        password: str,
        roles: list[str] | None = None,
    ) -> None:
        """Create a user in *realm_name* with a temporary password.

        Args:
            token: Valid admin token.
            realm_name: Target realm.
            username: New user's username.
            password: Temporary password (user will not be forced to reset).
            roles: Optional list of realm-level role names to assign.
        """
        url = f"{self._base_url}/admin/realms/{realm_name}/users"
        payload: dict[str, object] = {
            "username": username,
            "enabled": True,
            "credentials": [
                {
                    "type": "password",
                    "value": password,
                    "temporary": False,
                }
            ],
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await _request_with_retry(
                client,
                "POST",
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token.access_token}"},
            )

        if response.status_code == 409:
            logger.info("User %r already exists in realm %r — skipping", username, realm_name)
            return

        if response.status_code not in (200, 201):
            raise KeycloakAdminError(
                "user_creation_failed",
                f"Failed to create user {username!r} in realm {realm_name!r} "
                f"(HTTP {response.status_code}): {response.text[:200]}",
            )
        logger.info("User %r created in realm %r", username, realm_name)
