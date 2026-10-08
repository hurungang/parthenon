"""Decision execution engine — state build, dispatch, response parse, gate, persist.

Orchestrates one decision tool execution in Control Center:
resolve the decision tool (within the caller's tenant) → apply the state
preset to input/agent data → single evaluation dispatch of all questions →
normalize typed answers → compute the confidence gate → persist a
DecisionExecutionResult keyed to the tool.

Confidence gating
-----------------
``compute_confidence_gate`` maps the effective confidence and the tool's
thresholds to an outcome: confidence >= act_threshold → ``act``;
confidence >= confirm_threshold → ``confirm``; else ``escalate``.

Noul questions have no provider-supplied ``confidence`` field. For gating
purposes their effective confidence is derived as ``abs(2 * noul - 1)`` —
a noul value at the extremes (0 or 1) means maximal confidence, 0.5 means
maximal uncertainty. This derivation is intentionally conservative and is
documented here as the single source of truth.

The engine-wide gate uses the MINIMUM effective confidence across all
answered questions: a decision is only as trustworthy as its least
confident answer.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.decision_tools import (
    DecisionQuestionType,
    DecisionTool,
    DecisionToolQuestion,
)
from app.db.models.results import (
    DecisionExecutionResult,
    DecisionExecutionStatus,
    DecisionOutcome,
)
from app.schemas.decision_tools import StatePresetMapping
from app.services.system_one.client import (
    SystemOneClient,
    SystemOneClientError,
    TypeSafeJevClient,
    build_questions_payload,
)
from app.services.system_one.decision_tool_service import (
    DecisionToolService,
    DecisionToolValidationError,
)
from app.services.system_one.provider_config_service import (
    SystemOneProviderConfigService,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def derive_effective_confidence(answer: dict[str, Any]) -> float:
    """Return the confidence used for gating for one normalized answer.

    Uses the provider-supplied ``confidence`` when present; for noul answers
    (which carry no confidence field) derives ``abs(2 * noul - 1)``.
    """
    confidence = answer.get("confidence")
    if confidence is not None:
        return float(confidence)
    value = answer.get("noul")
    if value is not None:
        return abs(2.0 * float(value) - 1.0)
    return 0.0


def compute_confidence_gate(
    confidence: float,
    act_threshold: float,
    confirm_threshold: float,
) -> DecisionOutcome:
    """Map confidence + thresholds to act / confirm / escalate."""
    if confidence >= act_threshold:
        return DecisionOutcome.act
    if confidence >= confirm_threshold:
        return DecisionOutcome.confirm
    return DecisionOutcome.escalate


class DecisionExecutionError(Exception):
    """Raised when a decision tool cannot be executed."""


class DecisionExecutionEngine:
    """Executes decision tools against the configured System One provider."""

    def __init__(
        self,
        client: SystemOneClient | None = None,
        provider_service: SystemOneProviderConfigService | None = None,
        tool_service: DecisionToolService | None = None,
    ) -> None:
        self._client = client or TypeSafeJevClient()
        self._providers = provider_service or SystemOneProviderConfigService()
        self._tools = tool_service or DecisionToolService()

    async def resolve_tool(
        self,
        db: AsyncSession,
        name: str,
        tenant_id: uuid.UUID | None,
    ) -> DecisionTool:
        """Resolve a decision tool by name WITHIN the caller's tenant.

        Tenant-contained: a tool named ``tool_a`` in tenant A is never
        resolvable from tenant B.
        """
        tool = await self._tools.get_by_name(db, name, tenant_id)
        if not tool:
            raise DecisionExecutionError(
                f"Decision tool '{name}' not found in tenant"
                f"{'' if tenant_id is None else f' {tenant_id}'}"
            )
        if not tool.enabled:
            raise DecisionExecutionError(f"Decision tool '{name}' is disabled")
        return tool

    async def execute(
        self,
        db: AsyncSession,
        tool: DecisionTool,
        input_state: dict[str, Any] | None = None,
        conversation_session_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> DecisionExecutionResult:
        """Run one decision execution and persist a result (completed or failed)."""
        questions = sorted(tool.questions, key=lambda q: q.ordering)

        try:
            state = self.build_state(tool.state_preset, input_state or {})
            questions_payload = {
                q.question_key: build_questions_payload(
                    q.question_type, q.instructions, q.criteria_options
                )
                for q in questions
            }

            # Resolve provider + decrypt key INSIDE the execution path only.
            # Tenant containment: resolution is scoped to the tool's tenant.
            provider, api_key = await self._providers.get_active_provider(
                db, tenant_id if tenant_id is not None else tool.tenant_id
            )
            model = tool.provider_model or provider.default_model

            with tracer.start_as_current_span("system_one.evaluate") as span:
                span.set_attribute("system_one.provider", provider.provider_type.value)
                span.set_attribute("system_one.model", model)
                span.set_attribute("system_one.tool", tool.name)
                span.set_attribute("system_one.questions", len(questions_payload))
                raw_response = await self._client.evaluate(
                    base_url=provider.base_url,
                    api_key=api_key,
                    model=model,
                    state=state,
                    questions=questions_payload,
                )

            answers = self.normalize_answers(raw_response, questions)
            gate_confidence = min(
                (derive_effective_confidence(a) for a in answers.values()),
                default=0.0,
            )
            outcome = compute_confidence_gate(
                gate_confidence, tool.act_threshold, tool.confirm_threshold
            )
            result = DecisionExecutionResult(
                tenant_id=tenant_id if tenant_id is not None else tool.tenant_id,
                decision_tool_id=tool.id,
                conversation_session_id=conversation_session_id,
                input_state_snapshot=state,
                answers={"answers": answers, "gate_confidence": gate_confidence},
                outcome=outcome,
                status=DecisionExecutionStatus.completed,
                provider_model=raw_response.get("model", model),
            )
            db.add(result)
            await db.flush()
            await db.refresh(result)
            logger.info(
                "Decision tool '%s' executed: outcome=%s gate_confidence=%.3f",
                tool.name,
                outcome.value,
                gate_confidence,
            )
            return result
        except (DecisionExecutionError, SystemOneClientError, Exception) as exc:
            logger.exception("Decision tool '%s' execution failed", tool.name)
            try:
                snapshot = (
                    self.build_state(tool.state_preset, input_state or {})
                    if tool.state_preset
                    else None
                )
            except Exception:
                # Preset itself failed to resolve — persist the failure
                # without a snapshot rather than masking the original error.
                snapshot = None
            failed = DecisionExecutionResult(
                tenant_id=tenant_id if tenant_id is not None else tool.tenant_id,
                decision_tool_id=tool.id,
                conversation_session_id=conversation_session_id,
                input_state_snapshot=snapshot,
                answers=None,
                outcome=DecisionOutcome.escalate,
                status=DecisionExecutionStatus.failed,
                provider_model=None,
                error_message=str(exc)[:2000],
            )
            db.add(failed)
            await db.flush()
            await db.refresh(failed)
            return failed

    # ── State + response handling ─────────────────────────────────────────

    @staticmethod
    def build_state(
        state_preset: dict[str, Any] | None,
        input_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply the state preset to the execution input.

        Each preset mapping resolves ``state_key`` from:
        - ``input``: ``input_state[key]``
        - ``agent_data``: ``input_state["agent_data"][key]`` (named data saved
          by the agent during the session, passed in under ``agent_data``).

        Unresolvable mappings raise a validation error so failures are explicit.
        """
        if not state_preset:
            return dict(input_state)
        state: dict[str, Any] = {}
        errors: list[str] = []
        for state_key, raw in state_preset.items():
            mapping = (
                raw
                if isinstance(raw, StatePresetMapping)
                else StatePresetMapping.model_validate(raw)
            )
            if mapping.source == "input":
                if mapping.key not in input_state:
                    errors.append(
                        f"state key '{state_key}': input data key '{mapping.key}' not provided"
                    )
                else:
                    state[state_key] = input_state[mapping.key]
            elif mapping.source == "agent_data":
                agent_data = input_state.get("agent_data") or {}
                if mapping.key not in agent_data:
                    errors.append(
                        f"state key '{state_key}': agent data key '{mapping.key}' not provided"
                    )
                else:
                    state[state_key] = agent_data[mapping.key]
        if errors:
            raise DecisionToolValidationError(errors)
        return state

    @staticmethod
    def normalize_answers(
        raw_response: dict[str, Any],
        questions: list[DecisionToolQuestion],
    ) -> dict[str, dict[str, Any]]:
        """Normalize the provider response into per-question typed answers."""
        raw_answers = raw_response.get("answers") or {}
        normalized: dict[str, dict[str, Any]] = {}
        for question in questions:
            raw = raw_answers.get(question.question_key)
            if raw is None:
                if question.is_required:
                    raise SystemOneClientError(
                        f"Provider response missing required answer for "
                        f"question '{question.question_key}'"
                    )
                continue
            qtype = question.question_type
            answer: dict[str, Any] = {
                "type": raw.get("type", qtype.value),
                "question_type": qtype.value,
            }
            value = raw.get(qtype.value)
            if value is None:
                value = next(
                    (raw.get(t.value) for t in DecisionQuestionType if raw.get(t.value) is not None),
                    None,
                )
            answer["value"] = value
            if qtype == DecisionQuestionType.choice:
                answer["choice"] = value
            elif qtype == DecisionQuestionType.score:
                answer["score"] = value
            else:
                answer["noul"] = value
            if raw.get("probabilities") is not None:
                answer["probabilities"] = raw["probabilities"]
            if raw.get("confidence") is not None:
                answer["confidence"] = raw["confidence"]
            if raw.get("legend") is not None:
                answer["legend"] = raw["legend"]
            answer["effective_confidence"] = derive_effective_confidence(answer)
            normalized[question.question_key] = answer
        return normalized
