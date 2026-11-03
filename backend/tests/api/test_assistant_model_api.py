"""API tests for the per-tenant assistant model configuration endpoints.

Covers:
- GET /agents/model-configs/assistant-model: options sourced from the current
  tenant's Model Configurations, selection from the tenant's own assistant
  ``AgentType`` row.
- PUT /agents/model-configs/assistant-model: persists onto the tenant's
  assistant row, creates the row when missing, and 422-rejects models that
  are not enabled in the tenant's model configs.
- Cross-tenant isolation: tenant B's selection never affects tenant A.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.agents import AgentInputType, AgentType, ModelConfig, ModelProvider
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.db.tenant_scoping import apply_tenant_scope, register_tenant_scope_listener


async def _clear_scope_and_reload(session: AsyncSession) -> None:
    """Drop the request tenant scope so verification can see all tenants."""
    session.info.pop("parthenon_tenant_scope", None)
    session.expire_all()
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware
from app.services.agents.assistant_seeder import (
    ASSISTANT_AGENT_TYPE_NAME,
    ASSISTANT_SYSTEM_INSTRUCTION,
)


# ── Auth helpers (same harness as test_model_configs_api.py) ──────────────────


def _bypass_auth(tenant_id: uuid.UUID):
    """Inject an admin identity AND a resolved tenant context (replacing the
    auth + tenant-resolution middlewares, as a real scoped request would)."""

    async def patched_auth_dispatch(self, request, call_next):
        request.state.identity = {"sub": "admin-sub", "roles": ["admin"]}
        return await call_next(request)

    async def patched_tenant_dispatch(self, request, call_next):
        from app.core.tenant_context import TenantContext, set_tenant_context

        set_tenant_context(
            request,
            TenantContext(tenant_id=tenant_id, slug="test", name="Test"),
        )
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_auth_dispatch), patch.object(
        __import__("app.middleware.tenant_resolution", fromlist=["TenantResolutionMiddleware"]).TenantResolutionMiddleware,
        "dispatch",
        patched_tenant_dispatch,
    )


def _allow_permission_overrides(app) -> None:
    """Override the RT_AGENT permission dependencies to always allow."""
    from app.api.deps import require_permission
    from app.core.resource_types import RT_AGENT

    app.dependency_overrides[require_permission(RT_AGENT, "read")] = lambda: {}
    app.dependency_overrides[require_permission(RT_AGENT, "update")] = lambda: {}


# ── Seed helpers ───────────────────────────────────────────────────────────────


async def _seed_tenants(db: AsyncSession) -> tuple[Tenant, Tenant]:
    suffix = uuid.uuid4().hex[:8]
    tenant_a = Tenant(name=f"Assistant A {suffix}", slug=f"assistant-a-{suffix}")
    tenant_b = Tenant(name=f"Assistant B {suffix}", slug=f"assistant-b-{suffix}")
    db.add_all([tenant_a, tenant_b])
    await db.flush()
    return tenant_a, tenant_b


async def _seed_model_config(
    db: AsyncSession, tenant_id: uuid.UUID, display_name: str, models: list[str]
) -> ModelConfig:
    config = ModelConfig(
        tenant_id=tenant_id,
        display_name=display_name,
        provider_type=ModelProvider.openai,
        enabled_models=models,
    )
    db.add(config)
    await db.flush()
    return config


async def _seed_assistant(
    db: AsyncSession, tenant_id: uuid.UUID, model_id: str | None
) -> AgentType:
    agent_type = AgentType(
        tenant_id=tenant_id,
        name=ASSISTANT_AGENT_TYPE_NAME,
        description="test assistant",
        system_instruction=ASSISTANT_SYSTEM_INSTRUCTION,
        input_type=AgentInputType.conversation,
        is_active=True,
        is_system=True,
        model_id=model_id,
    )
    db.add(agent_type)
    await db.flush()
    return agent_type


def _scoped_db_override(session: AsyncSession, tenant_id: uuid.UUID):
    # The ORM scope listeners are normally registered lazily by get_db; the
    # test harness must register them explicitly (idempotent).
    register_tenant_scope_listener()

    async def override():
        register_tenant_scope_listener()
        apply_tenant_scope(session, tenant_id)
        yield session
        await session.commit()

    return override


def _app_with_db(session: AsyncSession, tenant_id: uuid.UUID):
    app = create_app()
    app.dependency_overrides[get_db] = _scoped_db_override(session, tenant_id)
    _allow_permission_overrides(app)
    return app


async def _client_call(app, method: str, url: str, json_body: dict | None = None, tenant_id: uuid.UUID | None = None):
    auth_patch, tenant_patch = _bypass_auth(tenant_id)
    with auth_patch, tenant_patch:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, url, json=json_body)


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_assistant_model_options_and_selection(db_session) -> None:
    tenant_a, _ = await _seed_tenants(db_session)
    tenant_a_id = tenant_a.id
    await _seed_model_config(db_session, tenant_a.id, "OpenAI A", ["gpt-4o", "gpt-4o-mini"])
    await _seed_model_config(db_session, tenant_a.id, "Other A", ["claude-x"])
    await _seed_assistant(db_session, tenant_a.id, "gpt-4o-mini")
    await db_session.commit()

    app = _app_with_db(db_session, tenant_a.id)
    resp = await _client_call(app, "GET", "/api/v1/agents/model-configs/assistant-model", tenant_id=tenant_a.id)

    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_model_id"] == "gpt-4o-mini"
    assert [o["model_id"] for o in body["options"]] == ["gpt-4o", "gpt-4o-mini", "claude-x"]
    assert body["options"][0]["config_display_name"] == "OpenAI A"


@pytest.mark.asyncio
async def test_get_assistant_model_without_assistant_row_returns_null_selection(db_session) -> None:
    tenant_a, _ = await _seed_tenants(db_session)
    tenant_a_id = tenant_a.id
    await _seed_model_config(db_session, tenant_a.id, "OpenAI A", ["gpt-4o"])
    await db_session.commit()

    app = _app_with_db(db_session, tenant_a.id)
    resp = await _client_call(app, "GET", "/api/v1/agents/model-configs/assistant-model", tenant_id=tenant_a.id)

    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_model_id"] is None
    assert [o["model_id"] for o in body["options"]] == ["gpt-4o"]


@pytest.mark.asyncio
async def test_put_assistant_model_persists_onto_tenant_assistant_row(db_session) -> None:
    tenant_a, tenant_b = await _seed_tenants(db_session)
    tenant_a_id = tenant_a.id
    tenant_b_id = tenant_b.id
    await _seed_model_config(db_session, tenant_a.id, "OpenAI A", ["gpt-4o"])
    assistant_a = await _seed_assistant(db_session, tenant_a.id, None)
    assistant_a_id = assistant_a.id
    # Tenant B has its own config and assistant — must stay untouched.
    await _seed_model_config(db_session, tenant_b.id, "OpenAI B", ["b-model"])
    assistant_b = await _seed_assistant(db_session, tenant_b.id, "b-model")
    assistant_b_id = assistant_b.id
    await db_session.commit()

    app = _app_with_db(db_session, tenant_a.id)
    resp = await _client_call(
        app,
        "PUT",
        "/api/v1/agents/model-configs/assistant-model",
        {"model_id": "gpt-4o"},
        tenant_id=tenant_a.id,
    )

    assert resp.status_code == 200
    assert resp.json()["selected_model_id"] == "gpt-4o"

    await db_session.rollback()  # drop the request-scoped state
    await _clear_scope_and_reload(db_session)
    rows = (
        await db_session.execute(select(AgentType).where(AgentType.name == ASSISTANT_AGENT_TYPE_NAME))
    ).scalars().all()
    by_tenant = {r.tenant_id: r for r in rows}
    assert by_tenant[tenant_a_id].model_id == "gpt-4o"
    # Cross-tenant isolation: B's selection untouched.
    assert by_tenant[tenant_b_id].model_id == "b-model"
    assert by_tenant[tenant_a_id].id == assistant_a_id
    assert by_tenant[tenant_b_id].id == assistant_b_id


@pytest.mark.asyncio
async def test_put_assistant_model_creates_missing_assistant_row(db_session) -> None:
    tenant_a, _ = await _seed_tenants(db_session)
    tenant_a_id = tenant_a.id
    await _seed_model_config(db_session, tenant_a.id, "OpenAI A", ["gpt-4o"])
    await db_session.commit()

    app = _app_with_db(db_session, tenant_a.id)
    resp = await _client_call(
        app,
        "PUT",
        "/api/v1/agents/model-configs/assistant-model",
        {"model_id": "gpt-4o"},
        tenant_id=tenant_a.id,
    )

    assert resp.status_code == 200
    assert resp.json()["selected_model_id"] == "gpt-4o"

    await db_session.rollback()
    await _clear_scope_and_reload(db_session)
    assistant = (
        await db_session.execute(
            select(AgentType).where(
                AgentType.name == ASSISTANT_AGENT_TYPE_NAME,
                AgentType.tenant_id == tenant_a_id,
            )
        )
    ).scalar_one()
    assert assistant.model_id == "gpt-4o"
    assert assistant.is_system is True
    assert assistant.input_type == AgentInputType.conversation


@pytest.mark.asyncio
async def test_put_assistant_model_rejects_model_not_enabled_for_tenant(db_session) -> None:
    tenant_a, tenant_b = await _seed_tenants(db_session)
    tenant_a_id = tenant_a.id
    tenant_b_id = tenant_b.id
    await _seed_model_config(db_session, tenant_a.id, "OpenAI A", ["gpt-4o"])
    # "b-only-model" is enabled for tenant B only — tenant A must not select it.
    await _seed_model_config(db_session, tenant_b.id, "OpenAI B", ["b-only-model"])
    await _seed_assistant(db_session, tenant_a.id, None)
    await db_session.commit()

    app = _app_with_db(db_session, tenant_a.id)
    resp = await _client_call(
        app,
        "PUT",
        "/api/v1/agents/model-configs/assistant-model",
        {"model_id": "b-only-model"},
        tenant_id=tenant_a.id,
    )

    assert resp.status_code == 422
    assert "not enabled" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_assistant_selection_is_cross_tenant_isolated(db_session) -> None:
    """Tenant B's selection never affects tenant A (and vice versa)."""
    tenant_a, tenant_b = await _seed_tenants(db_session)
    tenant_a_id = tenant_a.id
    tenant_b_id = tenant_b.id
    await _seed_model_config(db_session, tenant_a.id, "OpenAI A", ["a-model"])
    await _seed_model_config(db_session, tenant_b.id, "OpenAI B", ["b-model"])
    await _seed_assistant(db_session, tenant_a.id, "a-model")
    await _seed_assistant(db_session, tenant_b.id, "b-model")
    await db_session.commit()

    # As tenant B: switch selection.
    app_b = _app_with_db(db_session, tenant_b.id)
    resp = await _client_call(
        app_b,
        "PUT",
        "/api/v1/agents/model-configs/assistant-model",
        {"model_id": "b-model"},
        tenant_id=tenant_b.id,
    )
    assert resp.status_code == 200
    # Tenant B's GET shows only B's config options.
    resp = await _client_call(app_b, "GET", "/api/v1/agents/model-configs/assistant-model", tenant_id=tenant_b.id)
    body = resp.json()
    assert body["selected_model_id"] == "b-model"
    assert [o["config_display_name"] for o in body["options"]] == ["OpenAI B"]

    await db_session.rollback()
    await _clear_scope_and_reload(db_session)
    rows = (
        await db_session.execute(select(AgentType).where(AgentType.name == ASSISTANT_AGENT_TYPE_NAME))
    ).scalars().all()
    by_tenant = {r.tenant_id: r for r in rows}
    assert by_tenant[tenant_a_id].model_id == "a-model"
    assert by_tenant[tenant_b_id].model_id == "b-model"
