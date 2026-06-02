"""Tests for the UserCacheService — PlatformUser and Identity upserts.

Both upserts are idempotent and run on every successful JWT validation
in the auth middleware. They are the source of truth for "does this
OIDC subject have a matching record in our DB?".

The Identity upsert is the recent addition that fixes the
``Identity not found in platform`` 403 on ``request_termination`` for
users who authenticated before the upsert existed.
"""
from __future__ import annotations

import os
import pathlib
import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Make sure ``app.*`` resolves to the backend, not mcp-demo-app's app
BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault(
    "CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault(
    "OIDC_PROVIDER_URL", "http://localhost:8080/realms/parthenon"
)

import pytest

from app.db.models.identity import Identity, IdentityType
from app.db.models.platform_user import PlatformUser
from app.services.permissions.user_cache_service import UserCacheService


def _make_session_with(result_rows: list):
    """Return a mock AsyncSession whose .execute(...) returns the given rows.

    Supports both list-of-tuples (for select(...).fetchall()) and
    scalar_one_or_none (for select(...).scalar_one_or_none()).
    """
    session = AsyncMock()

    async def _execute(stmt):
        # Detect which kind of result the caller wants by inspecting
        # the statement text. Keeps the mock small and explicit.
        text = str(stmt)
        if "platform_users" in text or "PlatformUser" in text:
            return SimpleNamespace(
                scalar_one_or_none=MagicMock(return_value=result_rows[0] if result_rows else None)
            )
        if "identities" in text or "Identity" in text:
            return SimpleNamespace(
                scalar_one_or_none=MagicMock(return_value=result_rows[0] if result_rows else None)
            )
        raise AssertionError(f"Unexpected query in test: {text}")

    session.execute.side_effect = _execute
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_upsert_user_creates_new_record_when_missing():
    session = _make_session_with([])

    svc = UserCacheService()
    user = await svc.upsert_user(
        session, sub="abc-123", email="a@b.com", display_name="Alice"
    )

    assert isinstance(user, PlatformUser)
    assert user.sub == "abc-123"
    assert user.email == "a@b.com"
    assert user.display_name == "Alice"
    assert user.first_seen_at is not None
    assert user.last_seen_at is not None
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_user_refreshes_last_seen_on_existing_record():
    existing = PlatformUser(
        sub="abc-123",
        email="old@b.com",
        display_name="Alice",
        first_seen_at=datetime(2020, 1, 1),
        last_seen_at=datetime(2020, 1, 1),
    )
    session = _make_session_with([existing])

    svc = UserCacheService()
    user = await svc.upsert_user(
        session, sub="abc-123", email="new@b.com", display_name="Alice New"
    )

    assert user is existing
    assert user.email == "new@b.com"
    assert user.display_name == "Alice New"
    assert user.first_seen_at == datetime(2020, 1, 1)
    # last_seen_at must move forward on every auth
    assert user.last_seen_at > datetime(2020, 1, 1)
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_identity_creates_new_record_when_missing():
    """Regression: terminate endpoint previously returned
    ``Identity not found in platform. Please re-authenticate.`` for users
    who authenticated before the Identity upsert existed. The middleware
    must create an Identity row on first encounter of an OIDC subject.
    """
    session = _make_session_with([])

    svc = UserCacheService()
    identity = await svc.upsert_identity(
        session,
        sub="admin-sub",
        display_name="Platform Admin",
        email="admin@example.com",
    )

    assert isinstance(identity, Identity)
    assert identity.subject == "admin-sub"
    assert identity.display_name == "Platform Admin"
    assert identity.email == "admin@example.com"
    assert identity.identity_type == IdentityType.user
    assert identity.is_active is True
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_identity_is_idempotent():
    """Repeated auth by the same subject must NOT raise a unique-constraint
    error and must refresh ``is_active``/``display_name``/``email``.
    """
    existing = Identity(
        subject="admin-sub",
        display_name="Old Name",
        email="old@example.com",
        identity_type=IdentityType.user,
        is_active=False,
    )
    session = _make_session_with([existing])

    svc = UserCacheService()
    identity = await svc.upsert_identity(
        session,
        sub="admin-sub",
        display_name="New Name",
        email="new@example.com",
    )

    assert identity is existing
    assert identity.is_active is True
    assert identity.display_name == "New Name"
    assert identity.email == "new@example.com"
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_identity_falls_back_to_sub_for_display_name():
    """If neither display_name nor email is in the JWT, the Identity
    record should still be created with a sensible fallback so the
    terminate flow never has to second-guess the upsert.
    """
    session = _make_session_with([])

    svc = UserCacheService()
    identity = await svc.upsert_identity(
        session,
        sub="lonely-sub",
        display_name="",
    )

    assert identity.subject == "lonely-sub"
    # Falls back to sub when display_name is empty
    assert identity.display_name == "lonely-sub"
    assert identity.email is None
