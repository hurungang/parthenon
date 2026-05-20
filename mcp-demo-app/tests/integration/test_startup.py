"""Integration tests for app startup lifespan.

These tests require a real Keycloak instance to be reachable. If Keycloak is
not available, all tests in this module are skipped automatically.

Skip condition: KEYCLOAK_URL env var points to an unreachable host.
"""
from __future__ import annotations

import os

import httpx
import pytest

# ── Service availability check ────────────────────────────────────────────────

_KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8082")
_KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "ai_agents")
_TOKEN_URL = f"{_KEYCLOAK_URL}/realms/{_KEYCLOAK_REALM}/protocol/openid-connect/token"


def _keycloak_reachable() -> bool:
    try:
        with httpx.Client(timeout=3.0) as client:
            client.get(f"{_KEYCLOAK_URL}/realms/{_KEYCLOAK_REALM}")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _keycloak_reachable(),
    reason=f"Keycloak not reachable at {_KEYCLOAK_URL} — skipping integration tests",
)


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_keycloak_client_credentials_grant():
    """AC-1: App can obtain a client credentials token from Keycloak ai_agents realm."""
    from app.auth import KeycloakClient

    client = KeycloakClient()
    token = await client.get_own_access_token()
    assert isinstance(token, str)
    assert len(token) > 0


async def test_keycloak_jwks_retrieval():
    """AC-1: JWKS endpoint is reachable and returns at least one key."""
    from app.auth import KeycloakClient

    client = KeycloakClient()
    jwks = await client.get_jwks()
    assert "keys" in jwks
    assert len(jwks["keys"]) > 0


async def test_app_lifespan_startup_succeeds():
    """AC-1: Full lifespan startup succeeds when Keycloak + Hub are available.

    Uses a mocked Hub since only Keycloak connectivity is being validated here.
    The Hub registration is mocked to isolate Keycloak startup from Hub startup.
    """
    from unittest.mock import AsyncMock, patch

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    with patch("app.main.register_with_hub", new=AsyncMock()):
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
