"""FIX-20261101-000319 — ``cc____`` namespace + Control Center MCP entity.

The 36 management execution tools (create/update/list/get × 9 families) and
the 4 management meta tools (invoke_management_tool, get_management_tool_schema,
list_management_tools, search_assistant_knowledge) move to the dedicated
``cc____`` namespace (server slug ``cc``, the "Control Center" MCP entity).
General system tools keep the ``system____`` namespace untouched, and decision
tools keep ``decision____``.
"""
from __future__ import annotations

import uuid

import pytest

from app.services.agents.system_tool_registry import SystemToolRegistry
from app.services.agents.tool_naming import (
    RESERVED_SERVER_NAMES,
    build_tool_name,
    get_bare_tool_name,
    get_server_name,
    is_cc_tool,
    is_system_tool,
    parse_tool_name,
)

_MANAGEMENT_EXECUTION_COUNT = 36  # 9 families × 4 verbs
_MANAGEMENT_META = {
    "invoke_management_tool",
    "get_management_tool_schema",
    "list_management_tools",
    "search_assistant_knowledge",
}
_GENERAL_UNTOUCHED = [
    "save_data",
    "get_data",
    "get_output",
    "query_result",
    "send_notification",
    "get_recipient_group",
    "human_intervene",
    "get_implementation_plan",
    "generate_script",
    "execute_script",
]


def test_cc_is_a_reserved_server_slug() -> None:
    assert "cc" in RESERVED_SERVER_NAMES
    assert "system" in RESERVED_SERVER_NAMES
    assert "decision" in RESERVED_SERVER_NAMES


def test_management_tools_carry_management_category() -> None:
    management = SystemToolRegistry.get_management_tool_names()
    assert len(management) == _MANAGEMENT_EXECUTION_COUNT
    for bare in management:
        tool = SystemToolRegistry.get(bare)
        assert tool is not None
        assert tool.category == "management"
        assert tool.is_management_tool is True


def test_meta_management_tools_are_cc_category() -> None:
    for bare in _MANAGEMENT_META:
        tool = SystemToolRegistry.get(bare)
        assert tool is not None, bare
        assert tool.category == "management"
        # Meta tools carry no parity — mechanics unchanged.
        assert tool.is_management_tool is False


def test_canonical_names_are_category_aware() -> None:
    assert SystemToolRegistry.get("create_skill").canonical_name == "cc____create_skill"
    assert SystemToolRegistry.get("invoke_management_tool").canonical_name == (
        "cc____invoke_management_tool"
    )
    for bare in _GENERAL_UNTOUCHED:
        assert SystemToolRegistry.get(bare).canonical_name == f"system____{bare}"


def test_is_cc_tool() -> None:
    assert is_cc_tool("cc____create_skill") is True
    assert is_cc_tool("cc____invoke_management_tool") is True
    assert is_cc_tool("system____create_skill") is False  # legacy form rejected
    assert is_cc_tool("system____save_data") is False
    assert is_cc_tool("save_data") is False
    assert is_cc_tool("decision____approve") is False
    assert is_cc_tool("cc____not_a_real_tool") is False


def test_is_system_tool_accepts_cc_names_for_routing() -> None:
    """Routing treats built-in ``cc____`` tools on the internal system path."""
    assert is_system_tool("cc____create_skill") is True
    assert is_system_tool("system____save_data") is True
    assert is_system_tool("hello-world____ping") is False


def test_parse_tool_name_supports_cc() -> None:
    assert parse_tool_name("cc____create_skill") == ("cc", "create_skill")
    assert parse_tool_name("cc____invoke_management_tool") == (
        "cc",
        "invoke_management_tool",
    )
    # Legacy bare management names parse into the cc namespace.
    assert parse_tool_name("create_skill") == ("cc", "create_skill")
    # General bare names still map to system.
    assert parse_tool_name("save_data") == ("system", "save_data")
    assert get_server_name("cc____list_skills") == "cc"
    assert get_bare_tool_name("cc____list_skills") == "list_skills"


def test_registry_canonicalize_is_category_aware() -> None:
    assert SystemToolRegistry.canonicalize_name("create_skill") == "cc____create_skill"
    assert SystemToolRegistry.canonicalize_name("cc____create_skill") == "cc____create_skill"
    assert SystemToolRegistry.canonicalize_name("save_data") == "system____save_data"
    assert SystemToolRegistry.canonicalize_name("system____save_data") == "system____save_data"


def test_mcp_hub_entries_exclude_management_tools() -> None:
    """Management tools must NOT auto-seed into the generic System entity."""
    entries = SystemToolRegistry.get_mcp_hub_entries()
    names = {e["original_name"] for e in entries}
    management = SystemToolRegistry.get_management_tool_names() | _MANAGEMENT_META
    assert not (names & management)
    for bare in _GENERAL_UNTOUCHED:
        assert bare in names
        entry = next(e for e in entries if e["original_name"] == bare)
        assert entry["name"] == f"system____{bare}"


def test_cc_mcp_hub_entries_cover_management_and_meta() -> None:
    entries = SystemToolRegistry.get_cc_mcp_hub_entries()
    by_name = {e["original_name"]: e for e in entries}
    expected = SystemToolRegistry.get_management_tool_names() | _MANAGEMENT_META
    assert set(by_name) == expected
    for bare, entry in by_name.items():
        assert entry["name"] == f"cc____{bare}"
        assert isinstance(entry["id"], uuid.UUID)


def test_cc_endpoint_map_still_covers_all_tools() -> None:
    """CH routing resolves CC endpoints by bare name for BOTH namespaces."""
    endpoint_map = SystemToolRegistry.get_cc_endpoint_map("http://cc:8000")
    assert "create_skill" in endpoint_map
    assert "save_data" in endpoint_map
    assert "invoke_management_tool" in endpoint_map


def test_is_management_tool_accepts_cc_prefix() -> None:
    assert SystemToolRegistry.is_management_tool("cc____create_skill") is True
    assert SystemToolRegistry.is_management_tool("create_skill") is True
    assert SystemToolRegistry.is_management_tool("cc____save_data") is False
    assert SystemToolRegistry.is_management_tool("save_data") is False


def test_parity_map_unchanged() -> None:
    parity = SystemToolRegistry.get_parity_map()
    assert set(parity) == SystemToolRegistry.get_management_tool_names()
    assert parity["create_skill"] == ("agent::skills", "create")
    assert "invoke_management_tool" not in parity


def test_meta_tool_names_mechanics_unchanged() -> None:
    meta = SystemToolRegistry.get_meta_tool_names()
    assert _MANAGEMENT_META <= meta
    assert "human_intervene" in meta  # stays a general system tool
    assert SystemToolRegistry.get("human_intervene").category == "general"


def test_build_tool_name_with_cc_slug() -> None:
    assert build_tool_name("cc", "create_skill") == "cc____create_skill"


def test_new_tools_registered_with_explicit_category_parameter() -> None:
    """SystemTool accepts an explicit category; general is the default."""
    tool = SystemToolRegistry.get("save_data")
    assert tool.category == "general"


def test_cc_server_uuid_is_distinct_reserved_id() -> None:
    """The CC MCP entity uses a new reserved UUID, never the System server's."""
    from app.services.agents.assistant_seeder import _tenant_cc_server_id

    tenant = uuid.uuid4()
    cc_id = _tenant_cc_server_id(tenant)
    system_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    decision_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    assert cc_id != system_id
    assert cc_id != decision_id
    # Deterministic per tenant (idempotent across restarts).
    assert _tenant_cc_server_id(tenant) == cc_id
    assert _tenant_cc_server_id(uuid.uuid4()) != cc_id
