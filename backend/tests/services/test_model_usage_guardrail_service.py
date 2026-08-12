"""Tests for ModelUsageGuardrailService — per-period CRUD and resolution paths.

The API-level tests in ``tests/api/v1/test_model_usage_guardrails_api.py``
mock the service, so they never exercise the real ``create_configuration``
flow. This file targets the service directly with a mocked ``AsyncSession``
to catch regressions in the model-name → ``ModelConfig.id`` resolution
(e.g. a broken JSON containment query) and the per-period uniqueness check.
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

from app.db.models.model_guardrail_configuration import (
    ModelGuardrailConfiguration,
    ModelGuardrailEnforcementPosture,
    ModelGuardrailPeriod,
    ModelUsageUnit,
)
from app.services.control_center.model_usage_guardrail_service import (
    ModelGuardrailDuplicatePeriodError,
    ModelGuardrailModelNotFoundError,
    ModelUsageGuardrailService,
)


def _make_model_config(
    *, config_id: uuid.UUID | None = None, enabled_models: list[str] | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        id=config_id or uuid.uuid4(),
        enabled_models=enabled_models if enabled_models is not None else [],
    )


def _make_session_returning_for_resolver(
    model_configs: list[SimpleNamespace],
) -> AsyncMock:
    """Build an AsyncSession whose first ``execute(...).scalars().all()``
    returns ``model_configs`` (used by the in-Python resolver) and whose
    second ``execute(...)`` returns None (no pre-existing guardrail).
    """
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=model_configs)
    execute_result = MagicMock()
    execute_result.scalars = MagicMock(return_value=scalars_mock)
    # The pre-check for duplicate periods uses scalar_one_or_none; mock that
    # to return None so the create path proceeds.
    execute_result.scalar_one_or_none = MagicMock(return_value=None)
    session = AsyncMock()
    # First call: the resolver, returning the list. Second: pre-check, no rows.
    session.execute = AsyncMock(
        side_effect=[execute_result, execute_result]
    )
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def _make_session_returning_duplicate(
    existing_id: uuid.UUID, model_configs: list[SimpleNamespace]
) -> AsyncMock:
    """Build an AsyncSession whose pre-check finds an existing guardrail."""
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=model_configs)
    execute_result_with_list = MagicMock()
    execute_result_with_list.scalars = MagicMock(return_value=scalars_mock)

    duplicate_row = MagicMock()
    execute_result_duplicate = MagicMock()
    execute_result_duplicate.scalar_one_or_none = MagicMock(
        return_value=duplicate_row
    )

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[execute_result_with_list, execute_result_duplicate]
    )
    return session


@pytest.mark.asyncio
async def test_create_configuration_resolves_model_name_to_model_config_id():
    """When a matching ModelConfig exists, the service must use its UUID
    for the FK and surface the human-friendly model_name unchanged.
    """
    config_id = uuid.uuid4()
    session = _make_session_returning_for_resolver(
        [_make_model_config(config_id=config_id, enabled_models=["gpt-4.1-nano", "gpt-4.1"])]
    )
    captured: dict = {}

    def _capture_add(obj):
        captured["config"] = obj

    session.add.side_effect = _capture_add

    result = await ModelUsageGuardrailService().create_configuration(
        model_id="gpt-4.1-nano",
        model_name="gpt-4.1-nano",
        period=ModelGuardrailPeriod.hour,
        limit_value=10,
        unit=ModelUsageUnit.k,
        enforcement_posture=ModelGuardrailEnforcementPosture.terminate,
        is_active=True,
        db=session,
    )

    assert result is captured["config"]
    config: ModelGuardrailConfiguration = captured["config"]
    assert config.model_id == config_id
    assert config.model_name == "gpt-4.1-nano"
    assert config.period == ModelGuardrailPeriod.hour
    assert config.limit_value == 10
    assert config.is_active is True
    session.flush.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_configuration_raises_model_not_found_when_no_match():
    """If no ModelConfig lists the model in enabled_models, raise a
    clear error rather than silently passing a None FK to the DB.
    """
    session = _make_session_returning_for_resolver(
        [_make_model_config(enabled_models=["some-other-model"])]
    )

    with pytest.raises(ModelGuardrailModelNotFoundError) as excinfo:
        await ModelUsageGuardrailService().create_configuration(
            model_id="gpt-4.1-nano",
            model_name="gpt-4.1-nano",
            period=ModelGuardrailPeriod.hour,
            limit_value=10,
            db=session,
        )
    assert "gpt-4.1-nano" in str(excinfo.value)
    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_create_configuration_raises_duplicate_period_error():
    """A second guardrail for the same (model_config_id, period) raises
    ``ModelGuardrailDuplicatePeriodError`` so the API can return 409
    rather than letting the DB raise an opaque IntegrityError 500.
    """
    cfg_id = uuid.uuid4()
    session = _make_session_returning_duplicate(
        existing_id=uuid.uuid4(),
        model_configs=[
            _make_model_config(
                config_id=cfg_id, enabled_models=["gpt-4.1-nano"]
            )
        ],
    )

    with pytest.raises(ModelGuardrailDuplicatePeriodError) as excinfo:
        await ModelUsageGuardrailService().create_configuration(
            model_id="gpt-4.1-nano",
            model_name="gpt-4.1-nano",
            period=ModelGuardrailPeriod.hour,
            limit_value=10,
            db=session,
        )
    assert excinfo.value.model_config_id == cfg_id
    assert excinfo.value.period == ModelGuardrailPeriod.hour


@pytest.mark.asyncio
async def test_create_configuration_does_not_emit_postgres_json_like_query():
    """Regression guard: SQLAlchemy's generic ``JSON.contains`` compiles
    to ``WHERE enabled_models LIKE '%' || value::text || '%'`` which
    Postgres rejects at runtime with a 500.  The service must filter in
    Python, which means a single ``select(ModelConfig)`` with no JSON
    operator.
    """
    from sqlalchemy import select

    from app.db.models.agents import ModelConfig
    from app.services.control_center.model_usage_guardrail_service import (
        ModelUsageGuardrailService,
    )

    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    session.execute = AsyncMock(return_value=execute_result)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    with pytest.raises(ModelGuardrailModelNotFoundError):
        await ModelUsageGuardrailService()._resolve_model_name_to_config_id(
            "gpt-4.1-nano", session
        )

    # Inspect the SQLAlchemy statement passed to session.execute
    stmt = session.execute.await_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "LIKE" not in compiled, (
        f"Resolver emitted a LIKE query on JSON column — Postgres will 500: {compiled}"
    )
    assert "::JSON" not in compiled
    # Sanity: it really is a plain ModelConfig select
    assert "FROM model_configs" in compiled


@pytest.mark.asyncio
async def test_create_configuration_accepts_explicit_model_config_id():
    """When the caller already resolved the vendor UUID, the name
    resolver is skipped.
    """
    config_id = uuid.uuid4()
    pre_check_result = MagicMock()
    pre_check_result.scalar_one_or_none = MagicMock(return_value=None)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=pre_check_result)
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    captured: list = []

    def _capture_add(obj):
        captured.append(obj)

    # session.add is a regular MagicMock by default; replace it explicitly.
    session.add = MagicMock(side_effect=_capture_add)

    result = await ModelUsageGuardrailService().create_configuration(
        model_id="gpt-4.1-nano",
        model_name="gpt-4.1-nano",
        model_config_id=config_id,
        period=ModelGuardrailPeriod.day,
        limit_value=500,
        unit=ModelUsageUnit.tokens,
        db=session,
    )

    assert len(captured) == 1
    config: ModelGuardrailConfiguration = captured[0]
    assert result is config
    assert config.model_id == config_id
    assert config.period == ModelGuardrailPeriod.day
    assert config.limit_value == 500
    assert config.unit == ModelUsageUnit.tokens
