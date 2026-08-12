"""Unit tests for app/tools.py.

Covers: hello_world_tool, hello_agent_tool, hello_user_tool,
tool_registry, and TOOL_MANIFEST content.
"""
from __future__ import annotations

from app.tools import TOOL_MANIFEST, hello_agent_tool, hello_user_tool, hello_world_tool, tool_registry


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


# ── hello_agent_tool ─────────────────────────────────────────────────────────


def test_hello_agent_tool_returns_greeting_when_role_present():
    """hello_agent_tool succeeds when mcp_role is demo_agent."""
    identity = {"sub": "agent-abc", "iss": "http://kc/realms/ai", "mcp_role": "demo_agent"}
    result = hello_agent_tool(identity)
    assert result["message"] == "Hello Agent!"
    assert result["agent_sub"] == "agent-abc"
    assert result["agent_realm"] == "http://kc/realms/ai"
    assert result["agent_mcp_role"] == "demo_agent"
    assert result["agent_claims"] == identity


def test_hello_agent_tool_denies_when_role_absent():
    """hello_agent_tool returns access-denied when mcp_role is missing."""
    identity = {"sub": "agent-abc"}
    result = hello_agent_tool(identity)
    assert result == {"access_denied": True, "reason": "Agent identity lacks required mcp_role: demo_agent"}


def test_hello_agent_tool_denies_when_role_wrong():
    """hello_agent_tool returns access-denied when mcp_role is not demo_agent."""
    identity = {"sub": "agent-abc", "mcp_role": "other_role"}
    result = hello_agent_tool(identity)
    assert result == {"access_denied": True, "reason": "Agent identity lacks required mcp_role: demo_agent"}


def test_hello_agent_tool_empty_identity_denies():
    """hello_agent_tool handles empty identity dict — access denied."""
    result = hello_agent_tool({})
    assert result["access_denied"] is True


# ── hello_user_tool ──────────────────────────────────────────────────────────


def test_hello_user_tool_returns_greeting_when_role_present():
    """hello_user_tool succeeds when mcp_role is demo_user."""
    identity = {"sub": "user-xyz", "iss": "http://kc/realms/users", "mcp_role": "demo_user"}
    result = hello_user_tool(identity)
    assert result["message"] == "Hello User!"
    assert result["user_sub"] == "user-xyz"
    assert result["user_realm"] == "http://kc/realms/users"
    assert result["user_mcp_role"] == "demo_user"
    assert result["user_claims"] == identity


def test_hello_user_tool_denies_when_role_absent():
    """hello_user_tool returns access-denied when mcp_role is missing."""
    identity = {"sub": "user-xyz"}
    result = hello_user_tool(identity)
    assert result == {"access_denied": True, "reason": "User identity lacks required mcp_role: demo_user"}


def test_hello_user_tool_denies_when_role_wrong():
    """hello_user_tool returns access-denied when mcp_role is not demo_user."""
    identity = {"sub": "user-xyz", "mcp_role": "wrong_role"}
    result = hello_user_tool(identity)
    assert result == {"access_denied": True, "reason": "User identity lacks required mcp_role: demo_user"}


def test_hello_user_tool_empty_identity_denies():
    """hello_user_tool handles empty identity dict — access denied."""
    result = hello_user_tool({})
    assert result["access_denied"] is True


# ── tool_registry ────────────────────────────────────────────────────────────


def test_tool_registry_has_exactly_three_tools():
    assert len(tool_registry) == 3


def test_tool_registry_contains_hello_world():
    assert "helloWorld" in tool_registry


def test_tool_registry_contains_hello_agent():
    assert "helloAgent" in tool_registry


def test_tool_registry_contains_hello_user():
    assert "helloUser" in tool_registry


def test_tool_registry_hello_world_is_callable():
    assert callable(tool_registry["helloWorld"])


def test_tool_registry_hello_agent_is_callable():
    assert callable(tool_registry["helloAgent"])


def test_tool_registry_hello_user_is_callable():
    assert callable(tool_registry["helloUser"])


def test_tool_registry_hello_agent_invocable():
    handler = tool_registry["helloAgent"]
    result = handler({"sub": "agent-1", "mcp_role": "demo_agent"})
    assert result["message"] == "Hello Agent!"


def test_tool_registry_hello_user_invocable():
    handler = tool_registry["helloUser"]
    result = handler({"sub": "user-1", "mcp_role": "demo_user"})
    assert result["message"] == "Hello User!"


# ── TOOL_MANIFEST ────────────────────────────────────────────────────────────


def test_tool_manifest_has_exactly_three_entries():
    assert len(TOOL_MANIFEST) == 3


def test_tool_manifest_tool_names():
    names = {e["name"] for e in TOOL_MANIFEST}
    assert names == {"helloWorld", "helloAgent", "helloUser"}


def test_tool_manifest_hello_world_description():
    entry = next(e for e in TOOL_MANIFEST if e["name"] == "helloWorld")
    assert isinstance(entry["description"], str) and len(entry["description"]) > 0


def test_tool_manifest_hello_agent_description():
    entry = next(e for e in TOOL_MANIFEST if e["name"] == "helloAgent")
    assert "demo_agent" in entry["description"]


def test_tool_manifest_hello_user_description():
    entry = next(e for e in TOOL_MANIFEST if e["name"] == "helloUser")
    assert "demo_user" in entry["description"]


def test_tool_manifest_each_has_input_schema():
    for entry in TOOL_MANIFEST:
        schema = entry["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema


def test_tool_manifest_all_input_schemas_have_no_required_inputs():
    """All three tools take no arguments."""
    for entry in TOOL_MANIFEST:
        assert entry["inputSchema"]["required"] == []
