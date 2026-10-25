"""Unit tests for the self-improvement Repair Loop (Agent Runtime) — E9, E10, F3.

Covers:
- Deterministic defect diagnosis from the typed failure (F1 classification)
- RepairAttempt persistence via the CC internal API: defect diagnosis, diff
  applied, attempt number, and the repaired candidate link
- Bounded retry: max 2 attempts per fallback episode (E10)
- Only a re-verified candidate (verified/compiled) may be retried (V4)
- Budget exhaustion stops retry and reports exhaustion — the run stays on
  the unconditional LLM path (E2, E10)
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agent_runtime.scripts.repair import (
    MAX_REPAIR_ATTEMPTS,
    RETRY_PENDING,
    RETRY_SUCCEEDED,
    RepairContext,
    RepairLoop,
    RepairResult,
)
from app.agent_runtime.scripts.runner import (
    ExecutionError,
    OutputValidationFailure,
    SchemaMismatch,
)

GRAPH = {"name": "g", "steps": [{"kind": "tool_call", "name": "s1", "tool_name": "a____b"}]}


class FakeRegistry:
    """Records repair submissions; serves candidate lifecycle states."""

    def __init__(self, verified_statuses: list[str] | None = None):
        self.repairs: list[dict[str, Any]] = []
        self.verified_statuses = (
            ["verified"] if verified_statuses is None else verified_statuses
        )
        self.fail_report = False

    async def report_repair(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.fail_report:
            raise RuntimeError("CC unavailable")
        self.repairs.append(payload)
        return {"repaired_version_id": f"repaired-{len(self.repairs)}"}

    async def get_version(self, version_id: str) -> dict[str, Any]:
        index = int(version_id.rsplit("-", 1)[-1]) - 1
        status = (
            self.verified_statuses[index]
            if index < len(self.verified_statuses)
            else "draft"
        )
        return {"lifecycle_status": status}


def _context() -> RepairContext:
    return RepairContext(
        script_definition_id="def-1",
        script_version_id="ver-1",
        graph_json=GRAPH,
        session_id="sess-1",
        agent_type_id="at-1",
    )


async def _generator(diagnosis: str, graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "declarative_step_graph": dict(graph, name="repaired"),
        "diff_applied": "fixed tool args",
    }


# ── Diagnosis (E9) ────────────────────────────────────────────────────────────


class TestDiagnosis:
    @pytest.mark.parametrize(
        ("failure", "expected_trigger"),
        [
            (SchemaMismatch("keys missing"), "tool_schema_mismatch"),
            (OutputValidationFailure("bad output"), "output_validation_failure"),
            (ExecutionError("tool broke"), "execution_error"),
        ],
    )
    async def test_defect_diagnosis_classified_and_reported(
        self, failure, expected_trigger
    ):
        registry = FakeRegistry()
        await RepairLoop(registry).run(_context(), failure, llm_repair_generator=_generator)
        assert registry.repairs, "a repair attempt must be reported to CC"
        assert expected_trigger in registry.repairs[0]["defect_diagnosis"]
        assert type(failure).__name__ in registry.repairs[0]["defect_diagnosis"]

    async def test_repair_attempt_carries_version_diff_and_attempt_number(self):
        registry = FakeRegistry()
        result = await RepairLoop(registry).run(
            _context(), ExecutionError("broken"), llm_repair_generator=_generator
        )
        attempt = registry.repairs[0]
        assert attempt["script_version_id"] == "ver-1"
        assert attempt["defect_diagnosis"]
        assert attempt["diff_applied"] == "fixed tool args"
        assert attempt["attempt_number"] == 1
        assert result.has_candidate
        assert result.repaired_version_id == "repaired-1"


# ── Bounded retry (E10) ───────────────────────────────────────────────────────


class TestBoundedRetry:
    def test_default_budget_is_two_attempts(self):
        assert MAX_REPAIR_ATTEMPTS == 2

    async def test_unverified_candidate_is_not_served_and_loop_retries(self):
        """Attempt 1 fails re-verification → retry (bounded), attempt 2
        verifies → candidate produced (V4)."""
        registry = FakeRegistry(verified_statuses=["draft", "verified"])
        result = await RepairLoop(registry).run(
            _context(), ExecutionError("broken"), llm_repair_generator=_generator
        )
        assert len(registry.repairs) == 2
        assert registry.repairs[1]["attempt_number"] == 2
        assert result.has_candidate
        assert result.repaired_version_id == "repaired-2"

    async def test_budget_exhaustion_stops_retry_and_reports_exhaustion(self):
        """One-past-the-budget: the loop stops after MAX_REPAIR_ATTEMPTS
        attempts and reports exhaustion — the run stays on the LLM path."""
        registry = FakeRegistry(verified_statuses=["draft", "draft"])
        result = await RepairLoop(registry).run(
            _context(), ExecutionError("broken"), llm_repair_generator=_generator
        )
        assert len(registry.repairs) == MAX_REPAIR_ATTEMPTS
        assert not result.has_candidate
        assert result.exhausted
        assert result.repaired_version_id is None

    async def test_custom_smaller_budget_is_respected(self):
        registry = FakeRegistry(verified_statuses=["draft", "draft"])
        result = await RepairLoop(registry, max_attempts=1).run(
            _context(), ExecutionError("broken"), llm_repair_generator=_generator
        )
        assert len(registry.repairs) == 1
        assert result.exhausted

    async def test_exhaustion_result_shape_has_no_candidate(self):
        registry = FakeRegistry(verified_statuses=[])
        result = await RepairLoop(registry, max_attempts=2).run(
            _context(), ExecutionError("broken"), llm_repair_generator=_generator
        )
        assert isinstance(result, RepairResult)
        assert result.attempts == [
            {"attempt": 1, "repaired_version_id": "repaired-1"},
            {"attempt": 2, "repaired_version_id": "repaired-2"},
        ]
        assert not result.has_candidate


# ── Failure handling: repair never blocks the user run (E2) ───────────────────


class TestRepairNeverBlocks:
    async def test_cc_report_failure_counts_as_exhaustion(self):
        registry = FakeRegistry()
        registry.fail_report = True
        result = await RepairLoop(registry).run(
            _context(), ExecutionError("broken"), llm_repair_generator=_generator
        )
        assert not result.has_candidate
        assert result.exhausted

    async def test_llm_generator_failure_stops_the_episode(self):
        async def _bad_generator(diagnosis: str, graph: dict) -> dict[str, Any]:
            raise RuntimeError("LLM repair generation failed")

        registry = FakeRegistry()
        result = await RepairLoop(registry).run(
            _context(), ExecutionError("broken"), llm_repair_generator=_bad_generator
        )
        assert registry.repairs == []
        assert result.exhausted

    async def test_no_graph_json_means_no_candidate(self):
        context = RepairContext(
            script_definition_id="def-1",
            script_version_id="ver-1",
            graph_json=None,
            session_id="s",
            agent_type_id="a",
        )
        registry = FakeRegistry()
        result = await RepairLoop(registry).run(
            context, ExecutionError("broken"), llm_repair_generator=_generator
        )
        assert registry.repairs == []
        assert result.exhausted

    async def test_deterministic_fallback_when_llm_generator_omitted(self):
        """Without an LLM generator the loop still produces a candidate from
        the recorded graph (diagnosis + CC persistence are deterministic)."""
        registry = FakeRegistry()
        result = await RepairLoop(registry).run(_context(), ExecutionError("broken"))
        assert result.has_candidate
        assert registry.repairs[0]["declarative_step_graph"] == GRAPH
        assert RETRY_PENDING and RETRY_SUCCEEDED  # wire values exported
