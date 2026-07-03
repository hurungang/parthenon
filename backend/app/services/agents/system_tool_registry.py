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

#: Four-underscore separator used in canonical ``server____tool`` names.
TOOL_SEPARATOR = "____"


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
    ) -> None:
        if not name or not isinstance(name, str):
            raise ValueError("SystemTool name must be a non-empty string")
        if not description or not isinstance(description, str):
            raise ValueError("SystemTool description must be a non-empty string")
        if not cc_endpoint_path:
            raise ValueError("SystemTool cc_endpoint_path must be a non-empty string")

        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}
        self.cc_endpoint_path = cc_endpoint_path
        self.mcp_hub_id = mcp_hub_id
        self.skill_name = skill_name
        self.skill_description = skill_description
        self.skill_instructions = skill_instructions

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
        """Full canonical name in ``system____<name>`` format."""
        return f"system{TOOL_SEPARATOR}{self.name}"


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

    # ── Name parsing & routing helpers ──────────────────────────────────

    @classmethod
    def is_system_tool(cls, name: str) -> bool:
        """Return ``True`` if *name* refers to a registered system tool.

        Accepts all supported naming formats:
        - Canonical ``system____save_result``
        - Bare ``save_result``
        - Old display ``system/save_result``
        - Old sanitised ``system_save_result``
        """
        if name in cls._tools:
            return True
        if name.startswith("system" + TOOL_SEPARATOR):
            return name[len("system" + TOOL_SEPARATOR):] in cls._tools
        if name.startswith("system/"):
            return name[len("system/"):] in cls._tools
        if name.startswith("system_"):
            return name[len("system_"):] in cls._tools
        return False

    @classmethod
    def parse_name(cls, name: str) -> tuple[str, str] | None:
        """Parse a tool name into ``(server, bare_tool)``.

        Returns ``("system", "<bare_name>")`` if the name refers to a
        registered system tool in any supported format, or ``None`` otherwise.
        """
        if TOOL_SEPARATOR in name:
            parts = name.split(TOOL_SEPARATOR)
            if len(parts) == 2 and parts[0] == "system":
                return ("system", parts[1])
        if name in cls._tools:
            return ("system", name)
        return None

    @classmethod
    def canonicalize_name(cls, name: str) -> str | None:
        """Convert *name* to canonical ``system____<bare>`` format.

        Returns ``None`` for names that do not match any registered system tool.
        """
        parsed = cls.parse_name(name)
        if parsed is None:
            return None
        return f"system{TOOL_SEPARATOR}{parsed[1]}"


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
# NOTE: save_result is intentionally absent.  The CC endpoint and
# LangChainSaveResultTool are retained only for the final session-completion
# flow in langchain_tool_wrapper.py.  Agents use save_data instead.
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
