"""Unit tests for the Verification Engine (Agent Runtime) — V1, V2, V3.

Covers:
- Shadow-run comparison against the recorded LLM reference on identical inputs
- Deterministic comparison tolerance handling (numeric / case / order / keys),
  including the exact-tolerance boundary (inclusive)
- Verdict outcomes: match / match_within_tolerance / mismatch
- Structured diff evidence recorded on mismatch (V3)
- Evidence persisted via the CC registry client — never locally (V2)
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agent_runtime.scripts.runner import ExecutionError, ScriptRunner
from app.agent_runtime.scripts.schemas import ComparisonTolerance, StepGraph
from app.agent_runtime.scripts.verification import (
    OUTCOME_MATCH,
    OUTCOME_MATCH_WITHIN_TOLERANCE,
    OUTCOME_MISMATCH,
    VerificationEngine,
)


class FakeRegistryClient:
    """Records submitted evidence; returns canned payloads."""

    def __init__(self, llm_reference: dict[str, Any] | None = None):
        self.llm_reference = llm_reference or {}
        self.submitted: list[dict[str, Any]] = []

    async def get_llm_reference(self, session_id: str) -> dict[str, Any]:
        return self.llm_reference

    async def submit_verification(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.submitted.append(payload)
        return {"id": "vr-1", "verdict": "promoted", **payload}


class StaticRunner(ScriptRunner):
    """Runner double that returns a fixed result or raises a fixed error."""

    def __init__(self, result: Any = None, error: Exception | None = None):
        self._result = result
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def execute(self, graph, **kwargs) -> Any:  # type: ignore[override]
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._result


def _engine(runner: StaticRunner, registry: FakeRegistryClient) -> VerificationEngine:
    return VerificationEngine(runner=runner, registry_client=registry)  # type: ignore[arg-type]


def _graph(tolerance: dict | None = None) -> StepGraph:
    payload: dict[str, Any] = {
        "name": "g",
        "steps": [{"kind": "tool_call", "name": "s1", "tool_name": "a____b"}],
    }
    if tolerance:
        payload["comparison_tolerance"] = tolerance
    return StepGraph.model_validate(payload)


async def _verify(engine, graph, expected={"result": {"x": 1}}, **kwargs) -> dict:
    return await engine.verify(
        graph,
        script_version_id="ver-1",
        reference_session_id="ref-sess",
        session_id="shadow-sess",
        agent_type_id="at-1",
        expected_output=expected,
        **kwargs,
    )


# ── Shadow-run verdicts ───────────────────────────────────────────────────────


class TestShadowRunVerdicts:
    async def test_exact_match_submits_match_outcome(self):
        registry = FakeRegistryClient()
        runner = StaticRunner(result={"result": {"x": 1}})
        run = await _verify(_engine(runner, registry), _graph())
        assert registry.submitted[0]["comparison_outcome"] == OUTCOME_MATCH
        assert run["verdict"] == "promoted"

    async def test_within_tolerance_submits_match_within_tolerance(self):
        registry = FakeRegistryClient()
        runner = StaticRunner(result={"result": {"x": 1.04}})
        graph = _graph({"numeric_abs_tolerance": 0.1})
        run = await _verify(_engine(runner, registry), graph)
        assert registry.submitted[0]["comparison_outcome"] == OUTCOME_MATCH_WITHIN_TOLERANCE

    async def test_numeric_boundary_is_inclusive(self):
        engine = _engine(StaticRunner(), FakeRegistryClient())
        tol = ComparisonTolerance(numeric_abs_tolerance=0.5)
        assert engine.compare(1.0, 1.5, tol) is True   # exactly at tolerance
        assert engine.compare(1.0, 1.50001, tol) is False

    async def test_mismatch_records_diff_and_stays_draft(self):
        registry = FakeRegistryClient()
        runner = StaticRunner(result={"result": {"x": 999}})
        run = await _verify(_engine(runner, registry), _graph())
        payload = registry.submitted[0]
        assert payload["comparison_outcome"] == OUTCOME_MISMATCH
        assert "output mismatch" in (payload["verdict_reason"] or "")
        assert "x" in payload["verdict_reason"]

    async def test_runner_failure_is_recorded_as_mismatch_with_typed_reason(self):
        registry = FakeRegistryClient()
        runner = StaticRunner(error=ExecutionError("tool down"))
        run = await _verify(_engine(runner, registry), _graph())
        payload = registry.submitted[0]
        assert payload["comparison_outcome"] == OUTCOME_MISMATCH
        assert "ExecutionError" in payload["verdict_reason"]

    async def test_evidence_contains_inputs_expected_and_actual(self):
        """V2: evidence (inputs, expected vs actual, outcome) is stored via CC."""
        registry = FakeRegistryClient()
        runner = StaticRunner(result={"result": {"x": 1}})
        await _verify(
            _engine(runner, registry),
            _graph(),
            input_context={"ticket": "T-1"},
        )
        payload = registry.submitted[0]
        assert payload["input_context"] == {"ticket": "T-1"}
        assert payload["expected_output"] == {"result": {"x": 1}}
        assert payload["actual_output"] == {"result": {"x": 1}}
        assert payload["reference_execution_id"] == "ref-sess"
        assert payload["script_version_id"] == "ver-1"

    async def test_shadow_run_uses_dedicated_session_label(self):
        """The shadow run is distinct from the reference session (identical
        inputs, separate execution)."""
        runner = StaticRunner(result={"result": {}})
        engine = _engine(runner, FakeRegistryClient())
        await _verify(engine, _graph())
        assert runner.calls[0]["session_id"] == "shadow-sess"


# ── Reference extraction ──────────────────────────────────────────────────────


class TestReferenceExtraction:
    def test_prefers_last_assistant_turn(self):
        engine = _engine(StaticRunner(), FakeRegistryClient())
        reference = {
            "turns": [
                {"role": "user", "content": "go"},
                {"role": "assistant", "content": "the answer"},
            ]
        }
        assert engine._extract_reference_output(reference) == {"result": "the answer"}

    def test_falls_back_to_last_tool_call_output(self):
        engine = _engine(StaticRunner(), FakeRegistryClient())
        reference = {
            "turns": [],
            "tool_calls": [{"tool_name": "a____b", "tool_output": {"x": 1}}],
        }
        assert engine._extract_reference_output(reference) == {"result": {"x": 1}}

    def test_no_reference_yields_none(self):
        engine = _engine(StaticRunner(), FakeRegistryClient())
        assert engine._extract_reference_output({}) is None

    async def test_expected_output_defaults_to_reference_when_not_given(self):
        registry = FakeRegistryClient(
            llm_reference={"turns": [{"role": "assistant", "content": "expected!"}]}
        )
        runner = StaticRunner(result={"result": "expected!"})
        engine = _engine(runner, registry)
        await engine.verify(
            _graph(),
            script_version_id="ver-1",
            reference_session_id="ref-sess",
            session_id="shadow-sess",
            agent_type_id="at-1",
        )
        assert registry.submitted[0]["comparison_outcome"] == OUTCOME_MATCH


# ── Deterministic comparison / diff ───────────────────────────────────────────


class TestCompareAndDiff:
    def setup_method(self):
        self.engine = _engine(StaticRunner(), FakeRegistryClient())

    def test_ignore_keys_tolerance(self):
        tol = ComparisonTolerance(ignore_keys=["timestamp"])
        assert self.engine.compare(
            {"x": 1, "timestamp": "a"}, {"x": 1, "timestamp": "b"}, tol
        )

    def test_case_insensitive_strings(self):
        tol = ComparisonTolerance(string_case_insensitive=True)
        assert self.engine.compare("Hello", "hello", tol)
        assert not self.engine.compare("Hello", "hello", ComparisonTolerance())

    def test_ignore_order_in_lists(self):
        tol = ComparisonTolerance(ignore_order_in_lists=True)
        assert self.engine.compare([1, 2, 3], [3, 2, 1], tol)
        assert not self.engine.compare([1, 2], [2, 1], ComparisonTolerance())

    def test_nested_dict_key_set_must_match(self):
        assert not self.engine.compare(
            {"a": {"x": 1}}, {"a": {"x": 1, "y": 2}}, ComparisonTolerance()
        )

    def test_bool_identity_strict(self):
        tol = ComparisonTolerance()
        assert self.engine.compare(True, True, tol)
        assert not self.engine.compare(True, 1, tol)

    def test_diff_reports_added_removed_changed_keys(self):
        diff = self.engine.diff({"a": 1, "b": 2}, {"a": 1, "c": 3})
        assert diff["b"] == {"expected": 2, "actual": None}
        assert diff["c"] == {"expected": None, "actual": 3}

    def test_non_jsonable_values_fall_back_to_repr(self):
        diff = self.engine.diff({"a": object()}, {"a": 1})
        assert isinstance(diff["a"]["expected"], str)
