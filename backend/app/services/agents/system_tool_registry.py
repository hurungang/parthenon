"""Centralised registry for all built-in system tools.

This is the **single source of truth** for every system tool.  Adding a new
system tool requires exactly ONE change — add a ``SystemToolRegistry.register()``
call below with all fields populated.  Every consumer derives from this registry:

* LLM tool schemas      → ``SystemToolRegistry.get_all_schemas()``
* CommHub routing       → ``SystemToolRegistry.get_cc_endpoint_map(cc_base)``
* MCP Hub UI / seeding  → ``SystemToolRegistry.get_mcp_hub_entries()`` / ``get_mcp_hub_ids()``
* Skill seeder          → ``SystemToolRegistry.get_skill_definitions()``
* Name validation       → ``SystemToolRegistry.is_system_tool(name)``

No other file should maintain its own list of system tool names, UUIDs, or
CC endpoint paths.  If a consumer needs data not yet exposed by the registry,
add a method here rather than duplicating the list elsewhere.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.resource_types import (
    RT_AGENT,
    RT_AGENT_DATA_TYPES,
    RT_AGENT_SCHEDULES,
    RT_AGENT_SKILLS,
    RT_AGENT_SOPS,
    RT_INTEGRATION_MCP_HUB,
)

#: Four-underscore separator used in canonical ``server____tool`` names.
TOOL_SEPARATOR = "____"

#: Server slug of the dedicated Control Center management entity.  Management
#: tools surface canonically as ``cc____<bare>`` (FIX-20261101-000319);
#: general tools remain ``system____<bare>``.
CC_SERVER_SLUG = "cc"
SYSTEM_SERVER_SLUG = "system"

#: Tool categories.  ``management`` tools belong to the dedicated Control
#: Center MCP entity (``cc____`` namespace); ``general`` tools stay in the
#: generic System entity (``system____`` namespace).
TOOL_CATEGORIES = frozenset({"general", "management"})


class SystemTool:
    """Descriptor for a built-in system tool.

    Parameters
    ----------
    name:
        Bare tool name, e.g. ``"save_data"``.
    description:
        Human/LLM-facing description.
    parameters:
        OpenAI function-calling parameter schema.
    cc_endpoint_path:
        Path on the Control Center service that handles this tool call,
        e.g. ``"/api/v1/internal/system-tools/save-data"``.
        CommHub appends this to ``cc_base`` when routing.
    mcp_hub_id:
        Stable UUID used when seeding this tool's row in the ``mcp_tools``
        table.  Must be unique across all system tools and never change once
        the tool has been deployed.
    skill_name:
        Slug of the default platform skill that wraps this tool
        (e.g. ``"save-data"``).  ``None`` means no auto-seeded skill.
    skill_description:
        Short description for the seeded skill.
    skill_instructions:
        Agent-facing instructions for the seeded skill.
    parity:
        Optional ``(resource_type, action)`` tuple.  When set, the tool is a
        *management tool*: an OAuth-authenticated user may only list/call it
        when their permission scope satisfies this exact pair (the same pair
        the equivalent REST endpoint enforces via ``require_permission``).
        Management tools have no delete verb and never carry credentials.
    category:
        ``"general"`` (default) or ``"management"``.  Management-category
        tools surface canonically as ``cc____<bare>`` under the dedicated
        per-tenant Control Center MCP entity; general tools surface as
        ``system____<bare>`` under the generic System entity
        (FIX-20261101-000319).
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any] | None = None,
        *,
        cc_endpoint_path: str,
        mcp_hub_id: uuid.UUID,
        skill_name: str | None = None,
        skill_description: str | None = None,
        skill_instructions: str | None = None,
        parity: tuple[str, str] | None = None,
        category: str = "general",
    ) -> None:
        if not name or not isinstance(name, str):
            raise ValueError("SystemTool name must be a non-empty string")
        if not description or not isinstance(description, str):
            raise ValueError("SystemTool description must be a non-empty string")
        if not cc_endpoint_path:
            raise ValueError("SystemTool cc_endpoint_path must be a non-empty string")
        if category not in TOOL_CATEGORIES:
            raise ValueError(
                f"SystemTool category must be one of {sorted(TOOL_CATEGORIES)}, "
                f"got '{category}'"
            )

        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}
        self.cc_endpoint_path = cc_endpoint_path
        self.mcp_hub_id = mcp_hub_id
        self.skill_name = skill_name
        self.skill_description = skill_description
        self.skill_instructions = skill_instructions
        self.parity = parity
        self.category = category

    @property
    def is_management_tool(self) -> bool:
        """Return ``True`` when this tool carries a permission parity mapping."""
        return self.parity is not None

    @property
    def is_cc_tool(self) -> bool:
        """Return ``True`` when this tool belongs to the ``cc____`` namespace."""
        return self.category == "management"

    @property
    def server_slug(self) -> str:
        """Server slug of the entity this tool belongs to (``cc`` or ``system``)."""
        return CC_SERVER_SLUG if self.category == "management" else SYSTEM_SERVER_SLUG

    @property
    def openai_schema(self) -> dict[str, Any]:
        """Return OpenAI function-calling schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @property
    def canonical_name(self) -> str:
        """Full canonical name — category-aware ``cc____<name>`` / ``system____<name>``."""
        return f"{self.server_slug}{TOOL_SEPARATOR}{self.name}"


class SystemToolRegistry:
    """Single source of truth for all built-in system tools.

    Tools are registered at module import time via ``SystemToolRegistry.register()``.
    Once registered, all consumers use this class to discover tool names, schemas,
    and routing metadata — no hardcoded constants anywhere.
    """

    _tools: dict[str, SystemTool] = {}

    # ── Registration ────────────────────────────────────────────────────

    @classmethod
    def register(cls, tool: SystemTool) -> None:
        """Register a new system tool.

        Raises ``ValueError`` if a tool with the same name already exists.
        """
        if tool.name in cls._tools:
            raise ValueError(
                f"System tool '{tool.name}' is already registered"
            )
        cls._tools[tool.name] = tool

    @classmethod
    def registered_count(cls) -> int:
        return len(cls._tools)

    # ── Lookup ──────────────────────────────────────────────────────────

    @classmethod
    def get(cls, name: str) -> SystemTool | None:
        """Look up a ``SystemTool`` by its bare name (e.g. ``"save_result"``)."""
        return cls._tools.get(name)

    @classmethod
    def get_names(cls) -> frozenset[str]:
        """Return all registered bare system tool names."""
        return frozenset(cls._tools.keys())

    @classmethod
    def get_all_schemas(cls) -> list[dict[str, Any]]:
        """Return OpenAI function-calling schemas for every registered tool.

        This is the canonical source for LLM tool definitions — both the
        Control Centre context builder and the Agent Runtime tool loader
        use this method.
        """
        return [tool.openai_schema for tool in cls._tools.values()]

    @classmethod
    def get_schema(cls, name: str) -> dict[str, Any] | None:
        """Return the OpenAI function-calling schema for one tool by bare name."""
        tool = cls._tools.get(name)
        return tool.openai_schema if tool else None

    # ── Consumer-facing derivation helpers ──────────────────────────────

    @classmethod
    def get_cc_endpoint_map(cls, cc_base: str) -> dict[str, str]:
        """Return ``{bare_name: full_cc_url}`` for CommHub ``endpoint_map`` routing.

        ``cc_base`` should be the Control Center base URL without a trailing
        slash, e.g. ``"http://localhost:8000"``.
        """
        base = cc_base.rstrip("/")
        return {
            name: f"{base}{tool.cc_endpoint_path}"
            for name, tool in cls._tools.items()
        }

    @classmethod
    def get_mcp_hub_entries(cls) -> list[dict[str, Any]]:
        """Return data dicts for building McpToolRead objects and DB seeding.

        GENERAL tools only — management-category tools are NOT auto-seeded
        into the generic System entity; they belong to the dedicated
        Control Center entity (see :meth:`get_cc_mcp_hub_entries`).

        Each dict contains ``id``, ``name`` (canonical ``system____<bare>``),
        ``original_name``, ``description``, and ``input_schema``.
        Consumers use these to build framework-specific objects without
        importing this module's dependencies.
        """
        return [
            {
                "id": tool.mcp_hub_id,
                "name": f"system{TOOL_SEPARATOR}{tool.name}",
                "original_name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in cls._tools.values()
            if tool.category == "general"
        ]

    @classmethod
    def get_cc_mcp_hub_entries(cls) -> list[dict[str, Any]]:
        """Return data dicts for the Control Center MCP entity's tools.

        Management-category tools only (the 36 management execution tools +
        the 4 management meta tools), canonical ``cc____<bare>`` names.  Used
        by the assistant seeder to provision the per-tenant "Control Center"
        McpServer + McpTool rows (FIX-20261101-000319).
        """
        return [
            {
                "id": tool.mcp_hub_id,
                "name": f"{CC_SERVER_SLUG}{TOOL_SEPARATOR}{tool.name}",
                "original_name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in cls._tools.values()
            if tool.category == "management"
        ]

    @classmethod
    def get_mcp_hub_ids(cls) -> set[uuid.UUID]:
        """Return the set of all system tool UUIDs.

        Used to populate ``SYSTEM_TOOL_IDS`` in ``mcp_hub.py`` for
        request validation without hardcoding UUIDs in that file.
        """
        return {tool.mcp_hub_id for tool in cls._tools.values()}

    @classmethod
    def get_skill_definitions(cls) -> list[dict[str, Any]]:
        """Return a list of skill definition dicts for ``SkillSeeder``.

        Only tools with a non-``None`` ``skill_name`` produce an entry.
        Format matches ``SkillSeeder._DEFAULT_SKILLS``:
        ``{name, description, instructions, tool_names}``.
        """
        return [
            {
                "name": tool.skill_name,
                "description": tool.skill_description,
                "instructions": tool.skill_instructions,
                "tool_names": [tool.name],
            }
            for tool in cls._tools.values()
            if tool.skill_name is not None
        ]

    @classmethod
    def is_management_tool(cls, name: str) -> bool:
        """Return ``True`` when *name* refers to a registered management tool.

        Accepts the bare name, the canonical ``cc____<bare>`` form, or the
        legacy ``system____<bare>`` form.
        """
        bare = name
        for prefix in (
            CC_SERVER_SLUG + TOOL_SEPARATOR,
            SYSTEM_SERVER_SLUG + TOOL_SEPARATOR,
        ):
            if name.startswith(prefix):
                bare = name[len(prefix):]
                break
        tool = cls._tools.get(bare)
        return tool is not None and tool.is_management_tool

    @classmethod
    def is_cc_tool(cls, name: str) -> bool:
        """Return ``True`` when *name* refers to a ``cc____``-namespaced tool.

        Only management-category tools qualify; a ``cc____`` prefix over a
        general tool (or unknown name) is ``False``.
        """
        prefix = CC_SERVER_SLUG + TOOL_SEPARATOR
        if name.startswith(prefix):
            tool = cls._tools.get(name[len(prefix):])
            return tool is not None and tool.category == "management"
        return False

    @classmethod
    def get_parity_map(cls) -> dict[str, tuple[str, str]]:
        """Return ``{bare_name: (resource_type, action)}`` for management tools.

        This is the single source of truth for the management-tool →
        permission parity: every entry equals the matching REST endpoint's
        ``require_permission`` arguments (verified against skills.py, sops.py,
        agents.py, scheduling.py, data_types.py, mcp_hub.py).  No delete verb
        exists.
        """
        return {
            name: tool.parity
            for name, tool in cls._tools.items()
            if tool.parity is not None
        }

    @classmethod
    def get_management_tool_names(cls) -> frozenset[str]:
        """Return the bare names of every registered management tool."""
        return frozenset(cls.get_parity_map().keys())

    # ── Name parsing & routing helpers ──────────────────────────────────

    @classmethod
    def is_system_tool(cls, name: str) -> bool:
        """Return ``True`` if *name* refers to a registered built-in tool.

        Accepts all supported naming formats (both namespaces — used for
        ROUTING decisions, not for canonical display):
        - Canonical ``system____save_result`` / ``cc____create_skill``
        - Bare ``save_result`` / ``create_skill``
        - Old display ``system/save_result``
        - Old sanitised ``system_save_result``
        """
        if name in cls._tools:
            return True
        for prefix in (
            SYSTEM_SERVER_SLUG + TOOL_SEPARATOR,
            CC_SERVER_SLUG + TOOL_SEPARATOR,
        ):
            if name.startswith(prefix):
                return name[len(prefix):] in cls._tools
        if name.startswith("system/"):
            return name[len("system/"):] in cls._tools
        if name.startswith("system_"):
            return name[len("system_"):] in cls._tools
        return False

    @classmethod
    def parse_name(cls, name: str) -> tuple[str, str] | None:
        """Parse a tool name into ``(server, bare_tool)``.

        Returns the CATEGORY-AWARE server slug (``"cc"`` for management
        tools, ``"system"`` for general tools) if the name refers to a
        registered built-in tool in any supported format, or ``None``
        otherwise.
        """
        if TOOL_SEPARATOR in name:
            parts = name.split(TOOL_SEPARATOR)
            if len(parts) == 2 and parts[0] in (SYSTEM_SERVER_SLUG, CC_SERVER_SLUG):
                if parts[1] in cls._tools:
                    # Category-aware: a system____ prefix over a management
                    # tool canonicalizes to cc (legacy tolerance).
                    tool = cls._tools[parts[1]]
                    return (tool.server_slug, parts[1])
        if name in cls._tools:
            return (cls._tools[name].server_slug, name)
        return None

    @classmethod
    def canonicalize_name(cls, name: str) -> str | None:
        """Convert *name* to its canonical category-aware ``server____<bare>`` form.

        Management tools → ``cc____<bare>``; general tools → ``system____<bare>``.
        Returns ``None`` for names that do not match any registered tool.
        """
        parsed = cls.parse_name(name)
        if parsed is None:
            return None
        return f"{parsed[0]}{TOOL_SEPARATOR}{parsed[1]}"


# ═══════════════════════════════════════════════════════════════════════════
# Built-in system tool registration
# ═══════════════════════════════════════════════════════════════════════════
#
# To add a new system tool:
#   1. Add a SystemToolRegistry.register(SystemTool(...)) call below.
#   2. Add the corresponding CC handler in
#      backend/app/api/v1/internal/system_tools.py.
#   3. Add the corresponding LangChain tool class in
#      backend/app/services/agents/langchain_system_tools.py.
#
# Everything else (CommHub routing, MCP Hub UI, skill seeding, name
# validation) is derived automatically from this registry.
#
# NOTE: save_result is intentionally absent — retired in favour of save_data.
#
# UUID allocation (never reuse or change a deployed UUID):
#   00000000-0000-0000-0000-000000000001  → System server
#   00000000-0000-0000-0000-000000000002  → save_data  (was save_result)
#   00000000-0000-0000-0000-000000000003  → send_notification
#   00000000-0000-0000-0000-000000000004  → get_recipient_group
#   00000000-0000-0000-0000-000000000005  → human_intervene
#   00000000-0000-0000-0000-000000000006  → get_data
#   00000000-0000-0000-0000-000000000007  → get_output
#   00000000-0000-0000-0000-000000000008  → query_result

SystemToolRegistry.register(SystemTool(
    name="send_notification",
    description="Send a notification to a recipient group via configured channels",
    parameters={
        "type": "object",
        "properties": {
            "group_slug": {"type": "string", "description": "Slug of the recipient group"},
            "channel": {
                "type": "string",
                "description": "Optional channel selector within the recipient group (name, type, or ID).",
            },
            "subject": {"type": "string", "description": "Notification subject / title"},
            "body": {"type": "string", "description": "Notification body content"},
            "priority": {
                "type": "string",
                "enum": ["low", "normal", "high"],
                "description": "Notification priority level",
            },
        },
        "required": ["group_slug", "body"],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/send-notification",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
    skill_name="send-notification",
    skill_description="Dispatches notifications through configured channel integrations.",
    skill_instructions=(
        "Use this skill to dispatch a notification through one of the configured "
        "channel integrations (email, Slack, webhook, etc.). Specify the channel "
        "and message payload. Ensure the channel is active before invoking."
    ),
))

SystemToolRegistry.register(SystemTool(
    name="get_recipient_group",
    description="Get information about a notification recipient group",
    parameters={
        "type": "object",
        "properties": {
            "group_slug": {"type": "string", "description": "Slug of the recipient group to query"},
        },
        "required": ["group_slug"],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/get-recipient-group",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000004"),
    skill_name="get-recipient-group",
    skill_description="Retrieves information about notification recipient groups.",
    skill_instructions=(
        "Use this skill to retrieve details about a notification recipient group, "
        "including which channels are configured and their recipient properties. "
        "Call this before sending notifications to verify the group exists."
    ),
))

SystemToolRegistry.register(SystemTool(
    name="human_intervene",
    description=(
        "Request human intervention during agent execution. "
        "Call this when you need approval, a choice between options, or "
        "text input from a human operator. Execution will suspend until "
        "the human responds."
    ),
    parameters={
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Explanation of why human input is needed"},
            "intervention_type": {
                "type": "string",
                "enum": ["approval", "choice", "text"],
                "description": "Type of intervention needed",
            },
            "choices": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Available options when intervention_type is 'choice'",
            },
            "prompt": {
                "type": "string",
                "description": "Descriptive prompt when intervention_type is 'text'",
            },
        },
        "required": ["reason", "intervention_type"],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/human-intervene",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000005"),
    skill_name="human-intervene",
    skill_description="Creates a human-in-the-loop intervention request for operator approval, choice selection, or text input.",
    skill_instructions=(
        "Use this skill when the agent needs human input to proceed. "
        "Specify the intervention type (approval, choice, or text), the reason "
        "for the intervention, and optional choices for choice-type interventions. "
        "The agent will pause execution until an operator responds."
    ),
))

SystemToolRegistry.register(SystemTool(
    name="query_result",
    description=(
        "Query past typed agent outputs by data type name. "
        "Returns a list of typed results conforming to the requested schema."
    ),
    parameters={
        "type": "object",
        "properties": {
            "data_type_name": {
                "type": "string",
                "description": "Name or slug of the data type to query (e.g. 'incident_report')",
            },
            "filters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "ISO-8601 start date"},
                    "date_to": {"type": "string", "description": "ISO-8601 end date"},
                    "field_filters": {
                        "type": "object",
                        "description": "Key-value pairs to filter by field values",
                        "additionalProperties": True,
                    },
                },
                "description": "Optional filters to narrow results",
            },
        },
        "required": ["data_type_name"],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/query-result",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000008"),
    skill_name="query-result",
    skill_description="Queries past typed agent outputs by data type.",
    skill_instructions=(
        "Use this skill to retrieve and analyze past typed outputs produced by "
        "agents for a given data type. Provide the data type name and optional "
        "date or field filters to narrow the results."
    ),
))

SystemToolRegistry.register(SystemTool(
    name="save_data",
    description=(
        "Save named intermediate data during execution for later retrieval. "
        "Use this to persist any structured data produced during the task "
        "under a descriptive name. Can be called multiple times per session."
    ),
    parameters={
        "type": "object",
        "properties": {
            "data_name": {"type": "string", "description": "Name key for this data item"},
            "data_value": {"type": "object", "description": "JSON-serialisable value to store"},
            "data_type": {"type": "string", "description": "Value type hint (default 'json')"},
        },
        "required": ["data_name", "data_value"],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/save-data",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
    skill_name="save-data",
    skill_description="Persists named intermediate data produced during agent execution.",
    skill_instructions=(
        "Use this skill to save any structured intermediate data produced during "
        "the task under a descriptive name. You can save multiple different data "
        "items in a single session. Data is retrievable via the get-data skill."
    ),
))

SystemToolRegistry.register(SystemTool(
    name="get_data",
    description=(
        "Retrieve previously saved named data. "
        "At least one of data_name, agent_type_id, or session_id must be provided."
    ),
    parameters={
        "type": "object",
        "properties": {
            "data_name": {"type": "string", "description": "Filter by data name"},
            "agent_type_id": {"type": "string", "description": "Filter by agent type ID"},
            "session_id": {"type": "string", "description": "Filter by session ID"},
            "limit": {"type": "integer", "description": "Maximum records to return (default 50)"},
        },
        "required": [],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/get-data",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000006"),
    skill_name="get-data",
    skill_description="Retrieves named intermediate data saved in previous or current sessions.",
    skill_instructions=(
        "Use this skill to retrieve data previously saved with the save-data skill. "
        "Filter by data_name, agent_type_id, or session_id. At least one filter is required. "
        "Use this to enable cross-session data analysis and agent memory patterns."
    ),
))

SystemToolRegistry.register(SystemTool(
    name="get_output",
    description=(
        "Retrieve typed agent output records. "
        "All filters are optional. Results are ordered newest first."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_type_id": {"type": "string", "description": "Filter by agent type ID"},
            "session_id": {"type": "string", "description": "Filter by session ID"},
            "date_from": {"type": "string", "description": "ISO date string — include records on or after"},
            "date_to": {"type": "string", "description": "ISO date string — include records on or before"},
            "limit": {"type": "integer", "description": "Maximum records to return (default 50)"},
        },
        "required": [],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/get-output",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000007"),
    skill_name="get-output",
    skill_description="Retrieves typed agent output records from previous sessions.",
    skill_instructions=(
        "Use this skill to retrieve final typed outputs produced by agent sessions. "
        "Filter by agent_type_id, session_id, or date range to scope the query. "
        "Use this to build cross-session analysis, reports, or data pipelines."
    ),
))


# ── Optimization system tools (Optimize & Verify command-driven agent) ──────
#
# These power the "Optimize & Verify" command: a side execution of the agent
# authors the workflow composition through these tools. They are standard
# system tools (routed by Communication Hub to the CC handlers in
# backend/app/api/v1/internal/optimization_tools.py). No auto-seeded skills —
# they are invoked directly by the command mission.
#
# UUID allocation (continue the reserved system-tool block):
#   00000000-0000-0000-0000-000000000009  → get_implementation_plan
#   00000000-0000-0000-0000-000000000010  → get_optimized_implementation_plan
#   00000000-0000-0000-0000-000000000011  → generate_optimized_plan
#   00000000-0000-0000-0000-000000000012  → generate_script
#   00000000-0000-0000-0000-000000000013  → execute_script
#   00000000-0000-0000-0000-000000000014  → list_scripts
#   00000000-0000-0000-0000-000000000015  → get_script
#   (00000000-0000-0000-0000-000000000016 retired — record_verification)

SystemToolRegistry.register(SystemTool(
    name="get_implementation_plan",
    description=(
        "Read the base (high-level) implementation plan steps for an agent "
        "type. Returns the ordered step list the workflow must perform."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_type_id": {"type": "string", "description": "The target agent type id"},
        },
        "required": ["agent_type_id"],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/get-implementation-plan",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000009"),
))

SystemToolRegistry.register(SystemTool(
    name="get_optimized_implementation_plan",
    description=(
        "Read the current optimized implementation plan for an agent type: "
        "authored steps, script ids, verification log, feedback comments, "
        "status and the fully_scripted mark."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_type_id": {"type": "string", "description": "The target agent type id"},
        },
        "required": ["agent_type_id"],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/get-optimized-implementation-plan",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
))

SystemToolRegistry.register(SystemTool(
    name="generate_optimized_plan",
    description=(
        "Upsert the optimized implementation plan and associate/promote the "
        "authored script versions. Provide steps (each with python_source and "
        "optional script_version_id), fully_scripted, output_mode, "
        "output_template, and status."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_type_id": {"type": "string", "description": "The target agent type id"},
            "steps": {"type": "array", "description": "The authored composition steps"},
            "fully_scripted": {"type": "boolean", "description": "Zero-LLM end-to-end script?"},
            "output_mode": {"type": "string", "description": "deterministic | llm_render"},
            "output_template": {"type": "string", "description": "Optional output template"},
            "status": {"type": "string", "description": "ready | failed | needs_feedback"},
        },
        "required": ["agent_type_id", "steps"],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/generate-optimized-plan",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000011"),
))

SystemToolRegistry.register(SystemTool(
    name="generate_script",
    description=(
        "Sandbox-compile validate then save a draft script version for an "
        "agent type. Returns the version id; rejected (unsafe/broken) source "
        "returns a reason you must fix and retry."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_type_id": {"type": "string", "description": "The target agent type id"},
            "name": {"type": "string", "description": "Script definition name"},
            "description": {"type": "string", "description": "Short description"},
            "python_source": {"type": "string", "description": "Sandboxed Python defining run(context, tools)"},
        },
        "required": ["agent_type_id", "name", "python_source"],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/generate-script",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000012"),
))

SystemToolRegistry.register(SystemTool(
    name="execute_script",
    description=(
        "Run a script version's python_source through the real sandbox with "
        "the given input. Returns the output, or an error on a sandbox "
        "compile/violation/resource-cap failure. This is the verification "
        "primitive — a script that runs here runs at serving time."
    ),
    parameters={
        "type": "object",
        "properties": {
            "python_source": {"type": "string", "description": "FULL inline python_source of the script to execute (preferred for verification — pass the complete script you authored; do not save first)"},
            "script_version_id": {"type": "string", "description": "A saved script version id to run (alternative to python_source)"},
            "input": {"type": "object", "description": "Input context dict for run(context, tools)"},
        },
        "required": [],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/execute-script",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000013"),
))

SystemToolRegistry.register(SystemTool(
    name="list_scripts",
    description=(
        "List authored script definitions and their current version (with "
        "python_source and lifecycle) for an agent type, for reuse or repair."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_type_id": {"type": "string", "description": "The target agent type id"},
        },
        "required": ["agent_type_id"],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/list-scripts",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000014"),
))

SystemToolRegistry.register(SystemTool(
    name="get_script",
    description=(
        "Return one authored script definition (with python_source and "
        "lifecycle) by name or definition id for an agent type."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_type_id": {"type": "string", "description": "The target agent type id"},
            "name": {"type": "string", "description": "Script definition name"},
            "definition_id": {"type": "string", "description": "Script definition id"},
        },
        "required": ["agent_type_id"],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/get-script",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000015"),
))

SystemToolRegistry.register(SystemTool(
    name="get_scripts",
    description=(
        "Self-reflection: read the agent's OWN script definitions — versions, "
        "python_source, sandbox validation status and lifecycle — to assess "
        "the current state before authoring or re-authoring scripts."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_type_id": {"type": "string", "description": "The target agent type id"},
        },
        "required": ["agent_type_id"],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/get-scripts",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000017"),
))

SystemToolRegistry.register(SystemTool(
    name="get_execution_log",
    description=(
        "Self-reflection: read the agent's recent execution logs (most recent "
        "first, including failures) to learn from past errors before "
        "authoring or re-authoring scripts."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_type_id": {"type": "string", "description": "The target agent type id"},
            "limit": {"type": "integer", "description": "Max entries (default 30, max 100)"},
        },
        "required": ["agent_type_id"],
    },
    cc_endpoint_path="/api/v1/internal/system-tools/get-execution-log",
    mcp_hub_id=uuid.UUID("00000000-0000-0000-0000-000000000018"),
))


# ═══════════════════════════════════════════════════════════════════════════
# Management tools — Control Center Assistant (Agents-menu management)
# ═══════════════════════════════════════════════════════════════════════════
#
# These tools expose the Agents-menu management operations (create / update /
# read) as OAuth-authenticated MCP tools on the Communication Hub MCP protocol
# server.  Each tool carries its **parity** ``(resource_type, action)`` — the
# exact pair the equivalent REST endpoint enforces via ``require_permission``
# (verified against skills.py, sops.py, agents.py, scheduling.py,
# data_types.py, mcp_hub.py).  No delete verb is registered.
#
# The single source of truth for the parity map is ``SystemToolRegistry
# .get_parity_map()`` — the tool registry is the only place tool names, UUIDs,
# CC endpoint paths, and parity permissions are declared.
#
# UUID allocation (continue the reserved system-tool block, decimal):
#   00000000-0000-0000-0000-000000000019 .. 00000000-0000-0000-0000-000000000054

#: resource spec → (singular, plural, resource_type, create_action, update_action)
_MANAGEMENT_RESOURCES: tuple[tuple[str, str, str, str, str], ...] = (
    ("skill", "skills", RT_AGENT_SKILLS, "create", "update"),
    ("sop", "sops", RT_AGENT_SOPS, "manage", "manage"),
    ("agent_type", "agent_types", RT_AGENT, "create", "update"),
    ("agent_role", "agent_roles", RT_AGENT, "create", "update"),
    ("agent_identity", "agent_identities", RT_AGENT, "create", "update"),
    ("model_config", "model_configs", RT_AGENT, "create", "update"),
    ("schedule", "schedules", RT_AGENT_SCHEDULES, "create", "update"),
    ("data_type", "data_types", RT_AGENT_DATA_TYPES, "create", "update"),
    ("mcp_server", "mcp_servers", RT_INTEGRATION_MCP_HUB, "create", "update"),
)

_management_uuid_counter = 19  # continue after get_execution_log (018)


def _next_management_uuid() -> uuid.UUID:
    global _management_uuid_counter
    value = uuid.UUID(f"00000000-0000-0000-0000-{_management_uuid_counter:012d}")
    _management_uuid_counter += 1
    return value


def _register_management_tools() -> None:
    """Register the four management verbs per resource family (create/update/list/get)."""
    for singular, plural, resource_type, create_action, update_action in _MANAGEMENT_RESOURCES:
        display = singular.replace("_", " ")

        SystemToolRegistry.register(SystemTool(
            name=f"create_{singular}",
            description=(
                f"Create a new {display}. Performs the same action as the "
                f"Control Center management UI. Requires {resource_type}:{create_action} permission."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": f"Name for the new {display} (must be unique within the workspace)"},
                    "data": {"type": "object", "description": f"Field values for the new {display}", "additionalProperties": True},
                },
                "required": ["name"],
            },
            cc_endpoint_path=f"/api/v1/internal/management-tools/create_{singular}",
            mcp_hub_id=_next_management_uuid(),
            parity=(resource_type, create_action),
            category="management",
        ))

        SystemToolRegistry.register(SystemTool(
            name=f"update_{singular}",
            description=(
                f"Update an existing {display} by id. Performs the same action "
                f"as the Control Center management UI. Requires {resource_type}:{update_action} permission."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": f"ID of the {display} to update"},
                    "name": {"type": "string", "description": f"New name for the {display} (optional)"},
                    "data": {"type": "object", "description": f"Field values to update", "additionalProperties": True},
                },
                "required": ["id"],
            },
            cc_endpoint_path=f"/api/v1/internal/management-tools/update_{singular}",
            mcp_hub_id=_next_management_uuid(),
            parity=(resource_type, update_action),
            category="management",
        ))

        SystemToolRegistry.register(SystemTool(
            name=f"list_{plural}",
            description=(
                f"List {plural.replace('_', ' ')} in the current workspace. "
                f"Requires {resource_type}:read permission."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum number of records to return (default 50)"},
                    "offset": {"type": "integer", "description": "Pagination offset (default 0)"},
                },
                "required": [],
            },
            cc_endpoint_path=f"/api/v1/internal/management-tools/list_{plural}",
            mcp_hub_id=_next_management_uuid(),
            parity=(resource_type, "read"),
            category="management",
        ))

        SystemToolRegistry.register(SystemTool(
            name=f"get_{singular}",
            description=(
                f"Read a single {display} by id. Requires {resource_type}:read permission."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": f"ID of the {display} to read"},
                    "name": {"type": "string", "description": f"Name of the {display} to read (alternative to id)"},
                },
                "required": [],
            },
            cc_endpoint_path=f"/api/v1/internal/management-tools/get_{singular}",
            mcp_hub_id=_next_management_uuid(),
            parity=(resource_type, "read"),
            category="management",
        ))


_register_management_tools()


# ── Agent-type binding schema enrichment (FIX-20261031-071721) ──────────────
#
# create_agent_type / update_agent_type accept optional ``skill_ids`` and
# ``sop_ids`` (id or name, tenant-scoped) in their ``data`` object to
# associate skills/SOPs with the agent type.  Semantics: ADDITIVE MERGE —
# provided entries are added; existing bindings are never removed (no delete
# verb in this toolset); re-binding an existing pair is an idempotent no-op.
# Mutating the registered tools in place keeps their stable mcp_hub_ids and
# parity pairs untouched.


def _enrich_agent_type_binding_schemas() -> None:
    binding_fields: dict[str, Any] = {
        "skill_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Skill ids or names to associate with the agent "
            "type (tenant-scoped; unknown value → 404)",
        },
        "sop_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "SOP ids or names to associate with the agent "
            "type (tenant-scoped; unknown value → 404)",
        },
    }
    for tool_name, action_verb in (
        ("create_agent_type", "created"),
        ("update_agent_type", "updated"),
    ):
        tool = SystemToolRegistry.get(tool_name)
        if tool is None:
            continue
        data_prop = tool.parameters.setdefault("properties", {}).setdefault(
            "data", {"type": "object", "additionalProperties": True}
        )
        data_prop.setdefault("properties", {}).update(binding_fields)
        tool.description = (
            tool.description
            + " The data object may include skill_ids and/or sop_ids (ids or "
            "names) to ASSOCIATE skills/SOPs with the agent type. Bindings are "
            "additive: provided entries are added to the existing set, existing "
            "bindings are never removed, and re-binding an already-associated "
            "skill/SOP is an idempotent no-op. An agent type should always have "
            f"at least one skill/SOP associated (or an assigned role) by the time it is "
            f"{action_verb}, otherwise it cannot act."
        )


_enrich_agent_type_binding_schemas()


# ── Agent-role grant schema enrichment (FIX-20261031-131030) ────────────────
#
# create_agent_role / update_agent_role accept optional ``skill_ids`` and
# ``sop_ids`` (id or name, tenant-scoped) in their ``data`` object to GRANT
# skills/SOPs to the role.  Role-based agents resolve their runtime tool
# access from the role's grants, so granting the skill to the agent's role is
# what makes it accessible at runtime.  Same additive/idempotent semantics as
# the agent-type bindings.


def _enrich_agent_role_grant_schemas() -> None:
    grant_fields: dict[str, Any] = {
        "skill_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Skill ids or names to GRANT to the role "
            "(tenant-scoped; unknown value → 404)",
        },
        "sop_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "SOP ids or names to GRANT to the role "
            "(tenant-scoped; unknown value → 404)",
        },
    }
    for tool_name in ("create_agent_role", "update_agent_role"):
        tool = SystemToolRegistry.get(tool_name)
        if tool is None:
            continue
        data_prop = tool.parameters.setdefault("properties", {}).setdefault(
            "data", {"type": "object", "additionalProperties": True}
        )
        data_prop.setdefault("properties", {}).update(grant_fields)
        tool.description = (
            tool.description
            + " The data object may include skill_ids and/or sop_ids (ids or "
            "names) to GRANT skills/SOPs to the role. Role-based agents get "
            "their runtime tool access from the role's grants, so every "
            "skill/SOP the agent needs MUST be granted to its role. Grants "
            "are additive: provided entries are added to the existing set, "
            "existing grants are never removed, and re-granting an "
            "already-granted skill/SOP is an idempotent no-op."
        )


_enrich_agent_role_grant_schemas()


# ── Skill ↔ tool binding schema enrichment (FIX-20261101-000319) ────────────
#
# create_skill / update_skill accept optional ``tool_ids`` and ``tool_names``
# (canonical ``server____tool`` names — including ``cc____`` Control Center
# tools — or McpTool UUIDs; tenant-scoped) to associate MCP tools with the
# skill via ``SkillToolBinding`` rows.  Same additive/idempotent semantics as
# the agent-type/role bindings.


def _enrich_skill_tool_binding_schemas() -> None:
    binding_fields: dict[str, Any] = {
        "tool_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "MCP tool UUIDs to bind to the skill "
            "(tenant-scoped; unknown value → 404)",
        },
        "tool_names": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Canonical server____tool names to bind to the "
            "skill (e.g. 'supabase____run_sql', 'cc____create_skill'); "
            "tenant-scoped; unknown name → 404. Discover a server's tools "
            "with get_mcp_server first.",
        },
    }
    for tool_name, action_verb in (
        ("create_skill", "created"),
        ("update_skill", "updated"),
    ):
        tool = SystemToolRegistry.get(tool_name)
        if tool is None:
            continue
        data_prop = tool.parameters.setdefault("properties", {}).setdefault(
            "data", {"type": "object", "additionalProperties": True}
        )
        data_prop.setdefault("properties", {}).update(binding_fields)
        tool.description = (
            tool.description
            + " The data object may include tool_ids and/or tool_names "
            "(canonical server____tool names or UUIDs) to BIND MCP tools to "
            "the skill — a skill can only invoke tools BOUND to it. Bindings "
            "are additive: provided tools are added to the existing set, "
            "existing bindings are never removed, and re-binding an "
            "already-bound tool is an idempotent no-op. Discover an MCP "
            "server's synced tools with get_mcp_server (its 'tools' list) "
            "before binding. cc____ tools are Control Center management "
            "capabilities, distinct from general system____ tools. Skills "
            "without at least one bound tool cannot do anything. An unknown "
            "tool fails the whole call with 404 (no partial write)."
        )


_enrich_skill_tool_binding_schemas()


# ═══════════════════════════════════════════════════════════════════════════
# Assistant meta tools — progressive tool disclosure (O(1) context)
# ═══════════════════════════════════════════════════════════════════════════
#
# Instead of loading all ~36 management tool schemas into every assistant
# turn (~large payload), the conversational assistant context carries ONLY
# these constant meta tools:
#
#   invoke_management_tool      — dispatches to ANY registered management
#                                 tool through the existing management-tools
#                                 dispatch (permission parity re-enforced per
#                                 invocation against the signed-in user).
#   get_management_tool_schema  — full OpenAI schema for one tool, on demand.
#   list_management_tools       — cheap catalog (name + description +
#                                 permission requirement).
#   search_assistant_knowledge  — keyword search over the platform knowledge
#                                 corpus (app.services.agents.assistant_knowledge).
#
# The management execution tools stay registered and bound (they are what
# the wrapper dispatches to internally and what the parity map / resolve
# endpoint / external MCP clients use).  Meta tools carry NO parity — they
# never appear in the permission parity map.
#
# UUID allocation (continue the reserved system-tool block, decimal):
#   00000000-0000-0000-0000-000000000055  → invoke_management_tool
#   00000000-0000-0000-0000-000000000056  → get_management_tool_schema
#   00000000-0000-0000-0000-000000000057  → list_management_tools
#   00000000-0000-0000-0000-000000000058  → search_assistant_knowledge

_META_MANAGEMENT_TOOL_NAMES: tuple[str, ...] = (
    "invoke_management_tool",
    "get_management_tool_schema",
    "list_management_tools",
    "search_assistant_knowledge",
    # FIX-20261031-133253: the assistant MUST be able to pause for human
    # approval before any create/update — human_intervene is the 5th
    # always-loaded meta definition. It carries no parity (not a management
    # action) and routes to the existing CC /internal/system-tools/
    # human-intervene endpoint via the AR→CH system-tool path; the AR
    # wrapper already maps it to the LangGraph interrupt() HITL flow.
    "human_intervene",
)

_META_UUIDS: dict[str, str] = {
    "invoke_management_tool": "00000000-0000-0000-0000-000000000055",
    "get_management_tool_schema": "00000000-0000-0000-0000-000000000056",
    "list_management_tools": "00000000-0000-0000-0000-000000000057",
    "search_assistant_knowledge": "00000000-0000-0000-0000-000000000058",
}

SystemToolRegistry.register(SystemTool(
    name="invoke_management_tool",
    description=(
        "Invoke any registered Control Center management tool by name — e.g. "
        "create_skill, update_agent_type, list_model_configs. Pass the target "
        "tool_name and its args object (each tool's exact argument schema is "
        "available via get_management_tool_schema). Every invocation is "
        "authorized against the signed-in user's own permissions; deletion is "
        "not supported."
    ),
    parameters={
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Bare name of the management tool to invoke "
                "(see list_management_tools)",
            },
            "args": {
                "type": "object",
                "description": "Argument object for the target tool (see "
                "get_management_tool_schema for its exact schema)",
                "additionalProperties": True,
            },
        },
        "required": ["tool_name", "args"],
    },
    cc_endpoint_path="/api/v1/internal/management-tools/invoke_management_tool",
    mcp_hub_id=uuid.UUID(_META_UUIDS["invoke_management_tool"]),
    category="management",
    skill_name="invoke-management-tool",
    skill_description=(
        "Progressive-disclosure wrapper: executes any Control Center "
        "management tool by name with per-call permission parity."
    ),
    skill_instructions=(
        "Use this skill to run any Agents-menu management operation without "
        "loading every tool schema: pass the target management tool name and "
        "its arguments. Discover available tools with list_management_tools "
        "and inspect exact argument schemas with get_management_tool_schema "
        "before invoking an unfamiliar tool."
    ),
))

SystemToolRegistry.register(SystemTool(
    name="get_management_tool_schema",
    description=(
        "Return the full OpenAI function-calling schema (exact parameters) "
        "for one registered management tool, e.g. 'create_skill'. Call this "
        "before invoking an unfamiliar tool via invoke_management_tool."
    ),
    parameters={
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Bare name of the management tool (e.g. 'update_sop')",
            },
        },
        "required": ["tool_name"],
    },
    cc_endpoint_path="/api/v1/internal/management-tools/get_management_tool_schema",
    mcp_hub_id=uuid.UUID(_META_UUIDS["get_management_tool_schema"]),
    category="management",
))

SystemToolRegistry.register(SystemTool(
    name="list_management_tools",
    description=(
        "List every available Control Center management tool with a one-line "
        "description and the permission it requires "
        "(resource_type:action). Cheap catalog — use it to discover which "
        "management actions exist before invoking one."
    ),
    parameters={"type": "object", "properties": {}},
    cc_endpoint_path="/api/v1/internal/management-tools/list_management_tools",
    mcp_hub_id=uuid.UUID(_META_UUIDS["list_management_tools"]),
    category="management",
))

SystemToolRegistry.register(SystemTool(
    name="search_assistant_knowledge",
    description=(
        "Search the Parthenon platform knowledge base for domain rules "
        "(agent-type composition, roles/identities, model availability, "
        "input/output types, MCP hub, naming rules, boundaries). Use this "
        "before performing management actions whose platform rules you are "
        "unsure about."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language query, e.g. 'how do I attach "
                "MCP tools to an agent type'",
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum number of rule entries to return (default 3)",
            },
        },
        "required": ["query"],
    },
    cc_endpoint_path="/api/v1/internal/management-tools/search_assistant_knowledge",
    mcp_hub_id=uuid.UUID(_META_UUIDS["search_assistant_knowledge"]),
    category="management",
))

# ── Meta-tool registry accessor ─────────────────────────────────────────────


def _get_meta_tool_names(cls: type[SystemToolRegistry]) -> frozenset[str]:
    """Return the bare names of the assistant meta (progressive-disclosure) tools.

    These are the CONSTANT, small set of tool definitions the conversational
    assistant carries in context instead of all management execution schemas.
    They carry no parity mapping and never appear in ``get_parity_map()``.
    """
    return frozenset(_META_MANAGEMENT_TOOL_NAMES)


SystemToolRegistry.get_meta_tool_names = classmethod(_get_meta_tool_names)  # type: ignore[attr-defined]
