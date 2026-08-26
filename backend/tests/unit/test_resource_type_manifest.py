"""
Tests for the Resource Type Manifest.

Validates that the manifest structure is correct and contains expected resource types.
"""
import pytest
from app.core.resource_types import (
    ResourceTypeManifest,
    MODULE_GROUPS,
    RT_AGENT_MANAGEMENT,
    RT_AGENT_ROLES,
    RT_AGENT_IDENTITIES,
    RT_AGENT_RUNTIME_CONTROL,
    RT_AGENT_SKILLS,
    RT_AGENT_SOPS,
    RT_AGENT_MODEL_CONFIGS,
    RT_AGENT_SCHEDULES,
    RT_AGENT_TRAILS,
    RT_AGENT_HUMAN_INTERVENTION,
    RT_AGENT_DATA_TYPES,
    RT_AGENT_OUTPUTS,
    RT_INTEGRATION_MCP_HUB,
    RT_INTEGRATION_NOTIFICATIONS,
    RT_SYSTEM_OBSERVABILITY,
    RT_SYSTEM_PERMISSIONS,
    RT_SYSTEM_CONFIG,
    get_module_from_resource_type,
    is_valid_wildcard,
)


def test_manifest_structure():
    """Manifest should be a dict mapping resource types to action dicts."""
    assert isinstance(ResourceTypeManifest, dict)
    assert len(ResourceTypeManifest) > 0

    for resource_type, config in ResourceTypeManifest.items():
        assert isinstance(resource_type, str)
        assert isinstance(config, dict)
        assert "actions" in config
        actions = config["actions"]
        assert isinstance(actions, list)
        assert len(actions) > 0
        for action in actions:
            assert isinstance(action, str)
            assert len(action) > 0


def test_manifest_has_20_entries():
    """Manifest should contain exactly 20 resource types (19 namespaced + bare 'agent')."""
    assert len(ResourceTypeManifest) == 20


def test_all_resource_type_constants_exist():
    """All exported RT_* constants should be keys in the manifest."""
    expected_types = [
        RT_AGENT_ROLES,
        RT_AGENT_IDENTITIES,
        RT_AGENT_MANAGEMENT,
        RT_AGENT_RUNTIME_CONTROL,
        RT_AGENT_SKILLS,
        RT_AGENT_SOPS,
        RT_AGENT_MODEL_CONFIGS,
        RT_AGENT_SCHEDULES,
        RT_AGENT_TRAILS,
        RT_AGENT_HUMAN_INTERVENTION,
        RT_AGENT_DATA_TYPES,
        RT_AGENT_OUTPUTS,
        RT_INTEGRATION_MCP_HUB,
        RT_INTEGRATION_NOTIFICATIONS,
        RT_SYSTEM_OBSERVABILITY,
        RT_SYSTEM_PERMISSIONS,
        RT_SYSTEM_CONFIG,
    ]

    for resource_type in expected_types:
        assert resource_type in ResourceTypeManifest, f"{resource_type} missing from manifest"


def test_permissions_resource_type_has_expected_actions():
    """system::permissions should have create, read, update, delete, manage, approve, reject."""
    actions = ResourceTypeManifest[RT_SYSTEM_PERMISSIONS]["actions"]
    assert "read" in actions
    assert "manage" in actions
    assert "create" in actions
    assert "approve" in actions
    assert "reject" in actions


def test_agent_management_resource_type_has_expected_actions():
    """agent::management should have CRUD + execute actions."""
    actions = ResourceTypeManifest[RT_AGENT_MANAGEMENT]["actions"]
    assert "create" in actions
    assert "read" in actions
    assert "update" in actions
    assert "delete" in actions
    assert "execute" in actions


def test_invalid_resource_type_not_in_manifest():
    """Invalid resource types should not be in manifest."""
    assert "role" not in ResourceTypeManifest
    assert "invalid_resource_type" not in ResourceTypeManifest
    assert "fake_module" not in ResourceTypeManifest
    assert "" not in ResourceTypeManifest


def test_module_groups_have_three_modules():
    """MODULE_GROUPS should contain agent, integration, and system."""
    assert set(MODULE_GROUPS.keys()) == {"agent", "integration", "system"}


def test_agent_module_has_14_submodules():
    """Agent module should have 14 submodules."""
    assert len(MODULE_GROUPS["agent"]) == 14


def test_integration_module_has_2_submodules():
    """Integration module should have 2 submodules."""
    assert len(MODULE_GROUPS["integration"]) == 2


def test_system_module_has_3_submodules():
    """System module should have 3 submodules."""
    assert len(MODULE_GROUPS["system"]) == 3


def test_get_module_from_resource_type():
    """get_module_from_resource_type should extract the module prefix."""
    assert get_module_from_resource_type("agent::management") == "agent"
    assert get_module_from_resource_type("integration::mcp_hub") == "integration"
    assert get_module_from_resource_type("system::permissions") == "system"
    assert get_module_from_resource_type("not_a_namespaced_type") is None
    assert get_module_from_resource_type("") is None


def test_is_valid_wildcard():
    """is_valid_wildcard should accept valid wildcard patterns."""
    assert is_valid_wildcard("*::*") is True
    assert is_valid_wildcard("agent::*") is True
    assert is_valid_wildcard("integration::*") is True
    assert is_valid_wildcard("system::*") is True
    assert is_valid_wildcard("invalid::*") is False
    assert is_valid_wildcard("*") is False
    assert is_valid_wildcard("agent::management") is False
    assert is_valid_wildcard("agent::") is False
    assert is_valid_wildcard("::*") is False


def test_trails_merges_conversation_and_result():
    """agent::trails should have the union of conversation and result actions."""
    actions = ResourceTypeManifest[RT_AGENT_TRAILS]["actions"]
    assert "create" in actions
    assert "read" in actions
    assert "update" in actions
    assert "delete" in actions
