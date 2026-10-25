"""Self-improvement repair loop (Agent Runtime, E9/E10).

On a script-defect failure the dispatcher runs a bounded repair cycle:

1. **Diagnose** — deterministic defect classification from the typed failure
   plus the failure detail (the dispatcher stays deterministic).
2. **Repair** — the LLM agent path produces a repaired candidate step graph.
   Control Center persists the ``RepairAttempt`` record and the candidate as
   a new draft ``ScriptVersion`` with ``repaired_from`` lineage.
3. **Re-verify & retry** — the candidate must pass verification (V1/V4)
   before it can serve; the dispatcher retries the script path with it.

The loop is bounded by ``MAX_REPAIR_ATTEMPTS`` (default 2). Exhaustion is
recorded (retry outcome + repair exhaustion fallback reason) and the run
stays on the LLM path. Permissions never widen during repair; scripts never
hold credentials; all external interaction stays on the MCP tool-call path.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from opentelemetry import trace

from app.agent_runtime.scripts.cc_client import ScriptRegistryClient
from app.agent_runtime.scripts.runner import (
    ExecutionError,
    OutputValidationFailure,
    SchemaMismatch,
    ScriptExecutionError,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Execution guardrail: maximum repair attempts per fallback episode (E9/E10).
MAX_REPAIR_ATTEMPTS = 2

# Wire values (mirror RepairRetryOutcome in CC schemas)
RETRY_PENDING = "pending"
RETRY_SUCCEEDED = "succeeded"
RETRY_FAILED = "failed"


@dataclass
class RepairContext:
    """Everything the repair loop needs for one fallback episode."""

    script_definition_id: str | None
    script_version_id: str
    graph_json: dict[str, Any] | None
    session_id: str
    agent_type_id: str


@dataclass
class RepairResult:
    """Outcome of one repair episode."""

    repaired_version_id: str | None = None
    repaired_graph_json: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    exhausted: bool = False

    @property
    def has_candidate(self) -> bool:
        return self.repaired_version_id is not None


class RepairLoop:
    """Bounded defect-diagnosis → repaired-candidate → re-verify → retry loop."""

    def __init__(
        self,
        registry_client: ScriptRegistryClient,
        *,
        max_attempts: int = MAX_REPAIR_ATTEMPTS,
    ) -> None:
        self._registry = registry_client
        self._max_attempts = max_attempts

    async def run(
        self,
        context: RepairContext,
        failure: ScriptExecutionError,
        *,
        llm_repair_generator: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
        | None = None,
    ) -> RepairResult:
        """Run the bounded repair cycle for one script failure.

        Args:
            context: script/version/session identification.
            failure: the typed failure that triggered the fallback (F1).
            llm_repair_generator: the LLM agent path, invoked as
                ``await generator(diagnosis, graph_json) -> {"declarative_step_graph": ...,
                "diff_applied": ...}``. Repair generation is done by the LLM;
                this loop only orchestrates deterministically.

        Returns a ``RepairResult``; ``has_candidate`` is True when a verified
        repaired candidate is ready to retry.
        """
        result = RepairResult()
        trigger, diagnosis = self._diagnose(failure)

        with tracer.start_as_current_span("script.repair_attempt") as span:
            span.set_attribute("script.defect", trigger)
            span.set_attribute("script.max_repair_attempts", self._max_attempts)

            for attempt in range(1, self._max_attempts + 1):
                span.set_attribute("script.repair_outcome", "attempt")
                candidate = await self._produce_candidate(
                    context,
                    trigger,
                    diagnosis,
                    attempt,
                    llm_repair_generator,
                )
                if candidate is None:
                    # No candidate could be produced — record exhaustion.
                    result.exhausted = True
                    break

                repaired_version_id, graph_json = candidate
                result.attempts.append(
                    {
                        "attempt": attempt,
                        "repaired_version_id": repaired_version_id,
                    }
                )

                # The candidate must re-verify before it can serve (V1/V4) —
                # verification + promotion are orchestrated by the dispatcher
                # via the CC registry; a candidate only reaches us if CC
                # reports it as serving-eligible. If verification fails
                # CC-side, the candidate stays draft and is not returned.
                verified = await self._verify_candidate(repaired_version_id)
                if not verified:
                    logger.info(
                        "Repair attempt %d for version %s failed re-verification",
                        attempt, context.script_version_id,
                    )
                    continue

                result.repaired_version_id = repaired_version_id
                result.repaired_graph_json = graph_json
                span.set_attribute("script.repair_outcome", "succeeded")
                return result

            result.exhausted = True
            span.set_attribute("script.repair_outcome", "exhausted")
            logger.warning(
                "Repair budget exhausted for script version %s after %d attempt(s); "
                "staying on the LLM path",
                context.script_version_id, len(result.attempts),
            )
            return result

    # ── Diagnosis (deterministic, F1-classified) ──────────────────────────

    def _diagnose(self, failure: ScriptExecutionError) -> tuple[str, str]:
        """Classify the defect and produce a deterministic diagnosis string."""
        if isinstance(failure, SchemaMismatch):
            trigger = "tool_schema_mismatch"
        elif isinstance(failure, OutputValidationFailure):
            trigger = "output_validation_failure"
        elif isinstance(failure, ExecutionError):
            trigger = "execution_error"
        else:  # pragma: no cover — typed base caught by caller
            trigger = "execution_error"
        diagnosis = (
            f"Script defect ({trigger}) in version {failure}: "
            f"{type(failure).__name__}"
        )
        return trigger, diagnosis

    # ── Candidate production (LLM-generated; CC persists) ─────────────────

    async def _produce_candidate(
        self,
        context: RepairContext,
        trigger: str,
        diagnosis: str,
        attempt: int,
        llm_repair_generator: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
        | None,
    ) -> tuple[str, dict[str, Any]] | None:
        """Have the LLM produce a repaired candidate; CC persists it (E9)."""
        if context.graph_json is None:
            return None
        graph_json = context.graph_json
        diff_applied = f"repair attempt {attempt} ({trigger})"
        if llm_repair_generator is not None:
            try:
                produced = await llm_repair_generator(diagnosis, context.graph_json)
                graph_json = (
                    produced.get("declarative_step_graph") or context.graph_json
                )
                diff_applied = str(produced.get("diff_applied") or diff_applied)
            except Exception as exc:
                logger.warning(
                    "LLM repair generation failed (attempt %d): %s", attempt, exc
                )
                return None

        try:
            response = await self._registry.report_repair(
                {
                    "script_version_id": context.script_version_id,
                    "declarative_step_graph": graph_json,
                    "defect_diagnosis": diagnosis,
                    "diff_applied": diff_applied,
                    "attempt_number": attempt,
                    "created_by": "agent-runtime-repair-loop",
                }
            )
        except Exception as exc:
            logger.warning("Repair attempt report failed (attempt %d): %s", attempt, exc)
            return None

        repaired_version_id = (
            response.get("repaired_version_id") if isinstance(response, dict) else None
        )
        if not repaired_version_id:
            return None
        return str(repaired_version_id), graph_json

    async def _verify_candidate(self, repaired_version_id: str) -> bool:
        """Ask CC whether the repaired candidate passed re-verification (V1)."""
        try:
            version = await self._registry.get_version(repaired_version_id)
        except Exception as exc:
            logger.warning("Failed to fetch repaired candidate %s: %s",
                           repaired_version_id, exc)
            return False
        status = (version or {}).get("lifecycle_status")
        # Only a verified/compiled candidate may serve (V4, enforced CC-side).
        return status in ("verified", "compiled")
