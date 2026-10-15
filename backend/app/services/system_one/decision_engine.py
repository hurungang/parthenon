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
    build_questions_payload,
    get_system_one_client,
)
from app.services.system_one.decision_model_availability_service import (
    DecisionModelCatalogueError,
    DecisionModelCatalogueService,
    ResolvedDecisionModel,
)
from app.services.system_one.decision_tool_service import (
    DecisionToolService,
    DecisionToolValidationError,
    derive_questions_from_output_type,
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
        catalogue_service: DecisionModelCatalogueService | None = None,
    ) -> None:
        # Resolved lazily at execute time via the vendor registry, using the
        # selected provider config's provider_type (defaults below if injected).
        self._client = client
        self._providers = provider_service or SystemOneProviderConfigService()
        self._tools = tool_service or DecisionToolService()
        self._catalogue = catalogue_service or DecisionModelCatalogueService(
            self._providers
        )

    async def resolve_model_selection(
        self,
        db: AsyncSession,
        tool: DecisionTool,
        tenant_id: uuid.UUID | None,
    ) -> tuple[SystemOneProviderConfig, str, ResolvedDecisionModel | None]:
        """Resolve the tool's selected decision model to provider + model.

        Preferred path: the tool's ``decision_model_availability_id``
        reference, resolved (and availability-checked) through the decision
        model catalogue within the caller's tenant — toggles take effect on
        the next evaluation without restart. Legacy fallback: tools
        migrated before the model reference (NULL selection) resolve via
        the tenant's enabled provider and the legacy free-text
        ``provider_model``.
        """
        if tool.decision_model_availability_id is not None:
            try:
                resolved = await self._catalogue.resolve_selection(
                    db, tool.decision_model_availability_id, tenant_id
                )
            except DecisionModelCatalogueError as exc:
                # Unavailable/disabled selections fail with an actionable,
                # engine-level error (regular-model-equivalent outcome).
                raise DecisionExecutionError(str(exc)) from exc
            return resolved.provider, resolved.model_name, resolved

        # Legacy path (pre-migration tools): enabled provider + legacy text.
        provider, _ = await self._providers.get_active_provider(db, tenant_id)
        model = tool.provider_model or provider.default_model
        availability = await self._catalogue.resolve_legacy_default(
            db, provider, model
        )
        resolved = ResolvedDecisionModel(
            provider=provider,
            availability=availability,
            provider_id=provider.id,
            provider_type=provider.provider_type,
            provider_display_name=provider.display_name,
            model_name=model,
            availability_id=availability.id,
        )
        if not provider.enabled:
            raise DecisionExecutionError(
                f"Decision Model provider '{provider.display_name}' is disabled"
            )
        if availability.is_disabled:
            raise DecisionExecutionError(
                f"Decision model '{model}' on provider "
                f"'{provider.display_name}' is disabled"
            )
        return provider, model, resolved

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
        try:
            state = self.build_state(tool.state_preset, input_state or {})
            # Manual questions win; with none authored, derive them 1:1
            # from the tool's output data type at execution time.
            questions = sorted(tool.questions, key=lambda q: q.ordering)
            if not questions:
                questions = derive_questions_from_output_type(db, tool)
            if not questions:
                raise DecisionExecutionError(
                    f"Decision tool '{tool.name}' has no questions and no "
                    "output data type to derive them from"
                )
            questions_payload = {
                q.question_key: build_questions_payload(
                    q.question_type, q.instructions, q.criteria_options
                )
                for q in questions
            }

            # Resolve the tool's selected model (provider + model identity,
            # availability-checked). Disabled/unavailable selections raise
            # DecisionExecutionError with an actionable message.
            provider, model, resolved = await self.resolve_model_selection(
                db, tool, tenant_id if tenant_id is not None else tool.tenant_id
            )
            # Pre-call guardrail/budget check — same semantics as regular
            # model usage: a breached terminate-posture guardrail blocks
            # the vendor call before any key is decrypted.
            blocked_by = await self._catalogue.check_pre_call(
                db, provider, model
            )
            if blocked_by:
                raise DecisionExecutionError(
                    f"Decision model call blocked ({blocked_by}): model "
                    f"'{model}' on provider '{provider.display_name}' has a "
                    "breached guardrail or exhausted budget"
                )

            # Decrypt the provider key INSIDE the execution path only.
            # Tenant containment: resolution is scoped to the tool's tenant.
            _, api_key = await self._providers.get_active_provider_by_config(provider)

            with tracer.start_as_current_span("system_one.evaluate") as span:
                span.set_attribute("system_one.provider", provider.provider_type.value)
                span.set_attribute("system_one.provider_display_name", provider.display_name)
                span.set_attribute("system_one.provider_id", str(provider.id))
                span.set_attribute("system_one.model", model)
                span.set_attribute("system_one.tool", tool.name)
                span.set_attribute("system_one.questions", len(questions_payload))
                client = self._client or get_system_one_client(
                    provider.provider_type.value
                )
                raw_response = await client.evaluate(
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
            # Usage metering: record provider/model identity + the
            # provider-reported usage into the persisted result (shared
            # audit trail alongside regular model usage).
            usage_identity = self._catalogue.usage_identity(
                resolved, raw_response.get("usage")
            )
            result = DecisionExecutionResult(
                tenant_id=tenant_id if tenant_id is not None else tool.tenant_id,
                decision_tool_id=tool.id,
                conversation_session_id=conversation_session_id,
                input_state_snapshot=state,
                answers={
                    "answers": answers,
                    "gate_confidence": gate_confidence,
                    "provider": usage_identity,
                },
                outcome=outcome,
                status=DecisionExecutionStatus.completed,
                provider_model=raw_response.get("model", model),
            )
            db.add(result)
            await db.flush()
            await db.refresh(result)
            logger.info(
                "Decision tool '%s' executed: decision_tool_id=%s session=%s "
                "status=%s outcome=%s gate_confidence=%.3f answer_keys=%s "
                "provider=%s (%s) model=%s",
                tool.name,
                result.decision_tool_id,
                result.conversation_session_id,
                result.status.value,
                outcome.value,
                gate_confidence,
                sorted(answers.keys()),
                provider.display_name,
                provider.provider_type.value,
                model,
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

        Each preset mapping resolves ``state_key`` from the execution input:
        ``state[state_key] = input_state[mapping.key]``. State maps FROM THE
        INPUT ONLY — the legacy ``agent_data`` source is retired: such rows
        (in presets persisted before the retirement) are skipped with a
        warning instead of failing execution.

        Unresolvable mappings raise a validation error so failures are explicit.
        """
        if not state_preset:
            return dict(input_state)
        state: dict[str, Any] = {}
        errors: list[str] = []
        for state_key, raw in state_preset.items():
            try:
                mapping = (
                    raw
                    if isinstance(raw, StatePresetMapping)
                    else StatePresetMapping.model_validate(raw)
                )
            except Exception:
                logger.warning(
                    "state key '%s': legacy/invalid mapping ignored "
                    "(state maps from the input only)",
                    state_key,
                )
                continue
            if mapping.source != "input":
                logger.warning(
                    "state key '%s': legacy 'agent_data' mapping ignored "
                    "(state maps from the input only)",
                    state_key,
                )
                continue
            if mapping.key not in input_state:
                errors.append(
                    f"state key '{state_key}': input data key '{mapping.key}' not provided"
                )
            else:
                state[state_key] = input_state[mapping.key]
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
