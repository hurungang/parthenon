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


@pytest.mark.asyncio
async def test_get_workflow_generation_model_options_are_sourced_from_enabled_models():
    """GET /agents/model-configs/workflow-generation returns options from model-config enabled_models."""
    now = datetime.now(timezone.utc)
    cfg_1 = MagicMock(
        id=uuid.uuid4(),
        display_name="OpenAI Prod",
        provider_type="openai",
        enabled_models=["gpt-4o-mini", "gpt-4o"],
        created_at=now,
        updated_at=now,
    )
    cfg_2 = MagicMock(
        id=uuid.uuid4(),
        display_name="Anthropic Prod",
        provider_type="anthropic",
        enabled_models=["claude-3-5-sonnet"],
        created_at=now,
        updated_at=now,
    )

    _, db_dep = _db_returning(return_value=MagicMock())
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with (
        _bypass_auth(),
        _mock_permission_allow(),
        patch("app.api.v1.agents._model_config_service.list_model_configs", AsyncMock(return_value=[cfg_1, cfg_2])),
        patch("app.api.v1.agents.get_workflow_generation_model_id", return_value="gpt-4o-mini"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/agents/model-configs/workflow-generation")

    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_model_id"] == "gpt-4o-mini"
    assert [o["model_id"] for o in body["options"]] == ["gpt-4o-mini", "gpt-4o", "claude-3-5-sonnet"]
    assert body["options"][0]["config_display_name"] == "OpenAI Prod"
    assert body["options"][2]["provider_type"] == "anthropic"


@pytest.mark.asyncio
async def test_set_workflow_generation_model_rejects_non_enabled_model():
    """PUT /agents/model-configs/workflow-generation returns 422 for model IDs not in enabled_models."""
    now = datetime.now(timezone.utc)
    cfg = MagicMock(
        id=uuid.uuid4(),
        display_name="OpenAI Prod",
        provider_type="openai",
        enabled_models=["gpt-4o-mini"],
        created_at=now,
        updated_at=now,
    )

    _, db_dep = _db_returning(return_value=MagicMock())
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow(), patch(
        "app.api.v1.agents._model_config_service.list_model_configs", AsyncMock(return_value=[cfg])
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/agents/model-configs/workflow-generation",
                json={"model_id": "not-enabled-model"},
            )

    assert resp.status_code == 422
    assert "not enabled" in resp.json()["detail"].lower()


# ── Twelve-provider catalogue coverage (Phase 5.3) ────────────────────────────
#
# Per ``implementation-plan.md`` Task 5.3: list / create / get / update /
# delete endpoints must round-trip the 12 ``provider_type`` string literals;
# the list-models endpoint must return a non-empty list for every provider.

from app.db.models.agents import ModelProvider  # noqa: E402

ALL_TWELVE_PROVIDERS: list[ModelProvider] = list(ModelProvider)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider", ALL_TWELVE_PROVIDERS, ids=[p.value for p in ALL_TWELVE_PROVIDERS]
)
async def test_list_models_endpoint_returns_non_empty_for_every_provider(
    provider: ModelProvider,
):
    """GET /agents/model-configs/{id}/models returns >=1 model for every provider."""
    config_id = uuid.uuid4()
    provider_models = [f"{provider.value}-model-1", f"{provider.value}-model-2"]

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
    assert len(data) >= 1
    # The provider key must be reflected in the response payload's first
    # model id (or any model id) so the round-trip is byte-for-byte.
    assert any(provider.value in m for m in data)


@pytest.mark.asyncio
async def test_create_model_config_round_trips_every_provider_key():
    """POST /agents/model-configs accepts each of the 12 provider_type values."""
    _, db_dep = _db_returning(return_value=MagicMock())
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    for provider in ALL_TWELVE_PROVIDERS:
        cfg = MagicMock(
            id=uuid.uuid4(),
            display_name=f"{provider.value} Config",
            provider_type=provider.value,
            api_base_url=None,
            encrypted_api_key="enc:present",
            enabled_models=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        with _bypass_auth(), _mock_permission_allow():
            with patch(
                "app.api.v1.agents._model_config_service.create_model_config",
                AsyncMock(return_value=cfg),
            ):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.post(
                        "/api/v1/agents/model-configs",
                        json={
                            "display_name": cfg.display_name,
                            "provider_type": provider.value,
                            "api_key": f"sk-{provider.value}",
                        },
                    )
        assert resp.status_code in (200, 201), (
            f"create failed for {provider.value}: {resp.status_code} {resp.text}"
        )
        body = resp.json()
        assert body["provider_type"] == provider.value


@pytest.mark.asyncio
async def test_list_model_configs_round_trips_every_provider_key():
    """GET /agents/model-configs returns provider_type byte-for-byte for all 12 keys."""
    now = datetime.now(timezone.utc)
    cfgs = [
        MagicMock(
            id=uuid.uuid4(),
            display_name=f"{p.value} cfg",
            provider_type=p.value,
            api_base_url=None,
            encrypted_api_key="enc:present",
            enabled_models=[],
            created_at=now,
            updated_at=now,
        )
        for p in ALL_TWELVE_PROVIDERS
    ]
    _, db_dep = _db_returning(return_value=MagicMock())
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_config_service.list_model_configs",
            AsyncMock(return_value=cfgs),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/agents/model-configs")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 12
    returned_keys = {row["provider_type"] for row in body}
    assert returned_keys == {p.value for p in ALL_TWELVE_PROVIDERS}


@pytest.mark.asyncio
async def test_update_model_config_allows_provider_type_change_between_new_providers():
    """PUT /agents/model-configs/{id} allows provider_type to change from one new key to another."""
    config_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    updated_cfg = MagicMock(
        id=config_id,
        display_name="Changed",
        provider_type="mistral",  # changed from gemini
        api_base_url=None,
        encrypted_api_key="enc:present",
        enabled_models=["mistral-large-latest"],
        created_at=now,
        updated_at=now,
    )
    _, db_dep = _db_returning(return_value=MagicMock())
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_config_service.update_model_config",
            AsyncMock(return_value=updated_cfg),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.put(
                    f"/api/v1/agents/model-configs/{config_id}",
                    json={"provider_type": "mistral"},
                )

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_type"] == "mistral"


@pytest.mark.asyncio
async def test_create_model_config_rejects_empty_display_name():
    """POST /agents/model-configs returns 422 for an empty display_name."""
    _, db_dep = _db_returning(return_value=MagicMock())
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/agents/model-configs",
                json={
                    "display_name": "",  # invalid
                    "provider_type": "openai",
                },
            )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_model_config_rejects_unknown_provider_type():
    """POST /agents/model-configs returns 422 for a provider_type outside the 12-value enum."""
    _, db_dep = _db_returning(return_value=MagicMock())
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/agents/model-configs",
                json={
                    "display_name": "Unknown",
                    "provider_type": "future_provider",  # not in the 12-value enum
                },
            )

    assert resp.status_code == 422
