"""
Tests for the Resource Type Manifest.

Validates that the manifest structure is correct and contains expected resource types.
"""

from app.core.resource_types import (
    RT_ACCESS_REQUEST,
    RT_AGENT,
    RT_CONVERSATION,
    RT_GROUP,
    RT_MCP_SERVER,
    RT_NOTIFICATION,
    RT_PERMISSIONS,
    RT_ROLE,
    RT_SCHEDULING,
    RT_SKILL,
    RT_TAG,
    RT_USER,
    ResourceTypeManifest,
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


def test_all_resource_type_constants_exist():
    """All exported RT_* constants should be keys in the manifest."""
    expected_types = [
        RT_PERMISSIONS,
        RT_AGENT,
        RT_MCP_SERVER,
        RT_CONVERSATION,
        RT_NOTIFICATION,
        RT_SCHEDULING,
        RT_TAG,
        RT_ROLE,
        RT_GROUP,
        RT_USER,
        RT_ACCESS_REQUEST,
        RT_SKILL,
    ]

    for resource_type in expected_types:
        assert resource_type in ResourceTypeManifest, f"{resource_type} missing from manifest"


def test_permissions_resource_type_has_expected_actions():
    """Permissions resource type should have read and manage actions."""
    actions = ResourceTypeManifest[RT_PERMISSIONS]["actions"]
    assert "read" in actions
    assert "manage" in actions


def test_agent_resource_type_has_expected_actions():
    """Agent resource type should have CRUD actions."""
    actions = ResourceTypeManifest[RT_AGENT]["actions"]
    assert "create" in actions
    assert "read" in actions
    assert "update" in actions
    assert "delete" in actions


def test_invalid_resource_type_not_in_manifest():
    """Invalid resource types should not be in manifest."""
    assert "invalid_resource_type" not in ResourceTypeManifest
    assert "fake_module" not in ResourceTypeManifest
    assert "" not in ResourceTypeManifest
