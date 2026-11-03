"""Permission-parity tests for the management MCP tools.

Every management tool must key to the EXACT ``(resource_type, action)`` its
REST ``require_permission`` counterpart enforces.  This is the single source of
truth for "the assistant can never do what the REST API would deny":

- skills   → ``agent::skills``            (create / update / read)
- SOPs     → ``agent::sops``              (manage / manage / read)
- agent types / roles / identities / model configs → bare ``agent``
                                           (create / update / read)
- schedules→ ``agent::schedules``         (create / update / read)
- data types→ ``agent::data_types``       (create / update / read)
- MCP Hub  → ``integration::mcp_hub``     (create / update / read)

Also asserts deny-by-default invariants: every parity resource type is known to
the manifest, every parity action is declared for that resource type, and every
registered management tool has exactly one parity entry (no missing / orphan
entries).
"""
from __future__ import annotations

from app.core.resource_types import (
    RT_AGENT,
    RT_AGENT_DATA_TYPES,
    RT_AGENT_SCHEDULES,
    RT_AGENT_SKILLS,
    RT_AGENT_SOPS,
    RT_INTEGRATION_MCP_HUB,
    ResourceTypeManifest,
)
from app.services.agents.system_tool_registry import SystemToolRegistry

#: Expected ``{bare_name: (resource_type, action)}`` for all 36 management tools.
_EXPECTED_PARITY: dict[str, tuple[str, str]] = {}

_bare_agent = ("agent_type", "agent_role", "agent_identity", "model_config")
for _family, _rt, _create, _update in (
    ("skill", RT_AGENT_SKILLS, "create", "update"),
    ("sop", RT_AGENT_SOPS, "manage", "manage"),
    ("agent_type", RT_AGENT, "create", "update"),
    ("agent_role", RT_AGENT, "create", "update"),
    ("agent_identity", RT_AGENT, "create", "update"),
    ("model_config", RT_AGENT, "create", "update"),
    ("schedule", RT_AGENT_SCHEDULES, "create", "update"),
    ("data_type", RT_AGENT_DATA_TYPES, "create", "update"),
    ("mcp_server", RT_INTEGRATION_MCP_HUB, "create", "update"),
):
    _singular = {
        "skill": "skill",
        "sop": "sop",
        "agent_type": "agent_type",
        "agent_role": "agent_role",
        "agent_identity": "agent_identity",
        "model_config": "model_config",
        "schedule": "schedule",
        "data_type": "data_type",
        "mcp_server": "mcp_server",
    }[_family]
    _plural = {
        "skill": "skills",
        "sop": "sops",
        "agent_type": "agent_types",
        "agent_role": "agent_roles",
        "agent_identity": "agent_identities",
        "model_config": "model_configs",
        "schedule": "schedules",
        "data_type": "data_types",
        "mcp_server": "mcp_servers",
    }[_family]
    _EXPECTED_PARITY[f"create_{_singular}"] = (_rt, _create)
    _EXPECTED_PARITY[f"update_{_singular}"] = (_rt, _update)
    _EXPECTED_PARITY[f"list_{_plural}"] = (_rt, "read")
    _EXPECTED_PARITY[f"get_{_singular}"] = (_rt, "read")


def test_parity_map_is_exactly_the_expected_mapping() -> None:
    assert SystemToolRegistry.get_parity_map() == _EXPECTED_PARITY


def test_parity_map_has_36_entries() -> None:
    assert len(SystemToolRegistry.get_parity_map()) == 36


def test_get_parity_map_matches_get_management_tool_names() -> None:
    """The parity map and the management-tool name set are the same keys."""
    assert set(SystemToolRegistry.get_parity_map().keys()) == set(
        SystemToolRegistry.get_management_tool_names()
    )


def test_every_parity_resource_type_is_in_manifest() -> None:
    for bare, (resource_type, action) in SystemToolRegistry.get_parity_map().items():
        assert resource_type in ResourceTypeManifest, (
            f"tool {bare!r} parity resource type {resource_type!r} is not in the manifest"
        )


def test_every_parity_action_is_declared_for_its_resource_type() -> None:
    for bare, (resource_type, action) in SystemToolRegistry.get_parity_map().items():
        declared = ResourceTypeManifest[resource_type]["actions"]
        # SOPs use "manage" (declared); everything else uses create/update/read.
        assert action in declared, (
            f"tool {bare!r} parity action {action!r} not declared for {resource_type!r} "
            f"(declared: {declared})"
        )


def test_agent_type_management_uses_bare_agent_not_namespaced() -> None:
    """Agent-type / role / identity / model-config tools resolve to bare ``agent``."""
    for bare in (
        "create_agent_type",
        "update_agent_type",
        "create_agent_role",
        "update_agent_role",
        "create_agent_identity",
        "update_agent_identity",
        "create_model_config",
        "update_model_config",
    ):
        assert SystemToolRegistry.get_parity_map()[bare] == (RT_AGENT, bare.split("_", 1)[0])


def test_sop_create_update_map_to_manage() -> None:
    assert SystemToolRegistry.get_parity_map()["create_sop"] == (RT_AGENT_SOPS, "manage")
    assert SystemToolRegistry.get_parity_map()["update_sop"] == (RT_AGENT_SOPS, "manage")
    assert SystemToolRegistry.get_parity_map()["get_sop"] == (RT_AGENT_SOPS, "read")


def test_schedule_tools_map_to_schedules_not_agent() -> None:
    assert SystemToolRegistry.get_parity_map()["create_schedule"] == (RT_AGENT_SCHEDULES, "create")
    assert SystemToolRegistry.get_parity_map()["update_schedule"] == (RT_AGENT_SCHEDULES, "update")
    assert SystemToolRegistry.get_parity_map()["list_schedules"] == (RT_AGENT_SCHEDULES, "read")


def test_data_type_tools_map_to_data_types() -> None:
    assert SystemToolRegistry.get_parity_map()["create_data_type"] == (RT_AGENT_DATA_TYPES, "create")
    assert SystemToolRegistry.get_parity_map()["update_data_type"] == (RT_AGENT_DATA_TYPES, "update")
    assert SystemToolRegistry.get_parity_map()["get_data_type"] == (RT_AGENT_DATA_TYPES, "read")


def test_mcp_hub_tools_map_to_integration_mcp_hub() -> None:
    assert SystemToolRegistry.get_parity_map()["create_mcp_server"] == (
        RT_INTEGRATION_MCP_HUB,
        "create",
    )
    assert SystemToolRegistry.get_parity_map()["update_mcp_server"] == (
        RT_INTEGRATION_MCP_HUB,
        "update",
    )
    assert SystemToolRegistry.get_parity_map()["list_mcp_servers"] == (
        RT_INTEGRATION_MCP_HUB,
        "read",
    )


def test_no_delete_verb_in_parity_map() -> None:
    """No management tool maps to a delete action — deletion is not a tool."""
    for bare, (_, action) in SystemToolRegistry.get_parity_map().items():
        assert action != "delete", f"{bare} maps to delete"
        assert not bare.startswith("delete_")


def test_is_management_tool_accepts_bare_and_canonical_names() -> None:
    assert SystemToolRegistry.is_management_tool("create_skill") is True
    assert SystemToolRegistry.is_management_tool("cc____create_skill") is True
    assert SystemToolRegistry.is_management_tool("save_data") is False
    assert SystemToolRegistry.is_management_tool("system____save_data") is False
    assert SystemToolRegistry.is_management_tool("does_not_exist") is False
