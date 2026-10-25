"""Unit tests for the sandboxed script engine (Phase 5.1, N1–N3).

Covers:
- Allowlisted builtins/modules; computation scripts run deterministically
- No-I/O invariants: filesystem / network / db / subprocess fail closed
- Import/attribute escape attempts fail closed (typed errors)
- Contract enforcement (run(context, tools) returning a dict)
- Resource caps: wall-time safe termination (ResourceLimitExceededError,
  sandbox_termination=True)
- MCP-only tool facade: tool calls flow through the injected client only,
  non-MCP targets rejected
"""
from __future__ import annotations

import asyncio
from typing import Any

import textwrap

import pytest

from app.agent_runtime.scripts.sandbox import (
    ResourceLimitExceededError,
    SandboxCaps,
    SandboxCompileError,
    SandboxError,
    SandboxToolFacade,
    SandboxViolationError,
    build_safe_globals,
    compile_sandbox,
    run_sandboxed_python,
)


class _RecordingClient:
    """Fake session-bound CommHubToolClient (call recording)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def call_tool(self, tool_name, arguments, **kwargs) -> Any:
        self.calls.append({"tool_name": tool_name, "arguments": arguments, **kwargs})
        return {"ok": True, "tool": tool_name}


def _run(source: str, **kwargs: Any) -> dict[str, Any]:
    async def _go() -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await asyncio.to_thread(
            run_sandboxed_python, source, loop=loop, **kwargs
        )

    return asyncio.run(_go())


# ── Valid computation (determinism) ──────────────────────────────────────────


class TestValidScripts:
    def test_statistics_and_derivation_run(self):
        source = """
def run(context, tools):
    items = context.get('items') or []
    values = [item['v'] for item in items if isinstance(item, dict) and 'v' in item]
    return {'count': len(values), 'total': sum(values), 'mean': statistics.mean(values)}
"""
        result = _run(
            source,
            input_context={"items": [{"v": 1}, {"v": 2}, {"v": 3}]},
        )
        assert result == {"count": 3, "total": 6, "mean": 2.0}

    def test_pivot_and_report_assembly_with_json(self):
        source = """
def run(context, tools):
    rows = context.get('rows') or []
    pivoted = {}
    for row in rows:
        pivoted.setdefault(row['k'], []).append(row['v'])
    return {'report': json.dumps(pivoted, sort_keys=True)}
"""
        result = _run(
            source,
            input_context={"rows": [{"k": "a", "v": 1}, {"k": "a", "v": 2}, {"k": "b", "v": 3}]},
        )
        assert result["report"] == '{"a": [1, 2], "b": [3]}'

    def test_deterministic_repeat_runs(self):
        source = "def run(context, tools):\n    return {'n': len(context.get('items') or [])}"
        first = _run(source, input_context={"items": [1, 2, 3]})
        second = _run(source, input_context={"items": [1, 2, 3]})
        assert first == second == {"n": 3}


# ── No-I/O invariants (fail closed) ──────────────────────────────────────────


class TestNoIO:
    @pytest.mark.parametrize(
        "body",
        [
            "f = open('/etc/passwd')",                                   # filesystem
            "import socket\n    s = socket.socket()",                     # network
            "import sqlite3\n    conn = sqlite3.connect('x')",            # database
            "import subprocess\n    subprocess.run(['ls'])",              # subprocess
            "os.system('ls')",                                            # shell
        ],
    )
    def test_io_attempts_fail_closed(self, body):
        source = f"def run(context, tools):\n    {body}\n    return {{}}"
        with pytest.raises(SandboxError):
            _run(source)

    def test_forbidden_builtins_absent(self):
        source = "def run(context, tools):\n    return {'x': eval('1+1')}"
        with pytest.raises(SandboxError):
            _run(source)


# ── Import / attribute escapes ───────────────────────────────────────────────


class TestEscapes:
    def test_import_statement_fails_closed(self):
        # Imports are rejected at runtime (no __import__ in the sandbox);
        # the validator additionally rejects them statically.
        with pytest.raises(SandboxError):
            _run("def run(context, tools):\n    import os\n    return {}")

    def test_dunder_traversal_fails_closed(self):
        source = "def run(context, tools):\n    return {'c': context.__class__}"
        with pytest.raises(SandboxError):
            _run(source)

    def test_missing_entry_point_fails_closed(self):
        with pytest.raises(SandboxViolationError, match="run"):
            _run("x = 1")

    def test_non_dict_return_fails_closed(self):
        with pytest.raises(SandboxViolationError, match="dict"):
            _run("def run(context, tools):\n    return 'not a dict'")

    def test_syntax_error_typed(self):
        with pytest.raises(SandboxCompileError, match="SyntaxError"):
            compile_sandbox("def run(")


# ── Resource caps (N1) ───────────────────────────────────────────────────────


class TestResourceCaps:
    def test_wall_time_cap_terminates_runaway_script(self):
        source = (
            "def run(context, tools):\n"
            "    while True:\n"
            "        pass\n"
            "    return {}\n"
        )
        with pytest.raises(ResourceLimitExceededError) as excinfo:
            _run(source, caps=SandboxCaps(wall_time_limit_seconds=1))
        assert excinfo.value.sandbox_termination is True

    def test_caps_default_from_version_fields(self):
        caps = SandboxCaps.from_version_fields(None, None, None)
        assert caps.cpu_limit_seconds > 0
        assert caps.memory_limit_mb > 0
        assert caps.wall_time_limit_seconds > 0
        explicit = SandboxCaps.from_version_fields(5, 128, 7)
        assert (explicit.cpu_limit_seconds, explicit.memory_limit_mb,
                explicit.wall_time_limit_seconds) == (5, 128, 7)

    def test_env_overrides_caps(self, monkeypatch):
        monkeypatch.setenv("SANDBOX_WALL_TIME_SECONDS", "120")
        monkeypatch.setenv("SANDBOX_CPU_SECONDS", "60")
        monkeypatch.setenv("SANDBOX_MEMORY_LIMIT_MB", "2048")
        caps = SandboxCaps()
        assert (caps.cpu_limit_seconds, caps.memory_limit_mb,
                caps.wall_time_limit_seconds) == (60, 2048, 120)
        from_fields = SandboxCaps.from_version_fields(None, None, None)
        assert from_fields.wall_time_limit_seconds == 120
        monkeypatch.delenv("SANDBOX_WALL_TIME_SECONDS")
        monkeypatch.delenv("SANDBOX_CPU_SECONDS")
        monkeypatch.delenv("SANDBOX_MEMORY_LIMIT_MB")
        fallback = SandboxCaps()
        assert (fallback.cpu_limit_seconds, fallback.memory_limit_mb,
                fallback.wall_time_limit_seconds) == (10, 512, 30)

    def test_invalid_env_falls_back_to_defaults(self, monkeypatch):
        monkeypatch.setenv("SANDBOX_WALL_TIME_SECONDS", "not-a-number")
        assert SandboxCaps().wall_time_limit_seconds == 30


class _SlowClient:
    """Fake tool client whose call awaits a fixed duration (I/O latency)."""

    def __init__(self, sleep_seconds: float) -> None:
        self._sleep = sleep_seconds
        self.calls = 0

    async def call_tool(self, tool_name, arguments, **kwargs) -> Any:
        self.calls += 1
        await asyncio.sleep(self._sleep)
        return {"ok": True, "tool": tool_name}


class TestWallTimeExcludesAwaitedIO:
    def test_awaited_tool_time_does_not_count_against_wall_cap(self):
        # A tool call that AWAITS 2.5s plus ~0.5s of the script's own compute
        # must NOT breach a 2s wall-time cap: only compute counts. Before the
        # I/O exclusion the flat deadline covered the awaited time too, so
        # this exact shape failed with ResourceLimitExceededError.
        client = _SlowClient(sleep_seconds=2.5)
        source = """
def run(context, tools):
    first = tools.call('crm____getContact', {'id': context['id']})
    total = 0
    for i in range(1000000):
        total += i
    return {'got': first['tool'], 'total': total}
"""
        result = _run(
            source,
            tool_client=client,
            caps=SandboxCaps(wall_time_limit_seconds=2),
            input_context={"id": "abc-123"},
        )
        assert result["got"] == "crm____getContact"
        assert client.calls == 1

    def test_pure_compute_still_terminates_at_cap(self):
        # Security posture intact: a compute-only infinite loop still hits
        # the wall cap and fails closed (sandbox_termination=True).
        source = (
            "def run(context, tools):\n"
            "    n = 0\n"
            "    while True:\n"
            "        n = n + 1\n"
            "    return {}\n"
        )
        with pytest.raises(ResourceLimitExceededError) as excinfo:
            _run(
                source,
                tool_client=_SlowClient(sleep_seconds=0),
                caps=SandboxCaps(wall_time_limit_seconds=1),
            )
        assert excinfo.value.sandbox_termination is True

    def test_multiple_tool_awaits_accumulate_exclusion(self):
        # Two awaited calls (1s each) + compute stays well inside a 2s cap —
        # the budget is paused for EACH awaited duration.
        client = _SlowClient(sleep_seconds=1.0)
        source = """
def run(context, tools):
    a = tools.call('crm____getContact', {'id': '1'})
    b = tools.call('crm____getContact', {'id': '2'})
    return {'a': a['tool'], 'b': b['tool']}
"""
        result = _run(
            source,
            tool_client=client,
            caps=SandboxCaps(wall_time_limit_seconds=2),
        )
        assert result == {"a": "crm____getContact", "b": "crm____getContact"}


# ── MCP-only tool facade (E8) ────────────────────────────────────────────────


class TestToolFacade:
    def test_tool_calls_flow_through_injected_client(self):
        client = _RecordingClient()
        source = """
def run(context, tools):
    first = tools.call('crm____getContact', {'id': context['id']})
    return {'got': first['tool']}
"""

        async def _go() -> dict[str, Any]:
            loop = asyncio.get_running_loop()
            return await asyncio.to_thread(
                run_sandboxed_python,
                source,
                tool_client=client,
                session_id="s-1",
                agent_type_id="a-1",
                script_version_label="v1",
                input_context={"id": "abc-123"},
                loop=loop,
            )

        result = asyncio.run(_go())
        assert result == {"got": "crm____getContact"}
        assert len(client.calls) == 1
        call = client.calls[0]
        # Identity parity + provenance tagging on every facade call (SEC1).
        assert call["session_id"] == "s-1"
        assert call["agent_type_id"] == "a-1"
        assert call["provenance"] == "script"
        assert call["script_version"] == "v1"

    def test_non_mcp_tool_target_rejected(self):
        facade = SandboxToolFacade(
            _RecordingClient(), asyncio.new_event_loop(),
            session_id="s", agent_type_id="a", script_version_label=None,
        )
        with pytest.raises(SandboxViolationError, match="MCP"):
            facade.call("https://evil.example.com/exfil")

    def test_no_other_egress_exists(self):
        source = """
def run(context, tools):
    return {'tools_only': tools is not None}
"""
        result = _run(source, tool_client=_RecordingClient())
        assert result["tools_only"] is True
        # Introspection/escape hatches fail closed too.
        with pytest.raises(SandboxError):
            _run("def run(context, tools):\n    return {'d': dir()}")
        with pytest.raises(SandboxError):
            _run("def run(context, tools):\n    return {'o': open('/x')}")




# ── Issue regression: minimal business-logic script, end-to-end ───────────────


class TestMinimalBusinessLogicScriptEndToEnd:
    """A minimal business-logic-only script works end-to-end through the
    sandbox facade with a fake tool client: ``context`` carries the task input
    and prior outputs; ``tools.call`` performs the MCP calls on the agent's
    behalf (identity parity kwargs, envelope already unwrapped); the script
    itself contains ONLY business logic — no infra, no auth, no envelope
    handling."""

    def test_minimal_script_through_facade_with_fake_tool_client(self):
        from app.agent_runtime.scripts.sandbox import unwrap_mcp_tool_result

        class _FakeToolClient:
            """Fake session-bound client returning a RAW MCP envelope."""

            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            async def call_tool(self, tool_name, arguments, **kwargs) -> Any:
                self.calls.append(
                    {"tool_name": tool_name, "arguments": arguments, **kwargs}
                )
                return {
                    "content": [
                        {"type": "text", "text": '{"price": 42, "qty": 3}'}
                    ],
                    "isError": False,
                }

        source = textwrap.dedent(
            """
            def run(context, tools):
                task = context["task"]
                prior = context.get("prior_outputs", {})
                listing = tools.call("shop____get_product", {"id": task["product_id"]})
                # Pure business logic — no envelope handling, no auth, no infra.
                total = listing["price"] * listing["qty"] + prior.get("shipping", 0)
                return {"result": f"Total for {task['product_id']}: {total}"}
            """
        )

        client = _FakeToolClient()

        async def _go() -> dict[str, Any]:
            loop = asyncio.get_running_loop()
            return await asyncio.to_thread(
                run_sandboxed_python,
                source,
                tool_client=client,
                session_id="sess-min",
                agent_type_id="at-min",
                script_version_label="v1",
                input_context={
                    "task": {"product_id": "SKU-1"},
                    "prior_outputs": {"shipping": 5},
                },
                loop=loop,
            )

        result = asyncio.run(_go())

        # The user-facing result is the business answer.
        assert result["result"] == "Total for SKU-1: 131"
        # The tool call went through the agent-bound client with script
        # provenance (identity parity) — the script never handled the envelope.
        assert len(client.calls) == 1
        call = client.calls[0]
        assert call["tool_name"] == "shop____get_product"
        assert call["arguments"] == {"id": "SKU-1"}
        assert call["provenance"] == "script"
        assert call["session_id"] == "sess-min"
        assert call["agent_type_id"] == "at-min"
        # Sanity: the fake returned an envelope; the facade unwraps it.
        payload, was_unwrapped = unwrap_mcp_tool_result(
            {"content": [{"type": "text", "text": '{"a": 1}'}], "isError": False}
        )
        assert was_unwrapped and payload == {"a": 1}

    def test_capability_contract_states_agent_behalf_business_logic_only(self):
        from app.agent_runtime.scripts.sandbox import build_capability_contract

        contract = build_capability_contract(output_format="markdown")
        assert "runs on the agent's behalf" in contract
        assert "SAME MCP tools already in your toolset" in contract
        assert "identical names, argument schemas" in contract
        assert "ONLY business logic" in contract
        assert "no infra, no auth, no envelope handling" in contract
        assert "task input fields and each prior step's output" in contract
