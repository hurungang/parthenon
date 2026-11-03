"""Unit tests for the management MCP tools registered in SystemToolRegistry.

The Control Center Assistant exposes the Agents-menu management operations
(create / update / list / get across nine resource families) as
OAuth-authenticated MCP tools.  These tests lock down the tool surface:

- exactly 36 management tools (9 families x 4 verbs), all in the ``system____``
  canonical namespace;
- NO delete verb registered (defense-in-depth: destructive ops are declined in
  band by the tool-registry bridge);
- stable ``mcp_hub_id`` UUIDs (documented reserved block 019..054);
- every management tool carries a ``parity`` ``(resource_type, action)`` mapping;
- schemas are OpenAI function-calling shaped and name validation is canonical.
"""
from __future__ import annotations

import uuid

import pytest

from app.services.agents.system_tool_registry import (
    TOOL_SEPARATOR,
    SystemToolRegistry,
)

#: The nine resource families and the four verbs registered for each.
_FAMILIES = (
    "skill",
    "sop",
    "agent_type",
    "agent_role",
    "agent_identity",
    "model_config",
    "schedule",
    "data_type",
    "mcp_server",
)

_SINGULAR = {
    "skill": "skill",
    "sop": "sop",
    "agent_type": "agent_type",
    "agent_role": "agent_role",
    "agent_identity": "agent_identity",
    "model_config": "model_config",
    "schedule": "schedule",
    "data_type": "data_type",
    "mcp_server": "mcp_server",
}

_PLURAL = {
    "skill": "skills",
    "sop": "sops",
    "agent_type": "agent_types",
    "agent_role": "agent_roles",
    "agent_identity": "agent_identities",
    "model_config": "model_configs",
    "schedule": "schedules",
    "data_type": "data_types",
    "mcp_server": "mcp_servers",
}


def _expected_bare_names() -> set[str]:
    names: set[str] = set()
    for family in _FAMILIES:
        names.add(f"create_{_SINGULAR[family]}")
        names.add(f"update_{_SINGULAR[family]}")
        names.add(f"list_{_PLURAL[family]}")
        names.add(f"get_{_SINGULAR[family]}")
    return names


def test_management_tool_count_is_36() -> None:
    """Nine families x (create/update/list/get) = 36 management tools."""
    names = SystemToolRegistry.get_management_tool_names()
    assert len(names) == 36


def test_management_tool_names_cover_all_families() -> None:
    assert SystemToolRegistry.get_management_tool_names() == _expected_bare_names()


def test_no_delete_tool_is_registered() -> None:
    for name in SystemToolRegistry.get_management_tool_names():
        assert not name.startswith("delete_"), f"delete tool registered: {name}"
        assert not name.startswith("remove_"), f"remove tool registered: {name}"


def test_every_management_tool_is_system_tool() -> None:
    for name in SystemToolRegistry.get_management_tool_names():
        assert SystemToolRegistry.is_system_tool(name)
        assert SystemToolRegistry.is_system_tool(f"system{TOOL_SEPARATOR}{name}")


def test_every_management_tool_carries_parity() -> None:
    for name in SystemToolRegistry.get_management_tool_names():
        tool = SystemToolRegistry.get(name)
        assert tool is not None
        assert tool.is_management_tool is True
        assert tool.parity is not None
        resource_type, action = tool.parity
        assert resource_type
        assert action in {"create", "update", "read", "manage"}


def test_non_management_tools_do_not_carry_parity() -> None:
    """Plain system tools (save_data, get_data, ...) must NOT be management tools."""
    for name in ("save_data", "get_data", "get_output", "send_notification"):
        tool = SystemToolRegistry.get(name)
        assert tool is not None
        assert tool.is_management_tool is False
        assert tool.parity is None
    assert "save_data" not in SystemToolRegistry.get_management_tool_names()


def test_management_tool_uuids_are_stable_and_unique() -> None:
    """UUIDs are allocated from the reserved block (019..054) and never reused."""
    ids = {SystemToolRegistry.get(n).mcp_hub_id for n in SystemToolRegistry.get_management_tool_names()}
    assert len(ids) == 36, "management tool UUIDs must be unique"
    # Documented allocation: 00000000-0000-0000-0000-000000000019 .. 000000000054
    expected = {
        uuid.UUID(f"00000000-0000-0000-0000-{i:012d}") for i in range(19, 55)
    }
    assert ids == expected


def test_create_skill_has_documented_uuid() -> None:
    """The first management tool (create_skill) occupies the documented slot."""
    assert SystemToolRegistry.get("create_skill").mcp_hub_id == uuid.UUID(
        "00000000-0000-0000-0000-000000000019"
    )


def test_management_tool_schemas_are_openai_function_shaped() -> None:
    for name in SystemToolRegistry.get_management_tool_names():
        schema = SystemToolRegistry.get_schema(name)
        assert schema["type"] == "function"
        assert schema["function"]["name"] == name
        assert schema["function"]["parameters"]["type"] == "object"
        assert "properties" in schema["function"]["parameters"]


def test_create_tools_require_name() -> None:
    for family in _FAMILIES:
        schema = SystemToolRegistry.get_schema(f"create_{_SINGULAR[family]}")
        assert "name" in schema["function"]["parameters"].get("required", []), family


def test_update_tools_require_id() -> None:
    for family in _FAMILIES:
        schema = SystemToolRegistry.get_schema(f"update_{_SINGULAR[family]}")
        assert "id" in schema["function"]["parameters"].get("required", []), family


def test_list_and_get_tools_have_read_schemas() -> None:
    for family in _FAMILIES:
        list_schema = SystemToolRegistry.get_schema(f"list_{_PLURAL[family]}")
        assert "limit" in list_schema["function"]["parameters"]["properties"]
        get_schema = SystemToolRegistry.get_schema(f"get_{_SINGULAR[family]}")
        assert "id" in get_schema["function"]["parameters"]["properties"]


def test_get_management_tool_names_is_a_frozenset() -> None:
    assert isinstance(SystemToolRegistry.get_management_tool_names(), frozenset)


def test_register_rejects_duplicate_name() -> None:
    """Registration is name-unique; a duplicate raises ValueError."""
    with pytest.raises(ValueError):
        SystemToolRegistry.register(
            SystemToolRegistry.get("create_skill")  # type: ignore[arg-type]
        )
