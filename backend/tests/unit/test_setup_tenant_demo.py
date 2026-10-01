"""FIX-20260930-235927 — setup `identity --tenant-demo` seeding logic.

Unit tests for the demo tenant realm seeding: realm + public frontend
client + test users, all idempotent.  The Keycloak admin client is
mocked — no live Keycloak is touched.  (Live verification instructions
are in the fix report / setup README, not here.)
"""
from __future__ import annotations

from typing import Any

import pytest

from setup.identity import (
    _TENANT_DEMO_REDIRECT_URIS,
    _seed_demo_tenant_realm,
)


class FakeKeycloakAdminClient:
    """In-memory stand-in for KeycloakAdminClient (records every call)."""

    def __init__(self, *, realm_exists: bool = False,
                 client_exists: bool = False, users: dict[str, str] | None = None):
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._realm_exists = realm_exists
        self._client_exists = client_exists
        self.users: dict[str, str] = dict(users or {})  # username → id

    async def realm_exists(self, token, realm_name: str) -> bool:
        self.calls.append(("realm_exists", (realm_name,)))
        return self._realm_exists

    async def create_realm(self, token, realm_name: str, display_name: str = "") -> None:
        self.calls.append(("create_realm", (realm_name, display_name)))
        self._realm_exists = True

    async def client_exists(self, token, realm_name: str, client_id: str) -> bool:
        self.calls.append(("client_exists", (realm_name, client_id)))
        return self._client_exists

    async def create_oidc_client(self, token, realm_name: str, client_id: str,
                                 redirect_uris=None, web_origins=None, *,
                                 public_client: bool = False):
        self.calls.append((
            "create_oidc_client",
            (realm_name, client_id, tuple(redirect_uris or []), public_client),
        ))
        self._client_exists = True

    async def get_user_by_username(self, token, realm_name: str, username: str):
        self.calls.append(("get_user_by_username", (realm_name, username)))
        return self.users.get(username)

    async def create_user(self, token, realm_name: str, username: str,
                          password: str, roles=None):
        self.calls.append(("create_user", (realm_name, username, password, list(roles or []))))
        self.users[username] = f"id-{username}"


TOKEN = object()


@pytest.mark.asyncio
async def test_seeds_realm_public_client_and_users():
    kc = FakeKeycloakAdminClient()
    report = await _seed_demo_tenant_realm(
        kc, TOKEN, realm="parthenon-acme", ui_client_id="parthenon-api-ui",
        users=[{"username": "acme-admin", "password": "pw1"},
               {"username": "acme-user", "password": "pw2"}],
    )

    created = {(r["step"], r["status"]) for r in report}
    assert ("tenant_demo_realm", "created") in created
    assert ("tenant_demo_client", "created") in created
    assert ("tenant_demo_user", "created") in created

    calls = dict.fromkeys(name for name, _ in kc.calls)
    assert "create_realm" in calls
    client_calls = [args for name, args in kc.calls if name == "create_oidc_client"]
    assert len(client_calls) == 1
    realm, client_id, redirect_uris, public = client_calls[0]
    assert realm == "parthenon-acme"
    assert client_id == "parthenon-api-ui"
    # mirrors the main realm's UI client redirect URIs
    assert set(redirect_uris) == set(_TENANT_DEMO_REDIRECT_URIS)
    assert public is True

    user_creates = [args for name, args in kc.calls if name == "create_user"]
    assert sorted((u[1], u[2]) for u in user_creates) == [
        ("acme-admin", "pw1"), ("acme-user", "pw2"),
    ]


@pytest.mark.asyncio
async def test_idempotent_rerun_skips_existing():
    kc = FakeKeycloakAdminClient(
        realm_exists=True, client_exists=True,
        users={"acme-admin": "id-a", "acme-user": "id-b"},
    )
    report = await _seed_demo_tenant_realm(
        kc, TOKEN, realm="parthenon-acme", ui_client_id="parthenon-api-ui",
        users=[{"username": "acme-admin", "password": "pw1"},
               {"username": "acme-user", "password": "pw2"}],
    )

    assert all(r["status"] == "exists" for r in report), report
    names = [name for name, _ in kc.calls]
    assert "create_realm" not in names
    assert "create_oidc_client" not in names
    assert "create_user" not in names
    # existence was still probed (idempotency checks, not blind creation)
    assert "realm_exists" in names
    assert "client_exists" in names
    assert "get_user_by_username" in names


@pytest.mark.asyncio
async def test_partial_existing_only_creates_missing():
    kc = FakeKeycloakAdminClient(users={"acme-admin": "id-a"})
    report = await _seed_demo_tenant_realm(
        kc, TOKEN, realm="parthenon-acme", ui_client_id="parthenon-api-ui",
        users=[{"username": "acme-admin", "password": "pw1"},
               {"username": "acme-user", "password": "pw2"}],
    )

    statuses = {r["step"]: r["status"] for r in report}
    assert statuses["tenant_demo_realm"] == "created"
    assert statuses["tenant_demo_client"] == "created"
    # only the missing user was created; the existing one is untouched
    user_creates = [args for name, args in kc.calls if name == "create_user"]
    assert [u[1] for u in user_creates] == ["acme-user"]


@pytest.mark.asyncio
async def test_user_creation_failure_is_reported_not_raised():
    class FailingUserClient(FakeKeycloakAdminClient):
        async def create_user(self, token, realm_name, username, password, roles=None):
            from app.services.identity.keycloak_admin_client import KeycloakAdminError
            raise KeycloakAdminError("user_creation_failed", "boom")

    kc = FailingUserClient()
    report = await _seed_demo_tenant_realm(
        kc, TOKEN, realm="parthenon-acme", ui_client_id="parthenon-api-ui",
        users=[{"username": "acme-admin", "password": "pw1"}],
    )

    assert any(
        r["step"] == "tenant_demo_user" and r["status"] == "error" for r in report
    ), report
