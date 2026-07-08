"""Super Admin Auth Service — credential seeding, login, JWT issuance.

Provides a built-in super admin account that works before or independently
of OIDC configuration.  Credentials are seeded from environment variables on
first launch, stored as bcrypt hashes in the database, and validated on each
login attempt.  The super admin can be enabled/disabled dynamically.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import bcrypt
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.super_admin_credentials import SuperAdminCredentials

logger = logging.getLogger(__name__)

# Configurable expiry for super admin JWT (default 15 minutes)
_SUPER_ADMIN_TOKEN_EXPIRY_SECONDS = int(
    os.environ.get("SUPER_ADMIN_TOKEN_EXPIRY_SECONDS", "900")
)

# Env var names used for bootstrap
_ENV_USERNAME = "SUPER_ADMIN_USERNAME"
_ENV_PASSWORD_HASH = "SUPER_ADMIN_PASSWORD_HASH"
_ENV_ENABLED = "PARTHENON_SUPER_ADMIN_ENABLED"


class SuperAdminAuthError(Exception):
    """Raised when super admin authentication fails."""


class SuperAdminAuthService:
    """Handles super admin credential management, login, and JWT issuance."""

    def __init__(self) -> None:
        self._settings = get_settings()

    # ── Bootstrap / seeding ───────────────────────────────────────────────

    async def seed_credentials(self, db: AsyncSession) -> None:
        """Seed super admin credentials from env vars on first launch.

        Idempotent: if credentials already exist in the DB, only updates
        the password hash if the env var is set and has changed.
        """
        username = os.environ.get(_ENV_USERNAME, "").strip()
        password_hash = os.environ.get(_ENV_PASSWORD_HASH, "").strip()

        if not username:
            logger.info("SuperAdminAuth: %s not set; super admin will not be seeded.", _ENV_USERNAME)
            return

        existing = await self._get_credentials(db)

        if existing is None:
            # Create new credentials row
            hashed = password_hash if password_hash else _hash_plaintext("admin")
            creds = SuperAdminCredentials(
                id=uuid.uuid4(),
                username=username,
                hashed_password=hashed,
                is_enabled=True,
            )
            db.add(creds)
            await db.flush()
            logger.info(
                "SuperAdminAuth: seeded super admin user='%s'", username,
            )
        elif password_hash and password_hash != existing.hashed_password:
            # Update password hash from env var
            existing.hashed_password = password_hash
            existing.updated_at = datetime.now(timezone.utc)
            await db.flush()
            logger.info(
                "SuperAdminAuth: updated super admin password hash from env var",
            )

    # ── Login ─────────────────────────────────────────────────────────────

    async def login(
        self, db: AsyncSession, username: str, password: str
    ) -> str:
        """Validate credentials and return a short-lived JWT.

        Returns:
            A signed JWT string valid for :data:`_SUPER_ADMIN_TOKEN_EXPIRY_SECONDS`.

        Raises:
            SuperAdminAuthError: If credentials are invalid or super admin is disabled.
        """
        creds = await self._get_credentials(db)
        if creds is None:
            logger.warning("SuperAdminAuth: login attempt but no credentials seeded")
            raise SuperAdminAuthError("Super admin not configured")

        if not creds.is_enabled:
            logger.warning("SuperAdminAuth: login attempt while disabled")
            raise SuperAdminAuthError("Super admin login is disabled")

        if not _verify_password(password, creds.hashed_password):
            logger.warning("SuperAdminAuth: invalid password for user='%s'", username)
            raise SuperAdminAuthError("Invalid username or password")

        if username != creds.username:
            logger.warning(
                "SuperAdminAuth: username mismatch (expected='%s', got='%s')",
                creds.username, username,
            )
            raise SuperAdminAuthError("Invalid username or password")

        # Update last login timestamp
        creds.last_login_at = datetime.now(timezone.utc)
        await db.flush()

        logger.info("SuperAdminAuth: successful login for user='%s'", username)

        # Issue JWT
        token = self._issue_token(creds)
        return token

    def _issue_token(self, creds: SuperAdminCredentials) -> str:
        """Create a short-lived internal JWT for super admin access."""
        now = int(time.time())
        payload = {
            "sub": f"super_admin:{creds.username}",
            "username": creds.username,
            "is_super_admin": True,
            "iat": now,
            "exp": now + _SUPER_ADMIN_TOKEN_EXPIRY_SECONDS,
            "jti": str(uuid.uuid4()),
        }
        secret = self._settings.secret_key
        algorithm = "HS256"  # symmetric — Control Center internal only
        return jwt.encode(payload, secret, algorithm=algorithm)

    # ── Token validation ──────────────────────────────────────────────────

    def validate_token(self, token: str) -> dict:
        """Validate a super admin JWT and return decoded claims.

        Raises:
            SuperAdminAuthError: If the token is invalid or expired.
        """
        try:
            payload = jwt.decode(
                token,
                self._settings.secret_key,
                algorithms=["HS256"],
            )
        except Exception as exc:
            raise SuperAdminAuthError(f"Invalid super admin token: {exc}") from exc

        if not payload.get("is_super_admin"):
            raise SuperAdminAuthError("Token is not a super admin token")

        return payload

    # ── Enable / disable ──────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        """Check if super admin is enabled at the environment level.

        If ``PARTHENON_SUPER_ADMIN_ENABLED`` is explicitly set, it overrides
        the database value.
        """
        env_val = os.environ.get(_ENV_ENABLED, "").strip().lower()
        if env_val in ("true", "1", "yes"):
            return True
        if env_val in ("false", "0", "no"):
            return False
        # Env var not set — caller checks DB
        return True  # signal "not disabled by env"

    async def is_db_enabled(self, db: AsyncSession) -> bool:
        """Check if super admin is enabled in the database."""
        creds = await self._get_credentials(db)
        if creds is None:
            return False
        return creds.is_enabled

    async def toggle(
        self, db: AsyncSession, is_enabled: bool
    ) -> SuperAdminCredentials:
        """Enable or disable the super admin in the database."""
        creds = await self._get_credentials(db)
        if creds is None:
            raise SuperAdminAuthError("Super admin credentials not seeded")
        creds.is_enabled = is_enabled
        creds.updated_at = datetime.now(timezone.utc)
        await db.flush()
        logger.info(
            "SuperAdminAuth: toggled is_enabled=%s for user='%s'",
            is_enabled, creds.username,
        )
        return creds

    # ── Password update ───────────────────────────────────────────────────

    async def update_password(
        self, db: AsyncSession, current_password: str, new_password: str
    ) -> None:
        """Update the super admin password after verifying the current one."""
        creds = await self._get_credentials(db)
        if creds is None:
            raise SuperAdminAuthError("Super admin credentials not seeded")

        if not _verify_password(current_password, creds.hashed_password):
            raise SuperAdminAuthError("Current password is incorrect")

        creds.hashed_password = _hash_plaintext(new_password)
        creds.updated_at = datetime.now(timezone.utc)
        await db.flush()
        logger.info("SuperAdminAuth: password updated for user='%s'", creds.username)

    # ── Status ────────────────────────────────────────────────────────────

    async def get_status(self, db: AsyncSession) -> Optional[dict]:
        """Return public status info (no password)."""
        creds = await self._get_credentials(db)
        if creds is None:
            return None
        return {
            "is_enabled": creds.is_enabled,
            "username": creds.username,
            "last_login_at": (
                creds.last_login_at.isoformat() if creds.last_login_at else None
            ),
        }

    # ── Internal ──────────────────────────────────────────────────────────

    async def _get_credentials(
        self, db: AsyncSession
    ) -> Optional[SuperAdminCredentials]:
        """Return the single super admin credentials row, or ``None``."""
        result = await db.execute(select(SuperAdminCredentials))
        return result.scalar_one_or_none()


# ── Helpers ────────────────────────────────────────────────────────────────


def _hash_plaintext(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")


def _verify_password(plaintext: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(
        plaintext.encode("utf-8"), hashed.encode("utf-8")
    )
