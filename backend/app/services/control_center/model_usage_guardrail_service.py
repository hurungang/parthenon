"""ModelUsageGuardrailService — per-period CRUD and posture evaluation.

Phase 3.7 rework: the previous flat per-model row (with four period-limit
columns baked into one record) is replaced by ONE row per (model, period).
Each model can have up to four guardrails, one per period, and operators
configure only the periods they want. The service still owns model-name
resolution (in-Python, since Postgres JSON.contains compiles to a LIKE
query the database rejects) and the (model_config_id, period) uniqueness
rule that prevents duplicate guardrails on the same pair.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import ModelConfig
from app.db.models.model_guardrail_configuration import (
    ModelGuardrailConfiguration,
    ModelGuardrailEnforcementPosture,
    ModelGuardrailPeriod,
    ModelUsageUnit,
)
from app.db.models.model_usage_posture import (
    ModelUsagePosture,
    ModelUsagePosturePeriod,
    ModelUsagePostureState,
)


class ModelGuardrailModelNotFoundError(LookupError):
    """Raised when a guardrail operation references a model name that is not
    enabled by any registered ModelConfig.
    """

    def __init__(self, model_name: str) -> None:
        super().__init__(f"No ModelConfig found for model name '{model_name}'")
        self.model_name = model_name


class ModelGuardrailDuplicatePeriodError(ValueError):
    """Raised when a (model_config_id, period) guardrail already exists."""

    def __init__(
        self, model_config_id: uuid.UUID, period: ModelGuardrailPeriod
    ) -> None:
        super().__init__(
            f"Guardrail already exists for model {model_config_id} period {period.value}"
        )
        self.model_config_id = model_config_id
        self.period = period


logger = logging.getLogger(__name__)
_UNSET = object()


class ModelUsageGuardrailService:
    """
    Per-period CRUD and posture evaluation for model-usage guardrails.

    All writes stay in Control Center. Agent Runtime never interacts with
    this service directly.
    """

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def list_configurations(
        self, db: AsyncSession
    ) -> list[ModelGuardrailConfiguration]:
        """Return all per-period guardrail rows."""
        result = await db.execute(
            select(ModelGuardrailConfiguration).order_by(
                ModelGuardrailConfiguration.created_at.desc()
            )
        )
        return list(result.scalars().all())

    async def get_configuration(
        self, config_id: uuid.UUID, db: AsyncSession
    ) -> ModelGuardrailConfiguration | None:
        """Fetch a single guardrail by ID."""
        return await db.get(ModelGuardrailConfiguration, config_id)

    async def create_configuration(
        self,
        *,
        model_id: str,
        model_name: str,
        period: ModelGuardrailPeriod,
        limit_value: int,
        unit: ModelUsageUnit | None = None,
        enforcement_posture: ModelGuardrailEnforcementPosture | None = None,
        is_active: bool = True,
        details: dict | None = None,
        model_config_id: uuid.UUID | None = None,
        db: AsyncSession,
    ) -> ModelGuardrailConfiguration:
        """Create a single per-period guardrail.

        ``model_id`` is the provider-scoped model NAME (e.g.
        ``"gpt-4.1-nano"``) — the same identifier the frontend carries. The
        service resolves it to the ``ModelConfig.id`` UUID that the FK
        column requires, raising :class:`ModelGuardrailModelNotFoundError`
        when no ModelConfig lists this model in its ``enabled_models``
        allowlist.

        When ``model_config_id`` is supplied (the resolved vendor UUID is
        known to the caller), name resolution is skipped — useful for
        server-to-server callers that already looked it up. When the
        resolved ModelConfig already has a guardrail for ``period``, raise
        :class:`ModelGuardrailDuplicatePeriodError` so the API can return
        a deterministic 409 instead of a DB IntegrityError.
        """
        if model_config_id is None:
            config_uuid = await self._resolve_model_name_to_config_id(
                model_id, db
            )
        else:
            config_uuid = model_config_id

        # Pre-check uniqueness so we return a deterministic, friendly 409
        # before letting the DB raise a 500 from an IntegrityError.
        existing = await db.execute(
            select(ModelGuardrailConfiguration).where(
                ModelGuardrailConfiguration.model_id == config_uuid,
                ModelGuardrailConfiguration.model_name == model_name,
                ModelGuardrailConfiguration.period == period,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ModelGuardrailDuplicatePeriodError(config_uuid, period)

        config = ModelGuardrailConfiguration(
            model_id=config_uuid,
            model_name=model_name,
            period=period,
            limit_value=limit_value,
            unit=unit or ModelUsageUnit.k,
            enforcement_posture=(
                enforcement_posture
                or ModelGuardrailEnforcementPosture.terminate
            ),
            is_active=is_active,
            details=details or {},
        )
        db.add(config)
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise ModelGuardrailDuplicatePeriodError(config_uuid, period) from exc
        await db.commit()
        logger.info(
            "Created model guardrail for model '%s' period=%s limit=%s",
            model_name,
            period.value,
            limit_value,
        )
        return config

    async def _resolve_model_name_to_config_id(
        self, model_name: str, db: AsyncSession
    ) -> uuid.UUID:
        """Resolve a provider-scoped model name to its ``ModelConfig.id`` UUID.

        Looks up the first ``ModelConfig`` whose ``enabled_models`` allowlist
        contains ``model_name``.  Raises :class:`ModelGuardrailModelNotFoundError`
        if no such configuration exists.

        Implementation note: ``ModelConfig.enabled_models`` is a Postgres JSON
        column.  SQLAlchemy's generic ``JSON.contains`` compiles to
        ``WHERE enabled_models LIKE '%' || value::text || '%'`` which Postgres
        rejects at runtime with a 500, so we filter in Python — same pattern
        as :class:`app.services.agents.model_binding.ModelBindingLayer`.
        """
        result = await db.execute(select(ModelConfig))
        for config in result.scalars().all():
            if model_name in (config.enabled_models or []):
                return config.id
        raise ModelGuardrailModelNotFoundError(model_name)

    async def update_configuration(
        self,
        config_id: uuid.UUID,
        *,
        limit_value: int | object = _UNSET,
        unit: ModelUsageUnit | object = _UNSET,
        enforcement_posture: ModelGuardrailEnforcementPosture | object = _UNSET,
        is_active: bool | object = _UNSET,
        details: dict | None | object = _UNSET,
        db: AsyncSession,
    ) -> ModelGuardrailConfiguration | None:
        """Partially update a single per-period guardrail.

        ``model_id`` (the FK UUID) and ``period`` are immutable; this method
        only touches the mutable columns of one row.
        """
        config = await db.get(ModelGuardrailConfiguration, config_id)
        if config is None:
            return None

        if limit_value is not _UNSET:
            config.limit_value = limit_value  # type: ignore[assignment]
        if unit is not _UNSET:
            config.unit = unit  # type: ignore[assignment]
        if enforcement_posture is not _UNSET:
            config.enforcement_posture = enforcement_posture  # type: ignore[assignment]
        if is_active is not _UNSET:
            config.is_active = is_active  # type: ignore[assignment]
        if details is not _UNSET:
            config.details = details  # type: ignore[assignment]

        config.updated_at = datetime.now(timezone.utc)
        await db.flush()
        await db.commit()
        return config

    async def delete_configuration(
        self, config_id: uuid.UUID, db: AsyncSession
    ) -> bool:
        """Hard-delete a single per-period guardrail row."""
        config = await db.get(ModelGuardrailConfiguration, config_id)
        if config is None:
            return False
        await db.delete(config)
        await db.commit()
        return True

    # ── Posture ───────────────────────────────────────────────────────────────

    async def get_current_posture(
        self, db: AsyncSession
    ) -> list[ModelUsagePosture]:
        """Return latest posture snapshots for all guardrails."""
        result = await db.execute(
            select(ModelUsagePosture).order_by(ModelUsagePosture.observed_at.desc())
        )
        return list(result.scalars().all())

    async def refresh_posture_snapshots(
        self, db: AsyncSession
    ) -> list[ModelUsagePosture]:
        """Compute fresh posture snapshots from actual session token usage.

        Each ``ModelGuardrailConfiguration`` row covers exactly one period,
        so the rollup is per-row: take the guardrail's ``limit_value`` and
        compute the per-period usage from ``agent_jobs`` started within
        the period window. Upsert by (config, period).
        """
        from app.db.models.agents import AgentJob, AgentType

        configs_result = await db.execute(
            select(ModelGuardrailConfiguration).where(
                ModelGuardrailConfiguration.is_active.is_(True)
            )
        )
        configs = list(configs_result.scalars().all())
        now = datetime.now(timezone.utc)

        period_windows: dict[ModelGuardrailPeriod, timedelta] = {
            ModelGuardrailPeriod.hour: timedelta(hours=1),
            ModelGuardrailPeriod.day: timedelta(days=1),
            ModelGuardrailPeriod.week: timedelta(weeks=1),
            ModelGuardrailPeriod.month: timedelta(days=30),
        }

        refreshed: list[ModelUsagePosture] = []

        for config in configs:
            delta = period_windows.get(config.period)
            if delta is None:
                continue
            since = now - delta

            sessions_result = await db.execute(
                select(func.count(AgentJob.id)).where(
                    AgentJob.agent_type_id == AgentType.id,
                    AgentType.model_id == config.model_name,
                    AgentJob.started_at >= since,
                )
            )
            usage_value = sessions_result.scalar_one() or 0
            limit_val = int(config.limit_value)

            if usage_value >= limit_val:
                posture_state = ModelUsagePostureState.breached
            elif usage_value >= limit_val * 0.8:
                posture_state = ModelUsagePostureState.approaching_limit
            else:
                posture_state = ModelUsagePostureState.within_limit

            existing_result = await db.execute(
                select(ModelUsagePosture).where(
                    ModelUsagePosture.model_guardrail_configuration_id == config.id,
                )
            )
            existing = existing_result.scalar_one_or_none()

            if existing:
                existing.usage_value = usage_value
                existing.limit_value = limit_val
                existing.posture_state = posture_state
                existing.observed_at = now
                refreshed.append(existing)
            else:
                posture = ModelUsagePosture(
                    model_guardrail_configuration_id=config.id,
                    model_id=config.model_id,
                    posture_period=ModelUsagePosturePeriod(config.period.value),
                    usage_value=usage_value,
                    limit_value=limit_val,
                    posture_state=posture_state,
                    observed_at=now,
                )
                db.add(posture)
                refreshed.append(posture)

        await db.flush()
        await db.commit()
        return refreshed
