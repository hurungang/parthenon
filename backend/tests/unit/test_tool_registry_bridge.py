"""Unit tests for app.communication_hub.mcp.tool_registry_bridge.

Covers permission-filtered catalog construction (``load_skills`` meta tool,
system tools, proxied MCP tools with skill-sourced vs. stubbed metadata) and
dispatch authorization + routing, with the Control Center transport mocked out
via ``_post_cc``.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.communication_hub.mcp.session_manager import McpSession
from app.communication_hub.mcp.tool_registry_bridge import (
    LOAD_SKILLS_TOOL_NAME,
    ToolRegistryBridge,
)


@pytest.fixture
def bridge() -> ToolRegistryBridge:
    return ToolRegistryBridge()


def _session(**kwargs) -> McpSession:
    defaults = dict(
        session_id="session-1",
        agent_role_id="role-1",
        agent_identity_id="identity-1",
        permissions=[],
        skills=[],
    )
    defaults.update(kwargs)
    return McpSession(**defaults)


def _oauth_session(**kwargs) -> McpSession:
    """An OAuth-authenticated session (the Control Center Assistant plane)."""
    defaults = dict(
        session_id="session-1",
        auth_method="oauth",
        user_sub="user-1",
        platform_user_id="pu-1",
        permissions=["cc____create_skill"],
        skills=[],
    )
    defaults.update(kwargs)
    return McpSession(**defaults)


# ── build_catalog ─────────────────────────────────────────────────────────────


def test_build_catalog_always_includes_load_skills(bridge: ToolRegistryBridge) -> None:
    catalog = asyncio.run(bridge.build_catalog(_session()))
    assert catalog[0]["name"] == LOAD_SKILLS_TOOL_NAME
    assert catalog[0]["description"]
    assert catalog[0]["inputSchema"]["type"] == "object"


def test_build_catalog_includes_only_permitted_system_tools(
    bridge: ToolRegistryBridge,
) -> None:
    session = _session(permissions=["system____save_data"])
    catalog = asyncio.run(bridge.build_catalog(session))
    names = [t["name"] for t in catalog]
    assert LOAD_SKILLS_TOOL_NAME in names
    assert "system____save_data" in names
    assert "system____get_data" not in names
    entry = next(t for t in catalog if t["name"] == "system____save_data")
    assert entry["description"]
    assert entry["inputSchema"]["type"] == "object"


def test_build_catalog_proxied_tool_sources_skill_metadata(
    bridge: ToolRegistryBridge,
) -> None:
    skills = [
        {
            "name": "github-skill",
            "tools": [
                {
                    "name": "github____list_prs",
                    "description": "List pull requests",
                    "input_schema": {
                        "type": "object",
                        "properties": {"state": {"type": "string"}},
                    },
                }
            ],
        }
    ]
    session = _session(permissions=["github____list_prs"], skills=skills)
    catalog = asyncio.run(bridge.build_catalog(session))
    entry = next(t for t in catalog if t["name"] == "github____list_prs")
    assert entry["description"] == "List pull requests"
    assert entry["inputSchema"]["properties"] == {"state": {"type": "string"}}


def test_build_catalog_proxied_tool_stub_when_skill_absent(
    bridge: ToolRegistryBridge,
) -> None:
    session = _session(permissions=["github____list_prs"], skills=[])
    catalog = asyncio.run(bridge.build_catalog(session))
    entry = next(t for t in catalog if t["name"] == "github____list_prs")
    assert entry["description"] == ""
    assert entry["inputSchema"] == {"type": "object", "properties": {}}


# ── dispatch authorization ────────────────────────────────────────────────────


async def test_dispatch_raises_permission_error_for_unpermitted(
    bridge: ToolRegistryBridge,
) -> None:
    session = _session(permissions=[])
    with pytest.raises(PermissionError, match="not permitted"):
        await bridge.dispatch(None, session, "github____list_prs", {})


# ── dispatch routing (load_skills) ────────────────────────────────────────────


async def test_dispatch_routes_load_skills_with_agent_role_id(
    bridge: ToolRegistryBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONTROL_CENTER_URL", "http://control-center")
    session = _session(agent_role_id="role-123")
    mock = AsyncMock(return_value={"skills": [{"name": "s1"}]})
    monkeypatch.setattr(bridge, "_post_cc", mock)

    result = await bridge.dispatch(None, session, "load_skills", {})

    path = mock.await_args.args[2]
    payload = mock.await_args.args[3]
    assert path == "/api/v1/internal/system-tools/skills/resolve"
    assert payload["agent_role_id"] == "role-123"
    # Result is wrapped in MCP text content.
    assert result["content"][0]["type"] == "text"
    assert "s1" in result["content"][0]["text"]


async def test_dispatch_load_skills_passes_since(
    bridge: ToolRegistryBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONTROL_CENTER_URL", "http://control-center")
    session = _session(agent_role_id="role-1")
    mock = AsyncMock(return_value={"skills": []})
    monkeypatch.setattr(bridge, "_post_cc", mock)

    await bridge.dispatch(
        None, session, "load_skills", {"since": "2024-01-01T00:00:00Z"}
    )

    payload = mock.await_args.args[3]
    assert payload["since"] == "2024-01-01T00:00:00Z"


# ── dispatch routing (system tool) ────────────────────────────────────────────


async def test_dispatch_routes_system_tool(
    bridge: ToolRegistryBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONTROL_CENTER_URL", "http://control-center")
    session = _session(permissions=["system____save_data"])
    mock = AsyncMock(return_value={"result": {"saved": True}})
    monkeypatch.setattr(bridge, "_post_cc", mock)

    result = await bridge.dispatch(
        None,
        session,
        "system____save_data",
        {"data_name": "x", "data_value": {}},
    )

    path = mock.await_args.args[2]
    payload = mock.await_args.args[3]
    assert path.endswith("/api/v1/internal/system-tools/save-data")
    assert payload["session_id"] == "session-1"
    assert payload["tool_args"] == {"data_name": "x", "data_value": {}}
    assert result["content"][0]["type"] == "text"


# ── dispatch routing (proxied tool) ───────────────────────────────────────────


async def test_dispatch_routes_proxied_tool(
    bridge: ToolRegistryBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONTROL_CENTER_URL", "http://control-center")
    session = _session(permissions=["github____list_prs"])
    mock = AsyncMock(return_value={"result": {"prs": [{"number": 1}]}})
    monkeypatch.setattr(bridge, "_post_cc", mock)

    result = await bridge.dispatch(
        None, session, "github____list_prs", {"state": "open"}
    )

    path = mock.await_args.args[2]
    payload = mock.await_args.args[3]
    assert path == "/api/v1/internal/mcp/proxy-tool"
    assert payload["tool_name"] == "github____list_prs"
    assert payload["tool_args"] == {"state": "open"}
    assert payload["agent_role_id"] == "role-1"
    assert payload["agent_identity_id"] == "identity-1"
    assert payload["agent_session_id"] == "session-1"
    assert result["content"][0]["type"] == "text"


# ── OAuth (Control Center Assistant) catalog ────────────────────────────────


def test_oauth_catalog_lists_only_management_tools(bridge: ToolRegistryBridge) -> None:
    session = _oauth_session(
        permissions=["cc____create_skill", "cc____list_skills"]
    )
    catalog = asyncio.run(bridge.build_catalog(session))
    names = [t["name"] for t in catalog]
    assert "cc____create_skill" in names
    assert "cc____list_skills" in names
    # The OAuth catalog never includes the load_skills meta tool or proxied
    # tools — management tools only.
    assert LOAD_SKILLS_TOOL_NAME not in names
    for name in names:
        assert name.startswith("cc____")


def test_oauth_catalog_excludes_plain_system_tools(bridge: ToolRegistryBridge) -> None:
    # Even if a plain system tool sneaks into the permitted set, the OAuth
    # catalog must not surface it (management tools only).
    session = _oauth_session(
        permissions=["cc____create_skill", "system____save_data"]
    )
    catalog = asyncio.run(bridge.build_catalog(session))
    names = [t["name"] for t in catalog]
    assert "cc____create_skill" in names
    assert "system____save_data" not in names


def test_oauth_catalog_omits_unpermitted_management_tools(
    bridge: ToolRegistryBridge,
) -> None:
    session = _oauth_session(permissions=[])
    catalog = asyncio.run(bridge.build_catalog(session))
    assert catalog == []


# ── OAuth dispatch: permission denials + delete/out-of-scope decline ────────


async def test_oauth_dispatch_denies_unpermitted_in_band(
    bridge: ToolRegistryBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _oauth_session(permissions=[])
    result = await bridge.dispatch(None, session, "cc____create_skill", {"name": "x"})
    text = result["content"][0]["text"]
    assert '"error"' in text
    assert "permission_denied" in text


async def test_oauth_dispatch_declines_delete_shaped_call(
    bridge: ToolRegistryBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _oauth_session()
    result = await bridge.dispatch(None, session, "cc____delete_skill", {})
    text = result["content"][0]["text"]
    assert "deletion_not_supported" in text


async def test_oauth_dispatch_declines_out_of_scope_management_call(
    bridge: ToolRegistryBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A management-shaped verb for a resource that is not a registered
    # management tool (e.g. system module) is declined in-band.
    session = _oauth_session()
    result = await bridge.dispatch(None, session, "cc____delete_skill", {})
    text = result["content"][0]["text"]
    assert "deletion_not_supported" in text


async def test_oauth_dispatch_routes_permitted_management_tool(
    bridge: ToolRegistryBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONTROL_CENTER_URL", "http://control-center")
    session = _oauth_session(
        permissions=["cc____create_skill"], user_sub="user-123"
    )
    mock = AsyncMock(return_value={"result": {"record": {"id": "s-1", "name": "x"}}})
    monkeypatch.setattr(bridge, "_post_cc", mock)

    result = await bridge.dispatch(
        None, session, "cc____create_skill", {"name": "x"}
    )

    path = mock.await_args.args[2]
    payload = mock.await_args.args[3]
    assert path.endswith("/api/v1/internal/management-tools/create_skill")
    assert payload["user_sub"] == "user-123"
    assert payload["session_id"] == "session-1"
    # The identity token is never forwarded to CC — only the user sub.
    assert "identity_token" not in payload
    assert result["content"][0]["type"] == "text"


def test_management_scope_denial_ignores_non_system_names(
    bridge: ToolRegistryBridge,
) -> None:
    from app.communication_hub.mcp.tool_registry_bridge import _management_scope_denial

    assert _management_scope_denial("github____list_prs") is None
    assert _management_scope_denial("cc____delete_skill") is not None
    assert _management_scope_denial("cc____create_skill") is None
