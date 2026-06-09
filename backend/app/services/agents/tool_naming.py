"""Unified tool name resolver for all services.

All tool names use the canonical ``server____tool`` format with four underscores
as the separator:

  - System tools: ``system____save_result``, ``system____send_notification``,
                  ``system____get_recipient_group``
  - MCP tools:    ``hello-world____helloWorld``, ``github____list_prs``, etc.

The OpenAI API requires tool names to match ``^[a-zA-Z0-9_-]+$``.  The ``____``
separator is safe, but for maximum compatibility the sanitiser converts it to
``__`` (double underscore) before sending to OpenAI, then restores via the
tool_name_map on the way back.

:data:`RESERVED_SERVER_NAMES` ensures that no custom MCP server can be named
``"system"`` — doing so would collide with built-in system tools.
"""
from __future__ import annotations

from app.services.agents.system_tool_registry import SystemToolRegistry

#: Four-underscore separator between server slug and tool name.
TOOL_SEPARATOR = "____"

#: Server slugs that are reserved and cannot be used for custom MCP servers.
RESERVED_SERVER_NAMES: frozenset[str] = frozenset({"system"})

#: Bare names of the built-in system tools — sourced from the registry.
_LEGACY_SYSTEM_TOOL_NAMES: frozenset[str] = SystemToolRegistry.get_names()


def build_tool_name(server: str, tool: str) -> str:
    """Build a canonical tool name from server and tool components.

    Args:
        server: Server slug (e.g. ``"system"``, ``"hello-world"``).
        tool:   Bare tool name (e.g. ``"save_result"``, ``"helloWorld"``).

    Returns:
        Canonical tool name in ``server____tool`` format.

    Example::

        >>> build_tool_name("system", "save_result")
        'system____save_result'
    """
    return f"{server}{TOOL_SEPARATOR}{tool}"


def parse_tool_name(name: str) -> tuple[str, str]:
    """Split a canonical tool name into ``(server, tool)`` parts.

    Accepts the canonical ``server____tool`` format.  For backward-compatibility,
    bare legacy names like ``"save_result"`` are treated as system tools (i.e.
    they return ``("system", "save_result")``).

    Args:
        name: Tool name to parse.

    Returns:
        Tuple ``(server_name, bare_tool_name)``.

    Raises:
        ValueError: If *name* contains multiple ``____`` separators, has an
                    empty component, or is not a known legacy system tool name.

    Examples::

        >>> parse_tool_name("system____save_result")
        ('system', 'save_result')
        >>> parse_tool_name("hello-world____helloWorld")
        ('hello-world', 'helloWorld')
        >>> parse_tool_name("save_result")  # legacy bare name
        ('system', 'save_result')
    """
    if TOOL_SEPARATOR in name:
        parts = name.split(TOOL_SEPARATOR)
        if len(parts) != 2:
            raise ValueError(
                f"Tool name '{name}' contains multiple '{TOOL_SEPARATOR}' separators; "
                "expected exactly one."
            )
        server, tool = parts
        if not server or not tool:
            raise ValueError(
                f"Tool name '{name}' has an empty server or tool component."
            )
        return server, tool

    # Legacy bare-name fallback — treat as built-in system tool.
    if SystemToolRegistry.is_system_tool(name):
        return "system", name

    raise ValueError(
        f"Tool name '{name}' has no '{TOOL_SEPARATOR}' separator and is not a known "
        "legacy system tool name."
    )


def is_system_tool(name: str) -> bool:
    """Return ``True`` if *name* refers to a built-in system tool.

    Delegates to :class:`SystemToolRegistry` which acts as the single
    source of truth for all registered system tools.

    Args:
        name: Tool name in any supported format.

    Returns:
        ``True`` if the tool is a system tool; ``False`` otherwise.
    """
    return SystemToolRegistry.is_system_tool(name)


def get_server_name(name: str) -> str:
    """Return the server slug from a canonical tool name.

    Args:
        name: Canonical tool name (e.g. ``"system____save_result"``).

    Returns:
        Server slug (e.g. ``"system"``).

    Raises:
        ValueError: If *name* cannot be parsed (see :func:`parse_tool_name`).
    """
    server, _ = parse_tool_name(name)
    return server


def get_bare_tool_name(name: str) -> str:
    """Return the bare tool name suffix from a canonical tool name.

    Args:
        name: Canonical tool name (e.g. ``"system____save_result"``).

    Returns:
        Bare tool name (e.g. ``"save_result"``).

    Raises:
        ValueError: If *name* cannot be parsed (see :func:`parse_tool_name`).
    """
    _, tool = parse_tool_name(name)
    return tool
