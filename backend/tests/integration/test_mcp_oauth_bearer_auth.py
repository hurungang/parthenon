"""Integration test: OAuth/OIDC Bearer-token auth on the MCP protocol server.

Builds a minimal FastAPI app mounting the real ``OAuthBearerAuthMiddleware`` +
the real ``handle_streamable_http`` transport, then exercises the fail-closed
gate end to end:

- a valid OAuth token → session established with the user's identity/permission
  scope (``tools/list`` returns only the permitted management tools);
- missing token → 401 (transport-level ``is_request_authenticated``);
- invalid/expired token → 401 (middleware fail-closed);
- no elevated/service identity — the session binds the user's ``sub`` only.

The OIDC token validator and the CC ``resolve`` round-trip are stubbed; the
middleware + transport + session + catalog code paths run for real.
"""
from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.communication_hub.mcp.protocol_server import McpProtocolServer
from app.communication_hub.mcp.session_manager import McpSessionManager
from app.communication_hub.mcp.streamable_http import handle_streamable_http
from app.communication_hub.middleware.oauth_bearer_auth import OAuthBearerAuthMiddleware

_USER_CLAIMS = {"sub": "user-1", "tenant": "acme"}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _jwt(claims: dict[str, Any]) -> str:
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps(claims).encode())
    return header + "." + payload + ".fake-sig"


#: A well-formed JWT the stub validator accepts.
VALID_TOKEN = _jwt(_USER_CLAIMS)
#: A well-formed JWT the stub validator rejects (simulated expired/invalid).
EXPIRED_TOKEN = _jwt({"sub": "user-1", "exp": 1})


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    from app.communication_hub.middleware import oauth_bearer_auth as mod

    async def _fake_validate(token: str) -> dict[str, Any] | None:
        if token == VALID_TOKEN:
            return dict(_USER_CLAIMS)
        return None

    async def _fake_resolve(
        self: OAuthBearerAuthMiddleware, request: Request, sub: str, tenant: str | None
    ) -> dict[str, Any]:
        return {
            "platform_user_id": "pu-1",
            "user_sub": sub,
            "tenant_id": "tenant-1",
            "permitted_tools": ["cc____create_skill", "cc____list_skills"],
            "tenant_headers": None,
        }

    monkeypatch.setattr(mod, "_validate_token", _fake_validate)
    monkeypatch.setattr(OAuthBearerAuthMiddleware, "_resolve_with_cc", _fake_resolve)

    manager = McpSessionManager()
    server = McpProtocolServer()

    application = FastAPI()
    application.add_middleware(OAuthBearerAuthMiddleware)

    @application.post("/mcp")
    async def mcp(request: Request):
        return await handle_streamable_http(request, manager, server)

    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_valid_token_establishes_oauth_session(client: AsyncClient) -> None:
    response = await client.post(
        "/mcp",
        headers={"Authorization": "Bearer " + VALID_TOKEN},
        json={"id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 200
    assert response.headers.get("mcp-session-id")

    listed = await client.post(
        "/mcp",
        headers={"Authorization": "Bearer " + VALID_TOKEN},
        json={"id": 2, "method": "tools/list"},
    )
    assert listed.status_code == 200
    tools = listed.json()["result"]["tools"]
    names = {t["name"] for t in tools}
    # OAuth catalog = management tools only (no load_skills meta tool).
    assert "cc____create_skill" in names
    assert "cc____list_skills" in names
    assert "load_skills" not in names


async def test_missing_token_returns_401(client: AsyncClient) -> None:
    response = await client.post(
        "/mcp",
        json={"id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 401


async def test_expired_token_returns_401(client: AsyncClient) -> None:
    response = await client.post(
        "/mcp",
        headers={"Authorization": "Bearer " + EXPIRED_TOKEN},
        json={"id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 401
    body = response.json()
    assert body.get("auth_type") == "oauth"


async def test_opaque_api_key_falls_through_to_401(client: AsyncClient) -> None:
    # An opaque API key is not an OAuth token; the OAuth middleware lets it
    # through, and (with no API-key middleware mounted here) the transport 401s.
    response = await client.post(
        "/mcp",
        headers={"Authorization": "Bearer phn_sk_abcdef123456"},
        json={"id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 401


async def test_permission_scope_is_deny_by_default(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A user resolving to NO permitted management tools sees an empty catalog.
    async def _resolve_empty(
        self: OAuthBearerAuthMiddleware, request: Request, sub: str, tenant: str | None
    ) -> dict[str, Any]:
        return {
            "platform_user_id": "pu-2",
            "user_sub": sub,
            "tenant_id": "tenant-1",
            "permitted_tools": [],
            "tenant_headers": None,
        }

    monkeypatch.setattr(OAuthBearerAuthMiddleware, "_resolve_with_cc", _resolve_empty)

    listed = await client.post(
        "/mcp",
        headers={"Authorization": "Bearer " + VALID_TOKEN},
        json={"id": 2, "method": "tools/list"},
    )
    assert listed.status_code == 200
    assert listed.json()["result"]["tools"] == []
