"""Centralized system tool naming module.

Defines the canonical set of built-in system tools and helper functions
for consistent name resolution across all consumers (mcp_hub, agent_data,
runtime_executor).

Canonical form: bare name without prefix — e.g. ``"save_result"``
Display form:   prefixed name with server slug — e.g. ``"system/save_result"``

All consumers should import from this module to avoid naming drift.
"""
from __future__ import annotations

#: Canonical bare names for all built-in system tools.
SYSTEM_TOOL_NAMES: frozenset[str] = frozenset(
    {"save_result", "send_notification", "get_recipient_group", "human_intervene"}
)

#: Display names with the "system/" prefix — matches the ``name`` field returned by
#: ``_system_tool_reads()`` in mcp_hub.py and stored in the seeded DB rows.
SYSTEM_TOOL_DISPLAY_NAMES: frozenset[str] = frozenset(
    f"system/{n}" for n in SYSTEM_TOOL_NAMES
)


def is_system_tool(name: str) -> bool:
    """Return True if *name* refers to a built-in system tool.

    Accepts both canonical bare names (``"save_result"``) and the prefixed
    display names (``"system/save_result"``) for backward compatibility.
    Also handles OpenAI-sanitised names where ``/`` is replaced with ``_``
    (e.g. ``"system_save_result"``).
    """
    return get_canonical_name(name) in SYSTEM_TOOL_NAMES


def get_canonical_name(name: str) -> str:
    """Strip any ``"system/"`` or ``"system_"`` prefix to obtain the bare canonical name."""
    if name.startswith("system/"):
        return name[len("system/"):]
    if name.startswith("system_"):
        return name[len("system_"):]
    return name


def get_display_name(name: str) -> str:
    """Return the ``"system/{name}"`` display form used in the API and UI."""
    return f"system/{get_canonical_name(name)}"
