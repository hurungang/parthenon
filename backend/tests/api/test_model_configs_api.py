"""API tests for ModelConfig endpoints.

Covers the behaviour change in GET /agents/model-configs/{config_id}/models:
- Endpoint now always calls list_models_for_config (live provider query)
- NOT fetch_available_models (which short-circuits to cached enabled_models)
- Returns all provider models regardless of what is in enabled_models
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.db.session import get_db
from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT
from app.middleware.auth import JWTAuthMiddleware


# ── Auth / DB helpers ───────────────────────────────────────────────────────────


def _bypass_auth():
    """Patch JWTAuthMiddleware to inject a valid admin identity on every request."""

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "admin-sub", "roles": ["admin"]}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _mock_permission_allow():
    """Patch PermissionEngine.authorize to always allow."""
    from app.services.permissions.permission_engine import AuthorizationResult

    async def mock_authorize(*args, **kwargs):
        return AuthorizationResult(allowed=True, reason="Test override")

    return patch(
        "app.services.permissions.permission_engine.PermissionEngine.authorize",
        mock_authorize,
    )


def _deny_permission_override():
    """Dependency override that always raises 403."""
    from fastapi import HTTPException

    def override():
        raise HTTPException(status_code=403, detail="Permission denied.")

    return override


def _db_returning(return_value=None):
    """Return a (mock_session, dep_override) pair.

    *return_value* is used for both ``session.get()`` and scalar lookups so that
    PlatformUser resolution inside ``require_permission`` succeeds.
    """
    mock_session = AsyncMock()

    def make_execute_result(val):
        res = MagicMock()
        res.scalar_one_or_none = MagicMock(return_value=val)
        res.scalar_one = MagicMock(return_value=val)
        res.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[]))
        )
        return res

    mock_session.execute = AsyncMock(return_value=make_execute_result(return_value))
    mock_session.get = AsyncMock(return_value=return_value)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.delete = AsyncMock()

    async def override():
        yield mock_session

    return mock_session, override


# ── Tests ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_models_returns_all_provider_models():
    """GET /agents/model-configs/{id}/models returns all models from the live provider.

    Even when only 2 models are in enabled_models, the endpoint returns all 5 models
    that the provider API reports.  This is the expected behaviour after the change:
    always query the live provider so users can update their model selection.
    """
    config_id = uuid.uuid4()
    provider_models = ["gpt-4o", "gpt-4-turbo", "gpt-4o-mini", "gpt-3.5-turbo", "gpt-4"]

    _, db_dep = _db_returning(return_value=MagicMock())
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_config_service.list_models_for_config",
            AsyncMock(return_value=provider_models),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/api/v1/agents/model-configs/{config_id}/models")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 5
    assert set(data) == set(provider_models)


@pytest.mark.asyncio
async def test_list_models_calls_live_provider_not_enabled_list():
    """GET /agents/model-configs/{id}/models always calls list_models_for_config.

    Verifies the endpoint uses list_models_for_config (live query) and NOT
    fetch_available_models (which would short-circuit to cached enabled_models when
    enabled_models is non-empty).  This is the key behaviour change introduced in
    the backend API fix.
    """
    config_id = uuid.uuid4()
    live_models = ["gpt-4o", "gpt-4-turbo", "gpt-4o-mini"]

    _, db_dep = _db_returning(return_value=MagicMock())
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    list_models_mock = AsyncMock(return_value=live_models)
    # fetch_available_models would return only the cached enabled_models
    fetch_available_mock = AsyncMock(return_value=["gpt-4o"])

    with _bypass_auth(), _mock_permission_allow():
        with (
            patch(
                "app.api.v1.agents._model_config_service.list_models_for_config",
                list_models_mock,
            ),
            patch(
                "app.api.v1.agents._model_config_service.fetch_available_models",
                fetch_available_mock,
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/api/v1/agents/model-configs/{config_id}/models")

    assert resp.status_code == 200
    assert resp.json() == live_models
    list_models_mock.assert_called_once()
    fetch_available_mock.assert_not_called()


@pytest.mark.asyncio
async def test_list_models_returns_404_for_unknown_config():
    """GET /agents/model-configs/{id}/models returns 404 when config does not exist."""
    from app.services.agents.model_config_service import ModelConfigNotFoundError

    config_id = uuid.uuid4()
    _, db_dep = _db_returning(return_value=MagicMock())
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_config_service.list_models_for_config",
            AsyncMock(
                side_effect=ModelConfigNotFoundError(f"ModelConfig {config_id} not found")
            ),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(f"/api/v1/agents/model-configs/{config_id}/models")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_models_requires_agent_read_permission():
    """GET /agents/model-configs/{id}/models returns 403 without agent:read permission."""
    config_id = uuid.uuid4()
    _, db_dep = _db_returning(return_value=MagicMock())
    app = create_app()
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission(RT_AGENT, "read")] = _deny_permission_override()

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/agents/model-configs/{config_id}/models")

    assert resp.status_code == 403
