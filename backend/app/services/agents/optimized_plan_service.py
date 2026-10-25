"""OptimizedPlanService — persistence & association for the "Optimize & Verify" flow.

The optimize flow is now a COMMAND-PROMPT-DRIVEN SPECIAL AGENT EXECUTION: a
side execution of the agent (whose prompt is the ``optimize-and-verify``
command mission, NOT the agent type's own system instruction) authors the
workflow composition through the new system tools — ``generate_script``,
``execute_script`` and ``generate_optimized_plan``.

This service is the THIN persistence layer behind those tools. It keeps ONLY:

- the ``OptimizedImplementationPlan`` entity + persistence (upsert, read,
  feedback memory), and
- script-version association + promotion (so the Script-First Dispatcher's
  unchanged dispatch-preference gating picks up a fresh ``ready`` plan).

The bespoke optimizer (LLM authoring prompt, generate→test→refine loop,
composition normalization/chaining/splitting) is REMOVED — the agent does
authoring + verification through the sandboxed tools now.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace
from sqlalchemy import select

from app.db.models.agents import AgentPlan, AgentType
from app.db.models.optimized_plan import (
    OptimizedImplementationPlan,
    OptimizedPlanStatus,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class OptimizedPlanService:
    """Thin persistence layer behind the optimize-and-verify system tools."""

    # ── Reads (get_* system tools) ────────────────────────────────────────

    async def get_base_plan_steps(
        self, db: Any, agent_type_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Return the base (high-level) implementation plan steps for an agent type."""
        result = await db.execute(
            select(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
        )
        plan = result.scalar_one_or_none()
        return (plan.plan_steps or []) if plan else []

    async def get_latest_optimized_plan(
        self, db: Any, agent_type_id: uuid.UUID
    ) -> OptimizedImplementationPlan | None:
        """Return the latest optimized plan row for an agent type (or None)."""
        result = await db.execute(
            select(OptimizedImplementationPlan)
            .where(OptimizedImplementationPlan.agent_type_id == agent_type_id)
            .order_by(OptimizedImplementationPlan.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def retire_optimized_plan(self, db: Any, agent_type_id: uuid.UUID) -> int:
        """Mark ALL optimized plan rows for an agent type as ``retired``.

        Retired rows are KEPT for reference (composition lineage, feedback
        memory) but never gate execution: the dispatcher serves only
        ``ready`` plans. After retiring, the next Run Agent flow finds no
        `ready` plan and offers the opt-in optimization dialog again.
        Pair with ``ScriptRegistryService.retire_serving_versions`` so no
        stale serving script can shadow the next LLM-path execution.
        """
        result = await db.execute(
            select(OptimizedImplementationPlan).where(
                OptimizedImplementationPlan.agent_type_id == agent_type_id,
                OptimizedImplementationPlan.status != OptimizedPlanStatus.retired,
            )
        )
        plans = list(result.scalars().all())
        for plan in plans:
            plan.status = OptimizedPlanStatus.retired
        await db.flush()
        return len(plans)

    # ── Writes (generate_optimized_plan tool) ─────────────────────────────

    async def generate_optimized_plan(
        self,
        db: Any,
        *,
        agent_type: AgentType,
        base_plan: AgentPlan,
        steps: list[dict[str, Any]],
        fully_scripted: bool,
        output_mode: str | None = None,
        output_template: str | None = None,
        status: OptimizedPlanStatus | str = OptimizedPlanStatus.ready,
        error: str | None = None,
    ) -> OptimizedImplementationPlan:
        """Upsert the optimized plan and associate/promote the authored scripts.

        ``steps`` is the model-authored composition: each step may carry
        ``python_source`` (for the raw-log dialog) and/or ``script_version_id``
        (the script version the agent authored via ``generate_script``).
        """
        with tracer.start_as_current_span(
            "optimized_plan.generate_from_agent",
            attributes={"agent_type_id": str(agent_type.id)},
        ):
            status_enum = (
                status
                if isinstance(status, OptimizedPlanStatus)
                else OptimizedPlanStatus(str(status))
            )
            # The final output contract travels as top-level tool args; merge
            # them onto the LAST authored step so the raw-log dialog and the
            # dispatcher see a single, self-contained composition.
            if steps and (output_mode or output_template):
                final = dict(steps[-1])
                if output_mode and not final.get("output_mode"):
                    final["output_mode"] = output_mode
                if output_template and not final.get("output_template"):
                    final["output_template"] = output_template
                steps = [*steps[:-1], final]

            optimized = await self._upsert_optimized_plan(
                db,
                agent_type_id=agent_type.id,
                agent_plan_id=base_plan.id,
                plan_steps=steps,
                fully_scripted=fully_scripted,
                status=status_enum,
                error=error,
            )
            optimized.generated_at = datetime.now(timezone.utc)
            await db.flush()

            # Only a READY plan promotes its authored scripts to compiled
            # (a failed / needs_feedback plan must never leave a serving
            # artifact — the dispatcher's freshness gate serves only ready).
            if status_enum == OptimizedPlanStatus.ready:
                await self._associate_scripts(
                    db, agent_type, base_plan, optimized, steps, fully_scripted
                )
            await db.refresh(optimized)
            logger.info(
                "Optimized plan %s generated by agent for agent_type=%s "
                "(fully_scripted=%s, status=%s)",
                optimized.id, agent_type.id, fully_scripted, status_enum.value,
            )
            return optimized

    async def mark_failed(
        self,
        db: Any,
        *,
        agent_type_id: uuid.UUID,
        agent_plan_id: uuid.UUID,
        error: str,
    ) -> OptimizedImplementationPlan:
        """Persist a ``failed`` plan (no serving artifact).

        Used when the optimize side-execution fails to even start (e.g. the
        Communication Hub → Agent Runtime trigger errors) so the plan status
        reflects the REAL outcome instead of a stale ``ready`` plan from a
        previous run.
        """
        optimized = await self._upsert_optimized_plan(
            db,
            agent_type_id=agent_type_id,
            agent_plan_id=agent_plan_id,
            plan_steps=None,
            fully_scripted=False,
            status=OptimizedPlanStatus.failed,
            error=error,
        )
        optimized.generated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(optimized)
        logger.info(
            "Marked optimized plan %s as failed for agent_type=%s",
            optimized.id, agent_type_id,
        )
        return optimized

    # ── Script association (dispatch-preference feeding) ──────────────────

    async def _associate_scripts(
        self,
        db: Any,
        agent_type: AgentType,
        base_plan: AgentPlan,
        optimized: OptimizedImplementationPlan,
        steps: list[dict[str, Any]],
        fully_scripted: bool,
    ) -> None:
        """Retire stale serving versions, then promote the authored scripts.

        Each authored script step carries a ``script_version_id`` (created by
        ``generate_script``); its definition is linked to the optimized plan and
        the version is promoted to ``compiled`` so the Script-First Dispatcher
        serves it. A ``fully_scripted`` composition serves zero-LLM; otherwise
        the scripts stay invocable ``script____<name>`` tools.
        """
        from app.db.models.script_registry import (
            ScriptDefinition,
            ScriptLifecycleStatus,
        )
        from app.services.script_registry import ScriptRegistryService

        service = ScriptRegistryService()

        # The optimized plan supersedes any previously compiled serving scripts.
        await service.retire_serving_versions(
            db, agent_type.id, actor="optimize-plan"
        )

        for step in steps:
            version_id = step.get("script_version_id") if isinstance(step, dict) else None
            if version_id is None:
                continue
            try:
                version_id = uuid.UUID(str(version_id))
            except (ValueError, TypeError):
                continue
            version = await service.get_version(db, version_id)
            if version is None:
                continue
            definition = await db.get(ScriptDefinition, version.script_definition_id)
            if definition is None:
                continue
            definition.source_optimized_plan_id = optimized.id
            definition.fully_scripted = fully_scripted
            await db.flush()

            if version.lifecycle_status != ScriptLifecycleStatus.compiled:
                try:
                    await service.transition_version(
                        db, version.id, ScriptLifecycleStatus.compiled,
                        actor="optimize-plan",
                    )
                except Exception:
                    # draft → verified → compiled fallback (mirrors internal API).
                    await service.transition_version(
                        db, version.id, ScriptLifecycleStatus.verified,
                        actor="optimize-plan",
                    )
                    await service.transition_version(
                        db, version.id, ScriptLifecycleStatus.compiled,
                        actor="optimize-plan",
                    )
            await db.flush()
            logger.info(
                "Promoted authored script version %s (definition=%s) for "
                "optimized plan %s",
                version.id, definition.id, optimized.id,
            )

    # ── Feedback loop (memory) ────────────────────────────────────────────

    async def add_feedback(
        self,
        agent_type: AgentType,
        db: Any,
        raw_feedback: str,
    ) -> OptimizedImplementationPlan:
        """Summarize user feedback (one-shot LLM via the model layer) and append."""
        optimized = await self.get_latest_optimized_plan(db, agent_type.id)
        if optimized is None:
            raise ValueError(
                "no optimized plan exists yet — run Optimize & Verify first"
            )
        summary = await self._summarize_feedback(agent_type, db, raw_feedback)
        comments = list(optimized.feedback_comments or [])
        comments.append({
            "created_at": datetime.now(timezone.utc).isoformat(),
            "raw_feedback": raw_feedback.strip(),
            "summary": summary,
        })
        optimized.feedback_comments = comments
        await db.flush()
        await db.refresh(optimized)
        logger.info(
            "Feedback accumulated on optimized plan %s (%d comment(s) total)",
            optimized.id, len(comments),
        )
        return optimized

    async def _summarize_feedback(
        self, agent_type: AgentType, db: Any, raw_feedback: str
    ) -> str:
        """One-shot LLM summarization; falls back to the raw feedback on failure."""
        from app.services.agents.plan_generation_service import PlanGenerationService

        prompt = (
            "Summarize the following user feedback about an agent's optimized "
            "workflow plan in ONE concise sentence that captures the requested "
            "change. Respond with ONLY the summary sentence.\n\n"
            f"User feedback:\n\"\"\"\n{raw_feedback.strip()}\n\"\"\""
        )
        try:
            plan_service = PlanGenerationService()
            raw_response = await plan_service._invoke_llm(agent_type, db, prompt)
            text = plan_service._extract_text_from_response(raw_response)
            summary = (text or "").strip().strip('"')
            if summary:
                return summary.splitlines()[0][:500]
        except Exception as exc:
            logger.warning("Feedback summarization failed (%s) — storing raw", exc)
        return raw_feedback.strip()[:500]

    # ── Persistence helpers ───────────────────────────────────────────────

    async def _upsert_optimized_plan(
        self,
        db: Any,
        *,
        agent_type_id: uuid.UUID,
        agent_plan_id: uuid.UUID,
        plan_steps: list[dict[str, Any]] | None,
        fully_scripted: bool,
        status: OptimizedPlanStatus,
        error: str | None,
    ) -> OptimizedImplementationPlan:
        """Insert a new ACTIVE optimized plan row for an agent type.

        Any previous non-retired rows are MARKED ``retired`` (kept for
        reference — never deleted) so exactly ONE active record per agent
        type exists at any time. The dispatcher's freshness gate serves only
        ``ready`` rows, so a retired predecessor can never gate execution.
        """
        result = await db.execute(
            select(OptimizedImplementationPlan).where(
                OptimizedImplementationPlan.agent_type_id == agent_type_id,
                OptimizedImplementationPlan.status != OptimizedPlanStatus.retired,
            )
        )
        for stale in result.scalars().all():
            stale.status = OptimizedPlanStatus.retired

        now = datetime.now(timezone.utc)
        optimized = OptimizedImplementationPlan(
            agent_type_id=agent_type_id,
            agent_plan_id=agent_plan_id,
            plan_steps=plan_steps,
            fully_scripted=fully_scripted,
            status=status,
            error=error,
            generated_at=now,
        )
        db.add(optimized)
        await db.flush()
        await db.refresh(optimized)
        return optimized
