"""Decision model catalogue service — per-vendor/model availability authority.

Mirrors the LLM ``ModelAvailabilityService`` pattern
(``backend/app/services/control_center/model_availability_service.py``) for
Decision Model Providers:

- ``set_vendor_disabled`` toggles the provider-level ``enabled`` flag and
  materialises the cascade onto per-model ``DecisionModelAvailability``
  rows (manual disables are preserved; re-enabling clears only
  ``vendor_cascaded`` rows).
- ``set_model_disabled`` toggles one model with ``disabled_reason=manual``.
- ``list_hierarchy`` projects provider → model with effective disabled
  state and cascade source.
- ``list_enabled_models`` returns the flat enabled (provider enabled AND
  model enabled) list feeding the decision tool authoring selector.
- ``resolve_selection`` resolves a tool's selected availability row to a
  provider + model pair inside the execution path (tenant-contained,
  raises when disabled/unavailable).
- ``check_pre_call`` applies the same pre-call guardrail/posture check
  used for regular model usage (active terminate-posture guardrail in
  ``breached`` posture blocks the call).

Service boundary: only Control Center touches these tables (top-priority
rule: CC is the sole DB-connected service).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models.decision_model_availability import (
    DecisionModelAvailability,
    DecisionModelAvailabilityDisabledReason,
)
from app.db.models.system_one_provider_config import (
    SystemOneProviderConfig,
    SystemOneProviderType,
)
from app.services.system_one.provider_config_service import (
    SystemOneProviderConfigService,
    SystemOneProviderError,
)

logger = logging.getLogger(__name__)


class DecisionModelCatalogueError(SystemOneProviderError):
    """Raised when a decision model selection is unavailable/disabled."""


@dataclass
class ResolvedDecisionModel:
    """A tool's resolved provider + model pair (identity only, no secrets)."""

    provider: SystemOneProviderConfig
    availability: DecisionModelAvailability
    provider_id: uuid.UUID
    provider_type: SystemOneProviderType
    provider_display_name: str
    model_name: str
    availability_id: uuid.UUID


def _safe_flag_modified(instance: object, attr: str) -> None:
    """Mark an attribute modified, tolerating non-mapped (mock) instances."""
    try:
        flag_modified(instance, attr)
    except AttributeError:
        pass


class DecisionModelCatalogueService:
    """Vendor/model availability authority for Decision Model Providers."""

    def __init__(
        self,
        provider_service: SystemOneProviderConfigService | None = None,
    ) -> None:
        self._providers = provider_service or SystemOneProviderConfigService()

    # ── Catalogue derivation ─────────────────────────────────────────────

    @staticmethod
    def catalogue_model_names(provider: SystemOneProviderConfig) -> list[str]:
        """The vendor's model catalogue: the ``enabled_models`` list.

        The list is seeded at creation/sync/import (see
        ``SystemOneProviderConfigService.create`` / ``import_vendor_models``).
        An empty list no longer silently falls back to ``default_model`` —
        legacy rows without a seeded catalogue fall back to their
        availability rows (or the default model) at the read sites only,
        so existing data keeps working without being rewritten.
        """
        models = [m for m in (provider.enabled_models or []) if m]
        return list(dict.fromkeys(models))

    def _effective_catalogue(
        self,
        provider: SystemOneProviderConfig,
        row_names: set[str],
    ) -> list[str]:
        """Catalogue with legacy read-compat: seeded catalogue first, then
        availability-row names, then the default model (legacy rows)."""
        names = self.catalogue_model_names(provider)
        if names:
            return names
        if row_names:
            return sorted(row_names)
        return [provider.default_model]

    async def _get_provider(
        self,
        db: AsyncSession,
        provider_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
    ) -> SystemOneProviderConfig:
        config = await self._providers.get(db, provider_id, tenant_id)
        if config is None:
            raise DecisionModelCatalogueError(
                f"Decision Model provider {provider_id} not found"
            )
        return config

    async def _get_availability_rows(
        self,
        db: AsyncSession,
        provider_id: uuid.UUID,
    ) -> dict[str, DecisionModelAvailability]:
        result = await db.execute(
            select(DecisionModelAvailability).where(
                DecisionModelAvailability.decision_model_provider_id == provider_id
            )
        )
        return {row.model_name: row for row in result.scalars().all()}

    async def _get_availability_row(
        self,
        db: AsyncSession,
        provider_id: uuid.UUID,
        model_name: str,
    ) -> DecisionModelAvailability | None:
        result = await db.execute(
            select(DecisionModelAvailability).where(
                DecisionModelAvailability.decision_model_provider_id == provider_id,
                DecisionModelAvailability.model_name == model_name,
            )
        )
        return result.scalar_one_or_none()

    # ── Vendor toggle (cascades) ─────────────────────────────────────────

    async def set_vendor_disabled(
        self,
        db: AsyncSession,
        provider_id: uuid.UUID,
        is_disabled: bool,
        tenant_id: uuid.UUID | None = None,
    ) -> SystemOneProviderConfig:
        """Toggle the provider-level ``enabled`` flag and materialise the
        cascade (mirrors ``ModelAvailabilityService.set_vendor_disabled``).

        On disable: upsert a ``vendor_cascaded`` availability row per
        catalogue model (manually disabled rows keep their manual reason).
        On re-enable: clear only the cascaded rows; manual disables persist.
        """
        config = await self._get_provider(db, provider_id, tenant_id)
        config.enabled = not is_disabled
        _safe_flag_modified(config, "enabled")

        if is_disabled:
            row_names = set(await self._get_availability_rows(db, provider_id))
            for model_name in self._effective_catalogue(config, row_names):
                row = await self._get_availability_row(db, provider_id, model_name)
                if row is None:
                    db.add(
                        DecisionModelAvailability(
                            tenant_id=config.tenant_id,
                            model_name=model_name,
                            decision_model_provider_id=provider_id,
                            is_disabled=True,
                            disabled_reason=(
                                DecisionModelAvailabilityDisabledReason.vendor_cascaded
                            ),
                        )
                    )
                elif (
                    row.is_disabled
                    and row.disabled_reason
                    == DecisionModelAvailabilityDisabledReason.manual
                ):
                    # Already manually disabled by the operator: keep the
                    # manual reason so the state survives the vendor
                    # cascade round-trip (re-enable must NOT silently
                    # re-enable it).
                    row.is_disabled = True
                    _safe_flag_modified(row, "is_disabled")
                else:
                    row.is_disabled = True
                    row.disabled_reason = (
                        DecisionModelAvailabilityDisabledReason.vendor_cascaded
                    )
                    _safe_flag_modified(row, "is_disabled")
                    _safe_flag_modified(row, "disabled_reason")
        else:
            result = await db.execute(
                select(DecisionModelAvailability).where(
                    DecisionModelAvailability.decision_model_provider_id
                    == provider_id,
                    DecisionModelAvailability.disabled_reason
                    == DecisionModelAvailabilityDisabledReason.vendor_cascaded,
                )
            )
            for row in result.scalars().all():
                await db.delete(row)

        await db.flush()
        await db.refresh(config)
        logger.info(
            "Decision Model provider '%s' (%s) %s (tenant %s)",
            config.display_name,
            config.provider_type.value,
            "disabled (cascade applied)" if is_disabled else "enabled",
            tenant_id,
        )
        return config

    # ── Per-model toggle ─────────────────────────────────────────────────

    async def set_model_disabled(
        self,
        db: AsyncSession,
        provider_id: uuid.UUID,
        model_name: str,
        is_disabled: bool,
        tenant_id: uuid.UUID | None = None,
    ) -> DecisionModelAvailability:
        """Toggle per-model availability with ``disabled_reason=manual``.

        If the vendor is currently disabled, the row remains effectively
        disabled (the cascade wins) but the per-model state is preserved
        so that on vendor re-enable the prior manual state is restored.
        """
        config = await self._get_provider(db, provider_id, tenant_id)
        row = await self._get_availability_row(db, provider_id, model_name)
        if row is None:
            row = DecisionModelAvailability(
                tenant_id=config.tenant_id,
                model_name=model_name,
                decision_model_provider_id=provider_id,
                is_disabled=is_disabled,
                disabled_reason=DecisionModelAvailabilityDisabledReason.manual,
            )
            db.add(row)
        else:
            row.is_disabled = is_disabled
            row.disabled_reason = DecisionModelAvailabilityDisabledReason.manual
            _safe_flag_modified(row, "is_disabled")
            _safe_flag_modified(row, "disabled_reason")
        await db.flush()
        await db.refresh(row)
        return row

    # ── Projections ──────────────────────────────────────────────────────

    async def list_hierarchy(
        self, db: AsyncSession, tenant_id: uuid.UUID | None = None
    ) -> list[dict]:
        """Provider → model hierarchy with effective disabled state and the
        cascade source visible (mirrors ``ModelAvailabilityService``)."""
        providers = await self._providers.list_all(db, tenant_id)
        hierarchy: list[dict] = []
        for config in providers:
            rows = await self._get_availability_rows(db, config.id)
            vendor_disabled = not bool(config.enabled)
            models: list[dict] = []
            names = list(
                dict.fromkeys(
                    self._effective_catalogue(config, set(rows)) + sorted(
                        set(rows) - set(self._effective_catalogue(config, set(rows)))
                    )
                )
            )
            for model_name in names:
                row = rows.get(model_name)
                if vendor_disabled:
                    effective = True
                    reason = DecisionModelAvailabilityDisabledReason.vendor_cascaded
                elif row is not None:
                    effective = bool(row.is_disabled)
                    reason = row.disabled_reason
                else:
                    effective = False
                    reason = DecisionModelAvailabilityDisabledReason.manual
                models.append(
                    {
                        "availability_id": row.id if row else None,
                        "model_name": model_name,
                        "effective_is_disabled": effective,
                        "disabled_reason": reason,
                    }
                )
            hierarchy.append(
                {
                    "provider_id": config.id,
                    "display_name": config.display_name,
                    "provider_type": config.provider_type,
                    "default_model": config.default_model,
                    "is_disabled": vendor_disabled,
                    "models": models,
                }
            )
        return hierarchy

    async def list_enabled_models(
        self, db: AsyncSession, tenant_id: uuid.UUID | None = None
    ) -> list[ResolvedDecisionModel]:
        """Flat enabled-models list (provider enabled AND model enabled),
        feeding the decision tool authoring selector."""
        providers = await self._providers.list_enabled(db, tenant_id)
        enabled: list[ResolvedDecisionModel] = []
        for config in providers:
            rows = await self._get_availability_rows(db, config.id)
            for model_name in self._effective_catalogue(config, set(rows)):
                row = rows.get(model_name)
                if row is not None and bool(row.is_disabled):
                    continue
                if row is None:
                    # Seed the availability row persistently so the API can
                    # hand out a STABLE availability_id (the ORM default
                    # only applies at flush — a transient instance would
                    # carry id=None and break the Read schema).
                    row = DecisionModelAvailability(
                        id=uuid.uuid4(),
                        tenant_id=config.tenant_id,
                        model_name=model_name,
                        decision_model_provider_id=config.id,
                        is_disabled=False,
                        disabled_reason=(
                            DecisionModelAvailabilityDisabledReason.manual
                        ),
                    )
                    db.add(row)
                    rows[model_name] = row
                enabled.append(self._to_resolved(config, row))
        await db.flush()
        return enabled

    # ── Execution-path resolution ────────────────────────────────────────

    def _to_resolved(
        self,
        config: SystemOneProviderConfig,
        row: DecisionModelAvailability,
    ) -> ResolvedDecisionModel:
        return ResolvedDecisionModel(
            provider=config,
            availability=row,
            provider_id=config.id,
            provider_type=config.provider_type,
            provider_display_name=config.display_name,
            model_name=row.model_name,
            availability_id=row.id,
        )

    async def resolve_selection(
        self,
        db: AsyncSession,
        availability_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
    ) -> ResolvedDecisionModel:
        """Resolve a tool's selected availability row to provider + model.

        Strictly tenant-contained; raises ``DecisionModelCatalogueError``
        with an actionable message when the selection is unknown, the
        provider is disabled, or the model is disabled. Called inside the
        decision execution path only (credentials are decrypted separately
        at vendor-call time).
        """
        result = await db.execute(
            select(DecisionModelAvailability).where(
                DecisionModelAvailability.id == availability_id,
                DecisionModelAvailability.tenant_id == tenant_id
                if tenant_id is not None
                else DecisionModelAvailability.tenant_id.is_(None),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise DecisionModelCatalogueError(
                f"Selected decision model {availability_id} not found or "
                "not visible to this tenant"
            )
        provider = await self._providers.get(db, row.decision_model_provider_id, tenant_id)
        if provider is None:
            raise DecisionModelCatalogueError(
                "The provider for the selected decision model no longer exists"
            )
        if not provider.enabled:
            raise DecisionModelCatalogueError(
                f"Decision Model provider '{provider.display_name}' is disabled"
            )
        if row.is_disabled:
            reason = (
                "disabled by the vendor-level toggle"
                if row.disabled_reason
                == DecisionModelAvailabilityDisabledReason.vendor_cascaded
                else "disabled"
            )
            raise DecisionModelCatalogueError(
                f"Decision model '{row.model_name}' on provider "
                f"'{provider.display_name}' is {reason}"
            )
        return self._to_resolved(provider, row)

    async def resolve_legacy_default(
        self,
        db: AsyncSession,
        provider: SystemOneProviderConfig,
        model_name: str,
    ) -> DecisionModelAvailability:
        """Resolve (or seed) the availability row for a legacy free-text
        ``provider_model`` selection on an already-resolved provider."""
        row = await self._get_availability_row(db, provider.id, model_name)
        if row is None:
            row = DecisionModelAvailability(
                tenant_id=provider.tenant_id,
                model_name=model_name,
                decision_model_provider_id=provider.id,
                is_disabled=not provider.enabled,
                disabled_reason=(
                    DecisionModelAvailabilityDisabledReason.vendor_cascaded
                    if not provider.enabled
                    else DecisionModelAvailabilityDisabledReason.manual
                ),
            )
            db.add(row)
            await db.flush()
        return row

    # ── Pre-call guardrail/posture check (Phase 3.1) ─────────────────────

    async def check_pre_call(
        self,
        db: AsyncSession,
        provider: SystemOneProviderConfig,
        model_name: str,
    ) -> str | None:
        """Pre-call guardrail/budget check, regular-model-equivalent.

        Mirrors ``ModelAvailabilityService._check_guardrail_breach``: an
        ACTIVE terminate-posture guardrail whose latest posture snapshot is
        ``breached`` blocks the vendor call. Returns a stable
        ``blocked_by`` token (``guardrail_breached``) or None when allowed.
        """
        from app.db.models.model_guardrail_configuration import (
            ModelGuardrailConfiguration,
            ModelGuardrailEnforcementPosture,
            ModelGuardrailPeriod,
        )
        from app.db.models.model_usage_posture import (
            ModelUsagePosture,
            ModelUsagePostureState,
        )

        guards_result = await db.execute(
            select(ModelGuardrailConfiguration).where(
                # Decision scope: rows created by the Decision Model Providers
                # module (FIX-20261014-003000) — never LLM model-config rows.
                ModelGuardrailConfiguration.config_source == "decision_provider",
                ModelGuardrailConfiguration.decision_provider_id == provider.id,
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

        # Guard against raw-string period values (sqlite test backend
        # returns plain str for Enum columns).
        def _period_value(g) -> str:
            return g.period.value if isinstance(g.period, ModelGuardrailPeriod) else str(
                g.period
            )

        for g in sorted(guards, key=_period_value):
            p = latest.get(g.id)
            if p is not None and p.posture_state == ModelUsagePostureState.breached:
                logger.warning(
                    "Decision model call blocked by breached guardrail: "
                    "provider=%s model=%s period=%s usage=%s limit=%s",
                    provider.display_name,
                    model_name,
                    g.period.value if isinstance(g.period, ModelGuardrailPeriod) else g.period,
                    p.usage_value,
                    p.limit_value,
                )
                return "guardrail_breached"
        return None

    # ── Usage metering (Phase 3.2) ───────────────────────────────────────

    def usage_identity(
        self, resolved: ResolvedDecisionModel, usage: dict | None = None
    ) -> dict:
        """Usage/spend store entry for one decision evaluation.

        Carries the provider/model identity and the provider-reported
        usage payload (if any) — never credential material. Consumed by
        reporting alongside regular model usage.
        """
        identity: dict = {
            "provider_id": str(resolved.provider_id),
            "provider_type": resolved.provider_type.value,
            "provider_display_name": resolved.provider_display_name,
            "model_name": resolved.model_name,
        }
        if usage:
            identity["usage"] = usage
        return identity
