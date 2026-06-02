"""Service-level tests for ``ModelAvailabilityService``.

Uses mocked ``AsyncSession`` so the cascade semantics, hierarchy
projection, and pre-execution availability verdict can be verified
without a real database. Integration tests against the migrated real DB
live in ``tests/integration/test_model_availability_cascade.py`` (planned
per the test plan).
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import pytest

from app.db.models.agents import ModelProvider
from app.db.models.model_availability import ModelAvailabilityDisabledReason
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
from app.services.control_center.model_availability_service import (
    ModelAvailabilityService,
    PreflightAvailabilityOutcome,
)


def _make_model_config(
    *,
    config_id: uuid.UUID | None = None,
    enabled_models: list[str] | None = None,
    is_disabled: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=config_id or uuid.uuid4(),
        display_name="Vendor",
        provider_type=ModelProvider.openai,
        is_disabled=is_disabled,
        enabled_models=enabled_models if enabled_models is not None else [],
    )


def _make_availability_row(
    *,
    vendor_id: uuid.UUID,
    model_name: str,
    is_disabled: bool = False,
    disabled_reason: ModelAvailabilityDisabledReason = ModelAvailabilityDisabledReason.manual,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        model_name=model_name,
        vendor_model_config_id=vendor_id,
        is_disabled=is_disabled,
        disabled_reason=disabled_reason,
    )


def _make_scalars_returning(items: list) -> MagicMock:
    """Build a mock that emulates the ``result.scalars().all()`` pattern."""
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=items)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars_mock)
    result.scalar_one_or_none = MagicMock(return_value=items[0] if items else None)
    return result


# ── set_vendor_disabled cascade ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_vendor_disabled_marks_all_models_as_vendor_cascaded():
    cfg = _make_model_config(enabled_models=["gpt-4o", "gpt-4o-mini"])
    session = AsyncMock()
    session.get = AsyncMock(return_value=cfg)
    # Two lookups (one per enabled model) — no existing availability rows.
    session.execute = AsyncMock(
        side_effect=[
            _make_scalars_returning([]),  # for gpt-4o lookup
            _make_scalars_returning([]),  # for gpt-4o-mini lookup
        ]
    )
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    session.refresh = AsyncMock(return_value=cfg)

    captured: list = []
    session.add = MagicMock(side_effect=lambda obj: captured.append(obj))

    result = await ModelAvailabilityService().set_vendor_disabled(
        session, cfg.id, True
    )

    assert result is cfg
    assert cfg.is_disabled is True
    # Two ModelAvailability rows were created (one per enabled model).
    assert len(captured) == 2
    for row in captured:
        assert isinstance(row.is_disabled, bool) and row.is_disabled
        assert row.disabled_reason == ModelAvailabilityDisabledReason.vendor_cascaded
        assert row.vendor_model_config_id == cfg.id


@pytest.mark.asyncio
async def test_set_vendor_disabled_re_enable_removes_cascaded_rows_keeps_manual():
    cfg = _make_model_config(enabled_models=["gpt-4o"])
    cascaded_row = _make_availability_row(
        vendor_id=cfg.id,
        model_name="gpt-4o",
        is_disabled=True,
        disabled_reason=ModelAvailabilityDisabledReason.vendor_cascaded,
    )
    manual_row = _make_availability_row(
        vendor_id=cfg.id,
        model_name="gpt-4o-mini",
        is_disabled=True,
        disabled_reason=ModelAvailabilityDisabledReason.manual,
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=cfg)
    # Two lookups: the re-enable path looks up cascaded rows.
    session.execute = AsyncMock(
        side_effect=[
            _make_scalars_returning([cascaded_row]),  # cascaded row to delete
            _make_scalars_returning([cascaded_row, manual_row]),  # hierarchy load
            _make_scalars_returning([]),  # posture rows
        ]
    )
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock(return_value=cfg)
    deleted: list = []
    session.delete = AsyncMock(side_effect=lambda obj: deleted.append(obj))

    await ModelAvailabilityService().set_vendor_disabled(session, cfg.id, False)

    # The cascaded row was deleted; the manual row is untouched.
    assert deleted and deleted[0] is cascaded_row
    assert cfg.is_disabled is False


# ── set_model_disabled ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_model_disabled_creates_row_with_manual_reason():
    cfg = _make_model_config(enabled_models=["gpt-4o"])
    session = AsyncMock()
    # No existing row found -> create one.
    session.execute = AsyncMock(return_value=_make_scalars_returning([]))
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    captured: list = []
    session.add = MagicMock(side_effect=lambda obj: captured.append(obj))

    result = await ModelAvailabilityService().set_model_disabled(
        session, cfg.id, "gpt-4o", True
    )

    assert len(captured) == 1
    row = captured[0]
    assert row.model_name == "gpt-4o"
    assert row.vendor_model_config_id == cfg.id
    assert row.is_disabled is True
    assert row.disabled_reason == ModelAvailabilityDisabledReason.manual


@pytest.mark.asyncio
async def test_set_model_disabled_updates_existing_row():
    cfg = _make_model_config(enabled_models=["gpt-4o"])
    existing = _make_availability_row(
        vendor_id=cfg.id,
        model_name="gpt-4o",
        is_disabled=False,
        disabled_reason=ModelAvailabilityDisabledReason.manual,
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_make_scalars_returning([existing]))
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()  # should NOT be called

    result = await ModelAvailabilityService().set_model_disabled(
        session, cfg.id, "gpt-4o", True
    )

    assert result is existing
    assert existing.is_disabled is True
    assert existing.disabled_reason == ModelAvailabilityDisabledReason.manual
    session.add.assert_not_called()


# ── check_availability ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_availability_single_vendor_enabled_allows():
    cfg = _make_model_config(enabled_models=["gpt-4o"])
    session = AsyncMock()
    # get(config) -> the config; scalar_one_or_none() for availability row -> None
    session.get = AsyncMock(return_value=cfg)
    avail_result = MagicMock()
    avail_result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=avail_result)

    outcome = await ModelAvailabilityService().check_availability(
        session, model_name="gpt-4o", vendor_config_id=cfg.id
    )
    assert outcome.allowed is True


@pytest.mark.asyncio
async def test_check_availability_single_vendor_disabled_blocks():
    cfg = _make_model_config(enabled_models=["gpt-4o"], is_disabled=True)
    session = AsyncMock()
    session.get = AsyncMock(return_value=cfg)
    session.execute = AsyncMock()

    outcome = await ModelAvailabilityService().check_availability(
        session, model_name="gpt-4o", vendor_config_id=cfg.id
    )
    assert outcome.allowed is False
    assert outcome.blocked_by == "vendor_disabled"
    assert outcome.disabled_reason == ModelAvailabilityDisabledReason.vendor_cascaded


@pytest.mark.asyncio
async def test_check_availability_per_model_disabled_blocks():
    cfg = _make_model_config(enabled_models=["gpt-4o"], is_disabled=False)
    per_model_row = _make_availability_row(
        vendor_id=cfg.id,
        model_name="gpt-4o",
        is_disabled=True,
        disabled_reason=ModelAvailabilityDisabledReason.manual,
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=cfg)
    avail_result = MagicMock()
    avail_result.scalar_one_or_none = MagicMock(return_value=per_model_row)
    session.execute = AsyncMock(return_value=avail_result)

    outcome = await ModelAvailabilityService().check_availability(
        session, model_name="gpt-4o", vendor_config_id=cfg.id
    )
    assert outcome.allowed is False
    assert outcome.blocked_by == "model_disabled"
    assert outcome.disabled_reason == ModelAvailabilityDisabledReason.manual


@pytest.mark.asyncio
async def test_check_availability_vendor_not_offering_model_blocks():
    cfg = _make_model_config(enabled_models=["claude-3"])
    session = AsyncMock()
    session.get = AsyncMock(return_value=cfg)
    session.execute = AsyncMock()

    outcome = await ModelAvailabilityService().check_availability(
        session, model_name="gpt-4o", vendor_config_id=cfg.id
    )
    assert outcome.allowed is False
    assert outcome.blocked_by == "model_not_found"


@pytest.mark.asyncio
async def test_check_availability_multi_vendor_allows_via_healthy_vendor():
    cfg_a = _make_model_config(
        config_id=uuid.uuid4(),
        enabled_models=["gpt-4o"],
        is_disabled=True,
    )
    cfg_b = _make_model_config(
        config_id=uuid.uuid4(),
        enabled_models=["gpt-4o"],
        is_disabled=False,
    )
    session = AsyncMock()
    # When no vendor is supplied, the service scans all ModelConfigs and
    # then evaluates each.  Set up the result to return both configs and
    # then a per-vendor availability row (None for cfg_b).
    listing = _make_scalars_returning([cfg_a, cfg_b])
    # cfg_a -> vendor disabled -> block; cfg_b -> per-model row None -> allow
    avail_none = MagicMock()
    avail_none.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(
        side_effect=[listing, avail_none, avail_none]
    )
    session.get = AsyncMock(side_effect=[cfg_a, cfg_b])

    outcome = await ModelAvailabilityService().check_availability(
        session, model_name="gpt-4o"
    )
    assert outcome.allowed is True


@pytest.mark.asyncio
async def test_check_availability_no_vendor_offering_model_blocks():
    """When no ModelConfig offers the model, the preflight returns
    ``model_not_found``.
    """
    cfg = _make_model_config(enabled_models=["claude-3"])
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_make_scalars_returning([cfg]))

    outcome = await ModelAvailabilityService().check_availability(
        session, model_name="gpt-4o"
    )
    assert outcome.allowed is False
    assert outcome.blocked_by == "model_not_found"


# ── Guardrail breach enforcement (Phase 3.11) ──────────────────────────────


def _make_guardrail(
    *,
    guard_id: uuid.UUID | None = None,
    model_id: uuid.UUID,
    model_name: str,
    period: ModelGuardrailPeriod,
    enforcement: ModelGuardrailEnforcementPosture = (
        ModelGuardrailEnforcementPosture.terminate
    ),
    is_active: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=guard_id or uuid.uuid4(),
        model_id=model_id,
        model_name=model_name,
        period=period,
        limit_value=100,
        unit=ModelUsageUnit.k,
        enforcement_posture=enforcement,
        is_active=is_active,
        details={},
    )


def _make_posture(
    *,
    guard_id: uuid.UUID,
    model_id: uuid.UUID,
    period: ModelUsagePosturePeriod,
    usage_value: int,
    limit_value: int,
    state: ModelUsagePostureState,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        model_guardrail_configuration_id=guard_id,
        model_id=model_id,
        posture_period=period,
        usage_value=usage_value,
        limit_value=limit_value,
        posture_state=state,
        observed_at=SimpleNamespace(),  # placeholder
        details={},
    )


@pytest.mark.asyncio
async def test_check_availability_blocks_when_terminate_guardrail_breached():
    """If an active guardrail with ``enforcement_posture=terminate`` is in
    ``breached`` posture, the preflight must deny with
    ``blocked_by=guardrail_breached``.
    """
    cfg = _make_model_config(enabled_models=["gpt-4o"], is_disabled=False)
    guard = _make_guardrail(
        model_id=cfg.id,
        model_name="gpt-4o",
        period=ModelGuardrailPeriod.hour,
    )
    breached_posture = _make_posture(
        guard_id=guard.id,
        model_id=cfg.id,
        period=ModelUsagePosturePeriod.hour,
        usage_value=120,
        limit_value=100,
        state=ModelUsagePostureState.breached,
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=cfg)
    # execute calls (in order):
    #   1. _get_availability_row  -> scalar_one_or_none None
    #   2. guards select          -> [guard]
    #   3. posture select         -> [breached_posture]
    none_result = MagicMock()
    none_result.scalar_one_or_none = MagicMock(return_value=None)
    guards_result = _make_scalars_returning([guard])
    posture_result = _make_scalars_returning([breached_posture])
    session.execute = AsyncMock(
        side_effect=[none_result, guards_result, posture_result]
    )

    outcome = await ModelAvailabilityService().check_availability(
        session, model_name="gpt-4o", vendor_config_id=cfg.id
    )
    assert outcome.allowed is False
    assert outcome.blocked_by == "guardrail_breached"
    assert "breached" in (outcome.reason or "").lower()


@pytest.mark.asyncio
async def test_check_availability_allows_when_breached_guardrail_is_observe_only():
    """Guardrails with ``enforcement_posture=observe_only`` are
    statistics-only — they must not block dispatch even when breached.
    """
    cfg = _make_model_config(enabled_models=["gpt-4o"], is_disabled=False)
    guard = _make_guardrail(
        model_id=cfg.id,
        model_name="gpt-4o",
        period=ModelGuardrailPeriod.hour,
        enforcement=ModelGuardrailEnforcementPosture.observe_only,
    )
    breached_posture = _make_posture(
        guard_id=guard.id,
        model_id=cfg.id,
        period=ModelUsagePosturePeriod.hour,
        usage_value=200,
        limit_value=100,
        state=ModelUsagePostureState.breached,
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=cfg)
    none_result = MagicMock()
    none_result.scalar_one_or_none = MagicMock(return_value=None)
    guards_result = _make_scalars_returning([guard])
    posture_result = _make_scalars_returning([breached_posture])
    session.execute = AsyncMock(
        side_effect=[none_result, guards_result, posture_result]
    )

    outcome = await ModelAvailabilityService().check_availability(
        session, model_name="gpt-4o", vendor_config_id=cfg.id
    )
    assert outcome.allowed is True


@pytest.mark.asyncio
async def test_check_availability_allows_when_terminate_guardrail_within_limit():
    cfg = _make_model_config(enabled_models=["gpt-4o"], is_disabled=False)
    guard = _make_guardrail(
        model_id=cfg.id,
        model_name="gpt-4o",
        period=ModelGuardrailPeriod.hour,
    )
    within_posture = _make_posture(
        guard_id=guard.id,
        model_id=cfg.id,
        period=ModelUsagePosturePeriod.hour,
        usage_value=40,
        limit_value=100,
        state=ModelUsagePostureState.within_limit,
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=cfg)
    none_result = MagicMock()
    none_result.scalar_one_or_none = MagicMock(return_value=None)
    guards_result = _make_scalars_returning([guard])
    posture_result = _make_scalars_returning([within_posture])
    session.execute = AsyncMock(
        side_effect=[none_result, guards_result, posture_result]
    )

    outcome = await ModelAvailabilityService().check_availability(
        session, model_name="gpt-4o", vendor_config_id=cfg.id
    )
    assert outcome.allowed is True


@pytest.mark.asyncio
async def test_check_availability_allows_when_terminate_guardrail_is_inactive():
    """An ``is_active=False`` guardrail is a no-op for enforcement even
    if its last posture snapshot is breached.
    """
    cfg = _make_model_config(enabled_models=["gpt-4o"], is_disabled=False)
    guard = _make_guardrail(
        model_id=cfg.id,
        model_name="gpt-4o",
        period=ModelGuardrailPeriod.hour,
        is_active=False,
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=cfg)
    none_result = MagicMock()
    none_result.scalar_one_or_none = MagicMock(return_value=None)
    # No active guards -> the query is filtered to [] before posture lookup
    empty_guards = _make_scalars_returning([])
    session.execute = AsyncMock(side_effect=[none_result, empty_guards])

    outcome = await ModelAvailabilityService().check_availability(
        session, model_name="gpt-4o", vendor_config_id=cfg.id
    )
    assert outcome.allowed is True


@pytest.mark.asyncio
async def test_check_availability_multi_vendor_blocks_when_all_have_breach():
    """When no specific vendor is supplied and EVERY offering vendor's
    deny reason is ``guardrail_breached``, surface that as the dominant
    blocked_by (rather than a misleading ``model_disabled``).
    """
    cfg_a = _make_model_config(
        config_id=uuid.uuid4(),
        enabled_models=["gpt-4o"],
        is_disabled=False,
    )
    cfg_b = _make_model_config(
        config_id=uuid.uuid4(),
        enabled_models=["gpt-4o"],
        is_disabled=False,
    )
    guard_a = _make_guardrail(
        model_id=cfg_a.id,
        model_name="gpt-4o",
        period=ModelGuardrailPeriod.hour,
    )
    guard_b = _make_guardrail(
        model_id=cfg_b.id,
        model_name="gpt-4o",
        period=ModelGuardrailPeriod.hour,
    )
    breach_a = _make_posture(
        guard_id=guard_a.id,
        model_id=cfg_a.id,
        period=ModelUsagePosturePeriod.hour,
        usage_value=120,
        limit_value=100,
        state=ModelUsagePostureState.breached,
    )
    breach_b = _make_posture(
        guard_id=guard_b.id,
        model_id=cfg_b.id,
        period=ModelUsagePosturePeriod.hour,
        usage_value=150,
        limit_value=100,
        state=ModelUsagePostureState.breached,
    )

    session = AsyncMock()
    listing = _make_scalars_returning([cfg_a, cfg_b])
    none_result = MagicMock()
    none_result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(
        side_effect=[
            listing,                            # _find_vendors_offering
            none_result,                        # cfg_a availability row
            _make_scalars_returning([guard_a]), # cfg_a guard query
            _make_scalars_returning([breach_a]),# cfg_a posture query
            none_result,                        # cfg_b availability row
            _make_scalars_returning([guard_b]), # cfg_b guard query
            _make_scalars_returning([breach_b]),# cfg_b posture query
        ]
    )
    session.get = AsyncMock(side_effect=[cfg_a, cfg_b])

    outcome = await ModelAvailabilityService().check_availability(
        session, model_name="gpt-4o"
    )
    assert outcome.allowed is False
    assert outcome.blocked_by == "guardrail_breached"
