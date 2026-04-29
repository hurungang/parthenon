"""Unit tests for PermissionEngine."""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.services.permissions.permission_engine import PermissionEngine, AuthorizationResult
from app.db.models.policy_statement import PolicyEffect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db() -> AsyncMock:
    return AsyncMock()


def _make_scalars(items: list):
    """Return a mock execute result whose .scalars().all() returns items."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    result.scalars.return_value = scalars
    return result


def _setup_engine_db(
    db: AsyncMock,
    *,
    role_ids: list,
    user_group_ids: list = None,
    group_role_ids: list = None,
    statements: list = None,
    actions_per_stmt: dict = None,
    resources_per_stmt: dict = None,
    conditions_per_stmt: dict = None,
):
    """Wire up db.execute mock to return deterministic data for PermissionEngine."""
    user_group_ids = user_group_ids or []
    group_role_ids = group_role_ids or []
    statements = statements or []
    actions_per_stmt = actions_per_stmt or {}
    resources_per_stmt = resources_per_stmt or {}
    conditions_per_stmt = conditions_per_stmt or {}

    call_count = [0]

    async def execute_side_effect(query, *a, **kw):
        call_count[0] += 1
        c = call_count[0]
        # Call order inside _get_effective_role_ids:
        # 1: UserRole (direct roles)
        # 2: UserGroup (group ids)
        # 3: GroupRole (group-inherited role ids) — only if user_group_ids non-empty
        # After that, for authorize():
        # next: PolicyStatement query
        # then per-statement: PolicyAction, PolicyResource, PolicyTagCondition
        if c == 1:
            return _make_scalars(role_ids)
        if c == 2:
            return _make_scalars(user_group_ids)
        if c == 3 and user_group_ids:
            return _make_scalars(group_role_ids)

        # Policy statement query
        stmt_call = 3 + (1 if user_group_ids else 0)
        if c == stmt_call:
            return _make_scalars(statements)

        # Per-statement queries cycle: actions, resources, conditions
        offset = stmt_call + 1
        idx_in_cycle = (c - offset) % 3
        stmt_idx = (c - offset) // 3
        stmt = statements[stmt_idx] if stmt_idx < len(statements) else None

        if idx_in_cycle == 0:  # actions
            acts = actions_per_stmt.get(getattr(stmt, 'id', None), [])
            return _make_scalars(acts)
        if idx_in_cycle == 1:  # resources
            ress = resources_per_stmt.get(getattr(stmt, 'id', None), [])
            return _make_scalars(ress)
        if idx_in_cycle == 2:  # conditions
            conds = conditions_per_stmt.get(getattr(stmt, 'id', None), [])
            return _make_scalars(conds)

        return _make_scalars([])

    db.execute = execute_side_effect
    return db


def _stmt(role_id=None):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.role_id = role_id or uuid.uuid4()
    s.module = "agent"
    s.effect = PolicyEffect.allow
    return s


def _action(stmt_id, action: str):
    a = MagicMock()
    a.policy_statement_id = stmt_id
    a.action = action
    return a


def _resource(stmt_id, resource_id: str):
    r = MagicMock()
    r.policy_statement_id = stmt_id
    r.resource_id = resource_id
    return r


def _condition(stmt_id, tag_key: str, tag_value: str):
    c = MagicMock()
    c.policy_statement_id = stmt_id
    c.tag_key = tag_key
    c.tag_value = tag_value
    return c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deny_when_no_roles():
    """User with no roles is denied."""
    db = _mock_db()
    _setup_engine_db(db, role_ids=[])
    engine = PermissionEngine()
    result = await engine.authorize(db, uuid.uuid4(), "agent", "delete", "agent_1", {})
    assert result.allowed is False
    assert "no assigned roles" in result.reason.lower()


@pytest.mark.asyncio
async def test_deny_when_no_matching_statement():
    """User has roles but no policy statement for this module."""
    role_id = uuid.uuid4()
    db = _mock_db()
    _setup_engine_db(db, role_ids=[role_id], statements=[])
    engine = PermissionEngine()
    result = await engine.authorize(db, uuid.uuid4(), "agent", "delete", "agent_1", {})
    assert result.allowed is False


@pytest.mark.asyncio
async def test_allow_matching_policy():
    """Allow when a fully-matching allow policy exists."""
    role_id = uuid.uuid4()
    stmt = _stmt(role_id)
    act = _action(stmt.id, "delete")
    res = _resource(stmt.id, "agent_1")
    db = _mock_db()
    _setup_engine_db(
        db,
        role_ids=[role_id],
        statements=[stmt],
        actions_per_stmt={stmt.id: [act]},
        resources_per_stmt={stmt.id: [res]},
        conditions_per_stmt={stmt.id: []},
    )
    engine = PermissionEngine()
    result = await engine.authorize(db, uuid.uuid4(), "agent", "delete", "agent_1", {})
    assert result.allowed is True


@pytest.mark.asyncio
async def test_deny_when_action_not_in_policy():
    """Deny when user's policy has 'read' but request is 'delete'."""
    role_id = uuid.uuid4()
    stmt = _stmt(role_id)
    act = _action(stmt.id, "read")
    res = _resource(stmt.id, "agent_1")
    db = _mock_db()
    _setup_engine_db(
        db,
        role_ids=[role_id],
        statements=[stmt],
        actions_per_stmt={stmt.id: [act]},
        resources_per_stmt={stmt.id: [res]},
        conditions_per_stmt={stmt.id: []},
    )
    engine = PermissionEngine()
    result = await engine.authorize(db, uuid.uuid4(), "agent", "delete", "agent_1", {})
    assert result.allowed is False


@pytest.mark.asyncio
async def test_deny_when_tag_condition_not_satisfied():
    """Deny when tag condition requires env=prod but resource has env=dev."""
    role_id = uuid.uuid4()
    stmt = _stmt(role_id)
    act = _action(stmt.id, "delete")
    res = _resource(stmt.id, "*")
    cond = _condition(stmt.id, "env", "prod")
    db = _mock_db()
    _setup_engine_db(
        db,
        role_ids=[role_id],
        statements=[stmt],
        actions_per_stmt={stmt.id: [act]},
        resources_per_stmt={stmt.id: [res]},
        conditions_per_stmt={stmt.id: [cond]},
    )
    engine = PermissionEngine()
    result = await engine.authorize(db, uuid.uuid4(), "agent", "delete", "agent_1", {"env": "dev"})
    assert result.allowed is False


@pytest.mark.asyncio
async def test_allow_when_tag_condition_satisfied():
    """Allow when tag condition env=prod is satisfied."""
    role_id = uuid.uuid4()
    stmt = _stmt(role_id)
    act = _action(stmt.id, "delete")
    res = _resource(stmt.id, "*")
    cond = _condition(stmt.id, "env", "prod")
    db = _mock_db()
    _setup_engine_db(
        db,
        role_ids=[role_id],
        statements=[stmt],
        actions_per_stmt={stmt.id: [act]},
        resources_per_stmt={stmt.id: [res]},
        conditions_per_stmt={stmt.id: [cond]},
    )
    engine = PermissionEngine()
    result = await engine.authorize(db, uuid.uuid4(), "agent", "delete", "agent_1", {"env": "prod"})
    assert result.allowed is True


# ---------------------------------------------------------------------------
# _match_resource_id tests (synchronous)
# ---------------------------------------------------------------------------

def test_wildcard_star_matches_anything():
    engine = PermissionEngine()
    assert engine._match_resource_id("*", "anything") is True
    assert engine._match_resource_id("*", "") is True


def test_prefix_wildcard_matches_correct_prefix():
    engine = PermissionEngine()
    assert engine._match_resource_id("support_*", "support_001") is True
    assert engine._match_resource_id("support_*", "support_team") is True


def test_prefix_wildcard_no_match_different_prefix():
    engine = PermissionEngine()
    assert engine._match_resource_id("support_*", "monitoring_001") is False


def test_exact_match():
    engine = PermissionEngine()
    assert engine._match_resource_id("agent_abc", "agent_abc") is True
    assert engine._match_resource_id("agent_abc", "agent_xyz") is False
