"""Authoring-time tool-name extraction from model-authored script source.

A sandboxed script's only egress is ``tools.call('<name>', ...)``. Two callers
need the literal names *without* executing anything:

* Control Center's script authoring validation (``generate_script`` /
  ``execute_script``) refuses a source that names a tool the agent was never
  granted, with the valid names returned for repair.
* Control Center's live-test ledger derives the **tool-call preview** shown on
  the operator's approval card from the saved script version's own source, and
  the Agent Runtime live-test runner re-checks that preview against the
  subject's grants before the script runs.

Kept in a neutral, database-free module so both services can import it (the
Control Center API layer re-exports :func:`extract_tools_call_names` for
backwards compatibility).
"""
from __future__ import annotations

import ast

__all__ = ["extract_tools_call_names", "preview_entries"]


def extract_tools_call_names(python_source: str) -> list[str]:
    """Return the literal tool names from ``tools.call('<name>', ...)`` calls.

    Only constant-string first arguments are collected (dynamic names cannot be
    validated — or previewed — statically), preserving source order and
    removing duplicates so the preview reads as "it will call: a, b".

    A source that does not parse returns an empty list; the caller decides
    whether that is a validation failure (``generate_script``) or simply "no
    previewable tool calls".
    """
    if not isinstance(python_source, str) or not python_source.strip():
        return []
    try:
        tree = ast.parse(python_source)
    except SyntaxError:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "call"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            name = node.args[0].value
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def preview_entries(
    tool_names: list[str], *, limit: int
) -> list[dict[str, str | None]]:
    """Project tool names onto the stored preview entry shape.

    A preview entry is *evidence of what the script will call*, never the unit
    of execution (the script is). ``limit`` bounds what is rendered on the
    approval card; the remainder is reported in a single ``+N more`` marker so
    the operator still sees the true total.
    """
    bounded = list(tool_names[: max(0, limit)])
    entries: list[dict[str, str | None]] = [
        {"tool_name": name, "arguments": {}, "purpose": "called by the script"}
        for name in bounded
    ]
    remaining = len(tool_names) - len(bounded)
    if remaining > 0:
        entries.append(
            {
                "tool_name": f"+{remaining} more",
                "arguments": {},
                "purpose": "additional calls in this script",
            }
        )
    return entries
