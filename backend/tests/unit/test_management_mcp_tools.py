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


# ── Typed per-family schema invariants (Phase 3.2) ──────────────────────────

#: Parity map snapshot — every (tool → (resource_type, action)) pair, exactly
#: as enforced by the REST endpoints.  A change here is a BREAKING permission
#: change and must be a deliberate, reviewed act.
_PARITY_SNAPSHOT: dict[str, tuple[str, str]] = {
    "create_skill": ("agent::skills", "create"),
    "update_skill": ("agent::skills", "update"),
    "list_skills": ("agent::skills", "read"),
    "get_skill": ("agent::skills", "read"),
    "create_sop": ("agent::sops", "manage"),
    "update_sop": ("agent::sops", "manage"),
    "list_sops": ("agent::sops", "read"),
    "get_sop": ("agent::sops", "read"),
    "create_agent_type": ("agent", "create"),
    "update_agent_type": ("agent", "update"),
    "list_agent_types": ("agent", "read"),
    "get_agent_type": ("agent", "read"),
    "create_agent_role": ("agent", "create"),
    "update_agent_role": ("agent", "update"),
    "list_agent_roles": ("agent", "read"),
    "get_agent_role": ("agent", "read"),
    "create_agent_identity": ("agent", "create"),
    "update_agent_identity": ("agent", "update"),
    "list_agent_identities": ("agent", "read"),
    "get_agent_identity": ("agent", "read"),
    "create_model_config": ("agent", "create"),
    "update_model_config": ("agent", "update"),
    "list_model_configs": ("agent", "read"),
    "get_model_config": ("agent", "read"),
    "create_schedule": ("agent::schedules", "create"),
    "update_schedule": ("agent::schedules", "update"),
    "list_schedules": ("agent::schedules", "read"),
    "get_schedule": ("agent::schedules", "read"),
    "create_data_type": ("agent::data_types", "create"),
    "update_data_type": ("agent::data_types", "update"),
    "list_data_types": ("agent::data_types", "read"),
    "get_data_type": ("agent::data_types", "read"),
    "create_mcp_server": ("integration::mcp_hub", "create"),
    "update_mcp_server": ("integration::mcp_hub", "update"),
    "list_mcp_servers": ("integration::mcp_hub", "read"),
    "get_mcp_server": ("integration::mcp_hub", "read"),
}


def test_parity_map_is_unchanged() -> None:
    """Every (resource_type, action) parity pair matches the frozen snapshot."""
    assert SystemToolRegistry.get_parity_map() == _PARITY_SNAPSHOT


def test_no_delete_verb_in_parity_map_or_names() -> None:
    """No delete verb exists anywhere in the toolset."""
    assert not any(
        "delete" in name for name in SystemToolRegistry.get_names()
    ), "a delete-shaped tool name is registered"
    assert not any(
        action == "delete" for _, action in SystemToolRegistry.get_parity_map().values()
    )


def test_create_update_data_schemas_are_typed() -> None:
    """Every create/update tool has named, typed data properties (no free-form pass-through)."""
    from app.services.agents.system_tool_registry import _MANAGEMENT_DATA_FIELDS

    for family in _FAMILIES:
        decl = _MANAGEMENT_DATA_FIELDS[family]
        for verb in ("create", "update"):
            tool = SystemToolRegistry.get(f"{verb}_{_SINGULAR[family]}")
            data_prop = tool.parameters["properties"]["data"]
            assert data_prop["type"] == "object"
            assert data_prop.get("additionalProperties") is False, (
                f"{verb}_{family}: data must not be a free-form pass-through"
            )
            expected = set(decl["fields"])
            excluded = set(decl.get("update_only" if verb == "create" else "create_only", ()))
            expected -= excluded
            assert set(data_prop["properties"]) == expected, (
                f"{verb}_{family}: data properties must exactly match the declaration"
            )
            for prop in data_prop["properties"].values():
                assert "type" in prop, f"{verb}_{family}: property missing type"
                assert "description" in prop, f"{verb}_{family}: property missing description"


def test_enum_fields_carry_exact_model_values() -> None:
    """Enum-typed schema properties mirror the SQLAlchemy enum value lists exactly."""
    from app.db.models.agents import (
        AgentIdentityStatus,
        AgentIdentityType,
        AgentInputType,
        AgentOutputType,
        GuardrailConversationalContinuationPolicy,
        GuardrailConversationalTokenVisibilityMode,
        GuardrailTokenEnforcementMode,
        GuardrailTokenFallbackMode,
        ModelProvider,
    )
    from app.db.models.scheduling import JobTargetType

    at = SystemToolRegistry.get("create_agent_type").parameters["properties"]["data"]["properties"]
    assert at["input_type"]["enum"] == [e.value for e in AgentInputType]
    assert at["output_type"]["enum"] == [e.value for e in AgentOutputType]
    assert at["guardrail_token_enforcement_mode"]["enum"] == [
        e.value for e in GuardrailTokenEnforcementMode
    ]
    assert at["guardrail_token_fallback_mode"]["enum"] == [
        e.value for e in GuardrailTokenFallbackMode
    ]
    assert at["guardrail_conversational_token_visibility_mode"]["enum"] == [
        e.value for e in GuardrailConversationalTokenVisibilityMode
    ]
    assert at["guardrail_conversational_continuation_policy"]["enum"] == [
        e.value for e in GuardrailConversationalContinuationPolicy
    ]

    ident = SystemToolRegistry.get("create_agent_identity").parameters["properties"]["data"]["properties"]
    assert ident["status"]["enum"] == [e.value for e in AgentIdentityStatus]
    assert ident["identity_type"]["enum"] == [e.value for e in AgentIdentityType]

    mc = SystemToolRegistry.get("create_model_config").parameters["properties"]["data"]["properties"]
    assert mc["provider_type"]["enum"] == [e.value for e in ModelProvider]

    sched = SystemToolRegistry.get("create_schedule").parameters["properties"]["data"]["properties"]
    assert sched["target_type"]["enum"] == [e.value for e in JobTargetType]

    # Every enum property's description lists its allowed values.
    for props in (at, ident, mc, sched):
        for prop in props.values():
            if "enum" in prop:
                for value in prop["enum"]:
                    assert value in prop["description"]


def test_list_fields_describe_additive_merge_semantics() -> None:
    """Binding/grant/assignment list fields describe additive-merge semantics."""
    from app.services.agents.system_tool_registry import _MANAGEMENT_DATA_FIELDS

    merge_expectations = {
        "skill": {"tool_ids", "tool_names"},
        "agent_type": {"skill_ids", "sop_ids"},
        "agent_role": {"skill_ids", "sop_ids", "mcp_session_mappings"},
        "agent_identity": {"role_ids"},
    }
    for family, merge_fields in merge_expectations.items():
        decl = _MANAGEMENT_DATA_FIELDS[family]
        assert set(decl["merge"]) == merge_fields
        assert decl.get("merge_note"), f"{family}: merge note missing"
        for verb in ("create", "update"):
            tool = SystemToolRegistry.get(f"{verb}_{_SINGULAR[family]}")
            if tool is None:
                continue
            data_prop = tool.parameters["properties"]["data"]
            for field in merge_fields:
                if field in data_prop["properties"]:
                    assert "additive" in data_prop["properties"][field]["description"].lower()
            assert "additive" in tool.description.lower()


def test_uuid_allocation_unchanged_after_typed_schemas() -> None:
    """Typed schema application mutates tools in place — UUIDs must not move."""
    # Spot-check first/last of the management block plus the meta block.
    assert SystemToolRegistry.get("create_skill").mcp_hub_id == uuid.UUID(
        "00000000-0000-0000-0000-000000000019"
    )
    assert SystemToolRegistry.get("get_mcp_server").mcp_hub_id == uuid.UUID(
        "00000000-0000-0000-0000-000000000054"
    )
    assert SystemToolRegistry.get("invoke_management_tool").mcp_hub_id == uuid.UUID(
        "00000000-0000-0000-0000-000000000055"
    )
    assert SystemToolRegistry.get("search_assistant_knowledge").mcp_hub_id == uuid.UUID(
        "00000000-0000-0000-0000-000000000058"
    )


def test_create_update_descriptions_state_field_set_and_requirements() -> None:
    """Tool descriptions state the full field set, required-vs-optional, and merge semantics."""
    # agent_type create: field list + required fields spelled out
    desc = SystemToolRegistry.get("create_schedule").description
    assert "cron_expression" in desc and "target_id" in desc
    assert "Required in data at create" in desc

    desc = SystemToolRegistry.get("create_model_config").description
    assert "provider_type" in desc and "api_key" in desc
    assert "Required in data at create" in desc

    desc = SystemToolRegistry.get("update_schedule").description
    assert "immutable after create" in desc

    # get_management_tool_schema serves the enriched schemas via the registry.
    schema = SystemToolRegistry.get_schema("create_agent_type")
    assert schema["function"]["parameters"]["properties"]["data"]["additionalProperties"] is False
    assert "skill_ids" in schema["function"]["parameters"]["properties"]["data"]["properties"]


def test_sop_steps_schema_is_typed_with_enum_and_replace_semantics() -> None:
    """Task 2.7/3.5: create/update_sop expose a typed `steps` array with the
    step_type enum and full-list replace semantics, and the sop UUIDs/parity
    pairs stay untouched."""
    from app.db.models.skills import SopStepType

    for verb in ("create", "update"):
        tool = SystemToolRegistry.get(f"{verb}_sop")
        props = tool.parameters["properties"]["data"]["properties"]
        steps = props["steps"]
        assert steps["type"] == "array"
        items = steps["items"]
        assert items["type"] == "object"
        assert set(items["properties"]) == {
            "order", "step_type", "skill_id", "target_agent_type_id",
            "name", "description", "step_config",
        }
        assert items["properties"]["order"]["type"] == "integer"
        assert items["properties"]["step_type"]["enum"] == [e.value for e in SopStepType]
        for ref in ("skill_id", "target_agent_type_id"):
            assert "REQUIRED" in items["properties"][ref]["description"]
        assert items.get("additionalProperties") is False
        desc = steps["description"].lower()
        # Replace semantics: the steps property description always states it;
        # update_sop's tool description additionally carries the replace note.
        assert "replace" in desc and "omitted steps are deleted" in desc
        assert "requires" in desc or "required" in desc
        assert "gate" in desc
        if verb == "update":
            tool_desc = tool.description.lower()
            assert "replacement" in tool_desc and "omitted steps are deleted" in tool_desc
        # create_sop vs update_sop UUID / parity invariants unchanged.
        assert tool.parity == ("agent::sops", "manage")
        assert int(tool.mcp_hub_id) >= 0x19


def test_sop_tool_uuids_unchanged_with_steps_schema() -> None:
    """The steps schema addition must not move any registry UUID."""
    from app.services.agents.system_tool_registry import _MANAGEMENT_RESOURCES

    for singular, _plural, _rt, _ca, _ua in _MANAGEMENT_RESOURCES:
        for verb in ("create", "update", "list", "get"):
            name = f"{verb}_{singular}" if verb not in ("list",) else f"list_{_plural}"
            tool = SystemToolRegistry.get(name)
            if tool is None:
                continue
            hub = int(tool.mcp_hub_id)
            assert 0x19 <= hub <= 0x54, (name, tool.mcp_hub_id)


def test_management_tool_schemas_stay_bounded() -> None:
    """Progressive disclosure stays effective: no single schema balloons, and the
    assistant's always-on meta set stays small."""
    import json

    meta_names = SystemToolRegistry.get_meta_tool_names()
    meta_bytes = sum(
        len(json.dumps(SystemToolRegistry.get(n).openai_schema)) for n in meta_names
    )
    # The always-on context carries only the meta schemas — keep them small.
    assert meta_bytes < 10_000, meta_bytes
    for name in SystemToolRegistry.get_management_tool_names():
        size = len(json.dumps(SystemToolRegistry.get(name).openai_schema))
        # Largest (update_agent_type) is ~6 KB; nothing may balloon past 8 KB.
        assert size < 8_000, (name, size)


# ── task 3.6: agent_role mcp_session_mappings typed schema ──────────────────


def _agent_role_data_props() -> dict:
    for verb in ("create", "update"):
        tool = SystemToolRegistry.get(f"{verb}_agent_role")
        props = tool.parameters["properties"]["data"]["properties"]
        if "mcp_session_mappings" in props:
            return props
    raise AssertionError("mcp_session_mappings missing from agent_role data schema")


def test_agent_role_mcp_session_mappings_is_typed_array() -> None:
    """mcp_session_mappings is a typed {server, session} object array on create AND update."""
    for verb in ("create", "update"):
        tool = SystemToolRegistry.get(f"{verb}_agent_role")
        prop = tool.parameters["properties"]["data"]["properties"]["mcp_session_mappings"]
        assert prop["type"] == "array"
        item = prop["items"]
        assert item["type"] == "object"
        assert set(item["properties"]) == {"server", "session"}
        assert item["required"] == ["server", "session"]
        assert item["additionalProperties"] is False


def test_agent_role_mcp_session_mappings_describe_rules() -> None:
    """The schema description states id-or-name refs, additive merge, and the default rules."""
    from app.services.agents.system_tool_registry import _MANAGEMENT_DATA_FIELDS

    decl = _MANAGEMENT_DATA_FIELDS["agent_role"]
    assert "mcp_session_mappings" in decl["merge"]
    prop = _agent_role_data_props()["mcp_session_mappings"]
    text = (prop["description"] + " " + (decl.get("merge_note") or "")).lower()
    assert "id-or-name" in text or "id or name" in text
    assert "additive" in text
    assert "passthrough" in text
    assert "one session per server" in text
    assert "409" in text or "warning" in text
    assert "confirm" in text and "user" in text


def test_agent_role_uuids_unchanged_with_mappings_schema() -> None:
    """Parity: adding the typed mapping schema must not change any mcp_hub_id."""
    ids = {SystemToolRegistry.get(n).mcp_hub_id for n in SystemToolRegistry.get_management_tool_names()}
    assert len(ids) == 36
