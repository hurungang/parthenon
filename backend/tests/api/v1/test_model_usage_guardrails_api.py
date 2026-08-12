from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason='Requires running services (CC, AR, or CH)')

import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.models.model_guardrail_configuration import (
    ModelGuardrailEnforcementPosture,
    ModelGuardrailPeriod,
    ModelUsageUnit,
)
from app.db.models.model_usage_posture import (
    ModelUsagePosturePeriod,
    ModelUsagePostureState,
)
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware
from app.services.control_center.model_usage_guardrail_service import (
    ModelGuardrailDuplicatePeriodError,
    ModelGuardrailModelNotFoundError,
)


def _bypass_auth_with_claims():
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "admin-sub", "roles": ["admin"]}
        request.state.claims = {"platform_user_id": str(uuid.uuid4())}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _mock_permission_allow():
    from app.services.permissions.permission_engine import AuthorizationResult

    async def mock_authorize(*args, **kwargs):
        return AuthorizationResult(allowed=True, reason="Test override")

    return patch(
        "app.services.permissions.permission_engine.PermissionEngine.authorize",
        mock_authorize,
    )


def _build_test_app(mock_session: AsyncMock):
    permission_result = MagicMock()
    permission_result.scalar_one_or_none = MagicMock(
        return_value=SimpleNamespace(id=uuid.uuid4())
    )
    mock_session.execute = AsyncMock(return_value=permission_result)

    async def override_get_db():
        yield mock_session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    return app


def _fake_limit(
    limit_id: uuid.UUID | None = None,
    *,
    period: ModelGuardrailPeriod = ModelGuardrailPeriod.hour,
    unit: ModelUsageUnit = ModelUsageUnit.k,
    limit_value: int = 100,
    model_name: str = "gpt-4o-mini",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=limit_id or uuid.uuid4(),
        model_id=uuid.uuid4(),
        model_name=model_name,
        period=period,
        limit_value=limit_value,
        unit=unit,
        enforcement_posture=ModelGuardrailEnforcementPosture.terminate,
        is_active=True,
        details={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _fake_posture() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        model_guardrail_configuration_id=uuid.uuid4(),
        model_id=uuid.uuid4(),
        posture_period=ModelUsagePosturePeriod.hour,
        usage_value=84,
        limit_value=100,
        posture_state=ModelUsagePostureState.approaching_limit,
        observed_at=datetime.now(timezone.utc),
        details={},
    )


@pytest.mark.asyncio
async def test_list_model_usage_limits_returns_configurations():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    fake_limit = _fake_limit()

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.list_configurations",
            new=AsyncMock(return_value=[fake_limit]),
        ) as list_mock:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/agents/guardrails/model-usage-limits")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(fake_limit.id)
    assert body[0]["model_name"] == "gpt-4o-mini"
    assert body[0]["period"] == "hour"
    assert body[0]["limit_value"] == 100
    list_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_model_usage_limit_with_one_period_returns_201():
    """Creating a single per-period guardrail returns 201 with the row."""
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    fake_limit = _fake_limit()

    payload = {
        "model_id": "gpt-4.1-nano",
        "model_name": "gpt-4.1-nano",
        "period": "hour",
        "limit_value": 100,
        "unit": "k",
        "enforcement_posture": "terminate",
        "is_active": True,
    }

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.create_configuration",
            new=AsyncMock(return_value=fake_limit),
        ) as create_mock:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/agents/guardrails/model-usage-limits",
                    json=payload,
                )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(fake_limit.id)
    assert body["period"] == "hour"
    assert body["limit_value"] == 100
    create_mock.assert_awaited_once()
    _, kwargs = create_mock.call_args
    assert kwargs["period"].value == "hour"
    assert kwargs["limit_value"] == 100
    assert kwargs["model_id"] == "gpt-4.1-nano"


@pytest.mark.asyncio
async def test_create_model_usage_limit_duplicate_period_returns_409():
    """A second guardrail for the same (model, period) returns 409 with a
    deterministic conflict payload so the UI can render the error.
    """
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    cfg_id = uuid.uuid4()

    payload = {
        "model_id": "gpt-4.1-nano",
        "model_name": "gpt-4.1-nano",
        "period": "hour",
        "limit_value": 100,
        "unit": "k",
    }

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.create_configuration",
            new=AsyncMock(
                side_effect=ModelGuardrailDuplicatePeriodError(
                    cfg_id, ModelGuardrailPeriod.hour
                )
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/agents/guardrails/model-usage-limits",
                    json=payload,
                )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["error"] == "guardrail_period_conflict"
    assert body["detail"]["period"] == "hour"
    assert body["detail"]["model_config_id"] == str(cfg_id)


@pytest.mark.asyncio
async def test_create_model_usage_limit_returns_400_when_model_name_unknown():
    """If no ModelConfig lists the supplied model name, the endpoint
    surfaces a 400 with a clear message rather than a generic 500.
    """
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)

    payload = {
        "model_id": "unknown-model",
        "model_name": "unknown-model",
        "period": "hour",
        "limit_value": 100,
    }

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.create_configuration",
            new=AsyncMock(side_effect=ModelGuardrailModelNotFoundError("unknown-model")),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/agents/guardrails/model-usage-limits",
                    json=payload,
                )

    assert response.status_code == 400
    assert "unknown-model" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_model_usage_limit_changes_limit_value_and_posture():
    """Partial update: limit_value + enforcement_posture pass through to service."""
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    limit_id = uuid.uuid4()
    fake_limit = _fake_limit(
        limit_id=limit_id,
        limit_value=250,
        unit=ModelUsageUnit.tokens,
    )
    fake_limit.enforcement_posture = ModelGuardrailEnforcementPosture.observe_only

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.update_configuration",
            new=AsyncMock(return_value=fake_limit),
        ) as update_mock:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.put(
                    f"/api/v1/agents/guardrails/model-usage-limits/{limit_id}",
                    json={
                        "limit_value": 250,
                        "enforcement_posture": "observe_only",
                        "unit": "tokens",
                    },
                )

    assert response.status_code == 200
    body = response.json()
    assert body["limit_value"] == 250
    assert body["unit"] == "tokens"
    assert body["enforcement_posture"] == "observe_only"
    update_mock.assert_awaited_once()
    _, kwargs = update_mock.call_args
    assert kwargs["limit_value"] == 250
    assert kwargs["enforcement_posture"] == ModelGuardrailEnforcementPosture.observe_only
    assert kwargs["unit"] == ModelUsageUnit.tokens


@pytest.mark.asyncio
async def test_update_model_usage_limit_returns_404_when_missing():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    limit_id = uuid.uuid4()

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.update_configuration",
            new=AsyncMock(return_value=None),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.put(
                    f"/api/v1/agents/guardrails/model-usage-limits/{limit_id}",
                    json={"limit_value": 42},
                )

    assert response.status_code == 404
    assert response.json()["detail"] == "Model usage limit not found"


@pytest.mark.asyncio
async def test_delete_model_usage_limit_returns_204():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    limit_id = uuid.uuid4()

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.delete_configuration",
            new=AsyncMock(return_value=True),
        ) as delete_mock:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.delete(
                    f"/api/v1/agents/guardrails/model-usage-limits/{limit_id}"
                )

    assert response.status_code == 204
    delete_mock.assert_awaited_once_with(limit_id, mock_session)


@pytest.mark.asyncio
async def test_delete_model_usage_limit_returns_404_when_missing():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    limit_id = uuid.uuid4()

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.delete_configuration",
            new=AsyncMock(return_value=False),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.delete(
                    f"/api/v1/agents/guardrails/model-usage-limits/{limit_id}"
                )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_model_usage_limits_returns_multiple_periods_for_same_model():
    """The list returns one row per (model, period) — a model with four
    guardrails surfaces as four rows in the response.
    """
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    model_id = uuid.uuid4()
    created = datetime.now(timezone.utc)
    rows = [
        SimpleNamespace(
            id=uuid.uuid4(),
            model_id=model_id,
            model_name="gpt-4o",
            period=p,
            limit_value=100 * i,
            unit=ModelUsageUnit.k,
            enforcement_posture=ModelGuardrailEnforcementPosture.terminate,
            is_active=True,
            details={},
            created_at=created,
            updated_at=created,
        )
        for i, p in enumerate(
            [
                ModelGuardrailPeriod.hour,
                ModelGuardrailPeriod.day,
                ModelGuardrailPeriod.week,
                ModelGuardrailPeriod.month,
            ],
            start=1,
        )
    ]

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.list_configurations",
            new=AsyncMock(return_value=rows),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/agents/guardrails/model-usage-limits")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 4
    assert {row["period"] for row in body} == {"hour", "day", "week", "month"}
    assert {row["model_name"] for row in body} == {"gpt-4o"}


@pytest.mark.asyncio
async def test_get_model_usage_posture_refreshes_before_reading():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    fake_posture = _fake_posture()

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.refresh_posture_snapshots",
            new=AsyncMock(return_value=[fake_posture]),
        ) as refresh_mock:
            with patch(
                "app.api.v1.agents._model_usage_guardrail_service.get_current_posture",
                new=AsyncMock(return_value=[fake_posture]),
            ) as get_mock:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get(
                        "/api/v1/agents/guardrails/model-usage-posture?refresh=true"
                    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["posture_period"] == "hour"
    assert body[0]["posture_state"] == "approaching_limit"
    refresh_mock.assert_awaited_once()
    get_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_model_usage_limit_default_enforcement_posture_is_terminate():
    """Omitting ``enforcement_posture`` defaults to terminate."""
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    fake_limit = _fake_limit()

    payload = {
        "model_id": "gpt-4.1-nano",
        "model_name": "gpt-4.1-nano",
        "period": "hour",
        "limit_value": 100,
    }

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.create_configuration",
            new=AsyncMock(return_value=fake_limit),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/agents/guardrails/model-usage-limits",
                    json=payload,
                )

    assert response.status_code == 201
    body = response.json()
    assert body["enforcement_posture"] == "terminate"
    assert body["is_active"] is True
    assert body["unit"] == "k"


@pytest.mark.asyncio
async def test_create_model_usage_limit_default_unit_is_k():
    """Omitting ``unit`` defaults to ``k``."""
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    fake_limit = _fake_limit(unit=ModelUsageUnit.k)

    payload = {
        "model_id": "gpt-4.1-nano",
        "model_name": "gpt-4.1-nano",
        "period": "hour",
        "limit_value": 100,
    }

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.create_configuration",
            new=AsyncMock(return_value=fake_limit),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/agents/guardrails/model-usage-limits",
                    json=payload,
                )

    assert response.status_code == 201
    body = response.json()
    assert body["unit"] == "k"


@pytest.mark.asyncio
async def test_get_model_usage_limit_returns_full_per_guardrail_shape():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    limit_id = uuid.uuid4()
    fake_limit = _fake_limit(
        limit_id=limit_id,
        period=ModelGuardrailPeriod.day,
        unit=ModelUsageUnit.tokens,
        limit_value=10000,
    )

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.get_configuration",
            new=AsyncMock(return_value=fake_limit),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    f"/api/v1/agents/guardrails/model-usage-limits/{limit_id}"
                )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(limit_id)
    assert body["period"] == "day"
    assert body["unit"] == "tokens"
    assert body["limit_value"] == 10000
