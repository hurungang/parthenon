"""Unit tests for OIDCClient JWT validation."""
import os
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("OIDC_PROVIDER_URL", "http://localhost:8080/realms/parthenon")

from app.core.oidc_client import OIDCClient, OIDCError


class TestOIDCClient:
    """Tests for OIDCClient JWT validation."""

    def _make_client(self) -> OIDCClient:
        client = OIDCClient()
        client.clear_cache()
        return client

    @pytest.mark.asyncio
    async def test_validate_token_raises_on_invalid_jwt_header(self) -> None:
        client = self._make_client()
        with pytest.raises(OIDCError, match="Invalid JWT header"):
            await client.validate_token("not.a.valid.jwt")

    @pytest.mark.asyncio
    async def test_validate_token_raises_when_jwks_fetch_fails(self) -> None:
        client = self._make_client()
        # Create a fake token with a valid header structure
        import base64, json

        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "RS256", "kid": "test-kid"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "user123", "exp": time.time() + 3600}).encode()
        ).rstrip(b"=").decode()
        fake_token = f"{header}.{payload}.fakesig"

        with patch("httpx.AsyncClient.get", side_effect=Exception("network error")):
            with pytest.raises(OIDCError, match="Failed to fetch JWKS"):
                await client.validate_token(fake_token)

    @pytest.mark.asyncio
    async def test_validate_token_raises_on_expired_claims(self) -> None:
        """Test that expired tokens raise OIDCError."""
        client = self._make_client()
        import base64, json

        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "RS256", "kid": "test-kid"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "user123", "exp": time.time() - 1000}).encode()
        ).rstrip(b"=").decode()
        fake_token = f"{header}.{payload}.fakesig"

        # Mock JWKS fetch to return a fake key
        mock_jwks = {"test-kid": {"kty": "RSA", "use": "sig"}}
        mock_decoded = {"sub": "user123", "exp": time.time() - 1000}

        with patch.object(client, "_get_jwks", return_value=mock_jwks):
            with patch("jose.jwt.decode", return_value=mock_decoded):
                with pytest.raises(OIDCError, match="expired"):
                    await client.validate_token(fake_token)

    @pytest.mark.asyncio
    async def test_validate_token_succeeds_with_valid_claims(self) -> None:
        """Test that valid tokens return claims dict."""
        client = self._make_client()
        import base64, json

        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "RS256", "kid": "test-kid"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "user123", "exp": time.time() + 3600}).encode()
        ).rstrip(b"=").decode()
        fake_token = f"{header}.{payload}.fakesig"

        mock_jwks = {"test-kid": {"kty": "RSA", "use": "sig"}}
        valid_claims = {"sub": "user123", "exp": time.time() + 3600}

        with patch.object(client, "_get_jwks", return_value=mock_jwks):
            with patch("jose.jwt.decode", return_value=valid_claims):
                result = await client.validate_token(fake_token)
                assert result["sub"] == "user123"

    def test_clear_cache_resets_jwks(self) -> None:
        """Test that clear_cache empties the JWKS cache."""
        from app.core import oidc_client as oc

        oc._jwks_cache = {"some-kid": {"kty": "RSA"}}
        oc._jwks_cache_expiry = time.monotonic() + 300

        client = self._make_client()
        client.clear_cache()

        assert oc._jwks_cache == {}
        assert oc._jwks_cache_expiry == 0.0
