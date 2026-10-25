"""MCP-only script boundary tests (E8, SEC2).

Two levels:

1. **Static source analysis** — the Agent Runtime script execution modules
   must contain no direct network, filesystem, database or subprocess I/O:
   MCP tool calls (via the CH client) plus local data processing are the
   only capabilities a compiled script has.
2. **Runtime enforcement** — the Script Runner rejects graphs that attempt
   non-MCP external access (network-target-shaped tool references) or carry
   credential-shaped fields, with a typed boundary violation that routes to
   the unconditional LLM fallback (E2).
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.agent_runtime.scripts.runner import (
    ExecutionError,
    ScriptRunner,
)
from app.agent_runtime.scripts.schemas import StepGraph

SCRIPTS_PACKAGE = Path(__file__).resolve().parents[1] / "app" / "agent_runtime" / "scripts"

# Modules that constitute the script execution context (executed graphs).
_EXECUTION_MODULES = (
    "runner.py",
    "dispatch.py",
    "fallback.py",
    "repair.py",
    "compiler.py",
    "schemas.py",
)

# Imports/constructs that would indicate direct non-MCP I/O capability.
_FORBIDDEN_PATTERNS = (
    ("import socket", "raw network sockets"),
    ("import requests", "direct HTTP"),
    ("import urllib.request", "direct HTTP"),
    ("import asyncpg", "direct database"),
    ("import psycopg", "direct database"),
    ("import sqlite3", "direct database"),
    ("from sqlalchemy", "direct database"),
    ("import subprocess", "subprocess execution"),
    ("os.system(", "shell execution"),
    ("eval(", "dynamic code execution"),
    ("exec(", "dynamic code execution"),
    ("__import__(", "dynamic import execution"),
)


def _source(module: str) -> str:
    return (SCRIPTS_PACKAGE / module).read_text(encoding="utf-8")


# ── Static boundary analysis (E8, SEC2) ───────────────────────────────────────


class TestStaticBoundary:
    @pytest.mark.parametrize("module", _EXECUTION_MODULES)
    @pytest.mark.parametrize(
        ("pattern", "capability"),
        _FORBIDDEN_PATTERNS,
    )
    def test_no_direct_io_in_execution_modules(self, module, pattern, capability):
        assert pattern not in _source(module), (
            f"{module} must not contain {capability} — scripts are MCP-only (E8)"
        )

    @pytest.mark.parametrize("module", _EXECUTION_MODULES)
    def test_no_filesystem_access_outside_sandbox(self, module):
        source = _source(module)
        assert "open(" not in source, (
            f"{module} must not open files — no filesystem access (E8)"
        )
        assert "shutil" not in source and "pathlib" not in source, (
            f"{module} must not touch the filesystem (E8)"
        )

    def test_tool_calls_flow_through_the_ch_client_only(self):
        """The only outbound path is CommHubToolClient (MCP via CH)."""
        runner_source = _source("runner.py")
        assert "call_tool" in runner_source
        assert "CommHubToolClient" in runner_source


# ── Runtime enforcement (E8, E2) ──────────────────────────────────────────────


class _NoopClient:
    async def call_tool(self, *args, **kwargs):  # pragma: no cover
        return {}


def _runner() -> ScriptRunner:
    return ScriptRunner(tool_client=_NoopClient())  # type: ignore[arg-type]


class TestRuntimeBoundary:
    async def test_network_target_tool_reference_rejected(self):
        graph = StepGraph.model_validate(
            {
                "name": "exfil",
                "steps": [
                    {
                        "kind": "tool_call",
                        "name": "s1",
                        "tool_name": "https://evil.example.com/collect",
                    }
                ],
            }
        )
        with pytest.raises(ExecutionError, match="non-MCP tool target"):
            await _runner().execute(graph, session_id="s", agent_type_id="a")

    async def test_empty_tool_name_rejected(self):
        """An empty tool reference is rejected at graph validation time
        (StepGraph schema) — before any execution (E8)."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            StepGraph.model_validate(
                {
                    "name": "g",
                    "steps": [{"kind": "tool_call", "name": "s1", "tool_name": ""}],
                }
            )

    @pytest.mark.parametrize(
        "field",
        ["api_key", "token", "secret", "password", "authorization", "credential"],
    )
    async def test_credential_shaped_fields_rejected(self, field):
        graph = StepGraph.model_validate(
            {
                "name": "g",
                "steps": [
                    {
                        "kind": "tool_call",
                        "name": "s1",
                        "tool_name": "a____b",
                        "arguments": {field: "hunter2"},
                    }
                ],
            }
        )
        with pytest.raises(ExecutionError, match="forbidden field"):
            await _runner().execute(graph, session_id="s", agent_type_id="a")

    async def test_mcp_tool_call_passes_the_boundary(self):
        """A plain MCP tool reference + local transform is allowed (E8)."""
        graph = StepGraph.model_validate(
            {
                "name": "g",
                "steps": [
                    {"kind": "tool_call", "name": "s1", "tool_name": "jira____search"},
                    {"kind": "output", "name": "out", "output_key": "result"},
                ],
            }
        )
        result = await _runner().execute(graph, session_id="s", agent_type_id="a")
        assert result is not None or result is None  # must not raise
