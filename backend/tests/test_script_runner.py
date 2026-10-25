"""Unit tests for the Script Runner (Agent Runtime) — E1, F1, S1–S3, SEC1/SEC2.

Covers:
- Step-by-step deterministic execution through the Communication Hub client
- Provenance tagging on script tool calls (``provenance="script"``)
- Typed failures: ExecutionError / SchemaMismatch / OutputValidationFailure
- Transform and output projection steps
- Model-backed steps (semantic bridge, System One decision) marked in telemetry
- Permission-denied tool calls surface as ExecutionError (never widened, SEC2)
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agent_runtime.comm_hub_client import CommHubToolClientError
from app.agent_runtime.scripts.runner import (
    ExecutionError,
    OutputValidationFailure,
    SchemaMismatch,
    ScriptRunner,
)
from app.agent_runtime.scripts.schemas import StepGraph


class FakeToolClient:
    """Records call_tool invocations; returns canned results per tool name."""

    def __init__(self, results: dict[str, Any] | None = None, error: str | None = None):
        self.results = results or {}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        session_id: str,
        agent_type_id: str,
        provenance: str = "llm",
        script_version: str | None = None,
    ) -> Any:
        self.calls.append(
            {
                "tool_name": tool_name,
                "arguments": arguments,
                "session_id": session_id,
                "agent_type_id": agent_type_id,
                "provenance": provenance,
                "script_version": script_version,
            }
        )
        if self.error is not None:
            raise CommHubToolClientError(self.error)
        return self.results.get(tool_name, {"ok": True})


def _runner(client: FakeToolClient) -> ScriptRunner:
    return ScriptRunner(tool_client=client)  # type: ignore[arg-type]


def _two_step_graph() -> dict:
    return {
        "name": "g",
        "steps": [
            {
                "kind": "tool_call",
                "name": "s1",
                "tool_name": "a____query",
                "output_key": "s1",
                "expected_output_keys": ["id"],
            },
            {
                "kind": "tool_call",
                "name": "s2",
                "tool_name": "b____act",
                "output_key": "s2",
                "arguments": {"target": "s1"},
                "argument_templates": {"target": "{{s1.id}}"},
            },
            {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["s1", "s2"]},
        ],
    }


# ── Happy path ────────────────────────────────────────────────────────────────


class TestRunnerHappyPath:
    async def test_executes_steps_and_projects_output(self):
        client = FakeToolClient(results={"a____query": {"id": "abc-123"}})
        result = await _runner(client).execute(
            StepGraph.model_validate(_two_step_graph()),
            session_id="sess-1",
            agent_type_id="at-1",
            script_version_label="v1",
        )
        # s2's template resolved s1's output field "id"
        assert client.calls[1]["arguments"] == {"target": "abc-123"}
        assert result == {
            "s1": {"id": "abc-123"},
            "s2": {"ok": True},
            "__execution_telemetry__": {
                "duration_ms": result["__execution_telemetry__"]["duration_ms"],
                "tools_invoked": [
                    {"step": "s1", "tool_name": "a____query"},
                    {"step": "s2", "tool_name": "b____act"},
                ],
                "model_backed_steps_used": [],
            },
        }

    async def test_script_provenance_passed_to_every_tool_call(self):
        client = FakeToolClient(results={"a____query": {"id": "x"}})
        await _runner(client).execute(
            StepGraph.model_validate(_two_step_graph()),
            session_id="sess-1",
            agent_type_id="at-1",
            script_version_label="v3",
        )
        for call in client.calls:
            assert call["provenance"] == "script"
            assert call["script_version"] == "v3"
            assert call["session_id"] == "sess-1"
            assert call["agent_type_id"] == "at-1"

    async def test_telemetry_records_tools_and_model_backed_steps(self):
        client = FakeToolClient(results={"decision____gate": {"answer": "yes", "confidence": 0.8}})
        graph = StepGraph.model_validate(
            {
                "name": "g",
                "steps": [
                    {"kind": "decision", "name": "d1", "tool_name": "decision____gate", "output_key": "d1"},
                    {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["d1"]},
                ],
            }
        )
        result = await _runner(client).execute(
            graph, session_id="s", agent_type_id="a", script_version_label="v1"
        )
        telemetry = result["__execution_telemetry__"]
        assert telemetry["tools_invoked"] == [{"step": "d1", "tool_name": "decision____gate"}]
        assert telemetry["model_backed_steps_used"] == [{"step": "d1", "kind": "decision"}]

    async def test_semantic_bridge_step_routes_via_tool_client_with_script_provenance(self):
        """Semantic-bridge steps (e.g. the compiled ``render_output`` step)
        route through the same CH tool client as script tool calls, carry
        script provenance, and land in ``model_backed_steps_used``."""
        client = FakeToolClient(
            results={
                "a____query": {"id": "x", "total": 1},
                "semantic____render": {"text": "Found 1 issue."},
            }
        )
        graph = StepGraph.model_validate(
            {
                "name": "g",
                "steps": [
                    {
                        "kind": "tool_call",
                        "name": "s1",
                        "tool_name": "a____query",
                        "output_key": "s1",
                    },
                    {
                        "kind": "semantic_bridge",
                        "name": "render_output",
                        "tool_name": "semantic____render",
                        "prompt_template": "Render: {{s1}}",
                        "input_key": "s1",
                        "output_key": "render_output",
                    },
                    {
                        "kind": "output",
                        "name": "out",
                        "output_key": "result",
                        "select_keys": ["render_output"],
                    },
                ],
            }
        )
        result = await _runner(client).execute(
            graph, session_id="s", agent_type_id="a", script_version_label="v1"
        )
        assert len(client.calls) == 2
        semantic_call = client.calls[1]
        assert semantic_call["tool_name"] == "semantic____render"
        assert semantic_call["provenance"] == "script"
        assert semantic_call["script_version"] == "v1"
        assert semantic_call["session_id"] == "s"
        assert semantic_call["agent_type_id"] == "a"
        # Runner contract: prompt template resolved from context + input payload
        assert semantic_call["arguments"]["prompt"].startswith("Render: ")
        assert semantic_call["arguments"]["input"] == {"id": "x", "total": 1}
        # Token accounting: exactly one model-backed step (the render)
        telemetry = result["__execution_telemetry__"]
        assert telemetry["model_backed_steps_used"] == [
            {"step": "render_output", "kind": "semantic_bridge"}
        ]
        assert telemetry["tools_invoked"] == [
            {"step": "s1", "tool_name": "a____query"},
            {"step": "render_output", "tool_name": "semantic____render"},
        ]
        # Rendered text flows out as the session output
        # Rendered text flows out as the session output (unwrapped from the
        # single-key deterministic-render projection).
        telemetry = result.pop("__execution_telemetry__", None)
        assert telemetry is not None
        assert telemetry["model_backed_steps_used"] == [
            {"step": "render_output", "kind": "semantic_bridge"}
        ]
        assert result == {"text": "Found 1 issue."}

    async def test_initial_context_seeds_template_resolution(self):
        client = FakeToolClient()
        graph = StepGraph.model_validate(
            {
                "name": "g",
                "steps": [
                    {
                        "kind": "tool_call",
                        "name": "s1",
                        "tool_name": "a____query",
                        "arguments": {"q": "seed"},
                        "argument_templates": {"q": "{{seed_value}}"},
                    },
                ],
            }
        )
        await _runner(client).execute(
            graph,
            session_id="s",
            agent_type_id="a",
            script_version_label="v1",
            initial_context={"seed_value": "hello"},
        )
        assert client.calls[0]["arguments"] == {"q": "hello"}


# ── Typed failures (F1) ───────────────────────────────────────────────────────


class TestRunnerTypedFailures:
    async def test_missing_expected_keys_raises_schema_mismatch(self):
        client = FakeToolClient(results={"a____query": {"wrong": 1}})
        with pytest.raises(SchemaMismatch, match="missing expected keys"):
            await _runner(client).execute(
                StepGraph.model_validate(_two_step_graph()),
                session_id="s", agent_type_id="a", script_version_label="v1",
            )

    async def test_non_dict_result_with_expected_keys_raises_output_validation(self):
        client = FakeToolClient(results={"a____query": [1, 2, 3]})
        with pytest.raises(OutputValidationFailure, match="expected an object"):
            await _runner(client).execute(
                StepGraph.model_validate(_two_step_graph()),
                session_id="s", agent_type_id="a", script_version_label="v1",
            )

    async def test_tool_transport_failure_raises_execution_error(self):
        client = FakeToolClient(error="connection reset")
        with pytest.raises(ExecutionError, match="a____query"):
            await _runner(client).execute(
                StepGraph.model_validate(_two_step_graph()),
                session_id="s", agent_type_id="a", script_version_label="v1",
            )

    async def test_permission_denied_surfaces_as_execution_error_not_widened(self):
        """A script invoking a tool the agent identity is not permitted for
        fails loudly — the runner never retries with different credentials (SEC2)."""
        client = FakeToolClient(error="HTTP 403 permission denied by Control Center")
        with pytest.raises(ExecutionError, match="Permission denied"):
            await _runner(client).execute(
                StepGraph.model_validate(_two_step_graph()),
                session_id="s", agent_type_id="a", script_version_label="v1",
            )

    async def test_decision_step_non_structured_result_raises_output_validation(self):
        client = FakeToolClient(results={"decision____gate": "just a string"})
        graph = StepGraph.model_validate(
            {
                "name": "g",
                "steps": [{"kind": "decision", "name": "d1", "tool_name": "decision____gate"}],
            }
        )
        with pytest.raises(OutputValidationFailure, match="non-structured"):
            await _runner(client).execute(
                graph, session_id="s", agent_type_id="a", script_version_label="v1",
            )


# ── Transform & output steps ──────────────────────────────────────────────────


class TestTransformSteps:
    async def _run(self, steps: list[dict], initial: dict | None = None) -> Any:
        client = FakeToolClient()
        graph = StepGraph.model_validate({"name": "g", "steps": steps})
        return await _runner(client).execute(
            graph, session_id="s", agent_type_id="a", script_version_label="v1",
            initial_context=initial,
        )

    async def test_select_keys_transform(self):
        result = await self._run(
            [
                {"kind": "transform", "name": "t1", "op": "constant", "value": {"a": 1, "b": 2, "c": 3}, "output_key": "src"},
                {"kind": "transform", "name": "t2", "op": "select_keys", "input_key": "src", "keys": ["a", "c"], "output_key": "filtered"},
                {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["filtered"]},
            ]
        )
        assert result["filtered"] == {"a": 1, "c": 3}

    async def test_template_transform_renders_context(self):
        result = await self._run(
            [
                {"kind": "transform", "name": "t1", "op": "constant", "value": "world", "output_key": "who"},
                {"kind": "transform", "name": "t2", "op": "template", "template": "hello {{who}}", "output_key": "greeting"},
                {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["greeting"]},
            ]
        )
        assert result["greeting"] == "hello world"

    async def test_select_keys_on_non_dict_raises_output_validation(self):
        with pytest.raises(OutputValidationFailure, match="dict input"):
            await self._run(
                [
                    {"kind": "transform", "name": "t1", "op": "constant", "value": 42, "output_key": "num"},
                    {"kind": "transform", "name": "t2", "op": "select_keys", "input_key": "num", "keys": ["a"]},
                ]
            )

    # ── Computed-data ops ─────────────────────────────────────────────────

    async def test_count_array_and_object(self):
        result = await self._run(
            [
                {"kind": "transform", "name": "seed_list", "op": "constant", "value": [1, 2, 3], "output_key": "items"},
                {"kind": "transform", "name": "seed_obj", "op": "constant", "value": {"a": 1, "b": 2}, "output_key": "obj"},
                {"kind": "transform", "name": "c1", "op": "count", "input_key": "items", "output_key": "n_items"},
                {"kind": "transform", "name": "c2", "op": "count", "input_key": "obj", "output_key": "n_keys"},
                {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["n_items", "n_keys"]},
            ]
        )
        assert result["n_items"] == 3
        assert result["n_keys"] == 2

    async def test_count_on_scalar_raises(self):
        with pytest.raises(OutputValidationFailure, match="count requires"):
            await self._run(
                [
                    {"kind": "transform", "name": "seed", "op": "constant", "value": 7, "output_key": "x"},
                    {"kind": "transform", "name": "t", "op": "count", "input_key": "x"},
                ]
            )

    async def test_pluck_extracts_column(self):
        rows = [{"id": 1, "n": "a"}, {"id": 2, "n": "b"}, {"n": "c"}]
        result = await self._run(
            [
                {"kind": "transform", "name": "seed", "op": "constant", "value": rows, "output_key": "rows"},
                {"kind": "transform", "name": "t", "op": "pluck", "input_key": "rows", "field": "id", "output_key": "ids"},
                {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["ids"]},
            ]
        )
        assert result["ids"] == [1, 2]

    async def test_pluck_on_non_array_raises(self):
        with pytest.raises(OutputValidationFailure, match="pluck requires"):
            await self._run(
                [
                    {"kind": "transform", "name": "seed", "op": "constant", "value": {"a": 1}, "output_key": "x"},
                    {"kind": "transform", "name": "t", "op": "pluck", "input_key": "x", "field": "a"},
                ]
            )

    async def test_merge_objects_and_arrays(self):
        result = await self._run(
            [
                {"kind": "transform", "name": "s1", "op": "constant", "value": {"a": 1, "b": 1}, "output_key": "obj_a"},
                {"kind": "transform", "name": "s2", "op": "constant", "value": {"b": 2, "c": 3}, "output_key": "obj_b"},
                {"kind": "transform", "name": "s3", "op": "constant", "value": [1], "output_key": "arr_a"},
                {"kind": "transform", "name": "s4", "op": "constant", "value": [2, 3], "output_key": "arr_b"},
                {"kind": "transform", "name": "m1", "op": "merge", "input_key": "obj_a", "input_key_b": "obj_b", "output_key": "merged_obj"},
                {"kind": "transform", "name": "m2", "op": "merge", "input_key": "arr_a", "input_key_b": "arr_b", "output_key": "merged_arr"},
                {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["merged_obj", "merged_arr"]},
            ]
        )
        assert result["merged_obj"] == {"a": 1, "b": 2, "c": 3}
        assert result["merged_arr"] == [1, 2, 3]

    async def test_merge_mismatched_types_raises(self):
        with pytest.raises(OutputValidationFailure, match="merge requires"):
            await self._run(
                [
                    {"kind": "transform", "name": "s1", "op": "constant", "value": {"a": 1}, "output_key": "a"},
                    {"kind": "transform", "name": "s2", "op": "constant", "value": [1], "output_key": "b"},
                    {"kind": "transform", "name": "m", "op": "merge", "input_key": "a", "input_key_b": "b"},
                ]
            )

    async def test_sum_numeric_field_over_array(self):
        rows = [{"v": 1}, {"v": 2.5}, {"v": 3}, {"other": 100}]
        result = await self._run(
            [
                {"kind": "transform", "name": "seed", "op": "constant", "value": rows, "output_key": "rows"},
                {"kind": "transform", "name": "t", "op": "sum", "input_key": "rows", "field": "v", "output_key": "total"},
                {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["total"]},
            ]
        )
        assert result["total"] == 6.5

    async def test_sum_on_non_array_raises(self):
        with pytest.raises(OutputValidationFailure, match="sum requires"):
            await self._run(
                [
                    {"kind": "transform", "name": "seed", "op": "constant", "value": "nope", "output_key": "x"},
                    {"kind": "transform", "name": "t", "op": "sum", "input_key": "x", "field": "v"},
                ]
            )

    async def test_first_and_last_array_elements(self):
        result = await self._run(
            [
                {"kind": "transform", "name": "seed", "op": "constant", "value": [{"id": 1}, {"id": 2}], "output_key": "rows"},
                {"kind": "transform", "name": "f", "op": "first", "input_key": "rows", "output_key": "first_row"},
                {"kind": "transform", "name": "l", "op": "last", "input_key": "rows", "output_key": "last_row"},
                {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["first_row", "last_row"]},
            ]
        )
        assert result["first_row"] == {"id": 1}
        assert result["last_row"] == {"id": 2}

    async def test_first_on_empty_array_raises(self):
        with pytest.raises(OutputValidationFailure, match="empty array"):
            await self._run(
                [
                    {"kind": "transform", "name": "seed", "op": "constant", "value": [], "output_key": "rows"},
                    {"kind": "transform", "name": "t", "op": "first", "input_key": "rows"},
                ]
            )

    async def test_last_on_non_array_raises(self):
        with pytest.raises(OutputValidationFailure, match="last requires"):
            await self._run(
                [
                    {"kind": "transform", "name": "seed", "op": "constant", "value": {"a": 1}, "output_key": "x"},
                    {"kind": "transform", "name": "t", "op": "last", "input_key": "x"},
                ]
            )


# ── Session binding & identity parity (E7, SEC1) ──────────────────────────────


class TestSessionBinding:
    """A script run is bound to the owning agent session: no session identity
    context, no execution — scripts never run anonymously (E7/SEC1)."""

    @pytest.mark.parametrize("session_id", ["", None])
    async def test_missing_session_id_refuses_execution(self, session_id):
        client = FakeToolClient()
        with pytest.raises(ExecutionError, match="session identity context"):
            await _runner(client).execute(
                StepGraph.model_validate(_two_step_graph()),
                session_id=session_id,  # type: ignore[arg-type]
                agent_type_id="at-1",
            )
        assert client.calls == []

    @pytest.mark.parametrize("agent_type_id", ["", None])
    async def test_missing_agent_type_refuses_execution(self, agent_type_id):
        client = FakeToolClient()
        with pytest.raises(ExecutionError, match="session identity context"):
            await _runner(client).execute(
                StepGraph.model_validate(_two_step_graph()),
                session_id="sess-1",
                agent_type_id=agent_type_id,  # type: ignore[arg-type]
            )
        assert client.calls == []

    async def test_every_tool_call_carries_the_session_identity(self):
        """Identity parity: each CH call carries the same session/agent-type
        identity as the owning session — byte-identical across all steps,
        with no separate script identity (E7)."""
        client = FakeToolClient(results={"a____query": {"id": "x"}})
        await _runner(client).execute(
            StepGraph.model_validate(_two_step_graph()),
            session_id="sess-42",
            agent_type_id="at-9",
            script_version_label="v3",
        )
        assert len(client.calls) == 2
        for call in client.calls:
            assert call["session_id"] == "sess-42"
            assert call["agent_type_id"] == "at-9"
            assert call["provenance"] == "script"
            assert call["script_version"] == "v3"

    async def test_no_script_specific_identity_is_introduced(self):
        """The runner never injects an identity of its own: the only identity
        material passed to CH is the session's own context (E7/SEC1)."""
        client = FakeToolClient(results={"a____query": {"id": "x"}})
        await _runner(client).execute(
            StepGraph.model_validate(_two_step_graph()),
            session_id="sess-1",
            agent_type_id="at-1",
        )
        for call in client.calls:
            assert set(call.keys()) == {
                "tool_name",
                "arguments",
                "session_id",
                "agent_type_id",
                "provenance",
                "script_version",
            }

    async def test_binding_enforced_before_any_step_runs(self):
        """Unbound execution is refused before the MCP-only boundary check —
        no tool call, no partial execution (SEC1)."""
        client = FakeToolClient()
        graph = {
            "name": "g",
            "steps": [
                {"kind": "tool_call", "name": "s1", "tool_name": "https://evil.example.com"}
            ],
        }
        with pytest.raises(ExecutionError, match="session identity context"):
            await _runner(client).execute(
                StepGraph.model_validate(graph), session_id="", agent_type_id=""
            )
        assert client.calls == []


# ── Execution-log shipping (best-effort) ─────────────────────────────────────


class FakeLogShipper:
    """Records shipped execution log entries."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def __call__(
        self, event_type: str, message: str, data: dict[str, Any], log_level: str = "INFO"
    ) -> None:
        self.entries.append(
            {
                "event_type": event_type,
                "message": message,
                "data": data,
                "log_level": log_level,
            }
        )


@pytest.mark.asyncio
async def test_log_shipping_emits_start_steps_completion():
    """Script runs ship execution log entries: start (version, step count),
    one per step completion (name/kind, brief truncated outcome), and a
    completion entry."""
    shipper = FakeLogShipper()
    client = FakeToolClient(results={"a____query": {"id": "abc-123"}})
    result = await ScriptRunner(client, log_shipper=shipper).execute(
        StepGraph.model_validate(_two_step_graph()),
        session_id="sess-1",
        agent_type_id="at-1",
        script_version_label="v1",
    )
    types = [e["event_type"] for e in shipper.entries]
    assert types == [
        "script_run_started",
        "script_step_completed",
        "script_step_completed",
        "script_step_completed",
        "script_run_completed",
    ]
    started = shipper.entries[0]
    assert started["data"]["script_version"] == "v1"
    assert started["data"]["step_count"] == 3
    # Brief outcomes — no full payloads in the log stream
    step_entries = [e for e in shipper.entries if e["event_type"] == "script_step_completed"]
    assert step_entries[0]["data"]["step_name"] == "s1"
    assert step_entries[0]["data"]["step_kind"] == "tool_call"
    assert "abc-123" in step_entries[0]["data"]["outcome_brief"]
    assert len(step_entries[0]["data"]["outcome_brief"]) <= 350
    completed = shipper.entries[-1]
    assert "duration_ms" in completed["data"]
    assert result["s1"] == {"id": "abc-123"}


@pytest.mark.asyncio
async def test_log_shipping_marks_model_backed_steps():
    """LLM/model-backed steps (semantic bridge, decision) emit a dedicated
    event so script↔LLM segment iterations are visible in the log stream."""
    shipper = FakeLogShipper()
    client = FakeToolClient(
        results={"a____query": {"id": "x"}, "semantic____render": {"text": "ok"}}
    )
    graph = StepGraph.model_validate(
        {
            "name": "g",
            "steps": [
                {"kind": "tool_call", "name": "s1", "tool_name": "a____query", "output_key": "s1"},
                {
                    "kind": "semantic_bridge",
                    "name": "render_output",
                    "tool_name": "semantic____render",
                    "prompt_template": "Render: {{s1.id}}",
                    "output_key": "render_output",
                },
                {
                    "kind": "output",
                    "name": "out",
                    "output_key": "result",
                    "select_keys": ["render_output"],
                },
            ],
        }
    )
    await ScriptRunner(client, log_shipper=shipper).execute(
        graph, session_id="s", agent_type_id="a", script_version_label="v1"
    )
    model_events = [e for e in shipper.entries if e["event_type"] == "script_model_backed_step"]
    assert len(model_events) == 1
    assert model_events[0]["data"]["step_name"] == "render_output"
    assert model_events[0]["data"]["step_kind"] == "semantic_bridge"


@pytest.mark.asyncio
async def test_log_shipping_emits_failure_and_never_breaks_run():
    """Typed failures ship a failure entry; a broken log shipper never
    breaks the run (best-effort logging)."""
    client = FakeToolClient(error="transport down")
    graph = StepGraph.model_validate(
        {
            "name": "g",
            "steps": [
                {"kind": "tool_call", "name": "s1", "tool_name": "a____query"},
                {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["projects", "s1"]},
            ],
        }
    )
    shipper = FakeLogShipper()
    with pytest.raises(ExecutionError):
        await ScriptRunner(client, log_shipper=shipper).execute(
            graph, session_id="s", agent_type_id="a", script_version_label="v1"
        )
    failure_events = [e for e in shipper.entries if e["event_type"] == "script_run_failed"]
    assert len(failure_events) == 1
    assert failure_events[0]["data"]["failure_type"] == "ExecutionError"
    assert failure_events[0]["log_level"] == "WARNING"
    assert shipper.entries[0]["event_type"] == "script_run_started"

    # Broken shipper: logging failure never aborts execution.
    async def _broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("log sink down")

    result = await ScriptRunner(FakeToolClient(results={"a____query": {"id": "x"}}),
                                log_shipper=_broken).execute(
        StepGraph.model_validate(_two_step_graph()),
        session_id="s", agent_type_id="a", script_version_label="v1",
    )
    assert "s1" in result


# ── Phase 3: sandboxed script segments & humanized logs ──────────────────────


class TestSandboxedSegmentStep:
    async def test_script_segment_executes_with_injected_client(self):
        """A ScriptSegmentStep runs in the sandbox with the MCP-only client
        bound as ``tools``; its result lands in the step's output_key."""
        client = FakeToolClient(results={"crm____getContact": {"name": "Ada"}})
        runner = ScriptRunner(tool_client=client)
        graph = StepGraph.model_validate(
            {
                "name": "segmented",
                "steps": [
                    {
                        "kind": "tool_call",
                        "name": "fetch",
                        "tool_name": "crm____getContact",
                        "arguments": {"id": "x1"},
                        "output_key": "fetch",
                    },
                    {
                        "kind": "script_segment",
                        "name": "derive",
                        "python_source": (
                            "def run(context, tools):\n"
                            "    return {'greeting': 'Hello ' + context['fetch']['name']}\n"
                        ),
                        "output_key": "derive",
                    },
                    {
                        "kind": "output",
                        "name": "final_output",
                        "output_key": "result",
                        "select_keys": ["derive"],
                    },
                ],
            }
        )
        result = await runner.execute(
            graph, session_id="s-1", agent_type_id="a-1", script_version_label="v1"
        )
        assert result["derive"]["greeting"] == "Hello Ada"

    async def test_sandbox_violation_types_propagate(self):
        from app.agent_runtime.scripts.sandbox import SandboxViolationError

        client = FakeToolClient()
        runner = ScriptRunner(tool_client=client)
        graph = StepGraph.model_validate(
            {
                "name": "bad-segment",
                "steps": [
                    {
                        "kind": "script_segment",
                        "name": "escape",
                        "python_source": (
                            "def run(context, tools):\n"
                            "    import os\n"
                            "    return {}\n"
                        ),
                        "output_key": "escape",
                    },
                    {
                        "kind": "output",
                        "name": "final_output",
                        "output_key": "result",
                        "select_keys": ["escape"],
                    },
                ],
            }
        )
        with pytest.raises(SandboxViolationError):
            await runner.execute(
                graph, session_id="s-1", agent_type_id="a-1"
            )

    async def test_whole_script_execution_via_execute_python_source(self):
        client = FakeToolClient()
        runner = ScriptRunner(tool_client=client)
        result = await runner.execute_python_source(
            "def run(context, tools):\n    return {'n': len(context.get('items') or [])}",
            session_id="s-2",
            agent_type_id="a-1",
            script_version_label="v2",
            initial_context={"items": [1, 2]},
        )
        assert result["n"] == 2
        assert "__execution_telemetry__" in result

    async def test_execute_python_source_requires_identity_context(self):
        runner = ScriptRunner(tool_client=FakeToolClient())
        with pytest.raises(ExecutionError, match="session identity"):
            await runner.execute_python_source(
                "def run(context, tools):\n    return {}",
                session_id="",
                agent_type_id="",
            )


class TestHumanizedLogs:
    async def test_step_outcomes_are_humanized_not_json_blobs(self):
        """N5: shipped log messages contain natural-language outcome
        summaries — never truncated JSON dumps."""
        client = FakeToolClient(
            results={
                "crm____getContact": {
                    "id": "abc-123",
                    "name": "Ada Lovelace",
                    "email": "ada@example.com",
                }
            }
        )
        shipper = FakeLogShipper()
        runner = ScriptRunner(tool_client=client, log_shipper=shipper)
        graph = StepGraph.model_validate(
            {
                "name": "humanized",
                "steps": [
                    {
                        "kind": "tool_call",
                        "name": "fetch",
                        "tool_name": "crm____getContact",
                        "arguments": {"id": "x1"},
                        "output_key": "fetch",
                    },
                    {
                        "kind": "output",
                        "name": "final_output",
                        "output_key": "result",
                        "select_keys": ["fetch"],
                    },
                ],
            }
        )
        await runner.execute(
            graph, session_id="s-1", agent_type_id="a-1", script_version_label="v1"
        )
        step_messages = [
            entry["message"] for entry in shipper.entries
            if entry["event_type"] == "script_step_completed"
        ]
        assert step_messages, "expected step-completed log entries"
        for message in step_messages:
            assert not message.lstrip().startswith("{"), (
                f"log message is a raw JSON blob: {message!r}"
            )
        # The tool step's outcome is summarized in natural language.
        assert any("object with 3 key(s)" in m for m in step_messages)

    def test_brief_formats_common_shapes(self):
        assert ScriptRunner._brief(None) == "no output"
        assert ScriptRunner._brief("plain text") == "text: plain text"
        assert "2 item(s)" in ScriptRunner._brief([1, 2])
        assert "id=abc-123" in ScriptRunner._brief({"id": "abc-123"})
        assert ScriptRunner._brief({"id": "abc-123"}).startswith("object with 1 key(s)")


# ── SEC1 identity parity: forwarded tenant headers cross the thread bridge ───


# ── Bug: malformed tool name must fall back, not fail the session ────────────


class _RecordingRegistry:
    """Minimal registry fake for the fallback controller."""

    def __init__(self) -> None:
        self.executions: list[dict] = []
        self.fallbacks: list[dict] = []

    async def report_execution(self, payload):
        self.executions.append(payload)
        return {"id": "exec-1"}

    async def report_fallback(self, payload):
        self.fallbacks.append(payload)
        return {"id": "fb-1"}


class TestToolNotFoundRuntimeFallback:
    """A sandboxed script calling a MALFORMED tool name (e.g. two-underscore
    ``supabase__list_projects`` instead of ``supabase____list_projects``) must
    surface as a typed ExecutionError so the fallback controller routes to the
    LLM path — the session must NEVER fail with a raw CommHubToolClientError
    (live defect: CH 502 'MCP tool not found' propagated and failed the run)."""

    async def test_sandboxed_script_unknown_tool_raises_execution_error(self):
        from app.agent_runtime.scripts.runner import ScriptRunner

        client = FakeToolClient(
            error="Client error '502 Bad Gateway' for CH tool routing: "
            "MCP tool not found: supabase__list_projects"
        )
        source = """
def run(context, tools):
    projects = tools.call("supabase__list_projects", {})
    return {"result": projects}
"""
        with pytest.raises(ExecutionError, match="supabase__list_projects"):
            await ScriptRunner(tool_client=client).execute_python_source(
                source, session_id="s-1", agent_type_id="a-1"
            )

    async def test_tool_not_found_triggers_unconditional_llm_fallback(self):
        from app.agent_runtime.scripts.fallback import (
            TRIGGER_EXECUTION_ERROR,
            FallbackController,
        )
        from app.agent_runtime.scripts.runner import ScriptRunner

        client = FakeToolClient(
            error="MCP tool not found: supabase__list_projects"
        )
        source = """
def run(context, tools):
    return {"result": tools.call("supabase__list_projects", {})}
"""
        registry = _RecordingRegistry()

        async def _llm(_ctx):
            return "llm-completed"

        result = await FallbackController(registry).run_with_fallback(  # type: ignore[arg-type]
            lambda: ScriptRunner(tool_client=client).execute_python_source(
                source, session_id="s-1", agent_type_id="a-1"
            ),
            script_version_id="ver-1",
            script_version_label="v1",
            session_id="s-1",
            agent_type_id="a-1",
            llm_fallback=_llm,
        )
        assert result == "llm-completed"
        assert registry.fallbacks[0]["trigger_reason"] == TRIGGER_EXECUTION_ERROR
        assert "supabase__list_projects" in registry.fallbacks[0]["failure_detail"]


class TestSandboxTenantContextPropagation:
    """Sandboxed scripts run on a separate thread; tool calls bridge back to
    the event loop via ``run_coroutine_threadsafe``. contextvars do NOT cross
    that bridge implicitly — the forwarded signed tenant header set bound by
    AR middleware must be re-bound explicitly, or CC's data plane rejects the
    CH-forwarded call (HTTP 502 "Signed tenant context headers are required").
    """

    SENTINEL = {
        "X-Internal-Tenant-Id": "tenant-42",
        "X-Internal-Tenant-User-Id": "user-7",
        "X-Internal-Tenant-Signature": "sig",
        "X-Internal-Tenant-Timestamp": "123",
    }

    async def test_script_tool_call_carries_forwarded_tenant_headers(self, monkeypatch):
        """Header visibility invariant: during a script-issued tool call, the
        egress hook's view (``forward_tenant_headers()``) equals the set bound
        in the dispatching request context."""
        from app.core.tenant_signature import (
            bind_forwarded_tenant_headers,
            forward_tenant_headers,
        )

        captured: list[dict[str, str]] = []

        class _CapturingClient(FakeToolClient):
            async def call_tool(self, *args: Any, **kwargs: Any):
                # What the internal_httpx_client egress hook would attach.
                captured.append(dict(forward_tenant_headers()))
                return await super().call_tool(*args, **kwargs)

        client = _CapturingClient(results={"crm____getContact": {"name": "Ada"}})
        runner = ScriptRunner(tool_client=client)
        graph = StepGraph.model_validate(
            {
                "name": "segmented",
                "steps": [
                    {
                        "kind": "script_segment",
                        "name": "fetch_via_tools",
                        "python_source": (
                            "def run(context, tools):\n"
                            "    return {'c': tools.call('crm____getContact', {'id': 'x1'})}\n"
                        ),
                        "output_key": "seg",
                    },
                    {
                        "kind": "output",
                        "name": "final_output",
                        "output_key": "result",
                        "select_keys": ["seg"],
                    },
                ],
            }
        )
        token = bind_forwarded_tenant_headers(dict(self.SENTINEL))
        try:
            result = await runner.execute(
                graph, session_id="s-1", agent_type_id="a-1",
                script_version_label="v1",
            )
        finally:
            from app.core.tenant_signature import reset_forwarded_tenant_headers
            reset_forwarded_tenant_headers(token)
        assert captured == [self.SENTINEL]
        assert result["seg"]["c"]["name"] == "Ada"

    async def test_direct_tool_call_headers_unchanged(self):
        """Parity control: direct agent tool calls keep their header binding
        (the fix must not disturb the direct path)."""
        from app.core.tenant_signature import (
            bind_forwarded_tenant_headers,
            forward_tenant_headers,
            reset_forwarded_tenant_headers,
        )

        captured: list[dict[str, str]] = []

        class _CapturingClient(FakeToolClient):
            async def call_tool(self, *args: Any, **kwargs: Any):
                captured.append(dict(forward_tenant_headers()))
                return await super().call_tool(*args, **kwargs)

        client = _CapturingClient()
        runner = ScriptRunner(tool_client=client)
        graph = StepGraph.model_validate(
            {
                "name": "direct",
                "steps": [
                    {
                        "kind": "tool_call",
                        "name": "s1",
                        "tool_name": "a____query",
                        "arguments": {},
                    },
                    {
                        "kind": "output",
                        "name": "out",
                        "output_key": "result",
                    },
                ],
            }
        )
        token = bind_forwarded_tenant_headers(dict(self.SENTINEL))
        try:
            await runner.execute(
                graph, session_id="s-1", agent_type_id="a-1",
                script_version_label="v1",
            )
        finally:
            reset_forwarded_tenant_headers(token)
        assert captured == [self.SENTINEL]
        assert client.calls[0]["provenance"] == "script"  # tagging unchanged by the fix


# ── MCP content-envelope unwrapping (live-defect regression) ─────────────────


class TestMcpEnvelopeUnwrapping:
    """MCP tools return ``{"content": [{"type": "text", "text": "..."}],
    "isError": false}`` — the runner must store the PARSED payload in the
    step's ``output_key``, never the raw envelope (live defect: a sandboxed
    script saw the envelope, concluded "no supabase project found")."""

    async def test_json_text_envelope_yields_parsed_list(self):
        import json as _json

        projects = [{"id": "p1", "name": "alpha"}, {"id": "p2", "name": "beta"}]
        envelope = {
            "content": [{"type": "text", "text": _json.dumps(projects)}],
            "isError": False,
        }
        client = FakeToolClient(results={"supabase____list_projects": envelope})
        result = await _runner(client).execute(
            StepGraph.model_validate(
                {
                    "name": "g",
                    "steps": [
                        {
                            "kind": "tool_call",
                            "name": "s1",
                            "tool_name": "supabase____list_projects",
                            "output_key": "projects",
                            "arguments": {},
                        },
                        {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["projects", "s1"]},
                    ],
                }
            ),
            session_id="s-1",
            agent_type_id="a-1",
        )
        assert result["projects"] == projects

    async def test_non_json_text_envelope_yields_string(self):
        envelope = {
            "content": [{"type": "text", "text": "plain tool reply"}],
            "isError": False,
        }
        client = FakeToolClient(results={"a____query": envelope})
        result = await _runner(client).execute(
            StepGraph.model_validate(
                {
                    "name": "g",
                    "steps": [
                        {
                            "kind": "tool_call",
                            "name": "s1",
                            "tool_name": "a____query",
                            "output_key": "s1",
                            "arguments": {},
                        },
                        {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["projects", "s1"]},
                    ],
                }
            ),
            session_id="s-1",
            agent_type_id="a-1",
        )
        assert result["s1"] == "plain tool reply"

    async def test_is_error_envelope_raises_execution_error(self):
        envelope = {
            "content": [{"type": "text", "text": "boom"}],
            "isError": True,
        }
        client = FakeToolClient(results={"a____query": envelope})
        with pytest.raises(ExecutionError):
            await _runner(client).execute(
                StepGraph.model_validate(
                    {
                        "name": "g",
                        "steps": [
                            {
                                "kind": "tool_call",
                                "name": "s1",
                                "tool_name": "a____query",
                                "output_key": "s1",
                                "arguments": {},
                            },
                            {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["projects", "s1"]},
                        ],
                    }
                ),
                session_id="s-1",
                agent_type_id="a-1",
            )

    async def test_non_envelope_result_passes_through_unchanged(self):
        client = FakeToolClient(results={"a____query": {"id": "abc-123"}})
        result = await _runner(client).execute(
            StepGraph.model_validate(_two_step_graph()),
            session_id="s-1",
            agent_type_id="a-1",
        )
        assert result["s1"] == {"id": "abc-123"}

    async def test_log_entry_notes_unwrapping(self):
        from tests.test_script_runner import FakeLogShipper

        import json as _json

        envelope = {
            "content": [{"type": "text", "text": _json.dumps([{"id": "p1"}])}],
            "isError": False,
        }
        client = FakeToolClient(results={"a____query": envelope})
        shipper = FakeLogShipper()
        runner = ScriptRunner(tool_client=client, log_shipper=shipper)
        await runner.execute(
            StepGraph.model_validate(
                {
                    "name": "g",
                    "steps": [
                        {
                            "kind": "tool_call",
                            "name": "s1",
                            "tool_name": "a____query",
                            "output_key": "s1",
                            "arguments": {},
                        },
                        {"kind": "output", "name": "out", "output_key": "result", "select_keys": ["projects", "s1"]},
                    ],
                }
            ),
            session_id="s-1",
            agent_type_id="a-1",
        )
        step_entries = [
            e for e in shipper.entries if e["event_type"] == "script_step_completed"
        ]
        assert step_entries, "step completion log entry expected"
        assert "envelope" in step_entries[0]["message"].lower() or step_entries[
            0
        ]["data"].get("envelope_unwrapped")

    async def test_sandboxed_script_sees_unwrapped_payload_via_tools_facade(self):
        """The live defect: sandboxed script iterating projects from the raw
        envelope concluded 'no supabase project found'."""
        import json as _json

        from app.agent_runtime.scripts.runner import ScriptRunner as _R

        projects = [{"id": "p1", "name": "alpha"}, {"id": "p2", "name": "beta"}]
        envelope = {
            "content": [{"type": "text", "text": _json.dumps(projects)}],
            "isError": False,
        }
        client = FakeToolClient(results={"supabase____list_projects": envelope})
        source = """
def run(context, tools):
    projects = tools.call("supabase____list_projects", {})
    names = [p["name"] for p in projects]
    return {"result": "projects: " + ", ".join(names)}
"""
        result = await _R(tool_client=client).execute_python_source(
            source, session_id="s-1", agent_type_id="a-1"
        )
        assert result["result"] == "projects: alpha, beta"
