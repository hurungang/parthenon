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
        "Iteration saver: combine MULTIPLE associated tool calls plus "
        "intermediate computation into ONE sandboxed script, so a chain that "
        "would cost several LLM iterations costs one. Use it only when the "
        "workflow is script-feasible (deterministic data flow between calls) "
        "and the request warrants it. Inside the sandbox, `tools` is available "
        "to call YOUR associated MCP tools by their names — the facade exposes "
        "exactly the tools associated with you. Define run(context, tools), "
        "which must return a dict. Do NOT use it for a single tool call or a "
        "purely conversational answer — call those tools directly / reply "
        "directly. Secondary use: verification primitive — run a script "
        "version's python_source through the real sandbox (pass inline "
        "python_source or script_version_id); a script that runs here runs at "
        "serving time."
    ),
    parameters={
        "type": "object",
        "properties": {
            "python_source": {"type": "string", "description": "Sandboxed Python defining run(context, tools) — call your associated MCP tools via `tools.<name>(...)`, do intermediate computation, and return a dict (often one derived field from the last call's result)"},
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


# ── Typed per-family data schemas (generalized enrichment) ──────────────────
#
# FIX-20261108 (cc-assistant-management-tool-coverage Phase 3): the former
# one-off enrichment functions (_enrich_agent_type_binding_schemas,
# _enrich_agent_role_grant_schemas, _enrich_skill_tool_binding_schemas) are
# subsumed by this single per-family typed schema declaration.  Every
# create_<resource> / update_<resource> tool's ``data`` object gets NAMED,
# TYPED, DESCRIBED properties (replacing the free-form
# ``additionalProperties: true`` pass-through) and the tool description states
# the full field set, required-vs-optional, and additive-merge list semantics.
# The registered tools are MUTATED IN PLACE exactly as the old enrichment did,
# so every ``mcp_hub_id`` and parity pair stays byte-stable.
#
# Field declarations use small schema-builder helpers.  Id-or-name FK fields
# accept a UUID or the entity's exact name (tenant-scoped; unknown → 404).
# Enum fields carry their exact value lists (verified against the SQLAlchemy
# models in app.db.models.agents / scheduling).

_SLUG_PATTERN_HINT = "lowercase letters, digits, hyphens (must match ^[a-z0-9](-?[a-z0-9])*$)"


def _s(desc: str, *, pattern: str | None = None) -> dict[str, Any]:
    prop: dict[str, Any] = {"type": "string", "description": desc}
    if pattern:
        prop["pattern"] = pattern
    return prop


def _slist(desc: str) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "string"},
        "description": desc,
    }


def _objlist(desc: str) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "object", "additionalProperties": True},
        "description": desc,
    }


def _bool_field(desc: str) -> dict[str, Any]:
    return {"type": "boolean", "description": desc}


def _obj_field(desc: str) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": True, "description": desc}


def _enum_field(values: tuple[str, ...], desc: str) -> dict[str, Any]:
    return {
        "type": "string",
        "enum": list(values),
        "description": f"{desc} Allowed values: {', '.join(values)}.",
    }


#: Exact enum value lists (mirrors of the SQLAlchemy models — verified by the
#: registry invariant test against app.db.models).
_INPUT_TYPES: tuple[str, ...] = ("none", "typed", "conversation")  # AgentInputType
_OUTPUT_TYPES: tuple[str, ...] = ("auto", "typed", "markdown")  # AgentOutputType
_IDENTITY_TYPES: tuple[str, ...] = (
    "realm_user",
    "oauth",
    "service_account",
    "user_delegate",
)  # AgentIdentityType
_IDENTITY_STATUSES: tuple[str, ...] = (
    "active",
    "suspended",
    "deprovisioned",
)  # AgentIdentityStatus
_PROVIDER_TYPES: tuple[str, ...] = (
    "openai",
    "anthropic",
    "litellm_proxy",
    "azure_openai",
    "gemini",
    "mistral",
    "cohere",
    "groq",
    "together",
    "fireworks",
    "perplexity",
    "deepseek",
)  # ModelProvider
_TOKEN_ENFORCEMENT_MODES: tuple[str, ...] = ("observe", "enforce")
_TOKEN_FALLBACK_MODES: tuple[str, ...] = (
    "observe_and_log",
    "stop_on_next_hard_guardrail",
)
_CONVERSATIONAL_VISIBILITY_MODES: tuple[str, ...] = ("enabled", "disabled")
_CONVERSATIONAL_CONTINUATION_POLICIES: tuple[str, ...] = ("allow",)
_TARGET_TYPES: tuple[str, ...] = ("agent",)  # JobTargetType

_ID_OR_NAME = "(accepts a UUID or the entity's exact name, tenant-scoped; unknown value fails with 404 and no partial write)"

_GUARDRAIL_FIELDS: dict[str, Any] = {
    "guardrail_max_iterations": {
        "type": "integer",
        "description": "Guardrail: max LLM iterations per execution (1–1000; default 10).",
    },
    "guardrail_max_delegation_depth": {
        "type": "integer",
        "description": "Guardrail: max agent-to-agent delegation depth (0–32; default 3).",
    },
    "guardrail_max_delegated_steps": {
        "type": "integer",
        "description": "Guardrail: max delegated steps across the delegation tree (0–5000; default 20).",
    },
    "guardrail_execution_timeout_seconds": {
        "type": "integer",
        "description": "Guardrail: whole-execution timeout in seconds (1–86400; default 300).",
    },
    "guardrail_token_budget": {
        "type": "integer",
        "description": "Guardrail: optional token budget per execution (1–10000000; omit for none).",
    },
    "guardrail_token_enforcement_mode": _enum_field(
        _TOKEN_ENFORCEMENT_MODES,
        "Guardrail token enforcement mode (default observe; conversational agent types cannot use enforce).",
    ),
    "guardrail_token_fallback_mode": _enum_field(
        _TOKEN_FALLBACK_MODES,
        "Guardrail fallback when the provider cannot hard-enforce tokens (default observe_and_log).",
    ),
    "guardrail_conversational_token_visibility_mode": _enum_field(
        _CONVERSATIONAL_VISIBILITY_MODES,
        "Whether conversational token-usage snapshots are emitted (default enabled).",
    ),
    "guardrail_conversational_continuation_policy": _enum_field(
        _CONVERSATIONAL_CONTINUATION_POLICIES,
        "Conversational continuation behavior after the token threshold is reached (default allow).",
    ),
}

_SOP_STEP_TYPES: tuple[str, ...] = ("skill_invocation", "agent_delegation")  # SopStepType

_SOP_STEP_ITEMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "order": {
            "type": "integer",
            "description": "REQUIRED integer position of the step in the ordered list.",
        },
        "step_type": _enum_field(
            _SOP_STEP_TYPES,
            "Kind of step (default skill_invocation).",
        ),
        "skill_id": _s(
            f"Skill {_ID_OR_NAME} — REQUIRED for skill_invocation steps; not allowed on agent_delegation steps."
        ),
        "target_agent_type_id": _s(
            f"Target agent type {_ID_OR_NAME} — REQUIRED for agent_delegation steps; "
            "not allowed on skill_invocation steps. Delegation steps gate the permissions "
            "of every role bound to this SOP."
        ),
        "name": _s("Optional short step name."),
        "description": _s("Optional step description."),
        "step_config": _obj_field("Optional JSON configuration for the step."),
    },
    "required": ["order"],
    "additionalProperties": False,
}

#: Per-family ``data`` field declarations.  ``create`` / ``update`` select
#: which optional extras apply; ``required_create`` lists fields the handler
#: rejects a create without; ``merge`` lists additive-merge list fields.
_MANAGEMENT_DATA_FIELDS: dict[str, dict[str, Any]] = {
    "skill": {
        "fields": {
            "description": _s("Short description of what the skill does."),
            "instructions": _s("Skill instructions shown to agents that invoke it."),
            "is_active": _bool_field("Whether the skill is active (default true)."),
            "tool_ids": _slist(
                f"MCP tool UUIDs to BIND to the skill {_ID_OR_NAME}. Bindings are "
                "additive and idempotent. Discover tools with get_mcp_server first."
            ),
            "tool_names": _slist(
                "Canonical server____tool names to BIND to the skill "
                "(e.g. 'supabase____run_sql', 'cc____create_skill'); bindings are "
                "additive and idempotent; tenant-scoped; unknown name → 404. "
                "cc____ tools are Control Center management capabilities."
            ),
        },
        "required_create": (),
        "merge": ("tool_ids", "tool_names"),
        "merge_note": (
            "TOOL BINDINGS are ADDITIVE: provided tools are added to the existing set, "
            "existing bindings are never removed, re-binding is an idempotent no-op, and "
            "an unknown tool fails the whole call with 404 (no partial write). A skill "
            "without at least one bound tool cannot do anything."
        ),
    },
    "sop": {
        "fields": {
            "description": _s("Short description of the SOP."),
            "instructions": _s("SOP instructions / procedure body."),
            "is_active": _bool_field("Whether the SOP is active (default true)."),
            "steps": {
                "type": "array",
                "items": _SOP_STEP_ITEMS,
                "description": (
                    "Ordered SOP steps. REPLACE semantics: on update_sop the provided list "
                    "REPLACES the entire existing step list — omitted steps are DELETED — so "
                    "ALWAYS send the complete desired list (omitting 'steps' leaves them "
                    "untouched). Each skill_invocation step REQUIRES skill_id (skill id or "
                    "exact name); each agent_delegation step REQUIRES target_agent_type_id "
                    "(agent type id or exact name) — delegation steps gate the role "
                    "permissions of every role bound to the SOP."
                ),
            },
        },
        "required_create": (),
        "merge": (),
        "update_note": (
            "STEP LIST is a FULL REPLACEMENT, not additive: when 'steps' is present in an "
            "update it replaces the whole ordered list and omitted steps are deleted; when "
            "'steps' is absent the existing steps are untouched. Replacing steps invalidates "
            "the permission cache of every role bound to the SOP (agent_delegation steps "
            "affect allowed agent types)."
        ),
    },
    "agent_type": {
        "fields": {
            "description": _s("Short description of the agent type."),
            "identity_id": _s(f"Agent identity to attach to the type {_ID_OR_NAME}."),
            "role_id": _s(f"Agent role to attach to the type {_ID_OR_NAME}."),
            "model_id": _s(
                "Provider-scoped model identifier (e.g. 'gpt-4o') — must exist in an "
                "ENABLED model of a tenant Model Configuration (see list_model_configs)."
            ),
            "is_active": _bool_field("Whether the agent type is active (default true)."),
            "system_instruction": _s("System instruction for the agent."),
            "input_type": _enum_field(
                _INPUT_TYPES,
                "How the agent accepts input (default none). Conversational types cannot take output_data_type_id.",
            ),
            "input_schema": _obj_field("JSON schema for typed input (input_type=typed)."),
            "output_type": _enum_field(_OUTPUT_TYPES, "How the agent produces output (default auto)."),
            "output_schema": _obj_field("JSON schema for typed output."),
            "output_data_type_id": _s(
                f"Agent Data Type for typed outputs {_ID_OR_NAME}. REJECTED for conversational "
                "(input_type=conversation) agent types — structured 400."
            ),
            "skill_ids": _slist(f"Skill ids or names to ASSOCIATE with the agent type {_ID_OR_NAME}; bindings are additive and idempotent."),
            "sop_ids": _slist(f"SOP ids or names to ASSOCIATE with the agent type {_ID_OR_NAME}; bindings are additive and idempotent."),
            **_GUARDRAIL_FIELDS,
        },
        "required_create": (),
        "merge": ("skill_ids", "sop_ids"),
        "merge_note": (
            "SKILL/SOP BINDINGS are ADDITIVE: provided entries are added, existing bindings "
            "are never removed, re-binding is an idempotent no-op. An agent type should always "
            "have at least one skill/SOP associated (or an assigned role) by the time it is "
            "written, otherwise it cannot act."
        ),
    },
    "agent_role": {
        "fields": {
            "description": _s("Short description of the role."),
            "skill_ids": _slist(f"Skill ids or names to GRANT to the role {_ID_OR_NAME}; grants are additive and idempotent."),
            "sop_ids": _slist(f"SOP ids or names to GRANT to the role {_ID_OR_NAME}; grants are additive and idempotent."),
            "mcp_session_mappings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "server": _s(f"MCP server {_ID_OR_NAME} — REQUIRED."),
                        "session": _s(
                            "MCP session id, or the session NAME scoped to that server "
                            "(session names are unique per server) — REQUIRED; must belong "
                            "to that server."
                        ),
                    },
                    "required": ["server", "session"],
                    "additionalProperties": False,
                },
                "description": (
                    "Explicit MCP session mappings for the role (each {server, session}, "
                    "both id-or-name) — one session per MCP "
                    "server (agent MCP tools only work when the role maps a session for "
                    "every server its skills touch). Additive: mappings are added, never "
                    "removed or re-pointed. After explicit mappings, defaults apply "
                    "automatically so EVERY server ends up mapped: a server with a "
                    "passthrough session defaults to it; a server with exactly one "
                    "session defaults to that; a server with MULTIPLE sessions defaults "
                    "to the FIRST one (is_default first, then oldest) and the tool "
                    "response carries a warning — CONFIRM the defaulted session with the "
                    "user (alternatives are listed in the warning) and re-map if needed."
                ),
            },
        },
        "required_create": (),
        "merge": ("skill_ids", "sop_ids", "mcp_session_mappings"),
        "merge_note": (
            "GRANTS are ADDITIVE: provided entries are added, existing grants are never "
            "removed, re-granting is an idempotent no-op. Role-based agents get their runtime "
            "tool access from the role's grants, so every skill/SOP the agent needs MUST be "
            "granted to its role. MCP SESSION MAPPINGS: one session per server per role; "
            "mappings are added, never removed or re-pointed (re-mapping a server to a "
            "different session is a 409 conflict). Every MCP server the role's skills touch "
            "needs a mapped session or the MCP tools will not work for agents using the "
            "role — check the response 'warnings' for multi-session servers that were "
            "defaulted to the first session and confirm the choice with the user "
            "(alternatives are listed in the warning)."
        ),
    },
    "agent_identity": {
        "fields": {
            "description": _s("Short description of the identity (not a write field on create)."),
            "realm_name": _s("Agent-realm name the identity lives in."),
            "realm_username": _s("Username within the agent realm."),
            "status": _enum_field(_IDENTITY_STATUSES, "Lifecycle status (default active)."),
            "identity_type": _enum_field(
                _IDENTITY_TYPES,
                "Type of OIDC principal (create only, default realm_user; not updatable).",
            ),
            "role_ids": _slist(
                f"Role ids or names to ASSIGN to the identity {_ID_OR_NAME} (update only; "
                "assignments are additive and idempotent)."
            ),
        },
        "required_create": (),
        "create_only": ("identity_type",),
        "update_only": ("role_ids",),
        "merge": ("role_ids",),
        "merge_note": (
            "ROLE ASSIGNMENTS are ADDITIVE: provided roles are added, existing assignments "
            "are never removed, re-assigning is an idempotent no-op. Tokens and credentials "
            "are never accepted or returned."
        ),
    },
    "model_config": {
        "fields": {
            "display_name": _s("Display name (alternative key to the top-level name argument)."),
            "provider_type": _enum_field(_PROVIDER_TYPES, "LLM provider (REQUIRED at create)."),
            "api_base_url": _s("Optional API base URL override."),
            "api_key": _s(
                "WRITE-ONLY API key — accepted and encrypted at storage, NEVER echoed in any result."
            ),
            "enabled_models": _slist("Model identifiers enabled for this config."),
            "is_disabled": _bool_field("Vendor-level disable toggle (default false)."),
        },
        "required_create": ("provider_type",),
        "merge": (),
    },
    "schedule": {
        "fields": {
            "description": _s("Short description of the schedule."),
            "cron_expression": _s(
                "Cron expression (e.g. '0 9 * * *'); alias 'cron' accepted. REQUIRED at create."
            ),
            "cron": _s("Alias for cron_expression."),
            "payload": _obj_field("JSON object payload passed to the target on each trigger."),
            "target_type": _enum_field(
                _TARGET_TYPES, "Schedule target type (create only, default agent; immutable after create)."
            ),
            "target_id": _s(
                f"Target entity (agent type) {_ID_OR_NAME}. REQUIRED at create; immutable after create."
            ),
            "agent_type_id": _s("Alias for target_id for agent schedules."),
        },
        "required_create": ("cron_expression", "target_id"),
        "create_only": ("target_type", "target_id", "agent_type_id", "cron"),
        "update_only": (),
        "merge": (),
        "update_note": (
            "Updates accept name, description, cron_expression and payload only — "
            "target_type/target_id are immutable after create; changing the cron expression "
            "re-registers the schedule with the scheduler."
        ),
    },
    "data_type": {
        "fields": {
            "description": _s("Short description of the data type."),
            "slug": _s(
                f"URL-safe slug, unique per tenant (create only; REQUIRED at create; immutable after create). Pattern: {_SLUG_PATTERN_HINT}."
            ),
            "fields": _objlist(
                "Typed field definitions (each: name, type one of string/number/boolean/date/enum, "
                "required, enum values when type=enum). At least one field; duplicate field names rejected. REQUIRED at create."
            ),
        },
        "required_create": ("slug", "fields"),
        "create_only": ("slug",),
        "merge": (),
    },
    "mcp_server": {
        "fields": {
            "description": _s("Short description of the server connection."),
            "slug": _s(
                f"URL-safe slug, unique per tenant (create only; REQUIRED at create; immutable after create). Pattern: {_SLUG_PATTERN_HINT}."
            ),
            "base_url": _s("Base URL of the MCP server (REQUIRED at create)."),
        },
        "required_create": ("slug", "base_url"),
        "create_only": ("slug",),
        "merge": (),
    },
}


def _apply_typed_management_schemas() -> None:
    """Mutate every registered create/update management tool in place.

    Replaces the free-form ``data`` pass-through with the per-family typed
    declaration and rewrites the tool description to state the full field
    set, required-vs-optional, and additive-merge list semantics.  In-place
    mutation keeps every ``mcp_hub_id`` and parity pair byte-stable.
    """
    for singular, plural, resource_type, _create_action, _update_action in _MANAGEMENT_RESOURCES:
        decl = _MANAGEMENT_DATA_FIELDS.get(singular)
        if decl is None:
            continue
        all_fields: dict[str, Any] = decl["fields"]
        create_only = set(decl.get("create_only", ()))
        update_only = set(decl.get("update_only", ()))
        required_create = list(decl.get("required_create", ()))
        merge_fields = decl.get("merge", ())
        merge_note = decl.get("merge_note") or ""
        update_note = decl.get("update_note") or ""

        for verb in ("create", "update"):
            tool = SystemToolRegistry.get(f"{verb}_{singular}")
            if tool is None:
                continue
            excluded = update_only if verb == "create" else create_only
            applicable = {
                field: schema
                for field, schema in all_fields.items()
                if field not in excluded
            }
            # ``description`` is a common top-level arg handled by the
            # generic registration; the handlers also accept it in data, so
            # keep it typed in data too (it already lives in all_fields).
            data_prop = tool.parameters.setdefault("properties", {}).setdefault(
                "data", {"type": "object"}
            )
            data_prop["type"] = "object"
            data_prop["properties"] = dict(applicable)
            data_prop["additionalProperties"] = False
            data_prop["description"] = (
                f"Field values for the {singular.replace('_', ' ')} — accepts ONLY the "
                "named properties listed; unknown fields are rejected with a structured "
                "error naming the accepted set."
            )
            if verb == "create" and required_create:
                data_prop["required"] = required_create

            required_txt = ""
            if verb == "create" and required_create:
                required_txt = (
                    f" Required in data at create: {', '.join(required_create)}."
                )
            merge_txt = ""
            if merge_note:
                applicable_merges = [f for f in merge_fields if f in applicable]
                if applicable_merges:
                    merge_txt = f" Additive-merge list fields: {', '.join(applicable_merges)}."
                merge_txt += f" {merge_note}"
            extra_txt = update_note if (verb == "update" and update_note) else ""
            tool.description = (
                f"{tool.description} The data object accepts exactly these fields: "
                f"{', '.join(applicable)}.{required_txt} Each property is typed and "
                "described in the schema; enum properties list their allowed values; "
                "id/name reference fields accept a UUID or the entity's exact name "
                "(tenant-scoped; unknown value → 404, no partial write)."
                f"{merge_txt}{extra_txt}"
            )


_apply_typed_management_schemas()


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
