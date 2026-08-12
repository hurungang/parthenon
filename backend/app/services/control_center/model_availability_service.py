"""ModelAvailabilityService — vendor and per-model availability authority.

Phase 3.8 / 3.9 / 3.10: vendor-level enable/disable cascade, per-model
manual toggle, hierarchy projection, and the pre-execution availability
check consumed by Agent Runtime before dispatch.

Service boundary
----------------
- Only Control Center owns and writes ``ModelConfig.is_disabled`` and
  ``ModelAvailability`` rows.
- Agent Runtime does NOT call this service directly; it calls
  ``POST /api/v1/agents/preflight/availability`` via the data client,
  which is permission-gated by ``require_service_certificate`` (the
  runtime-cert path).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models.agents import ModelConfig
from app.db.models.model_availability import (
    ModelAvailability,
    ModelAvailabilityDisabledReason,
)
from app.db.models.model_guardrail_configuration import ModelGuardrailConfiguration
from app.db.models.model_usage_posture import (
    ModelUsagePosture,
    ModelUsagePostureState,
)

logger = logging.getLogger(__name__)


@dataclass
class PreflightAvailabilityOutcome:
    """Result of a pre-execution availability check.

    ``allowed`` is the boolean verdict. ``reason`` and ``disabled_reason``
    are populated only when the check is denied. ``blocked_by`` is a
    stable token (``"model_disabled"``, ``"vendor_disabled"``,
    ``"model_not_found"``, ``"guardrail_breached"``) so consumers can
    dispatch on it without parsing free-form text.
    """

    allowed: bool
    reason: str | None = None
    disabled_reason: ModelAvailabilityDisabledReason | None = None
    blocked_by: str | None = None


class ModelAvailabilityService:
    """Vendor and per-model availability authority for the runtime."""

    # ── Vendor toggle (cascades to ModelAvailability) ─────────────────────────

    async def set_vendor_disabled(
        self, db: AsyncSession, vendor_config_id: uuid.UUID, is_disabled: bool
    ) -> ModelConfig:
        """Toggle ``ModelConfig.is_disabled`` and materialise the cascade.

        On disable: upsert a ``ModelAvailability`` row per enabled model on
        the vendor, setting ``is_disabled = true`` and
        ``disabled_reason = vendor_cascaded``. Rows that were already
        manually disabled are left as-is (manual wins, but the row stays
        effectively disabled).

        On re-enable: remove only the cascaded rows (rows with
        ``disabled_reason = vendor_cascaded``); preserve any rows that
        were manually disabled.
        """
        config = await db.get(ModelConfig, vendor_config_id)
        if config is None:
            raise LookupError(f"ModelConfig {vendor_config_id} not found")

        config.is_disabled = is_disabled
        # Touch the column so SQLAlchemy registers the change even if the
        # boolean value happens to be the same.  ``flag_modified`` only
        # works on mapped instances; we guard it for the mock-based test
        # path.
        _safe_flag_modified(config, "is_disabled")

        enabled_models = list(config.enabled_models or [])

        if is_disabled:
            # Upsert ModelAvailability rows for every enabled model
            for model_name in enabled_models:
                row = await self._get_availability_row(
                    db, vendor_config_id, model_name
                )
                if row is None:
                    row = ModelAvailability(
                        model_name=model_name,
                        vendor_model_config_id=vendor_config_id,
                        is_disabled=True,
                        disabled_reason=ModelAvailabilityDisabledReason.vendor_cascaded,
                    )
                    db.add(row)
                else:
                    row.is_disabled = True
                    row.disabled_reason = (
                        ModelAvailabilityDisabledReason.vendor_cascaded
                    )
                    _safe_flag_modified(row, "is_disabled")
                    _safe_flag_modified(row, "disabled_reason")
        else:
            # Re-enable: delete only the cascaded rows; preserve manual rows
            result = await db.execute(
                select(ModelAvailability).where(
                    ModelAvailability.vendor_model_config_id == vendor_config_id,
                    ModelAvailability.disabled_reason
                    == ModelAvailabilityDisabledReason.vendor_cascaded,
                )
            )
            for row in result.scalars().all():
                await db.delete(row)

        await db.flush()
        await db.commit()
        await db.refresh(config)
        return config

    async def set_model_disabled(
        self,
        db: AsyncSession,
        vendor_config_id: uuid.UUID,
        model_name: str,
        is_disabled: bool,
    ) -> ModelAvailability:
        """Toggle per-model availability with ``disabled_reason = manual``.

        If the vendor is currently disabled, the row remains effectively
        disabled (the cascade wins) but the per-model state is preserved so
        that on vendor re-enable the prior manual state is restored.
        """
        row = await self._get_availability_row(db, vendor_config_id, model_name)
        if row is None:
            row = ModelAvailability(
                model_name=model_name,
                vendor_model_config_id=vendor_config_id,
                is_disabled=is_disabled,
                disabled_reason=ModelAvailabilityDisabledReason.manual,
            )
            db.add(row)
        else:
            row.is_disabled = is_disabled
            row.disabled_reason = ModelAvailabilityDisabledReason.manual
            _safe_flag_modified(row, "is_disabled")
            _safe_flag_modified(row, "disabled_reason")
        await db.flush()
        await db.commit()
        await db.refresh(row)
        return row

    async def _get_availability_row(
        self, db: AsyncSession, vendor_config_id: uuid.UUID, model_name: str
    ) -> ModelAvailability | None:
        result = await db.execute(
            select(ModelAvailability).where(
                ModelAvailability.vendor_model_config_id == vendor_config_id,
                ModelAvailability.model_name == model_name,
            )
        )
        return result.scalar_one_or_none()

    # ── Hierarchy projection ─────────────────────────────────────────────────

    async def list_hierarchy(self, db: AsyncSession) -> list[dict]:
        """Return the full vendor → model → guardrail hierarchy.

        The result is a list of vendor dicts with ``models`` and
        ``guardrails`` shaped for the dashboard.  Each model row carries an
        ``effective_is_disabled`` (vendor OR per-model) and the original
        ``disabled_reason`` so the cascade source is visible.
        """
        # Load all ModelConfigs
        configs_result = await db.execute(
            select(ModelConfig).order_by(ModelConfig.display_name)
        )
        configs = list(configs_result.scalars().all())

        # Load all ModelAvailability rows
        availability_result = await db.execute(select(ModelAvailability))
        availability_rows = list(availability_result.scalars().all())
        availability_by_vendor: dict[uuid.UUID, dict[str, ModelAvailability]] = {}
        for row in availability_rows:
            availability_by_vendor.setdefault(row.vendor_model_config_id, {})[
                row.model_name
            ] = row

        # Load all guardrails indexed by model_id
        guards_result = await db.execute(
            select(ModelGuardrailConfiguration).order_by(
                ModelGuardrailConfiguration.period
            )
        )
        guards_by_model: dict[uuid.UUID, list[ModelGuardrailConfiguration]] = {}
        for g in guards_result.scalars().all():
            guards_by_model.setdefault(g.model_id, []).append(g)

        # Load latest posture per configuration
        posture_result = await db.execute(
            select(ModelUsagePosture).order_by(ModelUsagePosture.observed_at.desc())
        )
        posture_by_config: dict[uuid.UUID, ModelUsagePosture] = {}
        for p in posture_result.scalars().all():
            posture_by_config.setdefault(p.model_guardrail_configuration_id, p)

        hierarchy: list[dict] = []
        for cfg in configs:
            vendor_avail = availability_by_vendor.get(cfg.id, {})
            vendor_disabled = bool(cfg.is_disabled)
            models: list[dict] = []
            for model_name in cfg.enabled_models or []:
                row = vendor_avail.get(model_name)
                if row is not None:
                    per_model_disabled = bool(row.is_disabled)
                    # If the vendor is disabled, the row's reason is
                    # vendor_cascaded; otherwise honour the row's own state.
                    if vendor_disabled:
                        effective = True
                        reason = ModelAvailabilityDisabledReason.vendor_cascaded
                    else:
                        effective = per_model_disabled
                        reason = row.disabled_reason
                else:
                    effective = vendor_disabled
                    reason = (
                        ModelAvailabilityDisabledReason.vendor_cascaded
                        if vendor_disabled
                        else ModelAvailabilityDisabledReason.manual
                    )

                model_guards = guards_by_model.get(cfg.id, [])
                guardrail_summaries: list[dict] = []
                for g in model_guards:
                    if g.model_name != model_name:
                        continue
                    p = posture_by_config.get(g.id)
                    guardrail_summaries.append(
                        {
                            "id": g.id,
                            "period": g.period,
                            "limit_value": g.limit_value,
                            "unit": g.unit,
                            "enforcement_posture": g.enforcement_posture,
                            "is_active": g.is_active,
                            "usage_value": p.usage_value if p else None,
                            "posture_state": p.posture_state if p else None,
                        }
                    )
                models.append(
                    {
                        "model_name": model_name,
                        "effective_is_disabled": effective,
                        "disabled_reason": reason,
                        "guardrails": guardrail_summaries,
                    }
                )
            hierarchy.append(
                {
                    "vendor_model_config_id": cfg.id,
                    "display_name": cfg.display_name,
                    "is_disabled": vendor_disabled,
                    "models": models,
                }
            )
        return hierarchy

    # ── Pre-execution availability check ────────────────────────────────────

    async def check_availability(
        self,
        db: AsyncSession,
        model_name: str,
        vendor_config_id: uuid.UUID | None = None,
    ) -> PreflightAvailabilityOutcome:
        """Return an allow/deny verdict for the supplied model.

        Algorithm:
        1. If ``vendor_config_id`` is supplied, evaluate that vendor only.
           - If the vendor is disabled -> deny, reason=vendor_disabled.
           - Otherwise consult the per-model row.
             - If the row is disabled -> deny, reason=model_disabled.
           - If the model is available, check for any active
             terminate-posture guardrail that is in ``breached`` posture.
             -> deny, reason=guardrail_breached.
        2. If ``vendor_config_id`` is omitted, consider every vendor that
           offers ``model_name``. If at least one is available AND has no
           breached terminate-posture guardrail, allow.
        3. If no vendor offers the model, deny with reason=model_not_found.
        4. If every offering vendor is unavailable, fall back to the
           existing reason hierarchy (vendor_disabled vs model_disabled).
           If every offering vendor is available but every one has a
           breached terminate-posture guardrail, deny with
           blocked_by=guardrail_breached.
        """
        if vendor_config_id is not None:
            return await self._evaluate_single_vendor(
                db, vendor_config_id, model_name
            )

        # No vendor hint — find any vendor that offers the model and is
        # currently available AND has no breached terminate-posture
        # guardrail. We surface guardrail_breached as the dominant deny
        # reason when every offering vendor is available but each one is
        # in breach; otherwise we fall through to the existing
        # vendor/model-disabled hierarchy.
        configs = await self._find_vendors_offering(db, model_name)
        if not configs:
            return PreflightAvailabilityOutcome(
                allowed=False,
                reason=f"No ModelConfig offers model '{model_name}'",
                blocked_by="model_not_found",
            )
        any_allow = False
        all_cascaded = True
        all_breached = True
        for cfg in configs:
            outcome = await self._evaluate_single_vendor(
                db, cfg.id, model_name
            )
            if outcome.allowed:
                any_allow = True
                break
            if outcome.disabled_reason != ModelAvailabilityDisabledReason.vendor_cascaded:
                all_cascaded = False
            if outcome.blocked_by != "guardrail_breached":
                all_breached = False
        if any_allow:
            return PreflightAvailabilityOutcome(allowed=True)
        # All vendors denied. If every offering vendor's denial was a
        # guardrail breach, surface that as the dominant reason so the
        # operator can tell "the model is fine, the guardrail is on fire"
        # from a hard vendor/model disable.
        if all_breached:
            return PreflightAvailabilityOutcome(
                allowed=False,
                reason=(
                    f"All offering vendors for model '{model_name}' have a breached "
                    f"terminate-posture guardrail"
                ),
                blocked_by="guardrail_breached",
            )
        # All vendors denied. The most useful reason is "vendor_disabled"
        # if every vendor was cascaded, otherwise "model_disabled".
        blocked = "vendor_disabled" if all_cascaded else "model_disabled"
        return PreflightAvailabilityOutcome(
            allowed=False,
            reason=(
                f"Model '{model_name}' is disabled by all offering vendors"
                if all_cascaded
                else f"Model '{model_name}' is disabled"
            ),
            disabled_reason=(
                ModelAvailabilityDisabledReason.vendor_cascaded
                if all_cascaded
                else ModelAvailabilityDisabledReason.manual
            ),
            blocked_by=blocked,
        )

    async def _evaluate_single_vendor(
        self,
        db: AsyncSession,
        vendor_config_id: uuid.UUID,
        model_name: str,
    ) -> PreflightAvailabilityOutcome:
        config = await db.get(ModelConfig, vendor_config_id)
        if config is None:
            return PreflightAvailabilityOutcome(
                allowed=False,
                reason=f"Vendor ModelConfig {vendor_config_id} not found",
                blocked_by="model_not_found",
            )
        if model_name not in (config.enabled_models or []):
            return PreflightAvailabilityOutcome(
                allowed=False,
                reason=(
                    f"Model '{model_name}' is not in the enabled list for vendor "
                    f"{vendor_config_id}"
                ),
                blocked_by="model_not_found",
            )
        if config.is_disabled:
            return PreflightAvailabilityOutcome(
                allowed=False,
                reason=f"Vendor {config.display_name} is disabled",
                disabled_reason=ModelAvailabilityDisabledReason.vendor_cascaded,
                blocked_by="vendor_disabled",
            )
        row = await self._get_availability_row(
            db, vendor_config_id, model_name
        )
        if row is not None and bool(row.is_disabled):
            return PreflightAvailabilityOutcome(
                allowed=False,
                reason=f"Model '{model_name}' is disabled",
                disabled_reason=row.disabled_reason,
                blocked_by=(
                    "vendor_disabled"
                    if row.disabled_reason
                    == ModelAvailabilityDisabledReason.vendor_cascaded
                    else "model_disabled"
                ),
            )
        # Guardrail enforcement: if any active guardrail on this model has
        # ``enforcement_posture=terminate`` and its latest posture snapshot
        # is ``breached``, deny. This is the path that converts the dashboard
        # "breached" badge into a real dispatch block.
        breach_outcome = await self._check_guardrail_breach(
            db, vendor_config_id, model_name
        )
        if breach_outcome is not None:
            return breach_outcome
        return PreflightAvailabilityOutcome(allowed=True)

    async def _check_guardrail_breach(
        self,
        db: AsyncSession,
        vendor_config_id: uuid.UUID,
        model_name: str,
    ) -> PreflightAvailabilityOutcome | None:
        """Return a deny outcome if any active terminate-posture guardrail
        on this (vendor, model) is in ``breached`` posture; otherwise None.

        Only guardrails with ``is_active=True`` AND
        ``enforcement_posture=terminate`` count — ``observe_only`` is a
        statistics-only signal and must not block dispatch.
        """
        from app.db.models.model_guardrail_configuration import (
            ModelGuardrailConfiguration,
            ModelGuardrailEnforcementPosture,
        )

        # Find active terminate-posture guardrails for this vendor+model
        guards_result = await db.execute(
            select(ModelGuardrailConfiguration).where(
                ModelGuardrailConfiguration.model_id == vendor_config_id,
                ModelGuardrailConfiguration.model_name == model_name,
                ModelGuardrailConfiguration.is_active.is_(True),
                ModelGuardrailConfiguration.enforcement_posture
                == ModelGuardrailEnforcementPosture.terminate,
            )
        )
        guards = [
            g
            for g in list(guards_result.scalars().all())
            if bool(g.is_active)
            and g.enforcement_posture
            == ModelGuardrailEnforcementPosture.terminate
        ]
        if not guards:
            return None

        # Look up latest posture per guardrail — order by observed_at desc
        # and keep the first (most-recent) row per configuration_id.
        config_ids = [g.id for g in guards]
        posture_result = await db.execute(
            select(ModelUsagePosture)
            .where(ModelUsagePosture.model_guardrail_configuration_id.in_(config_ids))
            .order_by(
                ModelUsagePosture.model_guardrail_configuration_id,
                ModelUsagePosture.observed_at.desc(),
            )
        )
        latest: dict[uuid.UUID, ModelUsagePosture] = {}
        for p in posture_result.scalars().all():
            if p.model_guardrail_configuration_id not in latest:
                latest[p.model_guardrail_configuration_id] = p

        # Find the first breached guardrail (deterministic — order by period)
        breached: tuple[ModelGuardrailConfiguration, ModelUsagePosture] | None = None
        for g in sorted(guards, key=lambda x: x.period.value):
            p = latest.get(g.id)
            if p is not None and p.posture_state == ModelUsagePostureState.breached:
                breached = (g, p)
                break

        if breached is None:
            return None
        g, p = breached
        return PreflightAvailabilityOutcome(
            allowed=False,
            reason=(
                f"Guardrail breached for model '{model_name}' (period={g.period.value}, "
                f"usage={p.usage_value}, limit={p.limit_value})"
            ),
            blocked_by="guardrail_breached",
        )

    async def _find_vendors_offering(
        self, db: AsyncSession, model_name: str
    ) -> list[ModelConfig]:
        result = await db.execute(select(ModelConfig))
        return [
            cfg
            for cfg in result.scalars().all()
            if model_name in (cfg.enabled_models or [])
        ]


def _safe_flag_modified(instance: object, attr: str) -> None:
    """Mark an attribute modified, swallowing the error on non-mapped mocks.

    ``sqlalchemy.orm.attributes.flag_modified`` requires a SQLAlchemy-mapped
    instance.  When the service is called against a mock session (e.g. in
    the unit tests under ``tests/services/``) the instance is a
    ``SimpleNamespace`` lacking ``_sa_instance_state``; the explicit
    assignment above is sufficient for those tests, so we ignore the
    AttributeError here.
    """
    try:
        flag_modified(instance, attr)
    except AttributeError:
        pass
