from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import (
    AgentInputType,
    AgentJob,
    AgentJobStatus,
    AgentOutputType,
    AgentType,
    ModelConfig,
    ModelProvider,
)
from app.db.models.guardrail_threshold_event import (
    GuardrailThresholdEvent,
    GuardrailThresholdEventType,
    GuardrailThresholdSeverity,
)
from app.db.models.model_guardrail_configuration import (
    ModelGuardrailConfiguration,
    ModelGuardrailEnforcementPosture,
    ModelGuardrailPeriod,
)
from app.db.models.model_guardrail_evaluation import (
    ModelGuardrailEvaluation,
    ModelGuardrailEvaluationOutcome,
    ModelGuardrailEvaluationPeriod,
    ModelGuardrailPolicyMode,
    ModelGuardrailPostureState,
)
from app.db.models.model_usage_posture import (
    ModelUsagePosture,
    ModelUsagePosturePeriod,
    ModelUsagePostureState,
)


async def _create_model_config(db_session: AsyncSession, suffix: str) -> ModelConfig:
    cfg = ModelConfig(
        display_name=f"ModelCfg-{suffix}",
        provider_type=ModelProvider.openai,
        api_base_url="https://api.openai.com/v1",
        encrypted_api_key="enc:key",
        enabled_models=["gpt-4o-mini"],
    )
    db_session.add(cfg)
    await db_session.flush()
    return cfg


async def _create_agent_job(db_session: AsyncSession, suffix: str) -> AgentJob:
    agent_type = AgentType(
        name=f"guardrail-agent-{suffix}",
        model_id="gpt-4o-mini",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
    )
    db_session.add(agent_type)
    await db_session.flush()

    job = AgentJob(
        agent_type_id=agent_type.id,
        status=AgentJobStatus.running,
        input_data={"query": "test"},
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.mark.asyncio
async def test_model_guardrail_configuration_defaults_to_terminate(
    db_session: AsyncSession,
):
    """A new per-period guardrail row defaults to ``terminate`` even when
    the operator does not pass ``enforcement_posture`` explicitly.
    """
    cfg = await _create_model_config(db_session, "default-posture")

    guardrail = ModelGuardrailConfiguration(
        model_id=cfg.id,
        model_name="gpt-4o-mini",
        period=ModelGuardrailPeriod.hour,
        limit_value=1000,
    )
    db_session.add(guardrail)
    await db_session.flush()
    await db_session.refresh(guardrail)

    assert guardrail.enforcement_posture == ModelGuardrailEnforcementPosture.terminate
    assert guardrail.is_active is True
    assert guardrail.unit.value == "k"


@pytest.mark.asyncio
async def test_model_usage_posture_supports_hour_day_week_month(
    db_session: AsyncSession,
):
    """One per-period guardrail per (model, period) — four guardrails per model
    in the per-guardrail shape, with one posture row keyed by the
    guardrail's id.
    """
    cfg = await _create_model_config(db_session, "all-periods")
    periods = [
        ModelGuardrailPeriod.hour,
        ModelGuardrailPeriod.day,
        ModelGuardrailPeriod.week,
        ModelGuardrailPeriod.month,
    ]
    for i, period in enumerate(periods, start=1):
        guardrail = ModelGuardrailConfiguration(
            model_id=cfg.id,
            model_name="gpt-4o-mini",
            enforcement_posture=ModelGuardrailEnforcementPosture.observe_only,
            period=period,
            limit_value=1000 * i,
        )
        db_session.add(guardrail)
        await db_session.flush()
        db_session.add(
            ModelUsagePosture(
                model_guardrail_configuration_id=guardrail.id,
                model_id=cfg.id,
                posture_period=ModelUsagePosturePeriod(period.value),
                usage_value=100 * i,
                limit_value=1000 * i,
                posture_state=ModelUsagePostureState.within_limit,
                details={"period": period.value},
            )
        )

    await db_session.flush()

    rows = (
        (
            await db_session.execute(
                select(ModelUsagePosture).where(ModelUsagePosture.model_id == cfg.id)
            )
        )
        .scalars()
        .all()
    )
    assert {row.posture_period for row in rows} == set(
        ModelUsagePosturePeriod
    )  # all four periods


@pytest.mark.asyncio
async def test_model_usage_posture_unique_by_configuration(db_session: AsyncSession):
    """Two posture rows for the same per-guardrail row violate the
    ``uq_model_usage_posture_configuration_period`` unique constraint.
    """
    cfg = await _create_model_config(db_session, "unique")
    guardrail = ModelGuardrailConfiguration(
        model_id=cfg.id,
        model_name="gpt-4o-mini",
        period=ModelGuardrailPeriod.hour,
        limit_value=1000,
    )
    db_session.add(guardrail)
    await db_session.flush()

    posture = ModelUsagePosture(
        model_guardrail_configuration_id=guardrail.id,
        model_id=cfg.id,
        posture_period=ModelUsagePosturePeriod.hour,
        usage_value=500,
        limit_value=1000,
        posture_state=ModelUsagePostureState.approaching_limit,
    )
    db_session.add(posture)
    await db_session.flush()

    db_session.add(
        ModelUsagePosture(
            model_guardrail_configuration_id=guardrail.id,
            model_id=cfg.id,
            posture_period=ModelUsagePosturePeriod.hour,
            usage_value=900,
            limit_value=1000,
            posture_state=ModelUsagePostureState.breached,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_threshold_event_persists_for_observe_only_evaluations(
    db_session: AsyncSession,
):
    suffix = uuid.uuid4().hex[:8]
    cfg = await _create_model_config(db_session, suffix)
    job = await _create_agent_job(db_session, suffix)
    guardrail = ModelGuardrailConfiguration(
        model_id=cfg.id,
        model_name="gpt-4o-mini",
        enforcement_posture=ModelGuardrailEnforcementPosture.observe_only,
        period=ModelGuardrailPeriod.hour,
        limit_value=1000,
    )
    db_session.add(guardrail)
    await db_session.flush()

    evaluation = ModelGuardrailEvaluation(
        model_guardrail_configuration_id=guardrail.id,
        agent_job_id=job.id,
        policy_name="token/hour",
        evaluated_period=ModelGuardrailEvaluationPeriod.hour,
        policy_mode=ModelGuardrailPolicyMode.observe_only,
        evaluation_outcome=ModelGuardrailEvaluationOutcome.threshold_reached,
        threshold_value=1000,
        observed_value=1050,
        posture_state=ModelGuardrailPostureState.breached,
        details={"source": "integration-test"},
    )
    db_session.add(evaluation)
    await db_session.flush()

    event = GuardrailThresholdEvent(
        model_guardrail_evaluation_id=evaluation.id,
        agent_job_id=job.id,
        event_type=GuardrailThresholdEventType.observe_only_threshold_reached,
        severity=GuardrailThresholdSeverity.warning,
        display_message="Model usage threshold reached in observe-only mode",
        emitted_to_execution_log=True,
    )
    db_session.add(event)
    await db_session.flush()

    fetched_event = await db_session.get(GuardrailThresholdEvent, event.id)
    assert fetched_event is not None
    assert fetched_event.emitted_to_execution_log is True
    assert fetched_event.severity == GuardrailThresholdSeverity.warning


@pytest.mark.asyncio
async def test_model_config_is_disabled_default_false(db_session: AsyncSession):
    """Newly created ``ModelConfig`` rows default to ``is_disabled = False``."""
    cfg = ModelConfig(
        display_name="DefaultEnabled",
        provider_type=ModelProvider.openai,
        enabled_models=[],
    )
    db_session.add(cfg)
    await db_session.flush()
    await db_session.refresh(cfg)
    assert cfg.is_disabled is False


@pytest.mark.asyncio
async def test_model_guardrail_unique_model_period(db_session: AsyncSession):
    """Two per-period guardrail rows for the same (model, period)
    violate the new ``uq_guardrail_model_period`` unique constraint.
    """
    cfg = await _create_model_config(db_session, "uq-period")
    db_session.add(
        ModelGuardrailConfiguration(
            model_id=cfg.id,
            model_name="gpt-4o-mini",
            period=ModelGuardrailPeriod.hour,
            limit_value=1000,
        )
    )
    await db_session.flush()

    db_session.add(
        ModelGuardrailConfiguration(
            model_id=cfg.id,
            model_name="gpt-4o-mini",
            period=ModelGuardrailPeriod.hour,
            limit_value=2000,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_model_guardrail_allows_four_periods_per_model(
    db_session: AsyncSession,
):
    """Operators can configure up to four guardrails per model — one per
    period. The unique constraint is per (model, period), so all four
    are accepted in a single transaction.
    """
    cfg = await _create_model_config(db_session, "all-four")
    for period in ModelGuardrailPeriod:
        db_session.add(
            ModelGuardrailConfiguration(
                model_id=cfg.id,
                model_name="gpt-4o-mini",
                period=period,
                limit_value=1000,
            )
        )
    await db_session.flush()
    rows = (
        (
            await db_session.execute(
                select(ModelGuardrailConfiguration).where(
                    ModelGuardrailConfiguration.model_id == cfg.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 4
    assert {r.period for r in rows} == set(ModelGuardrailPeriod)
