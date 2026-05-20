"""Unit tests for JWT validation logic in app/auth.py.

Uses a static RSA key pair to generate test JWTs without a live Keycloak instance.
"""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from fastapi import HTTPException
from jose import jwt

# ── Key-pair fixtures ────────────────────────────────────────────────────────


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
    """Build a minimal JWKS dict from the test public key."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
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
) -> str:
    now = int(time.time())
    if expired:
        exp = now - 60
        iat = now - 360
    else:
        exp = now + 300
        iat = now

    claims: dict[str, Any] = {
        "sub": sub,
        "iss": issuer,
        "iat": iat,
        "exp": exp,
    }
    if extra_claims:
        claims.update(extra_claims)

    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PrivateFormat,
        NoEncryption,
    )

    private_pem = rsa_private_key.private_bytes(
        Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    )
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": "test-key-id"})


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_token_returns_claims(rsa_private_key, jwks):
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


@pytest.mark.asyncio
async def test_expired_token_raises_401(rsa_private_key, jwks):
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


@pytest.mark.asyncio
async def test_wrong_issuer_raises_401(rsa_private_key, jwks):
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


@pytest.mark.asyncio
async def test_malformed_token_raises_401(jwks):
    with (
        patch("app.auth.settings") as mock_settings,
        patch("app.auth.keycloak_client") as mock_client,
    ):
        mock_settings.KEYCLOAK_URL = "http://keycloak:8082"
        mock_settings.KEYCLOAK_REALM = "ai_agents"
        mock_client.get_jwks = AsyncMock(return_value=jwks)

        from app.auth import verify_agent_jwt

        with pytest.raises(HTTPException) as exc_info:
            await verify_agent_jwt("not.a.valid.jwt.token")

    assert exc_info.value.status_code == 401
