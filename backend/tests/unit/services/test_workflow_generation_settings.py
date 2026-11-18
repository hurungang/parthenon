"""Authoring-model resolver — tenant-scoped, no fallback.

The workspace's single authoring model (``TenantSetting`` key
``workflow_generation_model_id``) is the ONLY model that authors Skill/SOP
workflows, base implementation plans, and optimized plans.

Covers:

- ``get_authoring_model_state`` derivation: unset, blank, usable, and
  "no longer in the tenant catalogue" (distinct ``reason_code``s),
- the stale selection id is echoed and the stored setting is NEVER rewritten
  (derived at read time so the UI can ask for a re-select),
- no fallback: another enabled model / another tenant's model is never chosen,
- session-tenant scoping (the root tenant when multi-tenancy is off) with the
  ModelConfig catalogue constrained to that tenant,
- ``require_authoring_model`` raising the structured
  ``AuthoringModelNotConfigured`` with the same reason, vs the never-raising
  state variant used by gates.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.tenant_context import (
    TenantContext,
    reset_current_tenant_context,
    set_current_tenant_context,
)
from app.db.models.agents import ModelConfig, ModelProvider
from app.db.models.tenant import Tenant, TenantStatus
from app.db.models.tenant_setting import TenantSetting
from app.db.session import Base
from app.services.agents.workflow_generation_settings import (
    REASON_AUTHORING_MODEL_NOT_CONFIGURED,
    REASON_AUTHORING_MODEL_NOT_ENABLED,
    WORKFLOW_GENERATION_MODEL_KEY,
    AuthoringModelNotConfigured,
    get_authoring_model_state,
    require_authoring_model,
)
from app.services.tenancy.tenant_settings_service import get_value, set_value


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory engine per test (no cross-test pollution)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(engine):
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def tenants(db):
    """Root tenant (the default workspace) + a second workspace."""
    root = Tenant(
        name="Root",
        slug="root",
        status=TenantStatus.active,
        is_onboarded=True,
        is_system_tenant=True,
    )
    other = Tenant(
        name="Other",
        slug="other",
        status=TenantStatus.active,
        is_onboarded=True,
    )
    db.add_all([root, other])
    await db.commit()
    return root, other


@contextmanager
def _as_tenant(tenant: Tenant):
    """Bind the session tenant context for the block."""
    token = set_current_tenant_context(
        TenantContext(
            tenant_id=tenant.id,
            slug=tenant.slug,
            name=tenant.name,
            is_system_tenant=bool(tenant.is_system_tenant),
        )
    )
    try:
        yield
    finally:
        reset_current_tenant_context(token)


async def _enable_model(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    model_id: str,
    *,
    display_name: str | None = None,
) -> ModelConfig:
    """Create an ENABLED model config listing ``model_id`` in the catalogue."""
    config = ModelConfig(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        display_name=display_name or f"cfg-{model_id}-{uuid.uuid4().hex[:6]}",
        provider_type=ModelProvider.openai,
        api_base_url="http://localhost:9999/v1",
        enabled_models=[model_id],
    )
    db.add(config)
    await db.flush()
    return config


async def _select(db: AsyncSession, tenant_id: uuid.UUID, model_id: str | None) -> None:
    await set_value(db, tenant_id, WORKFLOW_GENERATION_MODEL_KEY, model_id)
    await db.flush()


# ── Derived state: unset / blank ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_provider_config_is_not_usable(db, tenants):
    """A selected model whose provider config is disabled is not usable.

    ``is_disabled`` can be set while the model id remains in
    ``enabled_models`` (e.g. a vendor-availability cascade). Authoring must
    treat it as "not enabled" and never attempt the call.
    """
    root, _ = tenants
    db.add(
        ModelConfig(
            id=uuid.uuid4(),
            tenant_id=root.id,
            display_name=f"cfg-disabled-{uuid.uuid4().hex[:6]}",
            provider_type=ModelProvider.openai,
            api_base_url="http://localhost:9999/v1",
            enabled_models=["disabled-model"],
            is_disabled=True,
        )
    )
    await db.flush()
    await _select(db, root.id, "disabled-model")
    await db.commit()

    with _as_tenant(root):
        state = await get_authoring_model_state(db)

    assert state.configured is True
    assert state.enabled is False
    assert state.usable is False
    assert state.model_config is None
    assert state.reason_code == REASON_AUTHORING_MODEL_NOT_ENABLED


@pytest.mark.asyncio
async def test_unset_selection_is_not_configured(db, tenants):
    root, _ = tenants
    with _as_tenant(root):
        state = await get_authoring_model_state(db)

    assert state.model_id is None
    assert state.configured is False
    assert state.enabled is False
    assert state.model_config is None
    assert state.usable is False
    assert state.reason_code == REASON_AUTHORING_MODEL_NOT_CONFIGURED
    assert state.reason
    assert "System Config" in state.reason


@pytest.mark.asyncio
async def test_blank_selection_is_treated_as_unset(db, tenants):
    root, _ = tenants
    await _select(db, root.id, "   ")
    await db.commit()

    with _as_tenant(root):
        state = await get_authoring_model_state(db)

    assert state.configured is False
    assert state.usable is False
    assert state.reason_code == REASON_AUTHORING_MODEL_NOT_CONFIGURED


# ── Derived state: usable ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_usable_selection_resolves_model_and_config(db, tenants):
    root, _ = tenants
    config = await _enable_model(db, root.id, "authoring-large")
    await _select(db, root.id, "authoring-large")
    await db.commit()

    with _as_tenant(root):
        state = await get_authoring_model_state(db)

    assert state.model_id == "authoring-large"
    assert state.configured is True
    assert state.enabled is True
    assert state.usable is True
    assert state.reason_code is None
    assert state.reason is None
    assert state.model_config is not None
    assert state.model_config.id == config.id


@pytest.mark.asyncio
async def test_changing_the_selection_changes_subsequent_resolution(db, tenants):
    """One setting per workspace: a save immediately governs later reads."""
    root, _ = tenants
    await _enable_model(db, root.id, "small-model")
    await _enable_model(db, root.id, "large-model")
    await _select(db, root.id, "small-model")
    await db.commit()

    with _as_tenant(root):
        assert (await get_authoring_model_state(db)).model_id == "small-model"

    await _select(db, root.id, "large-model")
    await db.commit()

    with _as_tenant(root):
        state = await get_authoring_model_state(db)
        assert state.model_id == "large-model"
        assert state.usable is True


# ── Derived state: no longer enabled (removed/disabled) ─────────────────────


@pytest.mark.asyncio
async def test_selection_not_in_catalogue_is_not_enabled_and_echoes_id(db, tenants):
    root, _ = tenants
    # A different enabled model exists — it must NOT be used as a fallback.
    await _enable_model(db, root.id, "available-model")
    await _select(db, root.id, "removed-model")
    await db.commit()

    with _as_tenant(root):
        state = await get_authoring_model_state(db)

    assert state.model_id == "removed-model"
    assert state.configured is True
    assert state.enabled is False
    assert state.usable is False
    assert state.model_config is None
    assert state.reason_code == REASON_AUTHORING_MODEL_NOT_ENABLED
    assert "removed-model" in (state.reason or "")
    assert "Re-select" in (state.reason or "")


@pytest.mark.asyncio
async def test_stale_selection_is_never_rewritten_by_a_read(db, tenants):
    """The stored setting stays as-is (derived at read time) so the UI can
    show the stale value as a disabled "no longer available" entry."""
    root, _ = tenants
    await _select(db, root.id, "removed-model")
    await db.commit()

    with _as_tenant(root):
        await get_authoring_model_state(db)
        await get_authoring_model_state(db)

    stored = await get_value(db, root.id, WORKFLOW_GENERATION_MODEL_KEY)
    assert stored == "removed-model"

    from sqlalchemy import func, select

    row_count = (
        await db.execute(
            select(func.count())
            .select_from(TenantSetting)
            .where(TenantSetting.tenant_id == root.id)
        )
    ).scalar_one()
    assert row_count == 1


@pytest.mark.asyncio
async def test_no_fallback_to_another_tenant_model(db, tenants):
    """A model enabled in a DIFFERENT workspace never satisfies this one.

    The resolver reads through the tenant-scoped session, so the other
    workspace's ModelConfig is invisible — the selection is "not enabled"
    rather than silently resolving via that config.
    """
    from app.db.tenant_scoping import apply_tenant_scope, register_tenant_scope_listener

    root, other = tenants
    await _enable_model(db, other.id, "other-tenant-model")
    await _select(db, root.id, "other-tenant-model")
    await db.commit()

    register_tenant_scope_listener()
    apply_tenant_scope(db, root.id)

    with _as_tenant(root):
        state = await get_authoring_model_state(db)

    assert state.configured is True
    assert state.enabled is False
    assert state.usable is False
    assert state.reason_code == REASON_AUTHORING_MODEL_NOT_ENABLED


# ── require_authoring_model ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_require_returns_model_id_and_config(db, tenants):
    root, _ = tenants
    config = await _enable_model(db, root.id, "authoring-large")
    await _select(db, root.id, "authoring-large")
    await db.commit()

    with _as_tenant(root):
        authoring = await require_authoring_model(db)

    assert authoring.model_id == "authoring-large"
    assert authoring.model_config.id == config.id


@pytest.mark.asyncio
async def test_require_raises_not_configured(db, tenants):
    root, _ = tenants
    with _as_tenant(root):
        with pytest.raises(AuthoringModelNotConfigured) as excinfo:
            await require_authoring_model(db)

    assert excinfo.value.reason_code == REASON_AUTHORING_MODEL_NOT_CONFIGURED
    assert "System Config" in excinfo.value.message


@pytest.mark.asyncio
async def test_require_raises_not_enabled_for_stale_selection(db, tenants):
    root, _ = tenants
    await _select(db, root.id, "removed-model")
    await db.commit()

    with _as_tenant(root):
        with pytest.raises(AuthoringModelNotConfigured) as excinfo:
            await require_authoring_model(db)

    assert excinfo.value.reason_code == REASON_AUTHORING_MODEL_NOT_ENABLED
    assert "removed-model" in excinfo.value.message


# ── Session-tenant scoping ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_tenant_context_resolves_the_root_tenant(db, tenants):
    """Multi-tenancy off (no session context) → the root tenant's setting."""
    root, other = tenants
    await _enable_model(db, root.id, "root-model")
    await _select(db, root.id, "root-model")
    # A different workspace has its own (different) selection.
    await _enable_model(db, other.id, "other-model")
    await _select(db, other.id, "other-model")
    await db.commit()

    state = await get_authoring_model_state(db)

    assert state.model_id == "root-model"
    assert state.usable is True


@pytest.mark.asyncio
async def test_catalogue_is_constrained_to_the_session_tenant(db, tenants):
    """With the tenant scope bound, only that tenant's model configs resolve.

    Tenant A selects a model that only exists in tenant B's catalogue — it is
    "not enabled" for A (no cross-workspace leakage and no fallback), while
    A's own enabled model resolves normally.
    """
    from app.db.tenant_scoping import apply_tenant_scope, register_tenant_scope_listener

    root, other = tenants
    a_config = await _enable_model(db, root.id, "tenant-a-model")
    await _enable_model(db, other.id, "tenant-b-model")
    await _select(db, root.id, "tenant-b-model")
    await db.commit()

    register_tenant_scope_listener()
    apply_tenant_scope(db, root.id)

    with _as_tenant(root):
        state = await get_authoring_model_state(db)

    assert state.configured is True
    assert state.enabled is False
    assert state.usable is False
    assert state.reason_code == REASON_AUTHORING_MODEL_NOT_ENABLED

    # A's own enabled model resolves (scope still bound).
    await _select(db, root.id, "tenant-a-model")
    await db.commit()

    with _as_tenant(root):
        state = await get_authoring_model_state(db)
        authoring = await require_authoring_model(db)

    assert state.usable is True
    assert state.model_config is not None
    assert state.model_config.id == a_config.id
    assert authoring.model_id == "tenant-a-model"


@pytest.mark.asyncio
async def test_reads_are_point_in_time_no_cross_tenant_switch(db, tenants):
    """A read for tenant B after tenant A's selection returns B's own state."""
    root, other = tenants
    await _enable_model(db, root.id, "root-model")
    await _select(db, root.id, "root-model")
    await db.commit()

    with _as_tenant(root):
        assert (await get_authoring_model_state(db)).model_id == "root-model"

    with _as_tenant(other):
        state = await get_authoring_model_state(db)
        assert state.model_id is None
        assert state.configured is False
        assert state.reason_code == REASON_AUTHORING_MODEL_NOT_CONFIGURED
