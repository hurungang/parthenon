from __future__ import annotations

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

from app.db.models.model_availability import ModelAvailabilityDisabledReason
from app.db.models.model_guardrail_configuration import (
    ModelGuardrailEnforcementPosture,
    ModelGuardrailPeriod,
    ModelUsageUnit,
)
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware
from app.services.control_center.model_availability_service import (
    PreflightAvailabilityOutcome,
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


def _fake_model_config(
    config_id: uuid.UUID | None = None,
    *,
    display_name: str = "Vendor A",
    is_disabled: bool = False,
    enabled_models: list[str] | None = None,
) -> SimpleNamespace:
    from app.db.models.agents import ModelProvider

    return SimpleNamespace(
        id=config_id or uuid.uuid4(),
        display_name=display_name,
        provider_type=ModelProvider.openai,
        api_base_url="https://api.openai.com/v1",
        encrypted_api_key=None,
        is_disabled=is_disabled,
        enabled_models=enabled_models if enabled_models is not None else [],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _fake_availability_row(
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
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ── Vendor toggle ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_vendor_disabled_cascades_to_availability_rows():
    """PUT /model-configs/{id}/disabled=true returns the vendor with
    is_disabled=true and the service is invoked.
    """
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    cfg_id = uuid.uuid4()
    fake_cfg = _fake_model_config(config_id=cfg_id, is_disabled=True)

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_availability_service.set_vendor_disabled",
            new=AsyncMock(return_value=fake_cfg),
        ) as svc_mock:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.put(
                    f"/api/v1/agents/model-configs/{cfg_id}/disabled",
                    json={"is_disabled": True},
                )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(cfg_id)
    assert body["is_disabled"] is True
    svc_mock.assert_awaited_once()
    args, _kwargs = svc_mock.call_args
    # endpoint signature: (db, vendor_config_id, is_disabled)
    assert args[1] == cfg_id
    assert args[2] is True


@pytest.mark.asyncio
async def test_put_vendor_disabled_re_enables_returns_200():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    cfg_id = uuid.uuid4()
    fake_cfg = _fake_model_config(config_id=cfg_id, is_disabled=False)

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_availability_service.set_vendor_disabled",
            new=AsyncMock(return_value=fake_cfg),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.put(
                    f"/api/v1/agents/model-configs/{cfg_id}/disabled",
                    json={"is_disabled": False},
                )

    assert response.status_code == 200
    body = response.json()
    assert body["is_disabled"] is False


@pytest.mark.asyncio
async def test_put_vendor_disabled_unknown_vendor_returns_404():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    cfg_id = uuid.uuid4()

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_availability_service.set_vendor_disabled",
            new=AsyncMock(side_effect=LookupError("not found")),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.put(
                    f"/api/v1/agents/model-configs/{cfg_id}/disabled",
                    json={"is_disabled": True},
                )

    assert response.status_code == 404


# ── Per-model toggle ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_per_model_disabled_sets_manual_reason():
    """PUT .../models/{name}/disabled with is_disabled=true calls the
    service which returns a row with disabled_reason=manual.
    """
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    cfg_id = uuid.uuid4()
    fake_row = _fake_availability_row(
        vendor_id=cfg_id,
        model_name="gpt-4o",
        is_disabled=True,
        disabled_reason=ModelAvailabilityDisabledReason.manual,
    )

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_availability_service.set_model_disabled",
            new=AsyncMock(return_value=fake_row),
        ) as svc_mock:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.put(
                    f"/api/v1/agents/model-configs/{cfg_id}/models/gpt-4o/disabled",
                    json={"is_disabled": True},
                )

    assert response.status_code == 200
    body = response.json()
    assert body["is_disabled"] is True
    assert body["disabled_reason"] == "manual"
    assert body["model_name"] == "gpt-4o"
    svc_mock.assert_awaited_once()
    args, _kwargs = svc_mock.call_args
    # endpoint signature: (db, vendor_config_id, model_name, is_disabled)
    assert args[1] == cfg_id
    assert args[2] == "gpt-4o"
    assert args[3] is True


@pytest.mark.asyncio
async def test_put_per_model_disabled_re_enable_returns_200():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    cfg_id = uuid.uuid4()
    fake_row = _fake_availability_row(
        vendor_id=cfg_id,
        model_name="gpt-4o",
        is_disabled=False,
        disabled_reason=ModelAvailabilityDisabledReason.manual,
    )

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_availability_service.set_model_disabled",
            new=AsyncMock(return_value=fake_row),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.put(
                    f"/api/v1/agents/model-configs/{cfg_id}/models/gpt-4o/disabled",
                    json={"is_disabled": False},
                )

    assert response.status_code == 200
    body = response.json()
    assert body["is_disabled"] is False


# ── Hierarchy ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_hierarchy_returns_vendor_model_guardrail_effective_state():
    """GET /model-availability returns the full vendor → model → guardrail
    hierarchy with effective is_disabled state and the cascade source.
    """
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    cfg_a = uuid.uuid4()
    cfg_b = uuid.uuid4()
    hierarchy = [
        {
            "vendor_model_config_id": cfg_a,
            "display_name": "Vendor A",
            "is_disabled": True,
            "models": [
                {
                    "model_name": "gpt-4o",
                    "effective_is_disabled": True,
                    "disabled_reason": ModelAvailabilityDisabledReason.vendor_cascaded,
                    "guardrails": [
                        {
                            "id": uuid.uuid4(),
                            "period": ModelGuardrailPeriod.hour,
                            "limit_value": 1000,
                            "unit": ModelUsageUnit.k,
                            "enforcement_posture": ModelGuardrailEnforcementPosture.terminate,
                            "is_active": True,
                            "usage_value": 50,
                            "posture_state": None,
                        }
                    ],
                }
            ],
        },
        {
            "vendor_model_config_id": cfg_b,
            "display_name": "Vendor B",
            "is_disabled": False,
            "models": [
                {
                    "model_name": "claude-3",
                    "effective_is_disabled": False,
                    "disabled_reason": ModelAvailabilityDisabledReason.manual,
                    "guardrails": [],
                }
            ],
        },
    ]

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_availability_service.list_hierarchy",
            new=AsyncMock(return_value=hierarchy),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/agents/model-availability")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2

    vendor_a = body[0]
    assert vendor_a["vendor_display_name"] == "Vendor A"
    assert vendor_a["is_disabled"] is True
    assert len(vendor_a["models"]) == 1
    model = vendor_a["models"][0]
    assert model["model_name"] == "gpt-4o"
    assert model["is_disabled"] is True
    assert model["disabled_reason"] == "vendor_cascaded"
    assert len(model["guardrails"]) == 1
    guard = model["guardrails"][0]
    assert guard["period"] == "hour"
    assert guard["limit_value"] == 1000
    assert guard["unit"] == "k"
    assert guard["enforcement_posture"] == "terminate"

    vendor_b = body[1]
    assert vendor_b["is_disabled"] is False
    assert vendor_b["models"][0]["is_disabled"] is False
    assert vendor_b["models"][0]["disabled_reason"] == "manual"
    assert vendor_b["models"][0]["guardrails"] == []


@pytest.mark.asyncio
async def test_get_hierarchy_empty_when_no_vendors():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_availability_service.list_hierarchy",
            new=AsyncMock(return_value=[]),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/agents/model-availability")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_hierarchy_returns_flat_array_not_wrapped():
    """Regression: the hierarchy endpoint must return a flat array of
    vendor rows. The frontend ``ModelAvailabilityHierarchy`` type and
    the ``useModelAvailability`` hook both rely on this contract —
    wrapping the response (e.g. ``{"vendors": [...]}``) breaks
    ``hierarchy.map(...)`` in ``VendorModelGuardrailPanel``.
    """
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_availability_service.list_hierarchy",
            new=AsyncMock(return_value=[]),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/agents/model-availability")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert not isinstance(body, dict)
    assert "vendors" not in body


# ── Preflight availability ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_preflight_allows_when_both_enabled():
    """When vendor and model are both enabled, the preflight returns allowed=True."""
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    outcome = PreflightAvailabilityOutcome(allowed=True)

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_availability_service.check_availability",
            new=AsyncMock(return_value=outcome),
        ) as svc_mock:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/agents/preflight/availability",
                    json={"model_id": "gpt-4o"},
                )

    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is True
    assert body["reason"] is None
    assert body["disabled_reason"] is None
    assert body["blocked_by"] is None
    svc_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_preflight_blocks_model_disabled():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    outcome = PreflightAvailabilityOutcome(
        allowed=False,
        reason="Model 'gpt-4o' is disabled",
        disabled_reason=ModelAvailabilityDisabledReason.manual,
        blocked_by="model_disabled",
    )

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_availability_service.check_availability",
            new=AsyncMock(return_value=outcome),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/agents/preflight/availability",
                    json={"model_id": "gpt-4o"},
                )

    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is False
    assert body["blocked_by"] == "model_disabled"
    assert body["disabled_reason"] == "manual"


@pytest.mark.asyncio
async def test_post_preflight_blocks_vendor_disabled():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    outcome = PreflightAvailabilityOutcome(
        allowed=False,
        reason="Vendor A is disabled",
        disabled_reason=ModelAvailabilityDisabledReason.vendor_cascaded,
        blocked_by="vendor_disabled",
    )

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_availability_service.check_availability",
            new=AsyncMock(return_value=outcome),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/agents/preflight/availability",
                    json={
                        "model_id": "gpt-4o",
                        "vendor_model_config_id": str(uuid.uuid4()),
                    },
                )

    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is False
    assert body["blocked_by"] == "vendor_disabled"
    assert body["disabled_reason"] == "vendor_cascaded"


@pytest.mark.asyncio
async def test_post_preflight_allows_when_alternate_vendor_available():
    """When two vendors offer the model and one is disabled, the
    preflight (with no vendor_model_config_id) still allows the call
    because the other vendor is enabled.
    """
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    outcome = PreflightAvailabilityOutcome(allowed=True)

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_availability_service.check_availability",
            new=AsyncMock(return_value=outcome),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/agents/preflight/availability",
                    json={"model_id": "gpt-4o"},
                )

    assert response.status_code == 200
    assert response.json()["allowed"] is True


@pytest.mark.asyncio
async def test_post_preflight_blocks_model_not_found():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    outcome = PreflightAvailabilityOutcome(
        allowed=False,
        reason="No ModelConfig offers model 'unknown'",
        blocked_by="model_not_found",
    )

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_availability_service.check_availability",
            new=AsyncMock(return_value=outcome),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/agents/preflight/availability",
                    json={"model_id": "unknown"},
                )

    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is False
    assert body["blocked_by"] == "model_not_found"
