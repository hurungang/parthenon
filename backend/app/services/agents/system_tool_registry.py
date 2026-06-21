"""Centralised registry for all built-in system tools.

Usage::

    SystemToolRegistry.get_names()          # frozenset of bare names
    SystemToolRegistry.get_schema("save_result")  # OpenAI function schema
    SystemToolRegistry.is_system_tool(name) # bool, any naming format
    SystemToolRegistry.parse_name(name)     # ("system", "bare_name") or None

Adding a new system tool requires **exactly one change** — register a
``SystemTool`` instance.  Everything else (LLM tool definitions, routing,
name validation, canonicalisation) flows from the registry automatically.
"""

from __future__ import annotations

from typing import Any

#: Four-underscore separator used in canonical ``server____tool`` names.
TOOL_SEPARATOR = "____"


class SystemTool:
    """Descriptor for a built-in system tool."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        if not name or not isinstance(name, str):
            raise ValueError("SystemTool name must be a non-empty string")
        if not description or not isinstance(description, str):
            raise ValueError("SystemTool description must be a non-empty string")

        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}

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

SystemToolRegistry.register(SystemTool(
    name="save_result",
    description="Save the final result of agent execution to be retrieved later",
    parameters={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The result content to save",
            },
            "title": {
                "type": "string",
                "description": "Optional title for the result",
            },
        },
        "required": ["content"],
    },
))

SystemToolRegistry.register(SystemTool(
    name="send_notification",
    description=(
        "Send a notification to a recipient group via configured channels"
    ),
    parameters={
        "type": "object",
        "properties": {
            "group_slug": {
                "type": "string",
                "description": "Slug of the recipient group",
            },
            "channel": {
                "type": "string",
                "description": (
                    "Optional channel selector within the recipient group "
                    "(channel name, channel type, or channel ID)."
                ),
            },
            "subject": {
                "type": "string",
                "description": "Notification subject / title",
            },
            "body": {
                "type": "string",
                "description": "Notification body content",
            },
            "priority": {
                "type": "string",
                "enum": ["low", "normal", "high"],
                "description": "Notification priority level",
            },
        },
        "required": ["group_slug", "body"],
    },
))

SystemToolRegistry.register(SystemTool(
    name="get_recipient_group",
    description="Get information about a notification recipient group",
    parameters={
        "type": "object",
        "properties": {
            "group_slug": {
                "type": "string",
                "description": "Slug of the recipient group to query",
            },
        },
        "required": ["group_slug"],
    },
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
            "reason": {
                "type": "string",
                "description": "Explanation of why human input is needed",
            },
            "intervention_type": {
                "type": "string",
                "enum": ["approval", "choice", "text"],
                "description": "Type of intervention needed",
            },
            "choices": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Available options when intervention_type is 'choice'"
                ),
            },
            "prompt": {
                "type": "string",
                "description": "Descriptive prompt when intervention_type is 'text'",
            },
        },
        "required": ["reason", "intervention_type"],
    },
))

SystemToolRegistry.register(SystemTool(
    name="query_result",
    description=(
        "Query past typed agent outputs by data type name. "
        "Returns a list of typed results conforming to the requested schema. "
        "Call this when you need to retrieve and analyze past outputs "
        "produced by agents using the specified data type."
    ),
    parameters={
        "type": "object",
        "properties": {
            "data_type_name": {
                "type": "string",
                "description": (
                    "Name or slug of the data type to query "
                    "(e.g. 'incident_report' or 'Incident Report')"
                ),
            },
            "filters": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "string",
                        "description": (
                            "ISO-8601 date string — filter results created "
                            "on or after this date (e.g. '2025-01-01')"
                        ),
                    },
                    "date_to": {
                        "type": "string",
                        "description": (
                            "ISO-8601 date string — filter results created "
                            "on or before this date (e.g. '2025-12-31')"
                        ),
                    },
                    "field_filters": {
                        "type": "object",
                        "description": (
                            "Key-value pairs to filter by field values "
                            "(e.g. {'severity': 'high', 'region': 'us-east'})"
                        ),
                        "additionalProperties": True,
                    },
                },
                "description": "Optional filters to narrow results",
            },
        },
        "required": ["data_type_name"],
    },
))
