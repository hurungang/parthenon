"""ScriptRegistryService — Control Center governance for compiled bridge scripts.

Sole writer/reader of the script registry tables (SEC: only CC touches the
database). Provides:

- CRUD for ScriptDefinition / ScriptVersion (versions are immutable)
- Lifecycle state machine ``draft → verified → compiled → retired`` with
  server-side transition enforcement (V4: re-verification required after
  repair or tool-schema change)
- Verification evidence persistence (V2)
- Fallback event recording + script health degradation (F2, F4)
- Execution record reporting (G2) and token-savings aggregation (G3)
- RepairAttempt persistence + repair lineage (E9/E10) and repair listings
- Serving-version lookup for script-first dispatch (no modes exist, E1–E3)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from opentelemetry import trace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.agents import AgentPlan
from app.db.models.script_execution import (
    ScriptExecutionOutcome,
    ScriptExecutionRecord,
)
from app.db.models.script_registry import (
    FallbackEvent,
    FallbackResultingAction,
    FallbackTriggerReason,
    RepairAttempt,
    RepairRetryOutcome,
    SandboxValidationStatus,
    ScriptDefinition,
    ScriptHealthStatus,
    ScriptLifecycleStatus,
    ScriptVersion,
    VerificationComparisonOutcome,
    VerificationRun,
    VerificationVerdict,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# ── Lifecycle state machine ───────────────────────────────────────────────────
# Legal forward/backward transitions (C3, V3, V4). Anything not listed here
# is rejected server-side.
LEGAL_LIFECYCLE_TRANSITIONS: dict[ScriptLifecycleStatus, set[ScriptLifecycleStatus]] = {
    ScriptLifecycleStatus.draft: {
        ScriptLifecycleStatus.verified,   # promotion after successful verification
        ScriptLifecycleStatus.compiled,   # auto-compile: the recorded LLM run IS
                                          # the evidence; dispatch falls back to
                                          # the LLM path unconditionally on any
                                          # script failure, so no shadow gate
        ScriptLifecycleStatus.retired,    # operator discard
    },
    ScriptLifecycleStatus.verified: {
        ScriptLifecycleStatus.compiled,   # promotion to serving version
        ScriptLifecycleStatus.draft,      # operator demote (e.g. tool-schema change)
        ScriptLifecycleStatus.retired,
    },
    ScriptLifecycleStatus.compiled: {
        ScriptLifecycleStatus.verified,   # operator demote
        ScriptLifecycleStatus.retired,
    },
    ScriptLifecycleStatus.retired: set(),  # terminal state
}

# Health degradation thresholds (F4): consecutive/recent fallback windows.
HEALTH_DEGRADED_FALLBACK_THRESHOLD = 3
HEALTH_UNHEALTHY_FALLBACK_THRESHOLD = 6
HEALTH_WINDOW_HOURS = 24


class LifecycleTransitionError(ValueError):
    """Raised when a lifecycle transition violates the state machine (V4)."""


class ScriptRegistryService:
    """Business logic for the Software 3.0 script registry (Control Center)."""

    # ── Script definitions ────────────────────────────────────────────────

    async def create_definition(
        self,
        db: AsyncSession,
        *,
        name: str,
        agent_type_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
        description: str | None = None,
        source_plan_id: uuid.UUID | None = None,
        source_session_id: uuid.UUID | None = None,
    ) -> ScriptDefinition:
        """Create a script definition in draft state (G1 lineage captured)."""
        definition = ScriptDefinition(
            tenant_id=tenant_id,
            name=name,
            description=description,
            agent_type_id=agent_type_id,
            source_plan_id=source_plan_id,
            source_session_id=source_session_id,
            lifecycle_status=ScriptLifecycleStatus.draft,
            health_status=ScriptHealthStatus.healthy,
        )
        db.add(definition)
        await db.flush()
        await db.refresh(definition)
        logger.info(
            "Created ScriptDefinition %s (name=%s, agent_type=%s)",
            definition.id, name, agent_type_id,
        )
        return definition

    async def get_definition_by_name_and_agent_type(
        self,
        db: AsyncSession,
        *,
        name: str,
        agent_type_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> ScriptDefinition | None:
        stmt = select(ScriptDefinition).where(
            ScriptDefinition.name == name,
            ScriptDefinition.agent_type_id == agent_type_id,
        )
        if tenant_id is not None:
            stmt = stmt.where(ScriptDefinition.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_definition(
        self,
        db: AsyncSession,
        definition_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> ScriptDefinition | None:
        stmt = select(ScriptDefinition).where(ScriptDefinition.id == definition_id)
        if tenant_id is not None:
            stmt = stmt.where(ScriptDefinition.tenant_id == tenant_id)
        stmt = stmt.options(
            selectinload(ScriptDefinition.versions),
            selectinload(ScriptDefinition.current_version),
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_definitions(
        self,
        db: AsyncSession,
        *,
        tenant_id: uuid.UUID | None = None,
        agent_type_id: uuid.UUID | None = None,
        lifecycle_status: ScriptLifecycleStatus | None = None,
        health_status: ScriptHealthStatus | None = None,
    ) -> list[ScriptDefinition]:
        stmt = select(ScriptDefinition).order_by(ScriptDefinition.created_at.desc())
        if tenant_id is not None:
            stmt = stmt.where(ScriptDefinition.tenant_id == tenant_id)
        if agent_type_id is not None:
            stmt = stmt.where(ScriptDefinition.agent_type_id == agent_type_id)
        if lifecycle_status is not None:
            stmt = stmt.where(ScriptDefinition.lifecycle_status == lifecycle_status)
        if health_status is not None:
            stmt = stmt.where(ScriptDefinition.health_status == health_status)
        stmt = stmt.options(selectinload(ScriptDefinition.versions))
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ── Script versions (immutable) ───────────────────────────────────────

    async def create_version(
        self,
        db: AsyncSession,
        *,
        definition_id: uuid.UUID,
        declarative_step_graph: dict[str, Any],
        version_label: str | None = None,
        parent_version_id: uuid.UUID | None = None,
        content_reference: str | None = None,
        compiled_from_source: str | None = None,
        python_source: str | None = None,
        cpu_limit_seconds: int | None = None,
        memory_limit_mb: int | None = None,
        wall_time_limit_seconds: int | None = None,
        sandbox_validation_status: Any = None,
        sandbox_validation_reason: str | None = None,
        created_by: str | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> ScriptVersion:
        """Create an immutable candidate version (draft). Never executes.

        A version created with a parent (repair, F3) or after a tool-schema
        change always starts at draft and must pass verification before it
        can serve compiled runs (V4).
        """
        definition = await self.get_definition(db, definition_id, tenant_id)
        if definition is None:
            raise LookupError(f"ScriptDefinition {definition_id} not found")

        if version_label is None:
            version_label = await self._next_version_label(db, definition_id)

        version = ScriptVersion(
            tenant_id=tenant_id or definition.tenant_id,
            script_definition_id=definition_id,
            version_label=version_label,
            lifecycle_status=ScriptLifecycleStatus.draft,
            declarative_step_graph=declarative_step_graph,
            python_source=python_source,
            cpu_limit_seconds=cpu_limit_seconds,
            memory_limit_mb=memory_limit_mb,
            wall_time_limit_seconds=wall_time_limit_seconds,
            sandbox_validation_status=(
                sandbox_validation_status or SandboxValidationStatus.pending
            ),
            sandbox_validation_reason=sandbox_validation_reason,
            parent_version_id=parent_version_id,
            content_reference=content_reference,
            compiled_from_source=compiled_from_source,
            created_by=created_by,
        )
        db.add(version)
        await db.flush()
        await db.refresh(version)
        logger.info(
            "Created ScriptVersion %s (definition=%s, label=%s, parent=%s)",
            version.id, definition_id, version_label, parent_version_id,
        )
        return version

    async def link_plan_steps_to_version(
        self,
        db: AsyncSession,
        *,
        definition: ScriptDefinition,
        version: ScriptVersion,
    ) -> int:
        """Stamp plan steps with their backing script version (E4a).

        When a script version is compiled from an implementation plan
        (``definition.source_plan_id`` set), every plan step whose tool is
        covered by the version's step graph records the
        ``script_definition_id``/``script_version_id`` reference so the plan
        API and plan UI can expose the per-step link. Plans without
        compilation are left unchanged. Returns the number of steps linked.
        """
        if definition.source_plan_id is None:
            return 0
        plan = (
            await db.execute(
                select(AgentPlan).where(AgentPlan.id == definition.source_plan_id)
            )
        ).scalar_one_or_none()
        if plan is None or not plan.plan_steps:
            return 0

        tool_names: set[str] = set()
        for step in (version.declarative_step_graph or {}).get("steps", []):
            tool_name = step.get("tool_name") if isinstance(step, dict) else None
            if tool_name:
                tool_names.add(tool_name)
        if not tool_names:
            return 0

        linked = 0
        for plan_step in plan.plan_steps:
            if (
                isinstance(plan_step, dict)
                and plan_step.get("tool_name") in tool_names
                and not plan_step.get("script_version_id")
            ):
                plan_step["script_definition_id"] = str(definition.id)
                plan_step["script_version_id"] = str(version.id)
                linked += 1
        if linked:
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(plan, "plan_steps")
            logger.info(
                "Linked %d plan step(s) of plan %s to script version %s",
                linked, plan.id, version.id,
            )
        return linked

    async def get_version(
        self,
        db: AsyncSession,
        version_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> ScriptVersion | None:
        stmt = select(ScriptVersion).where(ScriptVersion.id == version_id)
        if tenant_id is not None:
            stmt = stmt.where(ScriptVersion.tenant_id == tenant_id)
        stmt = stmt.options(selectinload(ScriptVersion.verification_runs))
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_versions(
        self,
        db: AsyncSession,
        definition_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> list[ScriptVersion]:
        stmt = (
            select(ScriptVersion)
            .where(ScriptVersion.script_definition_id == definition_id)
            .order_by(ScriptVersion.created_at.asc())
        )
        if tenant_id is not None:
            stmt = stmt.where(ScriptVersion.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def version_diff(
        self,
        db: AsyncSession,
        version_id: uuid.UUID,
        against_version_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Structural diff between two versions' step graphs (audit/diff view)."""
        a = await self.get_version(db, version_id, tenant_id)
        b = await self.get_version(db, against_version_id, tenant_id)
        if a is None or b is None:
            raise LookupError("One or both script versions not found")

        graph_a = a.declarative_step_graph or {}
        graph_b = b.declarative_step_graph or {}
        steps_a = graph_a.get("steps", []) or []
        steps_b = graph_b.get("steps", []) or []

        def _step_key(step: dict[str, Any]) -> str:
            return str(step.get("name") or step.get("kind"))

        names_a = {_step_key(s) for s in steps_a if isinstance(s, dict)}
        names_b = {_step_key(s) for s in steps_b if isinstance(s, dict)}

        changed: list[dict[str, Any]] = []
        for sa in steps_a:
            if not isinstance(sa, dict):
                continue
            key = _step_key(sa)
            sb = next((s for s in steps_b if isinstance(s, dict) and _step_key(s) == key), None)
            if sb is not None and sa != sb:
                changed.append({"step": key, "field": "definition", "before": sb, "after": sa})

        return {
            "version_id": version_id,
            "against_version_id": against_version_id,
            "steps_added": sorted(names_a - names_b),
            "steps_removed": sorted(names_b - names_a),
            "steps_changed": changed,
            "tolerance_changed": graph_a.get("comparison_tolerance")
            != graph_b.get("comparison_tolerance"),
        }

    # ── Lifecycle transitions ─────────────────────────────────────────────

    async def transition_version(
        self,
        db: AsyncSession,
        version_id: uuid.UUID,
        target: ScriptLifecycleStatus,
        *,
        tenant_id: uuid.UUID | None = None,
        actor: str | None = None,
    ) -> ScriptVersion:
        """Apply a validated lifecycle transition to a script version.

        Rules:
        - Only transitions in LEGAL_LIFECYCLE_TRANSITIONS are allowed.
        - ``draft → verified`` requires a successful (match) VerificationRun (V4).
        - ``verified → compiled`` sets the definition's current_version_id so
          the version serves compiled runs; any previously compiled version is
          demoted to verified.
        - Retired is terminal.
        """
        version = await self.get_version(db, version_id, tenant_id)
        if version is None:
            raise LookupError(f"ScriptVersion {version_id} not found")

        current = version.lifecycle_status
        if target not in LEGAL_LIFECYCLE_TRANSITIONS.get(current, set()):
            raise LifecycleTransitionError(
                f"Illegal lifecycle transition {current.value} -> {target.value} "
                f"for ScriptVersion {version_id}"
            )

        if current == ScriptLifecycleStatus.draft and target == ScriptLifecycleStatus.verified:
            if not await self.has_passing_verification(db, version_id, tenant_id):
                raise LifecycleTransitionError(
                    "Cannot promote a draft version without a passing verification run (V4)"
                )

        if target == ScriptLifecycleStatus.compiled:
            await self._set_current_version(db, version)

        version.lifecycle_status = target
        if actor:
            version.created_by = version.created_by or actor
        await db.flush()
        await db.refresh(version)

        # Keep definition-level status aligned with its serving version.
        await self._sync_definition_status(db, version.script_definition_id)

        span = trace.get_current_span()
        if span is not None:
            span.set_attribute("script.version_id", str(version_id))
            span.set_attribute("script.lifecycle_transition", f"{current.value}->{target.value}")

        logger.info(
            "ScriptVersion %s transitioned %s -> %s (actor=%s)",
            version_id, current.value, target.value, actor,
        )
        return version

    async def retire_serving_versions(
        self,
        db: AsyncSession,
        agent_type_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID | None = None,
        actor: str | None = None,
    ) -> list[uuid.UUID]:
        """Retire every currently compiled (serving) script version for an agent type.

        Used when the agent type's implementation plan is regenerated: the old
        plan's serving scripts no longer match the new composition, so they must
        be retired and the serving pointer cleared. The next execution then
        re-runs the LLM, re-authors the composition from the NEW plan, and
        auto-compiles a matching script.

        Returns the ids of the retired versions. Retired is terminal — versions
        already retired are left untouched.
        """
        result = await db.execute(
            select(ScriptDefinition.id).where(
                ScriptDefinition.agent_type_id == agent_type_id
            )
        )
        definition_ids = [row[0] for row in result.fetchall()]
        if not definition_ids:
            return []

        result = await db.execute(
            select(ScriptVersion).where(
                ScriptVersion.script_definition_id.in_(definition_ids),  # type: ignore[attr-defined]
                ScriptVersion.lifecycle_status == ScriptLifecycleStatus.compiled,
            )
        )
        compiled_versions = list(result.scalars().all())
        retired_ids: list[uuid.UUID] = []
        for version in compiled_versions:
            version.lifecycle_status = ScriptLifecycleStatus.retired
            retired_ids.append(version.id)
            logger.info(
                "ScriptVersion %s retired (plan regenerated for agent type %s, actor=%s)",
                version.id, agent_type_id, actor,
            )
            span = trace.get_current_span()
            if span is not None:
                span.set_attribute("script.retired_version_id", str(version.id))

        if retired_ids:
            # Clear the serving pointer on every definition that pointed at a
            # retired version, then re-sync definition-level lifecycle status.
            result = await db.execute(
                select(ScriptDefinition).where(
                    ScriptDefinition.id.in_(definition_ids)
                )
            )
            for definition in result.scalars().all():
                if definition.current_version_id in retired_ids:
                    definition.current_version_id = None
                await self._sync_definition_status(db, definition.id)
            await db.flush()

        return retired_ids

    async def has_passing_verification(
        self,
        db: AsyncSession,
        version_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> bool:
        """True when the latest verification run for the version is a match (V4)."""
        stmt = (
            select(VerificationRun)
            .where(VerificationRun.script_version_id == version_id)
            .order_by(VerificationRun.created_at.desc())
            .limit(1)
        )
        if tenant_id is not None:
            stmt = stmt.where(VerificationRun.tenant_id == tenant_id)
        result = await db.execute(stmt)
        run = result.scalar_one_or_none()
        return run is not None and run.verdict == VerificationVerdict.promoted

    async def _set_current_version(self, db: AsyncSession, version: ScriptVersion) -> None:
        result = await db.execute(
            select(ScriptVersion).where(
                ScriptVersion.script_definition_id == version.script_definition_id,
                ScriptVersion.lifecycle_status == ScriptLifecycleStatus.compiled,
            )
        )
        for previously_compiled in result.scalars().all():
            if previously_compiled.id != version.id:
                previously_compiled.lifecycle_status = ScriptLifecycleStatus.verified

        definition = await db.get(ScriptDefinition, version.script_definition_id)
        if definition is not None:
            definition.current_version_id = version.id

    async def _sync_definition_status(
        self, db: AsyncSession, definition_id: uuid.UUID
    ) -> None:
        definition = await db.get(ScriptDefinition, definition_id)
        if definition is None:
            return
        result = await db.execute(
            select(ScriptVersion.lifecycle_status).where(
                ScriptVersion.script_definition_id == definition_id,
            )
        )
        statuses = {row[0] for row in result.fetchall()}
        if ScriptLifecycleStatus.compiled in statuses:
            definition.lifecycle_status = ScriptLifecycleStatus.compiled
        elif ScriptLifecycleStatus.verified in statuses:
            definition.lifecycle_status = ScriptLifecycleStatus.verified
        elif statuses == {ScriptLifecycleStatus.retired}:
            definition.lifecycle_status = ScriptLifecycleStatus.retired
        else:
            definition.lifecycle_status = ScriptLifecycleStatus.draft

    # ── Verification evidence (V1, V2) ────────────────────────────────────

    async def record_verification(
        self,
        db: AsyncSession,
        *,
        version_id: uuid.UUID,
        comparison_outcome: VerificationComparisonOutcome,
        input_context: dict[str, Any] | None = None,
        expected_output: dict[str, Any] | None = None,
        actual_output: dict[str, Any] | None = None,
        verdict_reason: str | None = None,
        reference_execution_id: uuid.UUID | None = None,
        sandbox_check_passed: bool | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> VerificationRun:
        """Persist verification evidence and apply the verdict (V3).

        A match (including within-tolerance) promotes the version to
        ``verified``; a mismatch leaves the candidate at ``draft`` with the
        recorded diff for repair.
        """
        version = await self.get_version(db, version_id, tenant_id)
        if version is None:
            raise LookupError(f"ScriptVersion {version_id} not found")

        promoted = comparison_outcome in (
            VerificationComparisonOutcome.match,
            VerificationComparisonOutcome.match_within_tolerance,
        )
        run = VerificationRun(
            tenant_id=tenant_id or version.tenant_id,
            script_version_id=version_id,
            reference_execution_id=reference_execution_id,
            input_context=input_context,
            expected_output=expected_output,
            actual_output=actual_output,
            comparison_outcome=comparison_outcome,
            verdict=VerificationVerdict.promoted if promoted else VerificationVerdict.rejected,
            verdict_reason=verdict_reason,
            sandbox_check_passed=sandbox_check_passed,
        )
        db.add(run)
        await db.flush()
        await db.refresh(run)

        if promoted and version.lifecycle_status == ScriptLifecycleStatus.draft:
            await self.transition_version(
                db, version_id, ScriptLifecycleStatus.verified, tenant_id=tenant_id
            )

        span = trace.get_current_span()
        if span is not None:
            span.set_attribute("script.verification_outcome", comparison_outcome.value)

        logger.info(
            "VerificationRun %s recorded for version %s: outcome=%s verdict=%s",
            run.id, version_id, comparison_outcome.value, run.verdict.value,
        )
        return run

    async def list_verifications(
        self,
        db: AsyncSession,
        definition_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> list[VerificationRun]:
        stmt = (
            select(VerificationRun)
            .join(ScriptVersion, ScriptVersion.id == VerificationRun.script_version_id)
            .where(ScriptVersion.script_definition_id == definition_id)
            .order_by(VerificationRun.created_at.desc())
        )
        if tenant_id is not None:
            stmt = stmt.where(VerificationRun.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ── Executions, fallbacks, health (F1–F4, G2) ─────────────────────────

    async def record_execution(
        self,
        db: AsyncSession,
        *,
        outcome: ScriptExecutionOutcome,
        script_version_id: uuid.UUID | None = None,
        duration_ms: int | None = None,
        tools_invoked: list[dict[str, Any]] | None = None,
        model_backed_steps_used: list[dict[str, Any]] | None = None,
        session_id: uuid.UUID | None = None,
        identity_parity_confirmed: bool | None = None,
        tokens_saved_estimate: int | None = None,
        tokens_saved_actual: int | None = None,
        sandbox_termination: bool | None = None,
        sandbox_violation_detail: str | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> ScriptExecutionRecord:
        """Persist one compiled/fallback execution record reported by Agent Runtime."""
        record = ScriptExecutionRecord(
            tenant_id=tenant_id,
            script_version_id=script_version_id,
            outcome=outcome,
            duration_ms=duration_ms,
            tools_invoked=tools_invoked,
            model_backed_steps_used=model_backed_steps_used,
            session_id=session_id,
            identity_parity_confirmed=identity_parity_confirmed,
            tokens_saved_estimate=tokens_saved_estimate,
            tokens_saved_actual=tokens_saved_actual,
            sandbox_termination=sandbox_termination,
            sandbox_violation_detail=sandbox_violation_detail,
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)
        logger.info(
            "ScriptExecutionRecord %s (version=%s, outcome=%s, tokens_saved=%s)",
            record.id, script_version_id, outcome.value, tokens_saved_estimate,
        )
        return record

    async def record_fallback(
        self,
        db: AsyncSession,
        *,
        execution_record_id: uuid.UUID,
        trigger_reason: FallbackTriggerReason,
        resulting_action: FallbackResultingAction,
        script_version_id: uuid.UUID | None = None,
        failure_detail: str | None = None,
        repaired_version_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> FallbackEvent:
        """Record a fallback event and degrade script health (F2, F4)."""
        event = FallbackEvent(
            tenant_id=tenant_id,
            execution_record_id=execution_record_id,
            script_version_id=script_version_id,
            trigger_reason=trigger_reason,
            failure_detail=failure_detail,
            resulting_action=resulting_action,
            script_health_impact=1,
            repaired_version_id=repaired_version_id,
        )
        db.add(event)
        await db.flush()
        await db.refresh(event)

        if script_version_id is not None:
            await self._degrade_health(db, script_version_id)

        logger.warning(
            "FallbackEvent %s (version=%s, reason=%s, action=%s)",
            event.id, script_version_id, trigger_reason.value, resulting_action.value,
        )
        return event

    async def _degrade_health(
        self, db: AsyncSession, version_id: uuid.UUID
    ) -> ScriptHealthStatus:
        """Aggregate recent fallbacks into a health status (F4)."""
        version = await self.get_version(db, version_id)
        if version is None:
            return ScriptHealthStatus.healthy
        definition = await db.get(ScriptDefinition, version.script_definition_id)
        if definition is None:
            return ScriptHealthStatus.healthy

        since = datetime.now(timezone.utc) - timedelta(hours=HEALTH_WINDOW_HOURS)
        result = await db.execute(
            select(func.count())
            .select_from(FallbackEvent)
            .join(
                ScriptVersion,
                ScriptVersion.id == FallbackEvent.script_version_id,
            )
            .where(
                ScriptVersion.script_definition_id == version.script_definition_id,
                FallbackEvent.created_at >= since,
            )
        )
        recent_fallbacks = int(result.scalar_one())

        if recent_fallbacks >= HEALTH_UNHEALTHY_FALLBACK_THRESHOLD:
            definition.health_status = ScriptHealthStatus.unhealthy
        elif recent_fallbacks >= HEALTH_DEGRADED_FALLBACK_THRESHOLD:
            definition.health_status = ScriptHealthStatus.degraded
        else:
            definition.health_status = ScriptHealthStatus.healthy

        span = trace.get_current_span()
        if span is not None:
            span.set_attribute("script.health_status", definition.health_status.value)
            span.set_attribute("script.recent_fallbacks", recent_fallbacks)
        return definition.health_status

    async def list_fallbacks(
        self,
        db: AsyncSession,
        definition_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> list[FallbackEvent]:
        stmt = (
            select(FallbackEvent)
            .join(ScriptVersion, ScriptVersion.id == FallbackEvent.script_version_id)
            .where(ScriptVersion.script_definition_id == definition_id)
            .order_by(FallbackEvent.created_at.desc())
        )
        if tenant_id is not None:
            stmt = stmt.where(FallbackEvent.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def health_summary(
        self,
        db: AsyncSession,
        definition_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Health status + recent fallback trend for operator surfacing (F4)."""
        definition = await self.get_definition(db, definition_id, tenant_id)
        if definition is None:
            raise LookupError(f"ScriptDefinition {definition_id} not found")
        events = await self.list_fallbacks(db, definition_id, tenant_id)
        since = datetime.now(timezone.utc) - timedelta(hours=HEALTH_WINDOW_HOURS)
        recent = [
            e for e in events
            if e.created_at is not None
            and e.created_at.astimezone(timezone.utc) >= since
        ]
        return {
            "script_definition_id": definition_id,
            "health_status": definition.health_status,
            "lifecycle_status": definition.lifecycle_status,
            "recent_fallback_count": len(recent),
            "total_fallback_count": len(events),
            "latest_fallback": (
                {
                    "id": events[0].id,
                    "trigger_reason": events[0].trigger_reason,
                    "failure_detail": events[0].failure_detail,
                    "created_at": events[0].created_at,
                }
                if events
                else None
            ),
        }

    # ── Repair loop (F3, V4) ──────────────────────────────────────────────

    async def create_repaired_candidate(
        self,
        db: AsyncSession,
        *,
        parent_version_id: uuid.UUID,
        declarative_step_graph: dict[str, Any],
        fallback_event_id: uuid.UUID | None = None,
        created_by: str | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> ScriptVersion:
        """Spawn a repaired candidate version linked to its parent (F3).

        The candidate starts at draft and can only serve compiled runs after
        a successful verification run (V4) — enforced by transition rules.
        """
        parent = await self.get_version(db, parent_version_id, tenant_id)
        if parent is None:
            raise LookupError(f"Parent ScriptVersion {parent_version_id} not found")

        repaired = await self.create_version(
            db,
            definition_id=parent.script_definition_id,
            declarative_step_graph=declarative_step_graph,
            version_label=f"{parent.version_label}.repair",
            parent_version_id=parent_version_id,
            created_by=created_by or "fallback-repair",
            tenant_id=tenant_id,
        )
        # Repair lineage (E9/E10)
        repaired.repaired_from_id = parent.id
        await db.flush()

        if fallback_event_id is not None:
            event = await db.get(FallbackEvent, fallback_event_id)
            if event is not None:
                event.repaired_version_id = repaired.id
                event.resulting_action = FallbackResultingAction.repaired_candidate_produced
                await db.flush()

        return repaired

    # ── Repair attempts & repair lineage (E9/E10) ─────────────────────────

    async def record_repair_attempt(
        self,
        db: AsyncSession,
        *,
        script_version_id: uuid.UUID,
        defect_diagnosis: str,
        declarative_step_graph: dict[str, Any],
        diff_applied: str | None = None,
        attempt_number: int = 1,
        retry_outcome: RepairRetryOutcome = RepairRetryOutcome.pending,
        created_by: str | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> RepairAttempt:
        """Persist a RepairAttempt and spawn the repaired candidate (E9/E10).

        The candidate is a new draft ScriptVersion with ``repaired_from``
        lineage pointing at the defective version; it must pass verification
        before it can serve compiled runs (V1/V4).
        """
        parent = await self.get_version(db, script_version_id, tenant_id)
        if parent is None:
            raise LookupError(f"ScriptVersion {script_version_id} not found")

        repaired = await self.create_version(
            db,
            definition_id=parent.script_definition_id,
            declarative_step_graph=declarative_step_graph,
            version_label=f"{parent.version_label}.r{attempt_number}",
            parent_version_id=parent.id,
            created_by=created_by or "agent-runtime-repair-loop",
            tenant_id=tenant_id,
        )
        # Repair lineage (E9/E10)
        repaired.repaired_from_id = parent.id
        await db.flush()

        # Link the attempt to the most recent fallback event for this version
        result = await db.execute(
            select(FallbackEvent)
            .where(FallbackEvent.script_version_id == script_version_id)
            .order_by(FallbackEvent.created_at.desc())
            .limit(1)
        )
        event = result.scalar_one_or_none()

        attempt = RepairAttempt(
            tenant_id=tenant_id or parent.tenant_id,
            fallback_event_id=event.id if event is not None else await self._ensure_fallback_event(
                db, parent, defect_diagnosis, tenant_id
            ),
            script_version_id=script_version_id,
            repaired_version_id=repaired.id,
            defect_diagnosis=defect_diagnosis,
            diff_applied=diff_applied,
            retry_outcome=retry_outcome,
        )
        db.add(attempt)
        await db.flush()
        await db.refresh(attempt)

        if event is not None:
            event.repaired_version_id = repaired.id
            event.resulting_action = FallbackResultingAction.repaired_candidate_produced
            await db.flush()

        span = trace.get_current_span()
        if span is not None:
            span.set_attribute("script.repair_attempt", str(attempt.id))
            span.set_attribute("script.repair_outcome", retry_outcome.value)

        logger.info(
            "RepairAttempt %s recorded (version=%s, candidate=%s, attempt=%d)",
            attempt.id, script_version_id, repaired.id, attempt_number,
        )
        return attempt

    async def _ensure_fallback_event(
        self,
        db: AsyncSession,
        parent: ScriptVersion,
        diagnosis: str,
        tenant_id: uuid.UUID | None,
    ) -> uuid.UUID:
        """Create a minimal fallback record so a RepairAttempt is always linked."""
        execution = await self.record_execution(
            db,
            outcome=ScriptExecutionOutcome.fell_back,
            script_version_id=parent.id,
            tenant_id=tenant_id,
        )
        event = await self.record_fallback(
            db,
            execution_record_id=execution.id,
            script_version_id=parent.id,
            trigger_reason=FallbackTriggerReason.execution_error,
            resulting_action=FallbackResultingAction.repair_not_produced,
            failure_detail=diagnosis,
            tenant_id=tenant_id,
        )
        return event.id

    async def update_repair_outcome(
        self,
        db: AsyncSession,
        attempt_id: uuid.UUID,
        retry_outcome: RepairRetryOutcome,
        tenant_id: uuid.UUID | None = None,
    ) -> RepairAttempt | None:
        attempt = await db.get(RepairAttempt, attempt_id)
        if attempt is None:
            return None
        if tenant_id is not None and attempt.tenant_id != tenant_id:
            return None
        attempt.retry_outcome = retry_outcome
        await db.flush()
        await db.refresh(attempt)
        return attempt

    async def list_repairs(
        self,
        db: AsyncSession,
        definition_id: uuid.UUID | None = None,
        script_version_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> list[RepairAttempt]:
        """List repair attempts, optionally scoped to a script definition (E10/G2)."""
        stmt = select(RepairAttempt).order_by(RepairAttempt.created_at.desc())
        if definition_id is not None:
            stmt = stmt.join(
                ScriptVersion,
                ScriptVersion.id == RepairAttempt.script_version_id,
            ).where(ScriptVersion.script_definition_id == definition_id)
        if script_version_id is not None:
            stmt = stmt.where(RepairAttempt.script_version_id == script_version_id)
        if tenant_id is not None:
            stmt = stmt.where(RepairAttempt.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ── Serving-version lookup (script-first dispatch; no modes) ──────────

    async def get_fresh_optimized_plan(
        self,
        db: AsyncSession,
        *,
        agent_type_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """Return the latest ready OptimizedImplementationPlan, only when it is
        fresher than the base implementation plan (execution preference).

        The Script-First Dispatcher consults this before running: a fresh
        optimized plan supersedes the base plan's scripts (fully_scripted →
        zero-LLM script; otherwise scripts are exposed as tools). A stale /
        absent / failed optimized plan returns ``None`` → base-plan fallback.
        """
        from app.db.models.optimized_plan import (
            OptimizedImplementationPlan,
            OptimizedPlanStatus,
        )

        result = await db.execute(
            select(OptimizedImplementationPlan)
            .where(
                OptimizedImplementationPlan.agent_type_id == agent_type_id,
                OptimizedImplementationPlan.status == OptimizedPlanStatus.ready,
            )
            .order_by(OptimizedImplementationPlan.updated_at.desc())
            .limit(1)
        )
        optimized = result.scalar_one_or_none()
        if optimized is None:
            return None
        if tenant_id is not None and optimized.tenant_id != tenant_id:
            return None

        base_plan = await db.get(AgentPlan, optimized.agent_plan_id)
        if base_plan is None:
            return None
        # Freshness: the optimized plan must be newer than the base plan it
        # optimized from (a regenerated base plan invalidates it).
        if optimized.updated_at is None or (
            base_plan.updated_at is not None
            and optimized.updated_at <= base_plan.updated_at
        ):
            return None
        return {
            "optimized_plan_id": optimized.id,
            "status": optimized.status.value,
            "fully_scripted": optimized.fully_scripted,
            "updated_at": optimized.updated_at,
        }

    async def get_serving_version(
        self,
        db: AsyncSession,
        *,
        agent_type_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """Current verified/compiled serving version for an agent type.

        Returns ``None`` when no serving version exists — the Script-First
        Dispatcher then takes the LLM path without error (E1–E3).
        """
        result = await db.execute(
            select(ScriptDefinition).where(
                ScriptDefinition.agent_type_id == agent_type_id,
                ScriptDefinition.lifecycle_status == ScriptLifecycleStatus.compiled,
            )
        )
        # Prefer the optimized-plan-linked composition: a legacy auto-compiled
        # definition must never shadow the optimized plan's serving script.
        definitions = sorted(
            result.scalars().all(),
            key=lambda d: d.source_optimized_plan_id is None,
        )
        for definition in definitions:
            if tenant_id is not None and definition.tenant_id != tenant_id:
                continue
            current_id = definition.current_version_id
            if current_id is None:
                continue
            current = await db.get(ScriptVersion, current_id)
            if current is not None and current.lifecycle_status == ScriptLifecycleStatus.compiled:
                return {
                    "script_definition_id": definition.id,
                    "script_definition_name": definition.name,
                    # Lineage (issue fix): the dispatcher must detect an
                    # optimized-plan artifact by its source-plan link, NOT by
                    # the definition name — command-authored scripts carry
                    # agent-chosen names, never ``optimized-<id8>``.
                    "source_optimized_plan_id": definition.source_optimized_plan_id,
                    "script_version_id": current.id,
                    "script_version_label": current.version_label,
                    "declarative_step_graph": current.declarative_step_graph,
                    "python_source": current.python_source,
                    "sandbox_validation_status": current.sandbox_validation_status,
                    "cpu_limit_seconds": current.cpu_limit_seconds,
                    "memory_limit_mb": current.memory_limit_mb,
                    "wall_time_limit_seconds": current.wall_time_limit_seconds,
                    "reference_tokens": None,
                    "fully_scripted": definition.fully_scripted,
                }
        return None

    async def list_invocable_scripts(
        self,
        db: AsyncSession,
        *,
        agent_type_id: uuid.UUID,
        tenant_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """All compiled (invocable) script definitions for an agent type.

        Powers the ``script____<name>`` virtual-tool surface: the Agent
        Runtime exposes each entry as a tool the agent LLM can invoke, and
        the AR script-execution endpoint resolves the payload by name.
        """
        result = await db.execute(
            select(ScriptDefinition).where(
                ScriptDefinition.agent_type_id == agent_type_id,
                ScriptDefinition.lifecycle_status == ScriptLifecycleStatus.compiled,
            )
        )
        items: list[dict[str, Any]] = []
        for definition in result.scalars().all():
            if tenant_id is not None and definition.tenant_id != tenant_id:
                continue
            current_id = definition.current_version_id
            if current_id is None:
                continue
            current = await db.get(ScriptVersion, current_id)
            if current is None:
                continue
            if (
                current.lifecycle_status != ScriptLifecycleStatus.compiled
                and current.lifecycle_status != ScriptLifecycleStatus.verified
            ):
                continue
            items.append(
                {
                    "script_definition_id": definition.id,
                    "script_version_id": current.id,
                    "script_version_label": current.version_label,
                    "name": definition.name,
                    "description": definition.description,
                    "declarative_step_graph": current.declarative_step_graph,
                    "python_source": current.python_source,
                    "sandbox_validation_status": current.sandbox_validation_status,
                    "cpu_limit_seconds": current.cpu_limit_seconds,
                    "memory_limit_mb": current.memory_limit_mb,
                    "wall_time_limit_seconds": current.wall_time_limit_seconds,
                    "fully_scripted": definition.fully_scripted,
                }
            )
        return items

    # ── Audit & cost reporting (G2–G4) ────────────────────────────────────

    async def cost_report(
        self,
        db: AsyncSession,
        *,
        agent_type_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Aggregate tokens saved vs LLM baseline and run mix (G3, G4)."""
        stmt = select(ScriptExecutionRecord)
        if agent_type_id is not None or tenant_id is not None:
            stmt = stmt.join(
                ScriptVersion,
                ScriptVersion.id == ScriptExecutionRecord.script_version_id,
                isouter=True,
            ).join(
                ScriptDefinition,
                ScriptDefinition.id == ScriptVersion.script_definition_id,
                isouter=True,
            )
            if agent_type_id is not None:
                stmt = stmt.where(ScriptDefinition.agent_type_id == agent_type_id)
            if tenant_id is not None:
                stmt = stmt.where(ScriptExecutionRecord.tenant_id == tenant_id)
        if since is not None:
            stmt = stmt.where(ScriptExecutionRecord.created_at >= since)
        if until is not None:
            stmt = stmt.where(ScriptExecutionRecord.created_at <= until)

        result = await db.execute(stmt)
        records = list(result.scalars().all())

        # No execution modes exist: script runs reference a script version,
        # LLM-only fallback records do not (E1–E3).
        script_runs = [r for r in records if r.script_version_id is not None]
        llm_runs = [r for r in records if r.script_version_id is None]
        fell_back = [r for r in script_runs if r.outcome == ScriptExecutionOutcome.fell_back]

        tokens_saved = sum(r.tokens_saved_estimate or 0 for r in script_runs)
        residual_model_steps = sum(
            len(r.model_backed_steps_used or []) for r in script_runs
        )
        total = len(records)
        return {
            "total_executions": total,
            "script_runs": len(script_runs),
            "llm_runs": len(llm_runs),
            "fallback_runs": len(fell_back),
            "script_hit_rate": (len(script_runs) - len(fell_back)) / total if total else 0.0,
            "fallback_rate": len(fell_back) / total if total else 0.0,
            "tokens_saved_total": tokens_saved,
            "residual_model_backed_steps": residual_model_steps,
        }

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _next_version_label(self, db: AsyncSession, definition_id: uuid.UUID) -> str:
        result = await db.execute(
            select(func.count())
            .select_from(ScriptVersion)
            .where(ScriptVersion.script_definition_id == definition_id)
        )
        count = int(result.scalar_one())
        return f"v{count + 1}"
