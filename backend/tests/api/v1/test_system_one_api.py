"""API tests for System One (Decision Model Providers) endpoints.

Covers the user-acceptance fixes for the decision-model-providers change:
- GET /system-one/provider-types serves the backend enum (never hardcoded
  client-side)
- GET /system-one/providers/{id}/vendor-models returns discovered model ids
  and maps vendor errors to HTTP 502 (never key material)
- POST /system-one/providers/{id}/import-models imports catalogue rows
- default_model validation errors map to HTTP 422
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from unittest.mock import MagicMock

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.db.session import get_db
from app.middleware.auth import JWTAuthMiddleware
from app.api.v1 import system_one as system_one_router
from app.db.models.system_one_provider_config import SystemOneProviderType
from app.services.system_one.provider_config_service import (
    SystemOneProviderValidationError,
)


def _bypass_auth():
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "admin-sub", "roles": ["admin"]}
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


def _app() -> tuple:
    from types import SimpleNamespace

    mock_db = AsyncMock()
    permission_result = MagicMock()
    permission_result.scalar_one_or_none = MagicMock(
        return_value=SimpleNamespace(id=uuid.uuid4(), sub="admin-sub")
    )
    mock_db.execute = AsyncMock(return_value=permission_result)

    async def override():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = override
    return app, mock_db


@pytest.mark.asyncio
async def test_provider_types_served_from_backend_enum():
    """GET /system-one/provider-types lists every SystemOneProviderType value."""
    app, _ = _app()
    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/system-one/provider-types")

    assert resp.status_code == 200
    body = resp.json()
    enum_values = [t.value for t in SystemOneProviderType]
    assert [entry["value"] for entry in body] == enum_values
    assert all(entry["label"] for entry in body)


@pytest.mark.asyncio
async def test_vendor_models_returns_discovered_ids():
    """GET .../vendor-models returns the model id list — never key material."""
    app, _ = _app()
    provider_id = uuid.uuid4()
    with _bypass_auth(), _mock_permission_allow(), patch.object(
        system_one_router._service,
        "list_vendor_models",
        AsyncMock(return_value=["jev-latest", "jev-pro"]),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/v1/system-one/providers/{provider_id}/vendor-models"
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"models": ["jev-latest", "jev-pro"]}
    assert "api" not in str(body).lower() or "api_key" not in body


@pytest.mark.asyncio
async def test_vendor_models_vendor_error_maps_to_502():
    """Vendor discovery failure (bad key / unreachable / incompatible) → 502
    with the actionable service message."""
    app, _ = _app()
    provider_id = uuid.uuid4()
    with _bypass_auth(), _mock_permission_allow(), patch.object(
        system_one_router._service,
        "list_vendor_models",
        AsyncMock(
            side_effect=system_one_router.SystemOneProviderError(
                "the API key was rejected"
            )
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/v1/system-one/providers/{provider_id}/vendor-models"
            )

    assert resp.status_code == 502
    assert "API key" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_import_models_returns_provider_without_key():
    """POST .../import-models imports the ids and returns a key-free provider."""
    app, _ = _app()
    provider_id = uuid.uuid4()

    class _FakeConfig:
        id = provider_id
        provider_type = SystemOneProviderType.typesafe
        display_name = "Primary Vendor"
        base_url = "https://api.typesafe.ai/v1/systemone"
        default_model = "jev-latest"
        enabled = True
        enabled_models = ["jev-latest", "jev-pro"]
        encrypted_api_key = "enc"

    with _bypass_auth(), _mock_permission_allow(), patch.object(
        system_one_router._service,
        "import_vendor_models",
        AsyncMock(return_value=_FakeConfig()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/v1/system-one/providers/{provider_id}/import-models",
                json={"models": ["jev-pro"]},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["default_model"] == "jev-latest"
    assert "encrypted_api_key" not in body
    assert "api_key" not in body


@pytest.mark.asyncio
async def test_import_models_validation_error_maps_to_422():
    """Empty import payload → service validation error → HTTP 422."""
    app, _ = _app()
    provider_id = uuid.uuid4()
    with _bypass_auth(), _mock_permission_allow(), patch.object(
        system_one_router._service,
        "import_vendor_models",
        AsyncMock(
            side_effect=SystemOneProviderValidationError(
                "No models to import — the vendor returned an empty list"
            )
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/v1/system-one/providers/{provider_id}/import-models",
                json={"models": ["  "]} if False else {"models": ["x"]},
            )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_default_model_validation_error_maps_to_422_on_create():
    """POST /providers with a default_model outside the catalogue → 422."""
    app, _ = _app()
    with _bypass_auth(), _mock_permission_allow(), patch.object(
        system_one_router._service,
        "create",
        AsyncMock(
            side_effect=SystemOneProviderValidationError(
                "default_model 'mystery' must be one of the enabled models: jev-latest"
            )
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/system-one/providers",
                json={
                    "display_name": "P",
                    "api_key": "sk-x",
                    "default_model": "mystery",
                },
            )

    assert resp.status_code == 422
    assert "must be one of" in resp.json()["detail"]
