"""FIX-20261101-000319 — ``cc____`` tools as first-class grantable MCP tools.

The Control Center management tools surface canonically as ``cc____<bare>``.
Bridge behavior:
  - OAuth catalog lists granted cc tools (and only management-category ones),
  - granted dispatch routes to the management handler with parity enforcement,
  - ungranted direct calls are denied (structured for OAuth, PermissionError
    for API-key sessions),
  - delete-shaped cc calls are declined,
  - ``system____`` routing is unchanged.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.communication_hub.mcp.session_manager import McpSession
from app.communication_hub.mcp.tool_registry_bridge import (
    ToolRegistryBridge,
    _management_scope_denial,
)


@pytest.fixture
def bridge() -> ToolRegistryBridge:
    return ToolRegistryBridge()


def _oauth_session(**kwargs) -> McpSession:
    defaults = dict(
        session_id="session-1",
        auth_method="oauth",
        user_sub="user-1",
        platform_user_id="pu-1",
        permissions=[],
        skills=[],
    )
    defaults.update(kwargs)
    return McpSession(**defaults)


def test_oauth_catalog_lists_granted_cc_tools(bridge: ToolRegistryBridge) -> None:
    session = _oauth_session(permissions=["cc____create_skill", "cc____list_skills"])
    catalog = asyncio.run(bridge.build_catalog(session))
    names = [t["name"] for t in catalog]
    assert "cc____create_skill" in names
    assert "cc____list_skills" in names
    assert all(name.startswith("cc____") for name in names)
    entry = next(t for t in catalog if t["name"] == "cc____create_skill")
    assert entry["description"]
    assert entry["inputSchema"]["type"] == "object"


def test_oauth_catalog_excludes_general_system_tools(bridge: ToolRegistryBridge) -> None:
    session = _oauth_session(permissions=["cc____create_skill", "system____save_data"])
    catalog = asyncio.run(bridge.build_catalog(session))
    names = [t["name"] for t in catalog]
    assert "cc____create_skill" in names
    assert "system____save_data" not in names


def test_oauth_catalog_omits_ungranted_cc_tools(bridge: ToolRegistryBridge) -> None:
    session = _oauth_session(permissions=[])
    catalog = asyncio.run(bridge.build_catalog(session))
    assert catalog == []


async def test_granted_cc_dispatch_routes_to_management_handler(
    bridge: ToolRegistryBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONTROL_CENTER_URL", "http://control-center")
    session = _oauth_session(permissions=["cc____create_skill"], user_sub="user-123")
    mock = AsyncMock(return_value={"result": {"record": {"id": "s-1", "name": "x"}}})
    monkeypatch.setattr(bridge, "_post_cc", mock)

    result = await bridge.dispatch(None, session, "cc____create_skill", {"name": "x"})

    path = mock.await_args.args[2]
    payload = mock.await_args.args[3]
    assert path.endswith("/api/v1/internal/management-tools/create_skill")
    assert payload["user_sub"] == "user-123"
    assert result["content"][0]["type"] == "text"


async def test_ungranted_cc_direct_call_denied_in_band(
    bridge: ToolRegistryBridge,
) -> None:
    session = _oauth_session(permissions=[])
    result = await bridge.dispatch(None, session, "cc____create_skill", {"name": "x"})
    text = result["content"][0]["text"]
    assert "permission_denied" in text


async def test_ungranted_cc_api_key_call_raises_permission_error(
    bridge: ToolRegistryBridge,
) -> None:
    session = McpSession(
        session_id="session-1",
        agent_role_id="role-1",
        agent_identity_id="identity-1",
        permissions=[],
        skills=[],
    )
    with pytest.raises(PermissionError):
        await bridge.dispatch(None, session, "cc____create_skill", {"name": "x"})


async def test_cc_delete_shaped_call_declined(bridge: ToolRegistryBridge) -> None:
    session = _oauth_session()
    result = await bridge.dispatch(None, session, "cc____delete_skill", {})
    text = result["content"][0]["text"]
    assert "deletion_not_supported" in text


def test_management_scope_denial_handles_cc_prefix() -> None:
    assert _management_scope_denial("cc____delete_skill") is not None
    assert _management_scope_denial("cc____create_skill") is None
    assert _management_scope_denial("github____list_prs") is None


async def test_meta_cc_tool_dispatch_routes_to_meta_handler(
    bridge: ToolRegistryBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meta tools (cc____list_management_tools etc.) route to their endpoints."""
    monkeypatch.setenv("CONTROL_CENTER_URL", "http://control-center")
    session = _oauth_session(
        permissions=["cc____list_management_tools"], user_sub="user-1"
    )
    mock = AsyncMock(return_value={"result": {"tools": [], "count": 0}})
    monkeypatch.setattr(bridge, "_post_cc", mock)

    await bridge.dispatch(None, session, "cc____list_management_tools", {})

    path = mock.await_args.args[2]
    assert path.endswith("/api/v1/internal/management-tools/list_management_tools")
