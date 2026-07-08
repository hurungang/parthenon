"""Super Admin Auth Service — environment-variable-based credentials.

Reads super admin credentials and enable state from environment variables
at runtime.  No database storage involved — simple and transparent.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from pathlib import Path

import bcrypt
from jose import jwt

logger = logging.getLogger(__name__)

_ENV_USERNAME = "SUPER_ADMIN_USERNAME"
_ENV_PASSWORD = "SUPER_ADMIN_PASSWORD"
_ENV_PASSWORD_HASH = "SUPER_ADMIN_PASSWORD_HASH"
_ENV_ENABLED = "PARTHENON_SUPER_ADMIN_ENABLED"
_DEFAULT_EXPIRY = int(os.environ.get("SUPER_ADMIN_TOKEN_EXPIRY_SECONDS", "900"))


def _read_dotenv(key: str) -> str | None:
    """Read a value from the project .env file as a fallback.

    The .env file at the project root is read on each call so that
    ``--reload`` restarts pick up changed values without a full process
    restart (env vars are frozen at process start on most platforms).
    """
    env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
    if not env_path.exists():
        return None
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", stripped)
            if m and m.group(1).upper() == key.upper():
                val = m.group(2).strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                if val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                return val
    except OSError:
        pass
    return None


def _get_env(key: str) -> str:
    """Read an env var, falling back to the .env file at project root."""
    val = os.environ.get(key, "")
    if val:
        return val
    dotenv_val = _read_dotenv(key)
    return dotenv_val or ""


class SuperAdminAuthError(Exception):
    """Raised when super admin authentication fails."""


def _get_env_bool(name: str) -> bool | None:
    """Return True/False if env var is explicitly set, or None."""
    val = _get_env(name).strip().lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    return None


def _resolve_credentials() -> tuple[str, str] | None:
    """Resolve super admin username and password hash from env vars.

    Returns (username, bcrypt_hash) or None if not configured.
    PASSWORD_HASH takes precedence over plaintext PASSWORD.
    """
    username = _get_env(_ENV_USERNAME).strip()
    if not username:
        return None

    password_hash = _get_env(_ENV_PASSWORD_HASH).strip()
    if password_hash:
        return username, password_hash

    plaintext = _get_env(_ENV_PASSWORD).strip()
    if plaintext:
        return username, bcrypt.hashpw(
            plaintext.encode(), bcrypt.gensalt()
        ).decode()

    # Dev default
    return username, bcrypt.hashpw(
        "admin".encode(), bcrypt.gensalt()
    ).decode()


def _verify_password(plaintext: str, hashed: str) -> bool:
    return bcrypt.checkpw(plaintext.encode(), hashed.encode())


def super_admin_enabled() -> bool:
    """True if the super admin is enabled and credentials are configured."""
    enabled = _get_env_bool(_ENV_ENABLED)
    if enabled is False:
        return False
    return _resolve_credentials() is not None


def is_env_controlled() -> bool:
    """True if PARTHENON_SUPER_ADMIN_ENABLED is explicitly set."""
    return _get_env_bool(_ENV_ENABLED) is not None


def super_admin_username() -> str | None:
    """The configured super admin username, or None."""
    creds = _resolve_credentials()
    return creds[0] if creds else None


def super_admin_reissue(username: str) -> str:
    """Re-issue a JWT for an already-authenticated super admin (no password check)."""
    if username != (super_admin_username() or ""):
        raise SuperAdminAuthError("Username mismatch")
    if not super_admin_enabled():
        raise SuperAdminAuthError("Super admin login is disabled")

    now = int(time.time())
    from app.core.config import get_settings
    secret = get_settings().secret_key
    payload = {
        "sub": f"super_admin:{username}",
        "username": username,
        "is_super_admin": True,
        "iat": now,
        "exp": now + _DEFAULT_EXPIRY,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def super_admin_login(username: str, password: str) -> str:
    """Validate credentials and return a short-lived JWT.

    Raises SuperAdminAuthError on failure.
    """
    creds = _resolve_credentials()
    if creds is None:
        raise SuperAdminAuthError("Super admin not configured")

    env_user, env_hash = creds
    if username != env_user:
        raise SuperAdminAuthError("Invalid username or password")

    if not _verify_password(password, env_hash):
        raise SuperAdminAuthError("Invalid username or password")

    if not super_admin_enabled():
        raise SuperAdminAuthError("Super admin login is disabled")

    now = int(time.time())
    from app.core.config import get_settings
    secret = get_settings().secret_key
    payload = {
        "sub": f"super_admin:{username}",
        "username": username,
        "is_super_admin": True,
        "iat": now,
        "exp": now + _DEFAULT_EXPIRY,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def validate_super_admin_token(token: str) -> dict:
    """Validate a super admin JWT and return decoded claims.

    Raises SuperAdminAuthError if invalid.
    """
    from app.core.config import get_settings
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except Exception as exc:
        raise SuperAdminAuthError(f"Invalid super admin token: {exc}") from exc
    if not payload.get("is_super_admin"):
        raise SuperAdminAuthError("Token is not a super admin token")
    return payload
