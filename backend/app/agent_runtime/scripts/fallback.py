"""Fallback handling (Agent Runtime).

Wraps compiled script runs. On ANY failure (tool schema mismatch, output
validation failure, script/execution error — F1) it **unconditionally**
switches execution to the LLM agent path: a run never fails solely because a
script failed (E2). There are no execution modes and no compiled-only
structured-failure path.

Every fallback is reported to Control Center with reason, script version,
failure detail and resulting action (F2), and hands off to the bounded
self-improvement repair loop (E9/E10). Permissions are never widened during
fallback: the LLM path runs under the same identity as the script path.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from opentelemetry import trace

from app.agent_runtime.scripts.cc_client import ScriptRegistryClient
from app.agent_runtime.scripts.runner import (
    ExecutionError,
    OutputValidationFailure,
    SchemaMismatch,
    ScriptExecutionError,
)
from app.agent_runtime.scripts.sandbox import (
    ResourceLimitExceededError,
    SandboxError,
    SandboxViolationError,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Wire values (mirror FallbackTriggerReason / FallbackResultingAction in CC schemas)
TRIGGER_EXECUTION_ERROR = "execution_error"
TRIGGER_SCHEMA_MISMATCH = "tool_schema_mismatch"
TRIGGER_OUTPUT_VALIDATION = "output_validation_failure"
TRIGGER_SANDBOX_VIOLATION = "sandbox_violation"
TRIGGER_RESOURCE_LIMIT = "resource_limit_exceeded"

ACTION_LLM_COMPLETED = "llm_completed"
ACTION_REPAIR_PRODUCED = "repaired_candidate_produced"
ACTION_REPAIR_NOT_PRODUCED = "repair_not_produced"


# The LLM agent path: an async callable that completes the run using the
# normal agent loop. Wired by the Script-First Dispatcher; the controller
# never touches tools directly during fallback — it delegates to the existing
# execution path under the same identity/permissions.
LLMFallbackPath = Callable[[dict[str, Any]], Awaitable[Any]]


class FallbackController:
    """Detects script failure and unconditionally routes to the LLM path (E2)."""

    def __init__(self, registry_client: ScriptRegistryClient) -> None:
        self._registry = registry_client

    async def run_with_fallback(
        self,
        run_coroutine: Callable[[], Awaitable[Any]],
        *,
        script_version_id: str | None,
        script_version_label: str | None,
        session_id: str | None,
        agent_type_id: str,
        llm_fallback: LLMFallbackPath | None = None,
        run_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a script run; on any typed failure fall back unconditionally.

        Returns the script result on success, otherwise the LLM path result.
        The fallback itself is reported (F2) with the recorded reason.
        """
        try:
            return await run_coroutine()
        except (ScriptExecutionError, SandboxError) as exc:
            trigger, detail = self._classify(exc)
            span = trace.get_current_span()
            if span is not None:
                span.set_attribute("script.fallback_reason", trigger)

            logger.warning(
                "Script run failed (version=%s, trigger=%s); falling back to LLM: %s",
                script_version_id, trigger, detail,
            )

            # Record the execution as fell_back first, so the fallback event
            # can link to the execution record (G2 provenance). Sandbox
            # failures carry termination + one-line violation detail (Flow C).
            execution = await self._registry.report_execution(
                {
                    "script_version_id": script_version_id,
                    "outcome": "fell_back",
                    "tools_invoked": None,
                    "model_backed_steps_used": None,
                    "session_id": session_id,
                    "tokens_saved_estimate": None,
                    **self.sandbox_fields(exc),
                }
            )
            execution_record_id = execution.get("id") if isinstance(execution, dict) else None

            if llm_fallback is None:
                # Unconditional fallback is the fixed strategy — a missing LLM
                # path is a wiring error, not a mode-conditional outcome.
                await self._registry.report_fallback(
                    {
                        "execution_record_id": execution_record_id,
                        "script_version_id": script_version_id,
                        "trigger_reason": trigger,
                        "resulting_action": ACTION_REPAIR_NOT_PRODUCED,
                        "failure_detail": f"{detail}; no LLM fallback path wired",
                    }
                )
                raise

            # F3: LLM path completes the run under the SAME identity/permissions.
            try:
                result = await llm_fallback(run_context or {})
            except Exception as llm_exc:
                logger.error("LLM fallback path failed: %s", llm_exc)
                await self._registry.report_fallback(
                    {
                        "execution_record_id": execution_record_id,
                        "script_version_id": script_version_id,
                        "trigger_reason": trigger,
                        "resulting_action": ACTION_REPAIR_NOT_PRODUCED,
                        "failure_detail": f"{detail}; llm fallback failed: {llm_exc}",
                    }
                )
                raise

            await self._registry.report_fallback(
                {
                    "execution_record_id": execution_record_id,
                    "script_version_id": script_version_id,
                    "trigger_reason": trigger,
                    "resulting_action": ACTION_LLM_COMPLETED,
                    "failure_detail": detail,
                }
            )
            return result

    # ── Classification (F1) ───────────────────────────────────────────────

    def _classify(self, exc: ScriptExecutionError) -> tuple[str, str]:
        if isinstance(exc, ResourceLimitExceededError):
            return TRIGGER_RESOURCE_LIMIT, str(exc)
        if isinstance(exc, SandboxViolationError):
            return TRIGGER_SANDBOX_VIOLATION, str(exc)
        if isinstance(exc, SchemaMismatch):
            return TRIGGER_SCHEMA_MISMATCH, str(exc)
        if isinstance(exc, OutputValidationFailure):
            return TRIGGER_OUTPUT_VALIDATION, str(exc)
        if isinstance(exc, ExecutionError):
            return TRIGGER_EXECUTION_ERROR, str(exc)
        return TRIGGER_EXECUTION_ERROR, f"{type(exc).__name__}: {exc}"

    @staticmethod
    def sandbox_fields(exc: BaseException) -> dict[str, Any]:
        """Sandbox accounting fields for the execution record (N5/Flow C).

        Returns ``sandbox_termination`` and a one-line human-readable
        ``sandbox_violation_detail`` when the failure originated in the
        sandbox; empty dict otherwise.
        """
        if isinstance(exc, (SandboxViolationError, ResourceLimitExceededError)):
            return {
                "sandbox_termination": getattr(
                    exc, "sandbox_termination", False
                ),
                "sandbox_violation_detail": str(exc)[:500],
            }
        return {}
