"""Unit tests for app/tools.py.

Covers: hello_world_tool, tool_registry, and TOOL_MANIFEST content.
Scenario coverage: AC-2 (tool visible and callable), AC-3 (agent identity surfaced).
"""
from __future__ import annotations

from app.tools import TOOL_MANIFEST, hello_world_tool, tool_registry


# ── hello_world_tool ─────────────────────────────────────────────────────────


def test_hello_world_tool_returns_greeting():
    result = hello_world_tool({"sub": "agent-123"})
    assert result["message"] == "Hello from MCP Demo App!"


def test_hello_world_tool_surfaces_agent_sub():
    result = hello_world_tool({"sub": "agent-xyz"})
    assert result["agent_sub"] == "agent-xyz"


def test_hello_world_tool_includes_full_claims():
    claims = {"sub": "agent-abc", "iss": "http://keycloak/realms/ai_agents", "iat": 1000}
    result = hello_world_tool(claims)
    assert result["agent_claims"] == claims


def test_hello_world_tool_missing_sub_returns_none():
    """If JWT has no 'sub' claim, agent_sub must be None (not raise)."""
    result = hello_world_tool({})
    assert result["agent_sub"] is None
    assert result["message"] == "Hello from MCP Demo App!"


def test_hello_world_tool_returns_all_keys():
    result = hello_world_tool({"sub": "s"})
    assert set(result.keys()) == {"message", "agent_sub", "agent_claims"}


# ── tool_registry ────────────────────────────────────────────────────────────


def test_tool_registry_has_exactly_one_tool():
    assert len(tool_registry) == 1


def test_tool_registry_contains_hello_world():
    assert "helloWorld" in tool_registry


def test_tool_registry_hello_world_is_callable():
    assert callable(tool_registry["helloWorld"])


def test_tool_registry_hello_world_invocable():
    handler = tool_registry["helloWorld"]
    result = handler({"sub": "test-agent"})
    assert result["message"] == "Hello from MCP Demo App!"


# ── TOOL_MANIFEST ────────────────────────────────────────────────────────────


def test_tool_manifest_has_exactly_one_entry():
    """AC-6 (out-of-scope: exactly one tool, no extras)."""
    assert len(TOOL_MANIFEST) == 1


def test_tool_manifest_tool_name_is_hello_world():
    assert TOOL_MANIFEST[0]["name"] == "helloWorld"


def test_tool_manifest_has_description():
    desc = TOOL_MANIFEST[0]["description"]
    assert isinstance(desc, str) and len(desc) > 0


def test_tool_manifest_has_input_schema():
    schema = TOOL_MANIFEST[0]["inputSchema"]
    assert schema["type"] == "object"
    assert "properties" in schema
    assert "required" in schema


def test_tool_manifest_no_required_inputs():
    """helloWorld tool takes no arguments."""
    assert TOOL_MANIFEST[0]["inputSchema"]["required"] == []
