"""Optimizer-model resolver — explicit → authoring fallback, never substituted.

The conversational optimizer runs on a workspace-chosen model kept separate
from the agent's runtime model:

1. explicit ``optimizer_model_id`` resolvable + enabled + not disabled →
   ``source="optimizer"``;
2. unset → the existing plan-authoring model → ``source="authoring"``;
3. explicit but unusable → ``optimizer_model_not_enabled`` (stale id echoed,
   no fallback);
4. unset and the authoring model unusable → ``optimizer_model_not_configured``
   echoing the authoring reason.

Reads never rewrite the setting row; there is no ``AgentType.model_id``
substitution and no first-available fallback; everything is scoped to the
session tenant (the root tenant when multi-tenancy is off). Control-Center only.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
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
from app.services.agents.optimizer_model_settings import (
    OPTIMIZER_MODEL_KEY,
    REASON_OPTIMIZER_MODEL_NOT_CONFIGURED,
    REASON_OPTIMIZER_MODEL_NOT_ENABLED,
    SOURCE_AUTHORING,
    SOURCE_OPTIMIZER,
    OptimizerModelNotConfigured,
    get_optimizer_model_id,
    get_optimizer_model_state,
    require_optimizer_model,
    set_optimizer_model_id,
)
from app.services.agents.workflow_generation_settings import (
    WORKFLOW_GENERATION_MODEL_KEY,
)
from app.services.tenancy.root_tenant import invalidate_root_tenant_cache
from app.services.tenancy.tenant_settings_service import set_value

BACKEND_ROOT = Path(__file__).resolve().parents[3]

OPTIMIZER_MODEL = "optimizer-large"
AUTHORING_MODEL = "authoring-large"
OTHER_ENABLED_MODEL = "some-other-enabled-model"
STALE_MODEL = "removed-model"
DISABLED_MODEL = "disabled-provider-model"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    invalidate_root_tenant_cache()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )()
    yield session
    await session.rollback()
    await session.close()
    await engine.dispose()
    invalidate_root_tenant_cache()


@pytest_asyncio.fixture
async def tenants(db):
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
def _as_tenant(tenant: Tenant, db: AsyncSession | None = None):
    token = set_current_tenant_context(
        TenantContext(
            tenant_id=tenant.id,
            slug=tenant.slug,
            name=tenant.name,
            is_system_tenant=bool(tenant.is_system_tenant),
        )
    )
    if db is not None:
        from app.db.tenant_scoping import (
            apply_tenant_scope,
            register_tenant_scope_listener,
        )

        # The request path registers the listener from ``get_db``; tests drive
        # the service directly, so install it explicitly (idempotent).
        register_tenant_scope_listener()
        apply_tenant_scope(db, tenant.id)
    try:
        yield
    finally:
        reset_current_tenant_context(token)
        if db is not None:
            db.sync_session.info.pop("parthenon_tenant_scope", None)


async def _enable_model(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    model_id: str,
    *,
    is_disabled: bool = False,
) -> ModelConfig:
    config = ModelConfig(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        display_name=f"opt-{model_id}-{uuid.uuid4().hex[:6]}",
        provider_type=ModelProvider.openai,
        api_base_url="http://localhost:9999/v1",
        enabled_models=[model_id],
        is_disabled=is_disabled,
    )
    db.add(config)
    await db.flush()
    return config


async def _select_optimizer(db: AsyncSession, tenant_id: uuid.UUID, model_id: str) -> None:
    await set_value(db, tenant_id, OPTIMIZER_MODEL_KEY, model_id)
    await db.flush()


async def _select_authoring(db: AsyncSession, tenant_id: uuid.UUID, model_id: str) -> None:
    await set_value(db, tenant_id, WORKFLOW_GENERATION_MODEL_KEY, model_id)
    await db.flush()


async def _setting_row(db: AsyncSession, tenant_id: uuid.UUID, key: str):
    return (
        await db.execute(
            select(TenantSetting).where(
                TenantSetting.tenant_id == tenant_id, TenantSetting.key == key
            )
        )
    ).scalar_one_or_none()


# ── Explicit selection ──────────────────────────────────────────────────────


class TestExplicitSelection:
    @pytest.mark.asyncio
    async def test_enabled_explicit_selection_is_used(self, db, tenants):
        root, _ = tenants
        config = await _enable_model(db, root.id, OPTIMIZER_MODEL)
        # The authoring model also exists — it must NOT win.
        await _enable_model(db, root.id, AUTHORING_MODEL)
        await _select_optimizer(db, root.id, OPTIMIZER_MODEL)
        await _select_authoring(db, root.id, AUTHORING_MODEL)
        await db.commit()

        with _as_tenant(root):
            state = await get_optimizer_model_state(db)

        assert state.usable is True
        assert state.source == SOURCE_OPTIMIZER
        assert state.model_id == OPTIMIZER_MODEL
        assert state.effective_model_id == OPTIMIZER_MODEL
        assert state.model_config is not None
        assert state.model_config.id == config.id
        assert state.configured is True
        assert state.enabled is True
        assert state.reason_code is None
        assert state.reason is None

    @pytest.mark.asyncio
    async def test_explicit_selection_wins_over_authoring(self, db, tenants):
        root, _ = tenants
        await _enable_model(db, root.id, OPTIMIZER_MODEL)
        await _enable_model(db, root.id, AUTHORING_MODEL)
        await _select_optimizer(db, root.id, OPTIMIZER_MODEL)
        await _select_authoring(db, root.id, AUTHORING_MODEL)
        await db.commit()

        with _as_tenant(root):
            state = await get_optimizer_model_state(db)

        assert state.effective_model_id == OPTIMIZER_MODEL
        assert state.source == SOURCE_OPTIMIZER


# ── Unset → authoring fallback ──────────────────────────────────────────────


class TestAuthoringFallback:
    @pytest.mark.asyncio
    async def test_unset_inherits_the_authoring_model(self, db, tenants):
        root, _ = tenants
        authoring_config = await _enable_model(db, root.id, AUTHORING_MODEL)
        await _select_authoring(db, root.id, AUTHORING_MODEL)
        await db.commit()

        with _as_tenant(root):
            state = await get_optimizer_model_state(db)

        assert state.usable is True
        assert state.source == SOURCE_AUTHORING
        assert state.model_id is None  # nothing selected — raw value is unset
        assert state.effective_model_id == AUTHORING_MODEL
        assert state.model_config is not None
        assert state.model_config.id == authoring_config.id
        assert state.configured is False

    @pytest.mark.asyncio
    async def test_unset_and_no_authoring_model_is_not_configured(
        self, db, tenants
    ):
        root, _ = tenants
        # Another enabled model exists but is never chosen implicitly.
        await _enable_model(db, root.id, OTHER_ENABLED_MODEL)
        await db.commit()

        with _as_tenant(root):
            state = await get_optimizer_model_state(db)

        assert state.usable is False
        assert state.source is None
        assert state.effective_model_id is None
        assert state.model_config is None
        assert state.reason_code == REASON_OPTIMIZER_MODEL_NOT_CONFIGURED
        assert state.reason
        assert "System Config" in state.reason

    @pytest.mark.asyncio
    async def test_unset_authoring_unusable_echoes_the_authoring_reason(
        self, db, tenants
    ):
        root, _ = tenants
        # Authoring selects a model that is not in the catalogue.
        await _enable_model(db, root.id, OTHER_ENABLED_MODEL)
        await _select_authoring(db, root.id, STALE_MODEL)
        await db.commit()

        with _as_tenant(root):
            state = await get_optimizer_model_state(db)

        assert state.usable is False
        assert state.reason_code == REASON_OPTIMIZER_MODEL_NOT_CONFIGURED
        # Echoes the authoring reason (which names the stale id).
        assert STALE_MODEL in (state.reason or "")


# ── Explicit but unusable → no fallback ─────────────────────────────────────


class TestExplicitUnusable:
    @pytest.mark.asyncio
    async def test_stale_explicit_selection_is_not_enabled(self, db, tenants):
        root, _ = tenants
        # A usable authoring model exists — it must NOT replace the selection.
        await _enable_model(db, root.id, AUTHORING_MODEL)
        await _select_authoring(db, root.id, AUTHORING_MODEL)
        await _select_optimizer(db, root.id, STALE_MODEL)
        await db.commit()

        with _as_tenant(root):
            state = await get_optimizer_model_state(db)

        assert state.usable is False
        assert state.source == SOURCE_OPTIMIZER
        # The stale id stays visible so the UI can ask for a re-select.
        assert state.model_id == STALE_MODEL
        assert state.effective_model_id is None
        assert state.configured is True
        assert state.enabled is False
        assert state.reason_code == REASON_OPTIMIZER_MODEL_NOT_ENABLED
        assert STALE_MODEL in (state.reason or "")

    @pytest.mark.asyncio
    async def test_disabled_provider_config_is_not_usable(self, db, tenants):
        root, _ = tenants
        await _enable_model(db, root.id, DISABLED_MODEL, is_disabled=True)
        await _select_optimizer(db, root.id, DISABLED_MODEL)
        await db.commit()

        with _as_tenant(root):
            state = await get_optimizer_model_state(db)

        assert state.usable is False
        assert state.enabled is False
        assert state.model_config is None
        assert state.reason_code == REASON_OPTIMIZER_MODEL_NOT_ENABLED
        assert state.model_id == DISABLED_MODEL

    @pytest.mark.asyncio
    async def test_stale_selection_never_falls_back_to_another_enabled_model(
        self, db, tenants
    ):
        root, _ = tenants
        await _enable_model(db, root.id, OTHER_ENABLED_MODEL)
        await _select_optimizer(db, root.id, STALE_MODEL)
        await db.commit()

        with _as_tenant(root):
            state = await get_optimizer_model_state(db)

        assert state.usable is False
        assert state.effective_model_id is None


# ── No substitution and no rewriting ───────────────────────────────────────


class TestNoSubstitutionNoRewrite:
    @pytest.mark.asyncio
    async def test_agent_runtime_model_is_never_substituted(self, db, tenants):
        root, _ = tenants
        from app.db.models.agents import AgentInputType, AgentOutputType, AgentType

        db.add(
            AgentType(
                id=uuid.uuid4(),
                tenant_id=root.id,
                name="optimizer-agent-model-only",
                model_id=OTHER_ENABLED_MODEL,
                input_type=AgentInputType.typed,
                output_type=AgentOutputType.markdown,
                is_active=True,
            )
        )
        await _enable_model(db, root.id, OTHER_ENABLED_MODEL)
        await db.commit()

        with _as_tenant(root):
            state = await get_optimizer_model_state(db)

        assert state.usable is False
        assert state.effective_model_id is None
        assert state.reason_code == REASON_OPTIMIZER_MODEL_NOT_CONFIGURED

    @pytest.mark.asyncio
    async def test_read_never_creates_or_rewrites_the_setting_row(
        self, db, tenants
    ):
        root, _ = tenants
        await _enable_model(db, root.id, AUTHORING_MODEL)
        await _select_authoring(db, root.id, AUTHORING_MODEL)
        await db.commit()

        with _as_tenant(root):
            await get_optimizer_model_state(db)

        assert await _setting_row(db, root.id, OPTIMIZER_MODEL_KEY) is None

        # A stale selection stays exactly as stored after many reads.
        await _select_optimizer(db, root.id, STALE_MODEL)
        await db.commit()
        with _as_tenant(root):
            for _ in range(3):
                state = await get_optimizer_model_state(db)
        assert state.model_id == STALE_MODEL
        row = await _setting_row(db, root.id, OPTIMIZER_MODEL_KEY)
        assert row is not None and row.value == STALE_MODEL

    @pytest.mark.asyncio
    async def test_get_optimizer_model_id_normalises_blank_to_none(
        self, db, tenants
    ):
        root, _ = tenants
        await _select_optimizer(db, root.id, "   ")
        await db.commit()

        with _as_tenant(root):
            assert await get_optimizer_model_id(db) is None

    @pytest.mark.asyncio
    async def test_set_and_clear_round_trip(self, db, tenants):
        root, _ = tenants
        await _enable_model(db, root.id, AUTHORING_MODEL)
        await _select_authoring(db, root.id, AUTHORING_MODEL)
        await db.commit()

        with _as_tenant(root):
            await set_optimizer_model_id(db, OPTIMIZER_MODEL)
            state = await get_optimizer_model_state(db)
            assert state.model_id == OPTIMIZER_MODEL

            await set_optimizer_model_id(db, None)
            state = await get_optimizer_model_state(db)
            assert state.model_id is None
            # Clearing restores the authoring fallback with no second value.
            assert state.source == SOURCE_AUTHORING
            assert state.effective_model_id == AUTHORING_MODEL


# ── Tenant scoping ──────────────────────────────────────────────────────────


class TestTenantScoping:
    @pytest.mark.asyncio
    async def test_only_the_session_tenants_setting_and_catalogue_are_consulted(
        self, db, tenants
    ):
        root, other = tenants
        # Identically-named models in two tenants: the configs differ.
        root_config = await _enable_model(db, root.id, OPTIMIZER_MODEL)
        await _enable_model(db, other.id, OPTIMIZER_MODEL)
        await _select_optimizer(db, root.id, OPTIMIZER_MODEL)
        await _select_optimizer(db, other.id, STALE_MODEL)
        await db.commit()

        with _as_tenant(root):
            root_state = await get_optimizer_model_state(db)
        with _as_tenant(other):
            other_state = await get_optimizer_model_state(db)

        assert root_state.usable is True
        assert root_state.source == SOURCE_OPTIMIZER
        assert root_state.model_config is not None
        assert root_state.model_config.id == root_config.id
        # Tenant B's stale selection is evaluated in tenant B only.
        assert other_state.usable is False
        assert other_state.reason_code == REASON_OPTIMIZER_MODEL_NOT_ENABLED

    @pytest.mark.asyncio
    async def test_cross_tenant_model_is_not_resolved(self, db, tenants):
        """A model enabled only in tenant B is unusable in tenant A.

        Resolution goes through the tenant-scoped ORM path, exactly like the
        request path (``get_db`` applies the scope when multi-tenancy is on).
        """
        root, other = tenants
        await _enable_model(db, other.id, OPTIMIZER_MODEL)
        await _select_optimizer(db, root.id, OPTIMIZER_MODEL)
        await db.commit()

        with _as_tenant(root, db):
            state = await get_optimizer_model_state(db)

        assert state.usable is False
        assert state.reason_code == REASON_OPTIMIZER_MODEL_NOT_ENABLED

    @pytest.mark.asyncio
    async def test_root_tenant_is_used_without_a_session_context(self, db, tenants):
        root, other = tenants
        await _enable_model(db, root.id, OPTIMIZER_MODEL)
        await _select_optimizer(db, root.id, OPTIMIZER_MODEL)
        await db.commit()

        # No bound tenant context (startup/background jobs) → root tenant.
        state = await get_optimizer_model_state(db)
        assert state.usable is True
        assert state.source == SOURCE_OPTIMIZER


# ── Never-raising state vs raising require_ ────────────────────────────────


class TestRequireOptimizerModel:
    @pytest.mark.asyncio
    async def test_require_returns_the_usable_model(self, db, tenants):
        root, _ = tenants
        config = await _enable_model(db, root.id, OPTIMIZER_MODEL)
        await _select_optimizer(db, root.id, OPTIMIZER_MODEL)
        await db.commit()

        with _as_tenant(root):
            optimizer = await require_optimizer_model(db)

        assert optimizer.model_id == OPTIMIZER_MODEL
        assert optimizer.model_config.id == config.id

    @pytest.mark.asyncio
    async def test_require_raises_with_the_documented_reason_code(
        self, db, tenants
    ):
        root, _ = tenants
        await _select_optimizer(db, root.id, STALE_MODEL)
        await db.commit()

        with _as_tenant(root):
            with pytest.raises(OptimizerModelNotConfigured) as exc_info:
                await require_optimizer_model(db)

        assert exc_info.value.reason_code == REASON_OPTIMIZER_MODEL_NOT_ENABLED
        assert exc_info.value.message

    @pytest.mark.asyncio
    async def test_state_never_raises_for_an_unusable_selection(
        self, db, tenants
    ):
        root, _ = tenants
        with _as_tenant(root):
            state = await get_optimizer_model_state(db)
        assert state.usable is False
        assert state.reason_code == REASON_OPTIMIZER_MODEL_NOT_CONFIGURED


# ── Import boundary: CC-only ────────────────────────────────────────────────


class TestImportBoundary:
    def test_agent_runtime_and_communication_hub_never_import_the_resolver(self):
        offenders: list[str] = []
        for service in ("agent_runtime", "communication_hub"):
            for path in (BACKEND_ROOT / "app" / service).rglob("*.py"):
                if "optimizer_model_settings" in path.read_text():
                    offenders.append(str(path.relative_to(BACKEND_ROOT)))
        assert offenders == []

    def test_module_is_importable_from_control_center(self):
        import importlib

        module = importlib.import_module(
            "app.services.agents.optimizer_model_settings"
        )
        assert module.OPTIMIZER_MODEL_KEY == "optimizer_model_id"
