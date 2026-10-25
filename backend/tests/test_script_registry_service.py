"""Service-contract tests for ScriptRegistryService (Control Center).

The registry service is the ONLY writer of the script tables (SEC4). Tests
run against the shared in-memory SQLite engine via the repo's ``db_session``
fixture. Covers:

- Definition / immutable version creation with auto labels and lineage (G1)
- Lifecycle state machine: legal transitions, V4 verification requirement,
  single current compiled version, terminal retired state (G1, V3, V4)
- Verification evidence recording with verdict application (V1–V3)
- Fallback recording and health degradation thresholds (F2, F4)
- Repair candidates linked to parent version + fallback (F3)
- Execution-mode configuration & resolution precedence (E1–E3)
- Cost / savings aggregation (G3, G4)
"""
from __future__ import annotations

import uuid

import pytest

from app.db.models.agents import AgentPlan, AgentPlanStatus, AgentType
from app.db.models.script_execution import (
    ScriptExecutionOutcome,
    ScriptExecutionRecord,
)
from app.db.models.script_registry import (
    FallbackResultingAction,
    FallbackTriggerReason,
    RepairRetryOutcome,
    ScriptLifecycleStatus,
    ScriptVersion,
    VerificationComparisonOutcome,
)
from app.services.script_registry import (
    LifecycleTransitionError,
    ScriptRegistryService,
)
from app.services.tenancy.root_tenant import get_root_tenant_id


MINIMAL_GRAPH = {
    "name": "g",
    "steps": [{"kind": "tool_call", "name": "s1", "tool_name": "a____b"}],
}


@pytest.fixture()
def service() -> ScriptRegistryService:
    return ScriptRegistryService()


@pytest.fixture()
async def agent_type(db_session) -> AgentType:
    at = AgentType(
        tenant_id=await get_root_tenant_id(db_session),
        name=f"script-test-agent-{uuid.uuid4().hex[:8]}",
        description="script registry test agent type",
    )
    db_session.add(at)
    await db_session.flush()
    return at


@pytest.fixture()
async def definition(db_session, service, agent_type):
    return await service.create_definition(
        db_session,
        name=f"def-{uuid.uuid4().hex[:8]}",
        agent_type_id=agent_type.id,
        tenant_id=await get_root_tenant_id(db_session),
    )


async def _verified_version(db_session, service, definition) -> "object":
    version = await service.create_version(
        db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
    )
    await service.record_verification(
        db_session,
        version_id=version.id,
        comparison_outcome=VerificationComparisonOutcome.match,
        expected_output={"result": 1},
        actual_output={"result": 1},
    )
    await db_session.refresh(version)
    return version


# ── Definitions & versions (G1) ───────────────────────────────────────────────


class TestDefinitionsAndVersions:
    async def test_create_definition_starts_draft_and_healthy(
        self, db_session, service, definition
    ):
        assert definition.lifecycle_status == ScriptLifecycleStatus.draft
        from app.db.models.script_registry import ScriptHealthStatus

        assert definition.health_status == ScriptHealthStatus.healthy

    async def test_version_labels_auto_increment(self, db_session, service, definition):
        v1 = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        v2 = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        assert v1.version_label == "v1"
        assert v2.version_label == "v2"

    async def test_repair_version_has_parent_lineage_and_label(
        self, db_session, service, definition
    ):
        parent = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        repaired = await service.create_repaired_candidate(
            db_session,
            parent_version_id=parent.id,
            declarative_step_graph=MINIMAL_GRAPH,
        )
        assert repaired.parent_version_id == parent.id
        assert repaired.version_label == "v1.repair"
        assert repaired.lifecycle_status == ScriptLifecycleStatus.draft

    async def test_create_version_for_missing_definition_raises(
        self, db_session, service
    ):
        with pytest.raises(LookupError):
            await service.create_version(
                db_session,
                definition_id=uuid.uuid4(),
                declarative_step_graph=MINIMAL_GRAPH,
            )

    async def test_version_diff_reports_added_removed_changed(
        self, db_session, service, definition
    ):
        graph_a = {
            "name": "g",
            "steps": [{"kind": "tool_call", "name": "s1", "tool_name": "a____b"}],
            "comparison_tolerance": {"numeric_abs_tolerance": 0.0},
        }
        graph_b = {
            "name": "g",
            "steps": [
                {"kind": "tool_call", "name": "s1", "tool_name": "a____renamed"},
                {"kind": "tool_call", "name": "s2", "tool_name": "c____d"},
            ],
            "comparison_tolerance": {"numeric_abs_tolerance": 0.5},
        }
        v1 = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=graph_a
        )
        v2 = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=graph_b
        )
        diff = await service.version_diff(db_session, v2.id, v1.id)
        assert diff["steps_added"] == ["s2"]
        assert diff["steps_removed"] == []
        assert diff["tolerance_changed"] is True
        changed_steps = [c["step"] for c in diff["steps_changed"]]
        assert "s1" in changed_steps

    async def test_diff_with_unknown_version_raises(self, db_session, service, definition):
        v1 = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        with pytest.raises(LookupError):
            await service.version_diff(db_session, v1.id, uuid.uuid4())


# ── Lifecycle state machine (G1, V4) ──────────────────────────────────────────


class TestLifecycleStateMachine:
    async def test_draft_to_verified_requires_passing_verification(
        self, db_session, service, definition
    ):
        version = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        with pytest.raises(LifecycleTransitionError, match="passing verification"):
            await service.transition_version(
                db_session, version.id, ScriptLifecycleStatus.verified
            )

    async def test_draft_to_compiled_is_legal_auto_compile_path(self, db_session, service, definition):
        # Auto-compile: the recorded LLM run is the promotion evidence; the
        # dispatcher's unconditional LLM fallback preserves safety.
        version = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        await service.transition_version(
            db_session, version.id, ScriptLifecycleStatus.compiled
        )
        await db_session.refresh(version)
        assert version.lifecycle_status == ScriptLifecycleStatus.compiled

    async def test_retire_a_draft_version_is_allowed_but_terminal(
        self, db_session, service, definition
    ):
        version = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        await service.transition_version(
            db_session, version.id, ScriptLifecycleStatus.retired
        )
        with pytest.raises(LifecycleTransitionError):
            await service.transition_version(
                db_session, version.id, ScriptLifecycleStatus.verified
            )

    async def test_promoting_a_retired_version_rejected(
        self, db_session, service, definition
    ):
        version = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        await service.transition_version(
            db_session, version.id, ScriptLifecycleStatus.retired
        )
        with pytest.raises(LifecycleTransitionError, match="retired -> verified"):
            await service.transition_version(
                db_session, version.id, ScriptLifecycleStatus.verified
            )

    async def test_full_lifecycle_with_verification_sets_current_version(
        self, db_session, service, definition
    ):
        version = await _verified_version(db_session, service, definition)
        assert version.lifecycle_status == ScriptLifecycleStatus.verified
        await db_session.refresh(definition)
        await service.transition_version(
            db_session, version.id, ScriptLifecycleStatus.compiled
        )
        await db_session.flush()
        await db_session.refresh(definition)
        assert definition.current_version_id == version.id
        assert definition.lifecycle_status == ScriptLifecycleStatus.compiled

    async def test_promoting_second_version_demotes_previous_compiled(
        self, db_session, service, definition
    ):
        first = await _verified_version(db_session, service, definition)
        await service.transition_version(
            db_session, first.id, ScriptLifecycleStatus.compiled
        )
        second = await _verified_version(db_session, service, definition)
        await service.transition_version(
            db_session, second.id, ScriptLifecycleStatus.compiled
        )
        await db_session.refresh(first)
        await db_session.refresh(definition)
        assert first.lifecycle_status == ScriptLifecycleStatus.verified
        assert definition.current_version_id == second.id

# ── Verification evidence (V1–V3) ─────────────────────────────────────────────


class TestVerificationRecording:
    async def test_match_promotes_draft_version(self, db_session, service, definition):
        version = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        run = await service.record_verification(
            db_session,
            version_id=version.id,
            comparison_outcome=VerificationComparisonOutcome.match,
        )
        assert run.verdict.value == "promoted"
        await db_session.refresh(version)
        assert version.lifecycle_status == ScriptLifecycleStatus.verified

    async def test_within_tolerance_also_promotes(self, db_session, service, definition):
        version = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        await service.record_verification(
            db_session,
            version_id=version.id,
            comparison_outcome=VerificationComparisonOutcome.match_within_tolerance,
        )
        await db_session.refresh(version)
        assert version.lifecycle_status == ScriptLifecycleStatus.verified

    async def test_mismatch_keeps_draft_and_records_diff_reason(
        self, db_session, service, definition
    ):
        version = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        run = await service.record_verification(
            db_session,
            version_id=version.id,
            comparison_outcome=VerificationComparisonOutcome.mismatch,
            expected_output={"result": {"x": 1}},
            actual_output={"result": {"x": 2}},
            verdict_reason="output mismatch: {'result': ...}",
        )
        assert run.verdict.value == "rejected"
        await db_session.refresh(version)
        assert version.lifecycle_status == ScriptLifecycleStatus.draft
        assert "mismatch" in (run.verdict_reason or "")

    async def test_verified_version_not_silently_repromoted_on_new_match(
        self, db_session, service, definition
    ):
        version = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        await service.record_verification(
            db_session,
            version_id=version.id,
            comparison_outcome=VerificationComparisonOutcome.match,
        )
        # A second match run must not undo a compiled state
        await service.transition_version(
            db_session, version.id, ScriptLifecycleStatus.compiled
        )
        await service.record_verification(
            db_session,
            version_id=version.id,
            comparison_outcome=VerificationComparisonOutcome.mismatch,
        )
        await db_session.refresh(version)
        assert version.lifecycle_status == ScriptLifecycleStatus.compiled


# ── Fallbacks & health (F2, F4) ───────────────────────────────────────────────


class TestFallbacksAndHealth:
    async def _compiled_version(self, db_session, service, definition):
        version = await _verified_version(db_session, service, definition)
        await service.transition_version(
            db_session, version.id, ScriptLifecycleStatus.compiled
        )
        return version

    async def test_fallback_event_recorded_with_reason_and_version(
        self, db_session, service, definition
    ):
        version = await self._compiled_version(db_session, service, definition)
        execution = await service.record_execution(
            db_session,
            outcome=ScriptExecutionOutcome.fell_back,
            script_version_id=version.id,
        )
        event = await service.record_fallback(
            db_session,
            execution_record_id=execution.id,
            script_version_id=version.id,
            trigger_reason=FallbackTriggerReason.tool_schema_mismatch,
            resulting_action=FallbackResultingAction.llm_completed,
            failure_detail="tool 'a____b' schema drifted",
        )
        assert event.script_version_id == version.id
        assert event.trigger_reason == FallbackTriggerReason.tool_schema_mismatch
        assert event.failure_detail == "tool 'a____b' schema drifted"

    async def test_health_degrades_after_three_fallbacks(
        self, db_session, service, definition
    ):
        from app.db.models.script_registry import ScriptHealthStatus

        version = await self._compiled_version(db_session, service, definition)
        for _ in range(3):
            execution = await service.record_execution(
                db_session,
                outcome=ScriptExecutionOutcome.fell_back,
                script_version_id=version.id,
            )
            await service.record_fallback(
                db_session,
                execution_record_id=execution.id,
                script_version_id=version.id,
                trigger_reason=FallbackTriggerReason.execution_error,
                resulting_action=FallbackResultingAction.llm_completed,
            )
        await db_session.flush()
        await db_session.refresh(definition)
        assert definition.health_status == ScriptHealthStatus.degraded

    async def test_health_unhealthy_after_six_fallbacks(
        self, db_session, service, definition
    ):
        from app.db.models.script_registry import ScriptHealthStatus

        version = await self._compiled_version(db_session, service, definition)
        for _ in range(6):
            execution = await service.record_execution(
                db_session,
                outcome=ScriptExecutionOutcome.fell_back,
                script_version_id=version.id,
            )
            await service.record_fallback(
                db_session,
                execution_record_id=execution.id,
                script_version_id=version.id,
                trigger_reason=FallbackTriggerReason.execution_error,
                resulting_action=FallbackResultingAction.llm_completed,
            )
        await db_session.flush()
        await db_session.refresh(definition)
        assert definition.health_status == ScriptHealthStatus.unhealthy

    async def test_health_summary_reports_fallback_trend(
        self, db_session, service, definition
    ):
        version = await self._compiled_version(db_session, service, definition)
        execution = await service.record_execution(
            db_session,
            outcome=ScriptExecutionOutcome.fell_back,
            script_version_id=version.id,
        )
        await service.record_fallback(
            db_session,
            execution_record_id=execution.id,
            script_version_id=version.id,
            trigger_reason=FallbackTriggerReason.output_validation_failure,
            resulting_action=FallbackResultingAction.repair_not_produced,
            failure_detail="validation diff recorded",
        )
        summary = await service.health_summary(db_session, definition.id)
        assert summary["total_fallback_count"] == 1
        assert summary["recent_fallback_count"] == 1
        assert summary["latest_fallback"]["failure_detail"] == "validation diff recorded"


# ── Execution-mode configuration & resolution (E1–E3) ─────────────────────────


# ── Cost & savings report (G3, G4) ────────────────────────────────────────────


class TestCostReport:
    async def test_report_aggregates_script_llm_and_fallback_mix(
        self, db_session, service, definition
    ):
        # Baseline: the shared test database may hold records from other
        # suites — assert on deltas, not absolute totals.
        baseline = await service.cost_report(db_session)
        version = await _verified_version(db_session, service, definition)
        await service.transition_version(
            db_session, version.id, ScriptLifecycleStatus.compiled
        )
        # Two successful script runs (1000 tokens saved each), one fallback, one LLM run
        await service.record_execution(
            db_session,
            outcome=ScriptExecutionOutcome.success,
            script_version_id=version.id,
            tokens_saved_estimate=1000,
            model_backed_steps_used=[{"step": "d1"}],
        )
        await service.record_execution(
            db_session,
            outcome=ScriptExecutionOutcome.success,
            script_version_id=version.id,
            tokens_saved_estimate=1000,
        )
        await service.record_execution(
            db_session,
            outcome=ScriptExecutionOutcome.fell_back,
            script_version_id=version.id,
        )
        await service.record_execution(
            db_session,
            outcome=ScriptExecutionOutcome.success,
        )
        report = await service.cost_report(db_session)
        assert report["total_executions"] - baseline["total_executions"] == 4
        assert report["script_runs"] - baseline["script_runs"] == 3
        assert report["llm_runs"] - baseline["llm_runs"] == 1
        assert report["fallback_runs"] - baseline["fallback_runs"] == 1
        assert report["tokens_saved_total"] - baseline["tokens_saved_total"] == 2000
        assert report["residual_model_backed_steps"] - baseline["residual_model_backed_steps"] == 1
        # Rates over the combined (baseline + delta) history
        total = baseline["total_executions"] + 4
        hits = (baseline["script_runs"] - baseline["fallback_runs"]) + 2
        fallbacks = baseline["fallback_runs"] + 1
        assert report["script_hit_rate"] == pytest.approx(hits / total)
        assert report["fallback_rate"] == pytest.approx(fallbacks / total)

    async def test_report_is_honest_for_empty_history(self, db_session, service):
        """A workflow with no history reports zeros honestly (G3) — scoped to
        a fresh agent type so unrelated records never leak in."""
        report = await service.cost_report(
            db_session, agent_type_id=uuid.uuid4()
        )
        assert report["total_executions"] == 0
        assert report["script_hit_rate"] == 0.0
        assert report["fallback_rate"] == 0.0
        assert report["tokens_saved_total"] == 0


# ── RepairAttempt persistence & no-mode invariants (E10, refinement) ──────────


class TestRepairAttemptPersistence:
    async def test_record_repair_attempt_persists_attempt_and_candidate(
        self, db_session, service, definition
    ):
        from sqlalchemy import select

        from app.db.models.script_registry import RepairAttempt

        parent = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        execution = await service.record_execution(
            db_session,
            outcome=ScriptExecutionOutcome.fell_back,
            script_version_id=parent.id,
        )
        event = await service.record_fallback(
            db_session,
            execution_record_id=execution.id,
            script_version_id=parent.id,
            trigger_reason=FallbackTriggerReason.execution_error,
            resulting_action=FallbackResultingAction.repair_not_produced,
            failure_detail="tool broke",
        )
        attempt = await service.record_repair_attempt(
            db_session,
            script_version_id=parent.id,
            defect_diagnosis="tool args drifted from recorded schema",
            declarative_step_graph=MINIMAL_GRAPH,
            diff_applied="repair attempt 1 (execution_error)",
            attempt_number=1,
            tenant_id=definition.tenant_id,
        )
        await db_session.flush()
        assert attempt.defect_diagnosis == "tool args drifted from recorded schema"
        assert attempt.diff_applied == "repair attempt 1 (execution_error)"
        assert attempt.retry_outcome == RepairRetryOutcome.pending
        assert attempt.script_version_id == parent.id
        assert attempt.fallback_event_id == event.id
        # The repaired candidate is a new draft version with lineage
        assert attempt.repaired_version_id is not None
        repaired = await db_session.get(ScriptVersion, attempt.repaired_version_id)
        assert repaired.lifecycle_status == ScriptLifecycleStatus.draft
        assert repaired.repaired_from_id == parent.id
        assert repaired.parent_version_id == parent.id
        # Attempt is listable per script
        attempts = await service.list_repairs(
            db_session, definition_id=definition.id
        )
        assert [a.id for a in attempts] == [attempt.id]

    async def test_repair_outcome_update_round_trips(self, db_session, service, definition):
        parent = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        attempt = await service.record_repair_attempt(
            db_session,
            script_version_id=parent.id,
            defect_diagnosis="drift",
            declarative_step_graph=MINIMAL_GRAPH,
        )
        updated = await service.update_repair_outcome(
            db_session, attempt.id, RepairRetryOutcome.succeeded
        )
        assert updated is not None
        assert updated.retry_outcome == RepairRetryOutcome.succeeded


class TestPlanStepLinking:
    """E4a: link_plan_steps_to_version stamps script refs onto plan steps."""

    async def _plan(self, db_session, agent_type, steps):
        plan = AgentPlan(
            agent_type_id=agent_type.id,
            plan_steps=steps,
            generation_status=AgentPlanStatus.success,
        )
        db_session.add(plan)
        await db_session.flush()
        return plan

    async def test_matching_plan_steps_stamped(self, db_session, service, agent_type):
        plan = await self._plan(
            db_session,
            agent_type,
            [
                {"name": "fetch", "tool_name": "a____b"},
                {"name": "decide", "tool_name": "other-tool"},
            ],
        )
        definition = await service.create_definition(
            db_session,
            name=f"def-{uuid.uuid4().hex[:8]}",
            agent_type_id=agent_type.id,
            source_plan_id=plan.id,
            tenant_id=await get_root_tenant_id(db_session),
        )
        version = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        linked = await service.link_plan_steps_to_version(
            db_session, definition=definition, version=version
        )
        assert linked == 1
        await db_session.flush()
        stamped = plan.plan_steps[0]
        assert stamped["script_definition_id"] == str(definition.id)
        assert stamped["script_version_id"] == str(version.id)
        assert "script_version_id" not in plan.plan_steps[1]

    async def test_plan_without_compilation_unchanged(self, db_session, service, agent_type):
        plan = await self._plan(
            db_session, agent_type, [{"name": "fetch", "tool_name": "a____b"}]
        )
        definition = await service.create_definition(
            db_session,
            name=f"def-{uuid.uuid4().hex[:8]}",
            agent_type_id=agent_type.id,
            tenant_id=await get_root_tenant_id(db_session),
        )
        version = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        assert await service.link_plan_steps_to_version(
            db_session, definition=definition, version=version
        ) == 0
        await db_session.flush()
        assert "script_version_id" not in plan.plan_steps[0]

    async def test_already_linked_steps_not_restamped(self, db_session, service, agent_type):
        plan = await self._plan(
            db_session, agent_type, [{"name": "fetch", "tool_name": "a____b"}]
        )
        definition = await service.create_definition(
            db_session,
            name=f"def-{uuid.uuid4().hex[:8]}",
            agent_type_id=agent_type.id,
            source_plan_id=plan.id,
            tenant_id=await get_root_tenant_id(db_session),
        )
        v1 = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        assert await service.link_plan_steps_to_version(
            db_session, definition=definition, version=v1
        ) == 1
        v2 = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        assert await service.link_plan_steps_to_version(
            db_session, definition=definition, version=v2
        ) == 0
        await db_session.flush()
        assert plan.plan_steps[0]["script_version_id"] == str(v1.id)

    async def test_missing_plan_is_a_noop(self, db_session, service, definition):
        version = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        assert await service.link_plan_steps_to_version(
            db_session, definition=definition, version=version
        ) == 0


class TestNoModeCrud:
    def test_service_has_no_mode_configuration_methods(self):
        """No execution-mode CRUD exists — modes were removed."""
        for name in dir(ScriptRegistryService):
            assert "execution_mode" not in name, f"unexpected mode method: {name}"
            assert not name.startswith(("get_mode", "set_mode", "resolve_mode", "list_modes")), (
                f"unexpected mode method: {name}"
            )

    def test_no_execution_mode_configuration_model(self):
        import app.db.models.script_execution as se

        assert not hasattr(se, "ExecutionModeConfiguration")

    def test_execution_records_have_no_mode_attribute(self):
        cols = {c.name for c in ScriptExecutionRecord.__table__.columns}
        assert "execution_mode" not in cols
        assert "identity_parity_confirmed" in cols


# ── Plan-regeneration retirement (serving scripts invalidated) ────────────────


class TestRetireServingVersionsOnPlanRegeneration:
    async def test_regenerating_plan_retires_compiled_version_and_clears_pointer(
        self, db_session, service, agent_type, definition
    ):
        version = await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )
        await service.transition_version(
            db_session, version.id, ScriptLifecycleStatus.compiled
        )
        await db_session.refresh(definition)
        assert definition.current_version_id == version.id

        retired = await service.retire_serving_versions(db_session, agent_type.id)

        assert retired == [version.id]
        await db_session.refresh(version)
        await db_session.refresh(definition)
        assert version.lifecycle_status == ScriptLifecycleStatus.retired
        assert definition.current_version_id is None

    async def test_retirement_is_scoped_to_the_agent_type(
        self, db_session, service, agent_type, definition
    ):
        other_at = AgentType(
            tenant_id=await get_root_tenant_id(db_session),
            name=f"other-{uuid.uuid4().hex[:8]}",
            description="other",
        )
        db_session.add(other_at)
        await db_session.flush()
        other_def = await service.create_definition(
            db_session,
            name=f"other-def-{uuid.uuid4().hex[:8]}",
            agent_type_id=other_at.id,
            tenant_id=await get_root_tenant_id(db_session),
        )
        version = await service.create_version(
            db_session, definition_id=other_def.id, declarative_step_graph=MINIMAL_GRAPH
        )
        await service.transition_version(
            db_session, version.id, ScriptLifecycleStatus.compiled
        )

        retired = await service.retire_serving_versions(db_session, agent_type.id)

        assert retired == []
        await db_session.refresh(version)
        assert version.lifecycle_status == ScriptLifecycleStatus.compiled

    async def test_no_serving_versions_is_a_noop(
        self, db_session, service, agent_type, definition
    ):
        await service.create_version(
            db_session, definition_id=definition.id, declarative_step_graph=MINIMAL_GRAPH
        )  # draft — not serving
        assert await service.retire_serving_versions(db_session, agent_type.id) == []


class TestFreshOptimizedPlanGating:
    """Dispatch gating: only a fresh READY optimized plan is served. A
    ``needs_feedback`` plan (verification exhausted, user must steer via
    feedback) or a failed one must NEVER reach the dispatcher."""

    async def _seed(self, db_session, agent_type, status):
        from datetime import datetime, timedelta, timezone

        from app.db.models.optimized_plan import (
            OptimizedImplementationPlan,
        )

        plan = AgentPlan(
            agent_type_id=agent_type.id,
            plan_steps=[{"name": "fetch", "tool_name": "a____b"}],
            generation_status=AgentPlanStatus.success,
            updated_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db_session.add(plan)
        await db_session.flush()
        optimized = OptimizedImplementationPlan(
            agent_type_id=agent_type.id,
            agent_plan_id=plan.id,
            plan_steps=[],
            fully_scripted=True,
            status=status,
            error=None,
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(optimized)
        await db_session.flush()
        return plan, optimized

    async def test_needs_feedback_plan_is_never_served(
        self, db_session, service, agent_type
    ):
        from app.db.models.optimized_plan import OptimizedPlanStatus

        _, _ = await self._seed(
            db_session, agent_type, OptimizedPlanStatus.needs_feedback
        )
        served = await service.get_fresh_optimized_plan(
            db_session, agent_type_id=agent_type.id
        )
        assert served is None

    async def test_failed_plan_is_never_served(self, db_session, service, agent_type):
        from app.db.models.optimized_plan import OptimizedPlanStatus

        _, _ = await self._seed(db_session, agent_type, OptimizedPlanStatus.failed)
        assert (
            await service.get_fresh_optimized_plan(
                db_session, agent_type_id=agent_type.id
            )
            is None
        )

    async def test_retired_plan_is_never_served(
        self, db_session, service, agent_type
    ):
        """A retired plan (kept for reference after "Retire plan") must never
        gate execution — only status='ready' is served."""
        from app.db.models.optimized_plan import OptimizedPlanStatus

        _, _ = await self._seed(db_session, agent_type, OptimizedPlanStatus.retired)
        assert (
            await service.get_fresh_optimized_plan(
                db_session, agent_type_id=agent_type.id
            )
            is None
        )

    async def test_ready_fresh_plan_is_served(self, db_session, service, agent_type):
        from app.db.models.optimized_plan import OptimizedPlanStatus

        _, optimized = await self._seed(
            db_session, agent_type, OptimizedPlanStatus.ready
        )
        served = await service.get_fresh_optimized_plan(
            db_session, agent_type_id=agent_type.id
        )
        assert served is not None
        assert served["optimized_plan_id"] == optimized.id
        assert served["status"] == "ready"
