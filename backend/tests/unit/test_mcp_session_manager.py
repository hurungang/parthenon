"""Unit tests for app.communication_hub.mcp.session_manager.

Covers session create/get/touch lifecycle, TTL expiry, deletion, the
public-context projection (identity-token non-exposure), and opportunistic
cleanup of expired sessions.
"""
from __future__ import annotations

import time

from app.communication_hub.mcp.session_manager import (
    CLEANUP_INTERVAL_SECONDS,
    McpSession,
    McpSessionManager,
)


def test_create_and_get_session() -> None:
    manager = McpSessionManager()
    session = manager.create_session(agent_role_id="role-1", identity_token="secret")
    assert session.session_id
    assert manager.get_session(session.session_id) is session


def test_get_unknown_session_returns_none() -> None:
    manager = McpSessionManager()
    assert manager.get_session("does-not-exist") is None


def test_get_session_touches_last_activity() -> None:
    manager = McpSessionManager()
    session = manager.create_session()
    original = session.last_activity
    # Force last_activity into the past, then confirm get_session refreshes it.
    session.last_activity = original - 100
    fetched = manager.get_session(session.session_id)
    assert fetched is session
    assert session.last_activity > original - 100


def test_session_expiry_after_ttl() -> None:
    manager = McpSessionManager(ttl_seconds=100)
    session = manager.create_session()
    # Simulate idle time exceeding the TTL.
    session.last_activity = time.time() - 200
    assert session.is_expired(100) is True
    assert manager.get_session(session.session_id) is None


def test_delete_session() -> None:
    manager = McpSessionManager()
    session = manager.create_session()
    manager.delete_session(session.session_id)
    assert manager.get_session(session.session_id) is None


def test_to_public_context_excludes_identity_token() -> None:
    session = McpSession(
        session_id="abc",
        initialized=True,
        identity_token="super-secret-token",
        agent_role_id="role-1",
        permissions=["system____save_data"],
        skills=[{"name": "skill"}],
        api_key_name="my-key",
    )
    ctx = session.to_public_context()
    assert "identity_token" not in ctx
    assert "permissions" not in ctx
    assert "skills" not in ctx
    assert ctx["session_id"] == "abc"
    assert ctx["initialized"] is True
    assert ctx["agent_role_id"] == "role-1"
    assert ctx["api_key_name"] == "my-key"


def test_maybe_cleanup_removes_expired() -> None:
    manager = McpSessionManager(ttl_seconds=100)
    s1 = manager.create_session()
    s2 = manager.create_session()
    s1.last_activity = time.time() - 200
    s2.last_activity = time.time() - 200
    # Ensure the cleanup interval has elapsed.
    manager._last_cleanup = time.time() - CLEANUP_INTERVAL_SECONDS - 1
    removed = manager.maybe_cleanup()
    assert removed == 2
    assert manager._sessions == {}


def test_maybe_cleanup_noop_when_recent() -> None:
    manager = McpSessionManager(ttl_seconds=100)
    manager.create_session()
    manager._last_cleanup = time.time()
    assert manager.maybe_cleanup() == 0
    assert len(manager._sessions) == 1
