"""Verification Engine (Agent Runtime).

Shadow-runs candidate script versions against recorded reference LLM
executions on identical inputs, compares outputs using the declared
comparison tolerance (deterministic), and produces match/mismatch verdicts
with a usable diff (V1). Evidence is persisted via the CC registry APIs —
never locally (V2).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from opentelemetry import trace

from app.agent_runtime.scripts.cc_client import ScriptRegistryClient
from app.agent_runtime.scripts.runner import (
    ExecutionError,
    OutputValidationFailure,
    SchemaMismatch,
    ScriptExecutionError,
    ScriptRunner,
)
from app.agent_runtime.scripts.schemas import ComparisonTolerance, StepGraph

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Wire values mirrored from VerificationComparisonOutcome (CC models)
OUTCOME_MATCH = "match"
OUTCOME_MATCH_WITHIN_TOLERANCE = "match_within_tolerance"
OUTCOME_MISMATCH = "mismatch"


class VerificationEngine:
    """Shadow-run + deterministic comparison producing persisted verdicts."""

    def __init__(
        self,
        runner: ScriptRunner,
        registry_client: ScriptRegistryClient,
    ) -> None:
        self._runner = runner
        self._registry = registry_client

    async def verify(
        self,
        graph: StepGraph,
        *,
        script_version_id: str,
        reference_session_id: str,
        session_id: str,
        agent_type_id: str,
        expected_output: Any = None,
        input_context: dict[str, Any] | None = None,
        python_source: str | None = None,
    ) -> dict[str, Any]:
        """Shadow-run the candidate and persist the verdict via CC.

        Returns the CC-created VerificationRun payload (id, verdict, ...).
        A match promotes the version to verified; a mismatch leaves it at
        draft with the recorded diff (V3) — both decided CC-side. When the
        candidate is a sandboxed python_source version, the shadow-run is
        executed in the sandbox and ``sandbox_check_passed`` evidence is
        recorded alongside the comparison outcome (N3).
        """
        with tracer.start_as_current_span("script.verify") as span:
            span.set_attribute("script.version_id", script_version_id)
            span.set_attribute("script.reference_session", reference_session_id)

            reference = await self._registry.get_llm_reference(reference_session_id)
            reference_output = expected_output if expected_output is not None else (
                self._extract_reference_output(reference)
            )

            outcome, actual_output, reason, sandbox_check_passed = await self._shadow_run(
                graph,
                session_id=session_id,
                agent_type_id=agent_type_id,
                expected_output=reference_output,
                input_context=input_context,
                python_source=python_source,
            )

            run = await self._registry.submit_verification(
                {
                    "script_version_id": script_version_id,
                    "comparison_outcome": outcome,
                    "verdict_reason": reason,
                    "input_context": input_context,
                    "expected_output": _jsonable(reference_output),
                    "actual_output": _jsonable(actual_output),
                    "reference_execution_id": reference_session_id,
                    "sandbox_check_passed": sandbox_check_passed,
                }
            )
            span.set_attribute("script.verification_outcome", outcome)
            logger.info(
                "Verification for version %s: outcome=%s verdict=%s",
                script_version_id, outcome, run.get("verdict"),
            )
            return run

    async def _shadow_run(
        self,
        graph: StepGraph,
        *,
        session_id: str,
        agent_type_id: str,
        expected_output: Any,
        input_context: dict[str, Any] | None,
        python_source: str | None = None,
    ) -> tuple[str, Any, str | None, bool | None]:
        """Run the candidate on identical inputs and compare (deterministic).

        Returns ``(outcome, actual_output, reason, sandbox_check_passed)``.
        ``sandbox_check_passed`` records sandbox-compliance evidence for
        model-authored versions (N3): ``True`` when the shadow run completed
        inside the sandbox, ``False`` when it failed sandbox compliance,
        ``None`` when not applicable (declarative graphs).
        """
        if python_source:
            # Sandbox-compliance evidence path (N3): the candidate only
            # shadow-runs successfully when it is sandbox-compliant.
            try:
                from app.agent_runtime.scripts.sandbox import (
                    SandboxCaps,
                    run_sandboxed_python,
                )

                loop = asyncio.get_running_loop()
                result = await asyncio.to_thread(
                    run_sandboxed_python,
                    python_source,
                    tool_client=self._runner._tool_client,
                    session_id=session_id,
                    agent_type_id=agent_type_id,
                    script_version_label="verification-shadow",
                    input_context=input_context,
                    caps=SandboxCaps(),
                    loop=loop,
                )
                if self.compare(expected_output, result, graph.comparison_tolerance):
                    return OUTCOME_MATCH, result, None, True
                return OUTCOME_MISMATCH, result, (
                    f"output mismatch: {self.diff(expected_output, result)}"
                ), True
            except Exception as exc:
                return (
                    OUTCOME_MISMATCH,
                    None,
                    f"sandbox violation: {exc}",
                    False,
                )
        try:
            result = await self._runner.execute(
                graph,
                session_id=session_id,
                agent_type_id=agent_type_id,
                script_version_label="verification-shadow",
                initial_context=input_context,
            )
        except (ExecutionError, SchemaMismatch, OutputValidationFailure) as exc:
            return OUTCOME_MISMATCH, None, f"{type(exc).__name__}: {exc}", None

        if self.compare(expected_output, result, graph.comparison_tolerance):
            exact = self.compare(
                expected_output, result, ComparisonTolerance()
            )
            outcome = OUTCOME_MATCH if exact else OUTCOME_MATCH_WITHIN_TOLERANCE
            return outcome, result, None, None  # type: ignore[return-value]
        diff = self.diff(expected_output, result)
        return OUTCOME_MISMATCH, result, f"output mismatch: {diff}", None

    # ── Deterministic comparison ──────────────────────────────────────────

    def compare(
        self,
        expected: Any,
        actual: Any,
        tolerance: ComparisonTolerance,
    ) -> bool:
        """Deterministic, order-stable comparison under the declared tolerance."""
        # Booleans must never compare equal to 0/1 (Python's ``True == 1``);
        # decide by type before the fast-path equality shortcut.
        if isinstance(expected, bool) != isinstance(actual, bool):
            return False
        if _strip_keys(expected, tolerance.ignore_keys) == _strip_keys(
            actual, tolerance.ignore_keys
        ):
            return True
        return self._tolerant_equal(expected, actual, tolerance)

    def _tolerant_equal(
        self, expected: Any, actual: Any, tolerance: ComparisonTolerance
    ) -> bool:
        expected = _strip_keys(expected, tolerance.ignore_keys)
        actual = _strip_keys(actual, tolerance.ignore_keys)

        if isinstance(expected, bool) or isinstance(actual, bool):
            return expected is actual
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            if tolerance.numeric_abs_tolerance:
                return abs(expected - actual) <= tolerance.numeric_abs_tolerance
            if tolerance.numeric_rel_tolerance:
                denom = max(abs(expected), abs(actual), 1e-12)
                return abs(expected - actual) / denom <= tolerance.numeric_rel_tolerance
            return expected == actual
        if isinstance(expected, str) and isinstance(actual, str):
            if tolerance.string_case_insensitive:
                return expected.lower() == actual.lower()
            return expected == actual
        if isinstance(expected, list) and isinstance(actual, list):
            if len(expected) != len(actual):
                return False
            if tolerance.ignore_order_in_lists:
                remaining = list(actual)
                for item in expected:
                    for index, candidate in enumerate(remaining):
                        if self._tolerant_equal(item, candidate, tolerance):
                            del remaining[index]
                            break
                    else:
                        return False
                return True
            return all(
                self._tolerant_equal(e, a, tolerance)
                for e, a in zip(expected, actual)
            )
        if isinstance(expected, dict) and isinstance(actual, dict):
            if set(expected.keys()) != set(actual.keys()):
                return False
            return all(
                self._tolerant_equal(expected[k], actual[k], tolerance)
                for k in expected
            )
        return expected == actual

    def diff(self, expected: Any, actual: Any) -> dict[str, Any]:
        """Produce a small, usable diff for repair (V3)."""
        diffs: dict[str, Any] = {}
        if isinstance(expected, dict) and isinstance(actual, dict):
            for key in sorted(set(expected) | set(actual)):
                if key not in actual:
                    diffs[key] = {"expected": _jsonable(expected[key]), "actual": None}
                elif key not in expected:
                    diffs[key] = {"expected": None, "actual": _jsonable(actual[key])}
                elif expected[key] != actual[key]:
                    diffs[key] = {
                        "expected": _jsonable(expected[key]),
                        "actual": _jsonable(actual[key]),
                    }
            return diffs
        return {"expected": _jsonable(expected), "actual": _jsonable(actual)}

    # ── Reference extraction ──────────────────────────────────────────────

    def _extract_reference_output(self, reference: dict[str, Any]) -> Any:
        """Derive the expected output from a recorded LLM session payload.

        Preference order: the last assistant turn's content, else the final
        recorded tool call output, else None.
        """
        turns = reference.get("turns") or []
        for turn in reversed(turns):
            if isinstance(turn, dict) and turn.get("role") == "assistant":
                return {"result": turn.get("content")}
        tool_calls = reference.get("tool_calls") or []
        if tool_calls:
            last = tool_calls[-1]
            if isinstance(last, dict):
                return {"result": last.get("tool_output")}
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _strip_keys(value: Any, keys: list[str]) -> Any:
    if not keys:
        return value
    if isinstance(value, dict):
        return {k: _strip_keys(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_strip_keys(v, keys) for v in value]
    return value


def _jsonable(value: Any) -> Any:
    try:
        import json

        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)
