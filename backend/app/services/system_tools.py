"""Centralized system tool naming module — thin facade over SystemToolRegistry.

All canonical data lives in ``SystemToolRegistry`` (system_tool_registry.py).
This module re-exports the names and helpers for backward-compatible imports
across the codebase.  Do not add new tool names here; register them in
``system_tool_registry.py`` instead.
"""
from __future__ import annotations

from app.services.agents.system_tool_registry import SystemToolRegistry

#: Canonical bare names for all built-in system tools — derived from registry.
#: Never edit this directly; update ``SystemToolRegistry`` registrations instead.
SYSTEM_TOOL_NAMES: frozenset[str] = SystemToolRegistry.get_names()

#: Display names with the "system/" prefix.
SYSTEM_TOOL_DISPLAY_NAMES: frozenset[str] = frozenset(
    f"system/{n}" for n in SYSTEM_TOOL_NAMES
)


def is_system_tool(name: str) -> bool:
    """Return True if *name* refers to a built-in system tool (any naming format)."""
    return SystemToolRegistry.is_system_tool(name)


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

