"""Regression tests: MCP OAuth refresh unrecoverable-failure classification.

When an MCP session's OAuth token refresh fails with an unrecoverable
provider error (e.g. ``400 invalid_grant`` / ``no such refresh token``),
the session must be flagged ``requires_reauth`` with the stored reason —
NOT silently deactivated. Transient failures must not set the flag.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.mcp.oauth_refresh import OAuthRefreshService


def _session(**overrides):
    """A McpSession-shaped object carrying the fields the refresh service reads."""
    s = MagicMock()
    s.id = "00000000-0000-0000-0000-000000000001"
    s.encrypted_credentials = "encrypted-blob"
    s.oauth_refresh_expires_at = datetime.now(tz=timezone.utc) + timedelta(days=30)
    s.oauth_metadata = {
        "token_url": "https://auth.example.com/token",
        "client_id": "client-1",
        "client_secret": "secret-1",
    }
    s.is_active = True
    s.requires_reauth = False
    s.last_refresh_error = None
    s.oauth_expires_at = None
    s.oauth_refresh_expires_at = datetime.now(tz=timezone.utc) + timedelta(days=30)
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _vault():
    vault = MagicMock()
    vault.decrypt.return_value = '{"refresh_token": "rt-1", "access_token": "at-1"}'
    vault.encrypt.return_value = "re-encrypted"
    return vault


class _Resp:
    def __init__(self, status_code: int, text: str, json_body=None):
        self.status_code = status_code
        self.text = text
        self._json = json_body or {}

    def json(self):
        return self._json


@pytest.mark.asyncio
async def test_unrecoverable_refresh_sets_requires_reauth() -> None:
    session = _session()
    db = AsyncMock()

    resp = _Resp(400, '{"error": "invalid_grant", "error_description": "No such refresh token found"}')
    client = MagicMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    client.post = AsyncMock(return_value=resp)

    with patch("app.services.mcp.oauth_refresh.get_vault", return_value=_vault()), patch(
        "app.services.mcp.oauth_refresh.httpx.AsyncClient", return_value=client
    ):
        result = await OAuthRefreshService().refresh_access_token(session, db)

    assert result is False
    assert session.requires_reauth is True
    assert session.last_refresh_error is not None
    assert "No such refresh token" in session.last_refresh_error


@pytest.mark.asyncio
async def test_transient_refresh_does_not_set_requires_reauth() -> None:
    session = _session()
    db = AsyncMock()

    # 400 but NOT an unrecoverable reason (e.g. a plain bad request)
    resp = _Resp(400, '{"error": "temporarily_unavailable"}')
    client = MagicMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    client.post = AsyncMock(return_value=resp)

    with patch("app.services.mcp.oauth_refresh.get_vault", return_value=_vault()), patch(
        "app.services.mcp.oauth_refresh.httpx.AsyncClient", return_value=client
    ):
        result = await OAuthRefreshService().refresh_access_token(session, db)

    assert result is False
    assert session.requires_reauth is False
    assert session.last_refresh_error is None


@pytest.mark.asyncio
async def test_successful_refresh_clears_requires_reauth() -> None:
    session = _session(requires_reauth=True, last_refresh_error="stale reason")
    db = AsyncMock()

    resp = _Resp(
        200,
        "",
        {
            "access_token": "new-at",
            "refresh_token": "new-rt",
            "expires_in": 3600,
        },
    )
    client = MagicMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    client.post = AsyncMock(return_value=resp)

    with patch("app.services.mcp.oauth_refresh.get_vault", return_value=_vault()), patch(
        "app.services.mcp.oauth_refresh.httpx.AsyncClient", return_value=client
    ):
        result = await OAuthRefreshService().refresh_access_token(session, db)

    assert result is True
    assert session.requires_reauth is False
    assert session.last_refresh_error is None
