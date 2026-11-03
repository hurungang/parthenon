"""Unit tests for the OAuth/OIDC Bearer-token auth middleware (MCP server).

Covers the fail-closed gate added to the Communication Hub MCP protocol server:

- ``_extract_bearer`` / ``_looks_like_jwt`` token classification (JWTs are
  OAuth tokens; opaque ``phn_sk_*`` API keys fall through to the API-key path);
- a valid OAuth token seeds the request state (``auth_method``, ``user_sub``,
  ``platform_user_id``, ``permissions``, ``tenant_id``) and holds the identity
  token server-side (never attached to the request state);
- invalid / expired / subject-less / unresolvable tokens → 401;
- missing or non-Bearer / non-JWT tokens fall through untouched (the transport
  applies its own 401 via ``is_request_authenticated``).
"""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.responses import Response

from app.communication_hub.middleware.oauth_bearer_auth import (
    OAuthBearerAuthMiddleware,
    _extract_bearer,
    _looks_like_jwt,
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _make_jwt(claims: dict[str, Any], *, alg: str = "RS256") -> str:
    header = _b64url(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    payload = _b64url(json.dumps(claims).encode())
    return f"{header}.{payload}.fake-signature"


def _make_request(path: str, authorization: str | None) -> Any:
    """Minimal stand-in for ``fastapi.Request`` (``url.path`` + case-sensitive headers).

    The middleware reads ``request.headers.get("Authorization")``; use the exact
    capitalisation here to mirror the real Starlette header key.
    """
    req = SimpleNamespace()
    req.url = SimpleNamespace(path=path)
    req.headers = {"Authorization": authorization} if authorization else {}
    req.state = SimpleNamespace()
    return req


def _ok_next():
    async def call_next(req: Any) -> Response:
        return Response(status_code=200)

    return call_next


# ── token classification ────────────────────────────────────────────────────


def test_extract_bearer_returns_token() -> None:
    req = _make_request("/mcp", "Bearer abc.def.ghi")
    assert _extract_bearer(req) == "abc.def.ghi"


def test_extract_bearer_returns_none_without_prefix() -> None:
    assert _extract_bearer(_make_request("/mcp", "abc.def.ghi")) is None


def test_extract_bearer_returns_none_for_empty() -> None:
    assert _extract_bearer(_make_request("/mcp", "Bearer  ")) is None
    assert _extract_bearer(_make_request("/mcp", None)) is None


def test_looks_like_jwt_true_for_jwt() -> None:
    assert _looks_like_jwt(_make_jwt({"sub": "u1"})) is True


def test_looks_like_jwt_false_for_api_key() -> None:
    assert _looks_like_jwt("phn_sk_abcdef123456") is False


def test_looks_like_jwt_false_for_garbage() -> None:
    assert _looks_like_jwt("not-a-jwt") is False


# ── middleware dispatch (fail-closed gate) ──────────────────────────────────


async def test_non_mcp_path_untouched() -> None:
    mw = OAuthBearerAuthMiddleware(app=None)
    called: list[str] = []

    async def call_next(req: Any) -> Response:
        called.append("next")
        return Response(status_code=200)

    response = await mw.dispatch(_make_request("/health", None), call_next)
    assert response.status_code == 200
    assert called == ["next"]


async def test_missing_token_falls_through() -> None:
    mw = OAuthBearerAuthMiddleware(app=None)
    called: list[str] = []

    async def call_next(req: Any) -> Response:
        called.append("next")
        return Response(status_code=200)

    response = await mw.dispatch(_make_request("/mcp", None), call_next)
    assert response.status_code == 200
    assert called == ["next"]


async def test_opaque_api_key_falls_through() -> None:
    mw = OAuthBearerAuthMiddleware(app=None)
    called: list[str] = []

    async def call_next(req: Any) -> Response:
        called.append("next")
        return Response(status_code=200)

    response = await mw.dispatch(
        _make_request("/mcp", "Bearer phn_sk_abcdef123456"), call_next
    )
    assert response.status_code == 200
    assert called == ["next"]


async def test_invalid_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_validate(token: str) -> None:
        return None

    monkeypatch.setattr(
        "app.communication_hub.middleware.oauth_bearer_auth._validate_token",
        _fake_validate,
    )
    mw = OAuthBearerAuthMiddleware(app=None)
    called: list[str] = []

    async def call_next(req: Any) -> Response:
        called.append("next")
        return Response(status_code=200)

    response = await mw.dispatch(
        _make_request("/mcp", f"Bearer {_make_jwt({'sub': 'u1'})}"), call_next
    )
    assert response.status_code == 401
    assert called == []
    body = json.loads(response.body)
    assert body["auth_type"] == "oauth"


async def test_missing_sub_claim_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_validate(token: str) -> dict[str, Any]:
        return {"iss": "x"}  # no sub

    monkeypatch.setattr(
        "app.communication_hub.middleware.oauth_bearer_auth._validate_token",
        _fake_validate,
    )
    mw = OAuthBearerAuthMiddleware(app=None)
    response = await mw.dispatch(
        _make_request("/mcp", f"Bearer {_make_jwt({'sub': 'u1'})}"),
        _ok_next(),
    )
    assert response.status_code == 401
    assert "missing subject" in json.loads(response.body)["detail"]


async def test_unresolvable_user_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_validate(token: str) -> dict[str, Any]:
        return {"sub": "u1"}

    monkeypatch.setattr(
        "app.communication_hub.middleware.oauth_bearer_auth._validate_token",
        _fake_validate,
    )
    mw = OAuthBearerAuthMiddleware(app=None)

    async def _resolve(request: Any, sub: str, tenant: str | None) -> None:
        return None

    monkeypatch.setattr(mw, "_resolve_with_cc", _resolve)
    response = await mw.dispatch(
        _make_request("/mcp", f"Bearer {_make_jwt({'sub': 'u1'})}"),
        _ok_next(),
    )
    assert response.status_code == 401


async def test_valid_token_seeds_state_and_holds_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_validate(token: str) -> dict[str, Any]:
        return {"sub": "user-123", "tenant": "acme"}

    monkeypatch.setattr(
        "app.communication_hub.middleware.oauth_bearer_auth._validate_token",
        _fake_validate,
    )
    mw = OAuthBearerAuthMiddleware(app=None)

    async def _resolve(request: Any, sub: str, tenant: str | None) -> dict[str, Any]:
        assert sub == "user-123"
        assert tenant == "acme"
        return {
            "platform_user_id": "pu-1",
            "tenant_id": "tenant-1",
            "permitted_tools": ["cc____create_skill"],
            "tenant_headers": None,
        }

    monkeypatch.setattr(mw, "_resolve_with_cc", _resolve)
    req = _make_request("/mcp", f"Bearer {_make_jwt({'sub': 'user-123', 'tenant': 'acme'})}")
    called: list[str] = []

    async def call_next(r: Any) -> Response:
        called.append("next")
        return Response(status_code=200)

    response = await mw.dispatch(req, call_next)
    assert response.status_code == 200
    assert called == ["next"]
    assert req.state.auth_method == "oauth"
    assert req.state.user_sub == "user-123"
    assert req.state.platform_user_id == "pu-1"
    assert req.state.permissions == ["cc____create_skill"]
    assert req.state.tenant_id == "tenant-1"
    # Identity token is held server-side only — never seeded onto the request.
    assert not hasattr(req.state, "identity_token")
