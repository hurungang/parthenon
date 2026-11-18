"""Optimizer-model config API — ``GET/PUT /agents/model-configs/optimizer-model``.

Workspace-scoped selection for the optimization conversation's model:

* ``GET`` returns the session tenant's enabled, non-disabled catalogue as
  options plus the raw ``selected_model_id`` and the effective id/source/
  configured/enabled/reason;
* ``PUT`` writes ONLY the session tenant's row, ``null`` clears (→ inherit the
  plan-authoring model), and a model that is not enabled in this workspace is
  rejected with ``422`` while the previous selection stays untouched;
* a stale saved value is still visible (raw) and reported as unusable — never
  silently auto-cleared and never replaced by another model;
* another tenant's models are not selectable.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT
from app.core.tenant_context import (
    TenantContext,
    reset_current_tenant_context,
    set_current_tenant_context,
)
from app.db.models.agents import ModelConfig, ModelProvider
from app.db.models.tenant import Tenant, TenantStatus
from app.db.models.tenant_setting import TenantSetting
from app.db.session import Base, get_db
from app.main import create_app
from app.services.agents.optimizer_model_settings import OPTIMIZER_MODEL_KEY
from app.services.agents.workflow_generation_settings import (
    WORKFLOW_GENERATION_MODEL_KEY,
)
from app.services.tenancy.root_tenant import invalidate_root_tenant_cache
from app.services.tenancy.tenant_settings_service import set_value

OPTIMIZER_MODEL = "cfg-optimizer-model"
SECOND_MODEL = "cfg-second-model"
AUTHORING_MODEL = "cfg-authoring-model"
OTHER_TENANT_MODEL = "cfg-other-tenant-model"
STALE_MODEL = "cfg-removed-model"
DISABLED_MODEL = "cfg-disabled-model"


@pytest_asyncio.fixture
async def env():
    invalidate_root_tenant_cache()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    root_id = uuid.uuid4()
    other_id = uuid.uuid4()
    async with SessionLocal() as session:
        session.add_all(
            [
                Tenant(
                    id=root_id,
                    slug="cfg-root",
                    name="Cfg Root",
                    status=TenantStatus.active,
                    is_system_tenant=True,
                ),
                Tenant(
                    id=other_id,
                    slug="cfg-other",
                    name="Cfg Other",
                    status=TenantStatus.active,
                ),
            ]
        )
        await session.commit()

    holder: dict = {"tenant_id": root_id, "tenancy_enabled": False}

    def _allow(action: str):
        def override():
            return {"sub": "cfg-admin", "roles": ["admin"]}

        return override

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "cfg-admin"}
        request.state.identity_id = None
        return await call_next(request)

    async def patched_resolution(self, request, call_next):
        request.state.tenancy_enabled = holder["tenancy_enabled"]
        if not holder["tenancy_enabled"]:
            return await call_next(request)
        token = set_current_tenant_context(
            TenantContext(
                tenant_id=holder["tenant_id"],
                slug="cfg",
                name="Cfg",
                is_system_tenant=False,
            )
        )
        try:
            return await call_next(request)
        finally:
            reset_current_tenant_context(token)

    from app.middleware.auth import JWTAuthMiddleware
    from app.middleware.tenant_resolution import TenantResolutionMiddleware

    app = create_app()
    for action in ("read", "update"):
        app.dependency_overrides[require_permission(RT_AGENT, action)] = _allow(
            action
        )

    async def override_db(request: Request):
        from app.db.tenant_scoping import (
            apply_tenant_scope,
            register_tenant_scope_listener,
        )

        async with SessionLocal() as session:
            if holder["tenancy_enabled"]:
                register_tenant_scope_listener()
                apply_tenant_scope(session, holder["tenant_id"])
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch), patch.object(
        TenantResolutionMiddleware, "dispatch", patched_resolution
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield {
                "client": client,
                "session_factory": SessionLocal,
                "root_id": root_id,
                "other_id": other_id,
                "holder": holder,
            }

    await engine.dispose()
    invalidate_root_tenant_cache()


async def _enable_model(
    factory,
    tenant_id: uuid.UUID,
    model_id: str,
    *,
    is_disabled: bool = False,
    display_name: str | None = None,
) -> ModelConfig:
    async with factory() as session:
        config = ModelConfig(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            display_name=display_name or f"cfg-{model_id}",
            provider_type=ModelProvider.openai,
            api_base_url="http://localhost:9999/v1",
            enabled_models=[model_id],
            is_disabled=is_disabled,
        )
        session.add(config)
        await session.commit()
        return config


async def _select(factory, tenant_id: uuid.UUID, key: str, value: str | None) -> None:
    async with factory() as session:
        await set_value(session, tenant_id, key, value)
        await session.commit()


async def _selected_row(factory, tenant_id: uuid.UUID):
    async with factory() as session:
        return (
            await session.execute(
                select(TenantSetting).where(
                    TenantSetting.tenant_id == tenant_id,
                    TenantSetting.key == OPTIMIZER_MODEL_KEY,
                )
            )
        ).scalar_one_or_none()


URL = "/api/v1/agents/model-configs/optimizer-model"


class TestOptimizerModelConfigGet:
    @pytest.mark.asyncio
    async def test_options_are_the_workspace_catalogue_and_state_is_derived(
        self, env
    ):
        factory = env["session_factory"]
        await _enable_model(factory, env["root_id"], OPTIMIZER_MODEL)
        await _enable_model(factory, env["root_id"], AUTHORING_MODEL)
        await _enable_model(factory, env["root_id"], DISABLED_MODEL, is_disabled=True)
        await _select(
            factory, env["root_id"], WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
        )

        response = await env["client"].get(URL)
        assert response.status_code == 200, response.text
        body = response.json()

        option_ids = {option["model_id"] for option in body["options"]}
        assert OPTIMIZER_MODEL in option_ids
        assert AUTHORING_MODEL in option_ids
        # A disabled provider config is never offered.
        assert DISABLED_MODEL not in option_ids

        assert body["selected_model_id"] is None
        assert body["effective_model_id"] == AUTHORING_MODEL
        assert body["source"] == "authoring"
        assert body["configured"] is False
        assert body["enabled"] is True
        assert body["reason_code"] is None

    @pytest.mark.asyncio
    async def test_explicit_selection_is_effective(self, env):
        factory = env["session_factory"]
        await _enable_model(factory, env["root_id"], OPTIMIZER_MODEL)
        await _select(factory, env["root_id"], OPTIMIZER_MODEL_KEY, OPTIMIZER_MODEL)

        body = (await env["client"].get(URL)).json()

        assert body["selected_model_id"] == OPTIMIZER_MODEL
        assert body["effective_model_id"] == OPTIMIZER_MODEL
        assert body["source"] == "optimizer"
        assert body["configured"] is True
        assert body["enabled"] is True

    @pytest.mark.asyncio
    async def test_stale_value_stays_visible_and_reports_not_enabled(self, env):
        factory = env["session_factory"]
        await _enable_model(factory, env["root_id"], OPTIMIZER_MODEL)
        await _select(factory, env["root_id"], OPTIMIZER_MODEL_KEY, STALE_MODEL)

        body = (await env["client"].get(URL)).json()

        # Raw value echoed — the UI can say "<id> is no longer available".
        assert body["selected_model_id"] == STALE_MODEL
        assert STALE_MODEL not in {o["model_id"] for o in body["options"]}
        assert body["effective_model_id"] is None
        assert body["source"] == "optimizer"
        assert body["configured"] is True
        assert body["enabled"] is False
        assert body["reason_code"] == "optimizer_model_not_enabled"

    @pytest.mark.asyncio
    async def test_nothing_configured_reports_not_configured(self, env):
        body = (await env["client"].get(URL)).json()
        assert body["selected_model_id"] is None
        assert body["effective_model_id"] is None
        assert body["reason_code"] == "optimizer_model_not_configured"


class TestOptimizerModelConfigPut:
    @pytest.mark.asyncio
    async def test_put_writes_only_the_session_tenant_row(self, env):
        factory = env["session_factory"]
        await _enable_model(factory, env["root_id"], OPTIMIZER_MODEL)

        response = await env["client"].put(URL, json={"model_id": OPTIMIZER_MODEL})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["selected_model_id"] == OPTIMIZER_MODEL
        assert body["effective_model_id"] == OPTIMIZER_MODEL
        assert body["source"] == "optimizer"

        root_row = await _selected_row(factory, env["root_id"])
        other_row = await _selected_row(factory, env["other_id"])
        assert root_row is not None and root_row.value == OPTIMIZER_MODEL
        assert other_row is None

    @pytest.mark.asyncio
    async def test_422_for_a_model_not_enabled_in_this_workspace(self, env):
        factory = env["session_factory"]
        await _enable_model(factory, env["root_id"], OPTIMIZER_MODEL)
        await _select(factory, env["root_id"], OPTIMIZER_MODEL_KEY, OPTIMIZER_MODEL)

        response = await env["client"].put(
            URL, json={"model_id": "not-in-this-catalogue"}
        )
        assert response.status_code == 422
        assert "catalogue" in str(response.json()["detail"]).lower()

        # The previous selection is unchanged.
        row = await _selected_row(factory, env["root_id"])
        assert row is not None and row.value == OPTIMIZER_MODEL

    @pytest.mark.asyncio
    async def test_422_for_a_disabled_provider_model(self, env):
        factory = env["session_factory"]
        await _enable_model(factory, env["root_id"], DISABLED_MODEL, is_disabled=True)

        response = await env["client"].put(URL, json={"model_id": DISABLED_MODEL})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_null_clears_and_restores_the_authoring_fallback(self, env):
        factory = env["session_factory"]
        authoring = await _enable_model(factory, env["root_id"], AUTHORING_MODEL)
        await _enable_model(factory, env["root_id"], OPTIMIZER_MODEL)
        await _select(
            factory, env["root_id"], WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
        )
        await _select(factory, env["root_id"], OPTIMIZER_MODEL_KEY, OPTIMIZER_MODEL)

        response = await env["client"].put(URL, json={"model_id": None})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["selected_model_id"] is None
        assert body["effective_model_id"] == AUTHORING_MODEL
        assert body["source"] == "authoring"
        assert body["configured"] is False

        # Exactly one row remains (no second value written) and it is cleared.
        row = await _selected_row(factory, env["root_id"])
        assert row is not None and row.value is None
        # The fallback still resolves to the authoring config.
        assert body["options"]
        assert authoring is not None

    @pytest.mark.asyncio
    async def test_a_stale_selection_can_be_replaced(self, env):
        factory = env["session_factory"]
        await _enable_model(factory, env["root_id"], SECOND_MODEL)
        await _select(factory, env["root_id"], OPTIMIZER_MODEL_KEY, STALE_MODEL)

        response = await env["client"].put(URL, json={"model_id": SECOND_MODEL})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["selected_model_id"] == SECOND_MODEL
        assert body["reason_code"] is None


class TestOptimizerModelConfigTenancy:
    @pytest.mark.asyncio
    async def test_another_tenants_models_are_not_selectable(self, env):
        factory = env["session_factory"]
        # The model exists ONLY in the other tenant's catalogue.
        await _enable_model(factory, env["other_id"], OTHER_TENANT_MODEL)
        # With tenancy off the deployment is root-only (no second tenant is
        # reachable); the qualified-resolution probe therefore runs with the
        # multi-tenant path enabled, which scopes the session like ``get_db``.
        env["holder"]["tenancy_enabled"] = True

        response = await env["client"].put(URL, json={"model_id": OTHER_TENANT_MODEL})
        assert response.status_code == 422
        assert await _selected_row(factory, env["root_id"]) is None

    @pytest.mark.asyncio
    async def test_options_are_tenant_scoped_when_tenancy_is_on(self, env):
        factory = env["session_factory"]
        await _enable_model(factory, env["root_id"], OPTIMIZER_MODEL)
        await _enable_model(factory, env["other_id"], OTHER_TENANT_MODEL)
        env["holder"]["tenancy_enabled"] = True

        body = (await env["client"].get(URL)).json()
        option_ids = {option["model_id"] for option in body["options"]}

        assert OPTIMIZER_MODEL in option_ids
        assert OTHER_TENANT_MODEL not in option_ids

    @pytest.mark.asyncio
    async def test_selection_is_per_tenant_when_tenancy_is_on(self, env):
        factory = env["session_factory"]
        await _enable_model(factory, env["root_id"], OPTIMIZER_MODEL)
        await _enable_model(factory, env["other_id"], OTHER_TENANT_MODEL)
        await _select(factory, env["other_id"], OPTIMIZER_MODEL_KEY, OTHER_TENANT_MODEL)
        env["holder"]["tenancy_enabled"] = True

        body = (await env["client"].get(URL)).json()
        # Tenant A does not see tenant B's selection (or resolve it).
        assert body["selected_model_id"] is None
        assert body["reason_code"] == "optimizer_model_not_configured"
