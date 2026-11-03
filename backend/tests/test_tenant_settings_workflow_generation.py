"""Tests for the tenant-scoped settings store and the DB-backed
workflow-generation model selection.

Covers:

- ``tenant_settings_service`` get/set round-trip and upsert semantics
- per-tenant isolation: tenant A's selection never leaks to tenant B
- ``get_workflow_generation_model_id`` resolves the session tenant context
  and falls back to the root tenant when no context is set
- legacy ``config/app.yaml`` adoption into the root tenant (idempotent,
  never overwrites an existing selection)
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.tenant_context import (  # noqa: E402
    TenantContext,
    reset_current_tenant_context,
    set_current_tenant_context,
)
from app.db.models.tenant import Tenant, TenantStatus  # noqa: E402
from app.db.models.tenant_setting import TenantSetting  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.services.agents.workflow_generation_settings import (  # noqa: E402
    WORKFLOW_GENERATION_MODEL_KEY,
    get_workflow_generation_model_id,
    set_workflow_generation_model_id,
)
from app.services.tenancy.tenant_settings_service import (  # noqa: E402
    get_value,
    set_value,
)


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
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def tenants(db):
    """Two tenants to prove isolation."""
    tenant_a = Tenant(name="A", slug="a", status=TenantStatus.active, is_onboarded=True)
    tenant_b = Tenant(name="B", slug="b", status=TenantStatus.active, is_onboarded=True)
    db.add_all([tenant_a, tenant_b])
    await db.flush()
    return tenant_a, tenant_b


@pytest.mark.asyncio
async def test_tenant_settings_roundtrip_and_upsert(db, tenants):
    tenant_a, _ = tenants
    assert await get_value(db, tenant_a.id, "k") is None

    await set_value(db, tenant_a.id, "k", {"model": "gpt-4o-mini"})
    assert await get_value(db, tenant_a.id, "k") == {"model": "gpt-4o-mini"}

    # Upsert: same row updated, not duplicated
    await set_value(db, tenant_a.id, "k", "m2")
    from sqlalchemy import select

    row_count = len(
        (
            await db.execute(
                select(TenantSetting).where(TenantSetting.tenant_id == tenant_a.id)
            )
        ).scalars().all()
    )
    assert row_count == 1
    assert await get_value(db, tenant_a.id, "k") == "m2"


@pytest.mark.asyncio
async def test_workflow_model_selection_is_tenant_isolated(db, tenants):
    tenant_a, tenant_b = tenants

    token = set_current_tenant_context(
        TenantContext(tenant_id=tenant_a.id, slug="a", name="A", is_system_tenant=False)
    )
    try:
        await set_workflow_generation_model_id(db, "gpt-4o-mini")
    finally:
        reset_current_tenant_context(token)

    # Tenant B sees nothing even though A has a selection.
    token_b = set_current_tenant_context(
        TenantContext(tenant_id=tenant_b.id, slug="b", name="B", is_system_tenant=False)
    )
    try:
        assert await get_workflow_generation_model_id(db) is None
        await set_workflow_generation_model_id(db, "claude-3-5-sonnet")
        assert await get_workflow_generation_model_id(db) == "claude-3-5-sonnet"
    finally:
        reset_current_tenant_context(token_b)

    # Tenant A's selection is untouched by B's write.
    token_a = set_current_tenant_context(
        TenantContext(tenant_id=tenant_a.id, slug="a", name="A", is_system_tenant=False)
    )
    try:
        assert await get_workflow_generation_model_id(db) == "gpt-4o-mini"
    finally:
        reset_current_tenant_context(token_a)


@pytest.mark.asyncio
async def test_unset_tenant_returns_none_and_blank_is_none(db, tenants):
    tenant_a, _ = tenants
    token = set_current_tenant_context(
        TenantContext(tenant_id=tenant_a.id, slug="a", name="A", is_system_tenant=False)
    )
    try:
        assert await get_workflow_generation_model_id(db) is None
        await set_workflow_generation_model_id(db, "   ")
        assert await get_workflow_generation_model_id(db) is None
    finally:
        reset_current_tenant_context(token)


@pytest.mark.asyncio
async def test_set_without_tenant_context_requires_root_tenant(db, tenants):
    tenant_a, _ = tenants
    # Make tenant A the root (system) tenant; no contextvar set → root fallback.
    tenant_a.is_system_tenant = True
    await db.flush()

    from app.services.tenancy import root_tenant

    root_tenant.invalidate_root_tenant_cache()
    try:
        await set_workflow_generation_model_id(db, "gpt-4o")
        assert await get_workflow_generation_model_id(db) == "gpt-4o"
        assert (
            await get_value(db, tenant_a.id, WORKFLOW_GENERATION_MODEL_KEY) == "gpt-4o"
        )
    finally:
        root_tenant.invalidate_root_tenant_cache()


@pytest.mark.asyncio
async def test_adopt_legacy_yaml_value_is_idempotent(db, tenants, monkeypatch, tmp_path):
    tenant_a, _ = tenants
    tenant_a.is_system_tenant = True
    await db.flush()

    import yaml

    from app.services.agents.workflow_generation_settings import (
        adopt_legacy_app_yaml_value,
    )
    from app.services.tenancy import root_tenant

    yaml_file = tmp_path / "app.yaml"
    yaml_file.write_text(yaml.safe_dump({"workflow_generation_model_id": "legacy-model"}))

    root_tenant.invalidate_root_tenant_cache()
    try:
        adopted = await adopt_legacy_app_yaml_value(
            db, yaml_path_resolver=lambda: str(yaml_file)
        )
        assert adopted == "legacy-model"
        assert await get_value(db, tenant_a.id, WORKFLOW_GENERATION_MODEL_KEY) == "legacy-model"

        # Idempotent: a second adoption never overwrites a newer selection.
        await set_value(db, tenant_a.id, WORKFLOW_GENERATION_MODEL_KEY, "newer-model")
        adopted = await adopt_legacy_app_yaml_value(
            db, yaml_path_resolver=lambda: str(yaml_file)
        )
        assert adopted is None
        assert await get_value(db, tenant_a.id, WORKFLOW_GENERATION_MODEL_KEY) == "newer-model"
    finally:
        root_tenant.invalidate_root_tenant_cache()


@pytest.mark.asyncio
async def test_adopt_skips_when_yaml_has_no_value(db, tenants, monkeypatch, tmp_path):
    tenant_a, _ = tenants
    tenant_a.is_system_tenant = True
    await db.flush()

    import yaml

    from app.services.agents.workflow_generation_settings import (
        adopt_legacy_app_yaml_value,
    )
    from app.services.tenancy import root_tenant

    yaml_file = tmp_path / "app.yaml"
    yaml_file.write_text(yaml.safe_dump({"other": 1}))

    root_tenant.invalidate_root_tenant_cache()
    try:
        adopted = await adopt_legacy_app_yaml_value(
            db, yaml_path_resolver=lambda: str(yaml_file)
        )
        assert adopted is None
        assert await get_value(db, tenant_a.id, WORKFLOW_GENERATION_MODEL_KEY) is None
    finally:
        root_tenant.invalidate_root_tenant_cache()
