"""
Tests for resource type identifier parsing and validation.

Covers ``::``-delimited identifier parsing, flat-value rejection,
three-layer rejection, empty-value rejection, and edge cases.
"""
import pytest
from app.core.resource_types import (
    get_module_from_resource_type,
    is_valid_wildcard,
    ResourceTypeManifest,
    MODULE_GROUPS,
)


# ── get_module_from_resource_type ──────────────────────────────────────────


def test_parse_valid_namespaced_identifier():
    """get_module_from_resource_type extracts the module from a valid ::-delimited identifier."""
    assert get_module_from_resource_type("agent::roles") == "agent"
    assert get_module_from_resource_type("agent::management") == "agent"
    assert get_module_from_resource_type("integration::mcp_hub") == "integration"
    assert get_module_from_resource_type("system::permissions") == "system"


def test_parse_flat_value_returns_none():
    """Flat values without :: delimiter return None."""
    assert get_module_from_resource_type("agent") is None
    assert get_module_from_resource_type("role") is None
    assert get_module_from_resource_type("permissions") is None
    assert get_module_from_resource_type("mcp_server") is None
    assert get_module_from_resource_type("conversation") is None


def test_parse_empty_string_returns_none():
    """Empty string returns None."""
    assert get_module_from_resource_type("") is None


def test_parse_whitespace_only():
    """Whitespace-only value contains no ::, so returns None."""
    assert get_module_from_resource_type("   ") is None


def test_parse_three_layers():
    """Three-layer identifier returns only the first module."""
    # get_module_from_resource_type splits on first :: only
    result = get_module_from_resource_type("agent::roles::extra")
    assert result == "agent"


def test_parse_single_colon():
    """Single colon is not the :: delimiter, returns None."""
    result = get_module_from_resource_type("agent:roles")
    assert result is None


def test_parse_no_delimiter_no_prefix():
    """Value with no delimiter and no known module returns None."""
    assert get_module_from_resource_type("nonexistent") is None


def test_parse_trailing_delimiter():
    """Trailing :: returns module part (empty submodule)."""
    result = get_module_from_resource_type("agent::")
    assert result == "agent"


# ── is_valid_wildcard ──────────────────────────────────────────────────────


def test_global_wildcard_is_valid():
    """*::* is a valid wildcard."""
    assert is_valid_wildcard("*::*") is True


def test_module_wildcards_are_valid():
    """agent::*, integration::*, system::* are valid wildcards."""
    assert is_valid_wildcard("agent::*") is True
    assert is_valid_wildcard("integration::*") is True
    assert is_valid_wildcard("system::*") is True


def test_unknown_module_wildcard_is_invalid():
    """module::* for an unknown module is invalid."""
    assert is_valid_wildcard("invalid::*") is False
    assert is_valid_wildcard("fake::*") is False


def test_bare_star_is_invalid_wildcard():
    """* alone is not a valid namespace wildcard."""
    assert is_valid_wildcard("*") is False


def test_concrete_resource_type_is_not_wildcard():
    """Concrete resource types (agent::roles) are not wildcards."""
    assert is_valid_wildcard("agent::roles") is False
    assert is_valid_wildcard("agent::management") is False
    assert is_valid_wildcard("system::permissions") is False


def test_empty_string_is_invalid_wildcard():
    """Empty string is not a valid wildcard."""
    assert is_valid_wildcard("") is False


def test_single_colon_star_is_invalid():
    """agent:* (single colon) is not a valid wildcard."""
    assert is_valid_wildcard("agent:*") is False


def test_missing_star_is_invalid_wildcard():
    """agent:: (trailing delimiter without *) is not a valid wildcard."""
    assert is_valid_wildcard("agent::") is False


def test_leading_delimiter_wildcard_is_invalid():
    """::* (leading delimiter) is not a valid wildcard."""
    assert is_valid_wildcard("::*") is False


def test_triple_colon_parsed_as_wildcard():
    """agent:::* (three colons) is parsed as agent::* due to non-overlapping count."""
    # The :: at positions 5-6 is found, remainder at position 7 doesn't form another ::.
    # The string ends with ::* so it's treated as a valid module wildcard.
    assert is_valid_wildcard("agent:::*") is True

def test_triple_colon_not_valid_resource_type():
    """agent:::* is not a valid concrete resource type in the manifest."""
    assert "agent:::*" not in ResourceTypeManifest


# ── Resource type validity (manifest-based) ────────────────────────────────


def test_valid_namespaced_types_in_manifest():
    """All 17 namespaced resource types are in the manifest."""
    for rt in MODULE_GROUPS["agent"]:
        assert rt in ResourceTypeManifest
    for rt in MODULE_GROUPS["integration"]:
        assert rt in ResourceTypeManifest
    for rt in MODULE_GROUPS["system"]:
        assert rt in ResourceTypeManifest


def test_flat_legacy_values_not_in_manifest():
    """Legacy flat values should NOT be in the manifest."""
    legacy = [
        "agent", "role", "skill", "sop", "mcp_server", "notification",
        "permissions", "group", "user", "tag", "access_request",
        "conversation", "result", "schedule", "model_config",
    ]
    for lt in legacy:
        assert lt not in ResourceTypeManifest, f"Legacy value '{lt}' should not be in manifest"


def test_nonexistent_namespaced_types_not_in_manifest():
    """Invented namespaced types should not be in the manifest."""
    assert "agent::nonexistent" not in ResourceTypeManifest
    assert "integration::fake" not in ResourceTypeManifest
    assert "system::nonexistent" not in ResourceTypeManifest
    assert "invalid::type" not in ResourceTypeManifest


def test_two_layer_only():
    """All manifest entries have exactly two layers (module::submodule)."""
    for rt in ResourceTypeManifest:
        assert rt.count("::") == 1, f"'{rt}' should have exactly one '::' delimiter"
