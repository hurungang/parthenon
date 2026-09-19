"""Unit tests for the env-var-based super admin auth service."""

import os
from unittest.mock import patch

import pytest
from jose import jwt as jose_jwt

from app.services.super_admin_auth_service import (
    SuperAdminAuthError,
    super_admin_enabled,
    super_admin_login,
    super_admin_reissue,
    super_admin_username,
    validate_super_admin_token,
)


def _hash(plaintext: str) -> str:
    import bcrypt

    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


@pytest.fixture
def configured_env():
    """Configure a super admin via env vars, overriding any .env fallback."""
    with patch.dict(
        os.environ,
        {
            "SUPER_ADMIN_USERNAME": "admin",
            "SUPER_ADMIN_PASSWORD_HASH": _hash("admin123"),
            "PARTHENON_SUPER_ADMIN_ENABLED": "true",
        },
    ):
        os.environ.pop("SUPER_ADMIN_PASSWORD", None)
        yield


# ── Enabled / username resolution ────────────────────────────────────────────


def test_super_admin_enabled_when_configured(configured_env):
    assert super_admin_enabled() is True


def test_super_admin_disabled_when_flag_false(configured_env):
    with patch.dict(os.environ, {"PARTHENON_SUPER_ADMIN_ENABLED": "false"}):
        assert super_admin_enabled() is False


def test_super_admin_username_resolution(configured_env):
    assert super_admin_username() == "admin"


# ── Login ────────────────────────────────────────────────────────────────────


def test_successful_login_returns_jwt(configured_env):
    token = super_admin_login("admin", "admin123")
    assert token
    payload = validate_super_admin_token(token)
    assert payload["is_super_admin"] is True
    assert payload["username"] == "admin"


def test_invalid_password_raises(configured_env):
    with pytest.raises(SuperAdminAuthError, match="Invalid username or password"):
        super_admin_login("admin", "wrongpass")


def test_login_disabled_raises(configured_env):
    with patch.dict(os.environ, {"PARTHENON_SUPER_ADMIN_ENABLED": "false"}):
        with pytest.raises(SuperAdminAuthError, match="disabled"):
            super_admin_login("admin", "admin123")


def test_login_not_configured_raises():
    with patch(
        "app.services.super_admin_auth_service._resolve_credentials",
        return_value=None,
    ):
        with pytest.raises(SuperAdminAuthError, match="not configured"):
            super_admin_login("admin", "pass")


# ── Token validation ─────────────────────────────────────────────────────────


def test_validate_invalid_token_raises():
    with pytest.raises(SuperAdminAuthError):
        validate_super_admin_token("invalid-token")


def test_validate_non_super_admin_token_raises():
    from app.core.config import get_settings

    token = jose_jwt.encode({"sub": "user"}, get_settings().secret_key, algorithm="HS256")
    with pytest.raises(SuperAdminAuthError):
        validate_super_admin_token(token)


# ── Reissue ──────────────────────────────────────────────────────────────────


def test_reissue_returns_jwt_for_configured_username(configured_env):
    token = super_admin_reissue("admin")
    assert token
    payload = validate_super_admin_token(token)
    assert payload["username"] == "admin"


def test_reissue_raises_for_mismatched_username(configured_env):
    with pytest.raises(SuperAdminAuthError, match="Username mismatch"):
        super_admin_reissue("someone-else")
