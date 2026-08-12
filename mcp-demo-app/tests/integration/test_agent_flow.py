"""Integration tests for end-to-end agent identity flow.

Requires a real Keycloak instance with the ai_agents realm configured.
If Keycloak is not reachable, all tests are skipped automatically.

Flow tested: obtain JWT → POST /mcp tools/call → verify agent_sub in response.
"""
from __future__ import annotations

import os

import httpx
import pytest

# ── Service availability check ────────────────────────────────────────────────

_KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8082")
_KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "ai_agents")
_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "mcp-demo-app-test")
_CLIENT_SECRET = os.environ.get("KEYCLOAK_CLIENT_SECRET", "test-secret")


def _keycloak_reachable() -> bool:
    try:
        with httpx.Client(timeout=3.0) as client:
            client.get(f"{_KEYCLOAK_URL}/realms/{_KEYCLOAK_REALM}")
        return True
    except Exception:
        return False


def _require_keycloak(func):
    """Decorator to skip individual tests when Keycloak is not reachable."""
    return pytest.mark.skipif(
        not _keycloak_reachable(),
        reason="Requires Keycloak",
    )(func)


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _obtain_agent_jwt() -> str:
    """Obtain a real client credentials JWT from Keycloak."""
    token_url = f"{_KEYCLOAK_URL}/realms/{_KEYCLOAK_REALM}/protocol/openid-connect/token"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": _CLIENT_ID,
                "client_secret": _CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()["access_token"]


# ── Tests ─────────────────────────────────────────────────────────────────────


@_require_keycloak
async def test_obtain_agent_jwt_from_keycloak():
    """AC-1: Client credentials grant returns a non-empty JWT."""
    token = await _obtain_agent_jwt()
    assert isinstance(token, str)
    # Sanity check: JWTs have three dot-separated segments
    assert len(token.split(".")) == 3


@_require_keycloak
async def test_tools_call_with_real_jwt_returns_agent_sub():
    """AC-3: End-to-end — real JWT → tools/call → agent_sub present in response.

    The MCP app is exercised via ASGITransport (no network to the app itself),
    but JWT validation uses the real Keycloak JWKS endpoint.
    """
    from unittest.mock import AsyncMock, patch

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    token = await _obtain_agent_jwt()

    # Mock hub registration so the lifespan completes without a running hub
    with patch("app.main.register_with_hub", new=AsyncMock()):
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "helloWorld"},
                },
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 200
    result = response.json()["result"]["result"]
    assert result["message"] == "Hello from MCP Demo App!"
    # agent_sub must be the client_id or the service account sub — never None
    assert result["agent_sub"] is not None


@_require_keycloak
async def test_tools_call_without_jwt_returns_401():
    """Scenario 3.8: tools/call with no auth → 401 even with real Keycloak running."""
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    with patch("app.main.register_with_hub", new=AsyncMock()):
        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "helloWorld"},
                },
            )

    assert response.status_code == 401


@_require_keycloak
async def test_verify_agent_jwt_validates_real_token():
    """AC-1 + AC-3: verify_agent_jwt accepts a real Keycloak-signed JWT."""
    from app.auth import verify_agent_jwt

    token = await _obtain_agent_jwt()
    claims = await verify_agent_jwt(token)
    assert isinstance(claims, dict)
    assert "iss" in claims
    assert _KEYCLOAK_REALM in claims["iss"]


# ── Dual-identity flow (mocked identities) ────────────────────────────────────


async def test_hello_agent_tool_with_role_returns_greeting():
    """Integration: helloAgent with mcp_role demo_agent → greeting."""
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    agent_identity = {"sub": "agent-int", "mcp_role": "demo_agent", "iss": "http://kc/ai"}

    with patch("app.main.register_with_hub", new=AsyncMock()):
        with patch("app.routes.mcp.get_agent_identity", new=AsyncMock(return_value=agent_identity)):
            app = create_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "helloAgent"},
                    },
                    headers={"Authorization": "Bearer fake.jwt"},
                )

    assert response.status_code == 200
    result = response.json()["result"]["result"]
    assert result["message"] == "Hello Agent!"
    assert result["agent_sub"] == "agent-int"


async def test_hello_agent_tool_without_role_returns_access_denied():
    """Integration: helloAgent without mcp_role → access-denied (HTTP 200)."""
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    agent_identity = {"sub": "agent-int", "mcp_role": "other"}

    with patch("app.main.register_with_hub", new=AsyncMock()):
        with patch("app.routes.mcp.get_agent_identity", new=AsyncMock(return_value=agent_identity)):
            app = create_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "helloAgent"},
                    },
                    headers={"Authorization": "Bearer fake.jwt"},
                )

    assert response.status_code == 200
    result = response.json()["result"]["result"]
    assert result["access_denied"] is True


async def test_hello_user_tool_with_role_returns_greeting():
    """Integration: helloUser with mcp_role demo_user → greeting."""
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    user_identity = {"sub": "user-int", "mcp_role": "demo_user", "iss": "http://kc/users"}

    with patch("app.main.register_with_hub", new=AsyncMock()):
        with patch("app.routes.mcp.get_user_identity", new=AsyncMock(return_value=user_identity)):
            app = create_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "helloUser"},
                    },
                    headers={"X-User-Identity": "Bearer fake.user.jwt"},
                )

    assert response.status_code == 200
    result = response.json()["result"]["result"]
    assert result["message"] == "Hello User!"
    assert result["user_sub"] == "user-int"


async def test_hello_user_tool_without_role_returns_access_denied():
    """Integration: helloUser without mcp_role → access-denied (HTTP 200)."""
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    user_identity = {"sub": "user-int", "mcp_role": "wrong"}

    with patch("app.main.register_with_hub", new=AsyncMock()):
        with patch("app.routes.mcp.get_user_identity", new=AsyncMock(return_value=user_identity)):
            app = create_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "helloUser"},
                    },
                    headers={"X-User-Identity": "Bearer fake.user.jwt"},
                )

    assert response.status_code == 200
    result = response.json()["result"]["result"]
    assert result["access_denied"] is True
