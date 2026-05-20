"""Unit tests for KeycloakClient, verify_agent_jwt, and get_agent_identity.

Uses a static RSA key pair to generate test JWTs without a live Keycloak
instance. Covers all auth scenarios from the test plan (sections 3.3 & 3.4).
"""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jose import jwt

# ── RSA key-pair fixtures ────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def rsa_private_key():
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )


@pytest.fixture(scope="module")
def rsa_public_key(rsa_private_key):
    return rsa_private_key.public_key()


@pytest.fixture(scope="module")
def jwks(rsa_public_key):
    """Minimal JWKS built from the test RSA public key."""
    from jose.backends import RSAKey

    rsa_key = RSAKey(rsa_public_key, algorithm="RS256")
    public_dict = rsa_key.public_key().to_dict()
    public_dict["kid"] = "test-key-id"
    public_dict["alg"] = "RS256"
    public_dict["use"] = "sig"
    return {"keys": [public_dict]}


# ── JWT helpers ───────────────────────────────────────────────────────────────

_TEST_ISSUER = "http://keycloak:8082/realms/ai_agents"


def _make_token(
    rsa_private_key,
    *,
    sub: str = "agent-123",
    issuer: str = _TEST_ISSUER,
    expired: bool = False,
    extra_claims: dict[str, Any] | None = None,
    include_sub: bool = True,
) -> str:
    now = int(time.time())
    if expired:
        exp = now - 60
        iat = now - 360
    else:
        exp = now + 300
        iat = now

    claims: dict[str, Any] = {
        "iss": issuer,
        "iat": iat,
        "exp": exp,
    }
    if include_sub:
        claims["sub"] = sub
    if extra_claims:
        claims.update(extra_claims)

    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
    )

    private_pem = rsa_private_key.private_bytes(
        Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    )
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": "test-key-id"})


# ── verify_agent_jwt ─────────────────────────────────────────────────────────


async def test_valid_token_returns_claims(rsa_private_key, jwks):
    """Scenario 3.3: valid JWT → decoded claims returned."""
    token = _make_token(rsa_private_key)

    with (
        patch("app.auth.settings") as mock_settings,
        patch("app.auth.keycloak_client") as mock_client,
    ):
        mock_settings.KEYCLOAK_URL = "http://keycloak:8082"
        mock_settings.KEYCLOAK_REALM = "ai_agents"
        mock_client.get_jwks = AsyncMock(return_value=jwks)

        from app.auth import verify_agent_jwt

        claims = await verify_agent_jwt(token)

    assert claims["sub"] == "agent-123"
    assert claims["iss"] == _TEST_ISSUER


async def test_expired_token_raises_401(rsa_private_key, jwks):
    """Scenario 3.3: expired JWT → 401."""
    token = _make_token(rsa_private_key, expired=True)

    with (
        patch("app.auth.settings") as mock_settings,
        patch("app.auth.keycloak_client") as mock_client,
    ):
        mock_settings.KEYCLOAK_URL = "http://keycloak:8082"
        mock_settings.KEYCLOAK_REALM = "ai_agents"
        mock_client.get_jwks = AsyncMock(return_value=jwks)

        from app.auth import verify_agent_jwt

        with pytest.raises(HTTPException) as exc_info:
            await verify_agent_jwt(token)

    assert exc_info.value.status_code == 401


async def test_wrong_issuer_raises_401(rsa_private_key, jwks):
    """Scenario 3.3: mismatched issuer → 401."""
    token = _make_token(rsa_private_key, issuer="http://evil.example.com/realms/hack")

    with (
        patch("app.auth.settings") as mock_settings,
        patch("app.auth.keycloak_client") as mock_client,
    ):
        mock_settings.KEYCLOAK_URL = "http://keycloak:8082"
        mock_settings.KEYCLOAK_REALM = "ai_agents"
        mock_client.get_jwks = AsyncMock(return_value=jwks)

        from app.auth import verify_agent_jwt

        with pytest.raises(HTTPException) as exc_info:
            await verify_agent_jwt(token)

    assert exc_info.value.status_code == 401


async def test_invalid_signature_raises_401(rsa_private_key, jwks):
    """Edge case: JWT signature tampered → 401."""
    token = _make_token(rsa_private_key)
    # Corrupt the signature (last segment)
    parts = token.split(".")
    parts[2] = parts[2][:-4] + "XXXX"
    bad_token = ".".join(parts)

    with (
        patch("app.auth.settings") as mock_settings,
        patch("app.auth.keycloak_client") as mock_client,
    ):
        mock_settings.KEYCLOAK_URL = "http://keycloak:8082"
        mock_settings.KEYCLOAK_REALM = "ai_agents"
        mock_client.get_jwks = AsyncMock(return_value=jwks)

        from app.auth import verify_agent_jwt

        with pytest.raises(HTTPException) as exc_info:
            await verify_agent_jwt(bad_token)

    assert exc_info.value.status_code == 401


# ── KeycloakClient JWKS cache ─────────────────────────────────────────────────


async def test_jwks_cache_used_within_ttl():
    """Scenario 3.4: JWKS fetched recently → cached value returned without HTTP call."""
    from app.auth import KeycloakClient

    client = KeycloakClient()
    client._jwks = {"keys": [{"kid": "cached"}]}
    client._jwks_fetched_at = time.monotonic()  # just fetched

    with patch("app.auth.httpx.AsyncClient") as MockHttpx:
        result = await client.get_jwks()

    # No outbound HTTP call should have been made
    MockHttpx.assert_not_called()
    assert result == {"keys": [{"kid": "cached"}]}


async def test_jwks_cache_refreshed_after_ttl():
    """Scenario 3.4: JWKS older than 10 min → re-fetched from Keycloak."""
    from unittest.mock import MagicMock

    from app.auth import KeycloakClient

    client = KeycloakClient()
    client._jwks = {"keys": [{"kid": "stale"}]}
    client._jwks_fetched_at = time.monotonic() - 700  # 11+ minutes ago — expired

    fresh_jwks = {"keys": [{"kid": "fresh"}]}
    # Response methods are synchronous in httpx — use MagicMock, not AsyncMock
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = fresh_jwks

    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=mock_response)

    with patch("app.auth.httpx.AsyncClient") as MockHttpx:
        MockHttpx.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        MockHttpx.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await client.get_jwks()

    assert result == fresh_jwks
    mock_http.get.assert_called_once()


# ── KeycloakClient token cache ────────────────────────────────────────────────


async def test_token_cache_used_when_still_valid():
    """Scenario 3.5: token not near expiry → cached token returned without HTTP call."""
    from app.auth import KeycloakClient

    client = KeycloakClient()
    client._access_token = "cached-token"
    # Expires well beyond the 30-second buffer
    client._token_expires_at = time.monotonic() + 120

    with patch("app.auth.httpx.AsyncClient") as MockHttpx:
        token = await client.get_own_access_token()

    MockHttpx.assert_not_called()
    assert token == "cached-token"


async def test_token_cache_refreshed_near_expiry():
    """Scenario 3.5: token within ~30 s of expiry → refreshed automatically."""
    from unittest.mock import MagicMock

    from app.auth import KeycloakClient

    client = KeycloakClient()
    client._access_token = "old-token"
    client._token_expires_at = time.monotonic() + 10  # inside the 30 s buffer

    fresh_payload = {"access_token": "new-token", "expires_in": 300}
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = fresh_payload

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_response)

    with patch("app.auth.httpx.AsyncClient") as MockHttpx:
        MockHttpx.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        MockHttpx.return_value.__aexit__ = AsyncMock(return_value=None)
        with patch("app.auth.settings") as mock_settings:
            mock_settings.KEYCLOAK_URL = "http://keycloak:8082"
            mock_settings.KEYCLOAK_REALM = "ai_agents"
            mock_settings.KEYCLOAK_CLIENT_ID = "mcp-demo-app-test"
            mock_settings.KEYCLOAK_CLIENT_SECRET = "test-secret"

            token = await client.get_own_access_token()

    assert token == "new-token"
    mock_http.post.assert_called_once()


async def test_token_cache_refreshed_when_no_token():
    """No cached token → always fetch from Keycloak."""
    from unittest.mock import MagicMock

    from app.auth import KeycloakClient

    client = KeycloakClient()
    # _access_token is None by default

    fresh_payload = {"access_token": "brand-new-token", "expires_in": 300}
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = fresh_payload

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_response)

    with patch("app.auth.httpx.AsyncClient") as MockHttpx:
        MockHttpx.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        MockHttpx.return_value.__aexit__ = AsyncMock(return_value=None)
        with patch("app.auth.settings") as mock_settings:
            mock_settings.KEYCLOAK_URL = "http://keycloak:8082"
            mock_settings.KEYCLOAK_REALM = "ai_agents"
            mock_settings.KEYCLOAK_CLIENT_ID = "mcp-demo-app-test"
            mock_settings.KEYCLOAK_CLIENT_SECRET = "test-secret"

            token = await client.get_own_access_token()

    assert token == "brand-new-token"


# ── get_agent_identity ────────────────────────────────────────────────────────


async def test_get_agent_identity_missing_header():
    """Scenario 3.3: no Authorization header → 401."""
    from unittest.mock import MagicMock

    from app.auth import get_agent_identity

    request = MagicMock()
    request.headers.get.return_value = ""

    with pytest.raises(HTTPException) as exc_info:
        await get_agent_identity(request)

    assert exc_info.value.status_code == 401


async def test_get_agent_identity_malformed_header():
    """Edge case: Authorization header without 'Bearer ' prefix → 401."""
    from unittest.mock import MagicMock

    from app.auth import get_agent_identity

    request = MagicMock()
    request.headers.get.return_value = "Basic abc123"

    with pytest.raises(HTTPException) as exc_info:
        await get_agent_identity(request)

    assert exc_info.value.status_code == 401


async def test_get_agent_identity_valid_bearer(rsa_private_key, jwks):
    """Scenario 3.3: valid Bearer token → decoded claims returned."""
    from unittest.mock import MagicMock

    token = _make_token(rsa_private_key)

    with (
        patch("app.auth.settings") as mock_settings,
        patch("app.auth.keycloak_client") as mock_client,
    ):
        mock_settings.KEYCLOAK_URL = "http://keycloak:8082"
        mock_settings.KEYCLOAK_REALM = "ai_agents"
        mock_client.get_jwks = AsyncMock(return_value=jwks)

        request = MagicMock()
        request.headers.get.return_value = f"Bearer {token}"

        from app.auth import get_agent_identity

        claims = await get_agent_identity(request)

    assert claims["sub"] == "agent-123"
