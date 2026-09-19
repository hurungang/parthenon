"""Unit tests for app.communication_hub.mcp.tool_registry_bridge.

Covers permission-filtered catalog construction (``load_skills`` meta tool,
system tools, proxied MCP tools with skill-sourced vs. stubbed metadata) and
dispatch authorization + routing, with the Control Center transport mocked out
via ``_post_cc``.
"""
from __future__ import annotations

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


# ── build_catalog ─────────────────────────────────────────────────────────────


def test_build_catalog_always_includes_load_skills(bridge: ToolRegistryBridge) -> None:
    catalog = bridge.build_catalog(_session())
    assert catalog[0]["name"] == LOAD_SKILLS_TOOL_NAME
    assert catalog[0]["description"]
    assert catalog[0]["inputSchema"]["type"] == "object"


def test_build_catalog_includes_only_permitted_system_tools(
    bridge: ToolRegistryBridge,
) -> None:
    session = _session(permissions=["system____save_data"])
    catalog = bridge.build_catalog(session)
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
    catalog = bridge.build_catalog(session)
    entry = next(t for t in catalog if t["name"] == "github____list_prs")
    assert entry["description"] == "List pull requests"
    assert entry["inputSchema"]["properties"] == {"state": {"type": "string"}}


def test_build_catalog_proxied_tool_stub_when_skill_absent(
    bridge: ToolRegistryBridge,
) -> None:
    session = _session(permissions=["github____list_prs"], skills=[])
    catalog = bridge.build_catalog(session)
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
