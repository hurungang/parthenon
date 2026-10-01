"""Platform Account Auth Service — password credentials + platform JWTs.

Self-serve (Phase 10) accounts are PLATFORM-issued: email + password
stored on ``PlatformUser`` (deliberately outside the per-tenant OIDC
registry), authenticating against Control Center itself.

- Passwords are hashed with **bcrypt** — the exact scheme used for the
  super admin credential (``super_admin_auth_service``), so no second
  hashing scheme enters the codebase.
- Sign-in issues an HS256 platform JWT (same signing key as the super
  admin token, ``settings.secret_key``) bound to the user's owned
  tenant: the ``tenant`` claim (slug) makes the token pass the existing
  tenant-claim middleware check, and the ``platform_account`` marker
  routes validation through the platform-account tier of
  ``validate_raw_token`` (never through per-tenant OIDC providers).
"""
from __future__ import annotations

import logging
import re
import time
import uuid

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.platform_user import PlatformUser
from app.db.models.tenant import Tenant

logger = logging.getLogger(__name__)

#: Lifetime of a platform-account session token (8 hours).
PLATFORM_ACCOUNT_TOKEN_EXPIRY_SECONDS = 8 * 60 * 60

#: Claim marking a token as a platform-issued account token.
PLATFORM_ACCOUNT_CLAIM = "platform_account"

#: Platform-issued subject prefix (never collides with OIDC `sub` values).
PLATFORM_ACCOUNT_SUB_PREFIX = "platform_account:"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PlatformAccountAuthError(Exception):
    """Raised when platform-account authentication fails (generic)."""


def normalize_email(email: str) -> str:
    """Trim + lowercase an email address (uniqueness canonical form)."""
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(normalize_email(email)))


def validate_password_rules(password: str) -> str | None:
    """Return a rejection reason for a weak password, or None when OK."""
    if not password or len(password) < 8:
        return "Password must be at least 8 characters long"
    if len(password) > 128:
        return "Password must be at most 128 characters long"
    if not re.search(r"[A-Za-z]", password):
        return "Password must contain at least one letter"
    if not re.search(r"[0-9]", password):
        return "Password must contain at least one digit"
    return None


def hash_password(plaintext: str) -> str:
    """Hash a password with bcrypt (same scheme as the super admin)."""
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    """Constant-time bcrypt verification; False on any malformed hash."""
    try:
        return bcrypt.checkpw(plaintext.encode(), hashed.encode())
    except Exception:
        return False


def new_platform_sub() -> str:
    """A fresh platform-issued subject for a self-serve account."""
    return f"{PLATFORM_ACCOUNT_SUB_PREFIX}{uuid.uuid4()}"


def create_platform_account_token(
    *,
    user: PlatformUser,
    tenant: Tenant,
    tenant_role: str = "tenant_admin",
) -> str:
    """Issue a tenant-bound platform JWT for a platform-issued account.

    Claims follow the existing token conventions: ``tenant`` (slug)
    satisfies the tenant-claim middleware binding; ``platform_account``
    marks the validation tier; ``platform_role`` carries the tenant role
    surfaced through membership.
    """
    now = int(time.time())
    claims = {
        "sub": user.sub,
        "email": user.email,
        "name": user.display_name,
        PLATFORM_ACCOUNT_CLAIM: True,
        "platform_role": tenant_role,
        "tenant": tenant.slug,
        "tenant_id": str(tenant.id),
        "tenant_access": "tenant",
        "iat": now,
        "exp": now + PLATFORM_ACCOUNT_TOKEN_EXPIRY_SECONDS,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, get_settings().secret_key, algorithm="HS256")


def validate_platform_account_token(token: str) -> dict | None:
    """Validate a platform-account JWT; None when it is not one / invalid.

    Signature + claims only (no DB round-trip) — downstream authorization
    re-resolves the PlatformUser row, so a deleted account cannot act
    even with an unexpired token.
    """
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except JWTError as exc:
        logger.debug("Platform account token invalid: %s", exc)
        return None
    if not payload.get(PLATFORM_ACCOUNT_CLAIM):
        return None
    if not payload.get("sub") or not payload.get("tenant"):
        return None
    return payload


async def authenticate_platform_account(
    db: AsyncSession, *, email: str, password: str
) -> tuple[PlatformUser, Tenant, str] | None:
    """Verify email+password; return (user, owned tenant, role) or None.

    The account must own an ACTIVE tenant (root membership) — platform
    password sign-in is the self-serve tenant-owner flow.  Failures are
    GENERIC (no user enumeration): every rejection path returns None.
    """
    normalized = normalize_email(email)
    user = (
        await db.execute(
            select(PlatformUser).where(PlatformUser.email == normalized)
        )
    ).scalar_one_or_none()
    if user is None or not user.password_credential:
        return None
    if not verify_password(password, user.password_credential):
        return None

    from app.db.models.tenant import TenantStatus
    from app.db.models.tenant_membership import (
        TenantUserMembership,
        TenantUserMembershipStatus,
    )

    row = (
        await db.execute(
            select(TenantUserMembership, Tenant)
            .join(Tenant, Tenant.id == TenantUserMembership.tenant_id)
            .where(
                TenantUserMembership.user_id == user.id,
                TenantUserMembership.is_root.is_(True),
                TenantUserMembership.status == TenantUserMembershipStatus.active,
                Tenant.status == TenantStatus.active,
            )
        )
    ).first()
    if row is None:
        return None
    membership, tenant = row
    return user, tenant, membership.tenant_role.value
