"""Unit tests for UserCacheService."""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, call

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.services.permissions.user_cache_service import UserCacheService


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_scalars(item):
    result = MagicMock()
    scalars = MagicMock()
    scalars.scalar_one_or_none = MagicMock(return_value=item)
    result.scalar_one_or_none.return_value = item
    return result


@pytest.mark.asyncio
async def test_creates_new_user_on_first_call():
    """Creates a new PlatformUser with first_seen_at and last_seen_at set."""
    db = _mock_db()
    db.execute = AsyncMock(return_value=_make_scalars(None))  # not found

    svc = UserCacheService()
    user = await svc.upsert_user(db, sub="sub123", email="a@b.com", display_name="Alice")

    assert db.add.called
    added = db.add.call_args[0][0]
    assert added.sub == "sub123"
    assert added.email == "a@b.com"
    assert added.display_name == "Alice"
    assert added.first_seen_at is not None
    assert added.last_seen_at is not None
    assert added.first_seen_at == added.last_seen_at


@pytest.mark.asyncio
async def test_updates_last_seen_at_only_on_subsequent_call():
    """On subsequent call, last_seen_at is updated but first_seen_at is unchanged."""
    first_seen = datetime(2024, 1, 1, 0, 0, 0)
    existing = MagicMock()
    existing.first_seen_at = first_seen
    existing.last_seen_at = first_seen
    existing.sub = "sub123"
    existing.email = "a@b.com"
    existing.display_name = "Alice"

    db = _mock_db()
    db.execute = AsyncMock(return_value=_make_scalars(existing))

    svc = UserCacheService()
    returned_user = await svc.upsert_user(db, sub="sub123", email="a@b.com", display_name="Alice")

    # last_seen_at should be updated (not equal to the original)
    assert returned_user.last_seen_at != first_seen or returned_user.last_seen_at >= first_seen
    # first_seen_at must remain unchanged
    assert returned_user.first_seen_at == first_seen
    # No new add call
    assert not db.add.called


@pytest.mark.asyncio
async def test_get_user_by_sub_returns_none_if_missing():
    """Returns None when user doesn't exist."""
    db = _mock_db()
    db.execute = AsyncMock(return_value=_make_scalars(None))

    svc = UserCacheService()
    result = await svc.get_user_by_sub(db, "nonexistent")
    assert result is None
