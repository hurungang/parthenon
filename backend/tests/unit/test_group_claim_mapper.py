"""Unit tests for GroupClaimMapper."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.services.permissions.group_claim_mapper import GroupClaimMapper


def _mock_db() -> AsyncMock:
    return AsyncMock()


def _make_scalars(items: list):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    result.scalars.return_value = scalars
    return result


def _make_group(claim_value: str) -> MagicMock:
    g = MagicMock()
    g.id = uuid.uuid4()
    g.idp_claim_value = claim_value
    return g


@pytest.mark.asyncio
async def test_creates_new_membership_when_claim_matches():
    """New UserGroup is created when JWT claim matches group's idp_claim_value."""
    group = _make_group("group-admin")
    user_id = uuid.uuid4()
    db = _mock_db()
    call = [0]

    async def execute_side(q, *a, **kw):
        call[0] += 1
        if call[0] == 1:
            return _make_scalars([group])  # matched groups
        return _make_scalars([])  # existing memberships (none)

    db.execute = execute_side
    db.add = MagicMock()
    db.flush = AsyncMock()

    mapper = GroupClaimMapper()
    newly_assigned = await mapper.map_claims(db, user_id, ["group-admin"])

    assert group.id in newly_assigned
    assert db.add.called


@pytest.mark.asyncio
async def test_idempotent_no_duplicate_on_second_call():
    """No new UserGroup created if membership already exists."""
    group = _make_group("group-admin")
    user_id = uuid.uuid4()
    db = _mock_db()
    call = [0]

    async def execute_side(q, *a, **kw):
        call[0] += 1
        if call[0] == 1:
            return _make_scalars([group])  # matched groups
        return _make_scalars([group.id])  # existing memberships = already member

    db.execute = execute_side
    db.add = MagicMock()
    db.flush = AsyncMock()

    mapper = GroupClaimMapper()
    newly_assigned = await mapper.map_claims(db, user_id, ["group-admin"])

    assert newly_assigned == []
    assert not db.add.called


@pytest.mark.asyncio
async def test_no_op_when_no_claims_match_any_group():
    """Returns empty list and no DB write when no claims match."""
    user_id = uuid.uuid4()
    db = _mock_db()

    async def execute_side(q, *a, **kw):
        return _make_scalars([])  # no matched groups

    db.execute = execute_side
    db.add = MagicMock()

    mapper = GroupClaimMapper()
    newly_assigned = await mapper.map_claims(db, user_id, ["some-unknown-claim"])

    assert newly_assigned == []
    assert not db.add.called


@pytest.mark.asyncio
async def test_empty_claims_returns_early():
    """Empty JWT claims list skips all DB queries."""
    db = _mock_db()
    db.execute = AsyncMock()

    mapper = GroupClaimMapper()
    result = await mapper.map_claims(db, uuid.uuid4(), [])

    assert result == []
    db.execute.assert_not_called()
