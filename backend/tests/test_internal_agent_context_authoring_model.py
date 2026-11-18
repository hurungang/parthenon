"""Internal agent-context: authoring model override for command runs.

The optimization run executes on the workspace AUTHORING model (the same
tenant-level model that authored the plans), while every normal run keeps
executing on the agent type's own RUNTIME model. ``get_agent_context`` applies
the override when the job carries the ``__command`` marker and fails closed
(``412 authoring_model_unavailable``) when the authoring model is unusable —
never silently falling back to the agent model.

Covers:

- normal run → ``AgentType.model_id`` + the config that enables it,
- conversational prepare / turn resume (session present, no ``__command``) →
  agent model,
- any ``__command`` run (optimize-and-verify and other commands) → authoring
  ``model_id`` + resolved ``model_config_id``,
- missing / stale authoring model → 412 with the structured reason, no
  fallback,
- identifiers only (no credentials or tokens in the response).
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.tenant_context import (
    TenantContext,
    reset_current_tenant_context,
    set_current_tenant_context,
)
from app.db.models.agents import (
    AgentInputType,
    AgentJob,
    AgentOutputType,
    AgentType,
    ModelConfig,
    ModelProvider,
)
from app.db.models.tenant import Tenant, TenantStatus
from app.db.session import Base
from app.services.agents.command_prompts import OPTIMIZE_AND_VERIFY_SLUG
from app.services.agents.workflow_generation_settings import (
    REASON_AUTHORING_MODEL_NOT_CONFIGURED,
    REASON_AUTHORING_MODEL_NOT_ENABLED,
    WORKFLOW_GENERATION_MODEL_KEY,
)
from app.services.tenancy.tenant_settings_service import set_value

AGENT_RUNTIME_MODEL = "agent-runtime-model"
AUTHORING_MODEL = "authoring-large-model"
STALE_AUTHORING_MODEL = "authoring-removed-model"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def isolated_db() -> AsyncSession:
    """Fresh in-memory engine + root tenant per test."""
    from app.services.tenancy.root_tenant import invalidate_root_tenant_cache

    invalidate_root_tenant_cache()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )()
    session.add(
        Tenant(
            id=uuid.uuid4(),
            slug="ctx-workspace",
            name="Ctx Workspace",
            status=TenantStatus.active,
            is_system_tenant=True,
        )
    )
    await session.commit()
    yield session
    await session.rollback()
    await session.close()
    await engine.dispose()
    invalidate_root_tenant_cache()


@contextmanager
def _as_tenant(tenant: Tenant):
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


async def _tenant(db: AsyncSession) -> Tenant:
    from sqlalchemy import select

    tenant = (
        await db.execute(select(Tenant).where(Tenant.slug == "ctx-workspace"))
    ).scalar_one()
    return tenant


async def _enable_model(
    db: AsyncSession, tenant_id: uuid.UUID, model_id: str, *, display_name: str
) -> ModelConfig:
    config = ModelConfig(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        display_name=f"{display_name}-{uuid.uuid4().hex[:6]}",
        provider_type=ModelProvider.openai,
        api_base_url="http://localhost:9999/v1",
        # A credential blob this response must NEVER expose.
        encrypted_api_key="gAAAAAB-encrypted-secret-blob",
        enabled_models=[model_id],
    )
    db.add(config)
    await db.flush()
    return config


async def _agent_type(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    model_id: str | None = AGENT_RUNTIME_MODEL,
    input_type: AgentInputType = AgentInputType.typed,
) -> AgentType:
    agent_type = AgentType(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=f"ctx-agent-{uuid.uuid4().hex[:8]}",
        description="ctx",
        model_id=model_id,
        input_type=input_type,
        output_type=(
            AgentOutputType.auto
            if input_type == AgentInputType.conversation
            else AgentOutputType.markdown
        ),
        is_active=True,
    )
    db.add(agent_type)
    await db.flush()
    return agent_type


async def _job(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_type_id: uuid.UUID,
    *,
    command: str | None = None,
) -> uuid.UUID:
    input_data: dict = {"message": "run"}
    if command:
        input_data = {"__command": command, "__command_agent_type_id": str(agent_type_id)}
    job = AgentJob(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        agent_type_id=agent_type_id,
        input_data=input_data,
    )
    db.add(job)
    await db.flush()
    return job.id


# ── Normal runs keep the agent runtime model ────────────────────────────────


@pytest.mark.asyncio
async def test_normal_run_returns_agent_model_and_config(isolated_db):
    from app.api.v1.internal.agent_data import get_agent_context

    tenant = await _tenant(isolated_db)
    runtime_config = await _enable_model(
        isolated_db, tenant.id, AGENT_RUNTIME_MODEL, display_name="runtime"
    )
    # A different authoring model exists — a normal run must ignore it.
    await _enable_model(
        isolated_db, tenant.id, AUTHORING_MODEL, display_name="authoring"
    )
    await set_value(
        isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
    )
    agent_type = await _agent_type(isolated_db, tenant.id)
    session_id = await _job(isolated_db, tenant.id, agent_type.id)
    await isolated_db.commit()

    with _as_tenant(tenant):
        context = await get_agent_context(
            agent_type_id=agent_type.id, db=isolated_db, session_id=session_id
        )

    assert context.model_id == AGENT_RUNTIME_MODEL
    assert context.model_config_id == runtime_config.id


@pytest.mark.asyncio
async def test_normal_run_without_session_keeps_agent_model(isolated_db):
    from app.api.v1.internal.agent_data import get_agent_context

    tenant = await _tenant(isolated_db)
    runtime_config = await _enable_model(
        isolated_db, tenant.id, AGENT_RUNTIME_MODEL, display_name="runtime"
    )
    agent_type = await _agent_type(isolated_db, tenant.id)
    await isolated_db.commit()

    with _as_tenant(tenant):
        context = await get_agent_context(
            agent_type_id=agent_type.id, db=isolated_db
        )

    assert context.model_id == AGENT_RUNTIME_MODEL
    assert context.model_config_id == runtime_config.id


@pytest.mark.asyncio
async def test_conversational_turn_resume_keeps_agent_model(isolated_db):
    """A conversational session (prepare/resume) is NOT a command run — it
    must keep the agent's own runtime model even when a plan was requested."""
    from app.api.v1.internal.agent_data import get_agent_context

    tenant = await _tenant(isolated_db)
    runtime_config = await _enable_model(
        isolated_db, tenant.id, AGENT_RUNTIME_MODEL, display_name="runtime"
    )
    await _enable_model(
        isolated_db, tenant.id, AUTHORING_MODEL, display_name="authoring"
    )
    await set_value(
        isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
    )
    agent_type = await _agent_type(
        isolated_db, tenant.id, input_type=AgentInputType.conversation
    )
    session_id = await _job(isolated_db, tenant.id, agent_type.id)
    await isolated_db.commit()

    with _as_tenant(tenant):
        context = await get_agent_context(
            agent_type_id=agent_type.id, db=isolated_db, session_id=session_id
        )

    assert context.model_id == AGENT_RUNTIME_MODEL
    assert context.model_config_id == runtime_config.id


@pytest.mark.asyncio
async def test_normal_run_works_without_any_authoring_model(isolated_db):
    """The override is command-run-only: a normal run never needs the
    authoring model and never fails because it is unset."""
    from app.api.v1.internal.agent_data import get_agent_context

    tenant = await _tenant(isolated_db)
    await _enable_model(
        isolated_db, tenant.id, AGENT_RUNTIME_MODEL, display_name="runtime"
    )
    agent_type = await _agent_type(isolated_db, tenant.id)
    session_id = await _job(isolated_db, tenant.id, agent_type.id)
    await isolated_db.commit()

    with _as_tenant(tenant):
        context = await get_agent_context(
            agent_type_id=agent_type.id, db=isolated_db, session_id=session_id
        )

    assert context.model_id == AGENT_RUNTIME_MODEL


# ── Command runs use the authoring model ────────────────────────────────────


@pytest.mark.asyncio
async def test_command_run_returns_authoring_model_and_config(isolated_db):
    from app.api.v1.internal.agent_data import get_agent_context

    tenant = await _tenant(isolated_db)
    await _enable_model(
        isolated_db, tenant.id, AGENT_RUNTIME_MODEL, display_name="runtime"
    )
    authoring_config = await _enable_model(
        isolated_db, tenant.id, AUTHORING_MODEL, display_name="authoring"
    )
    await set_value(
        isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
    )
    agent_type = await _agent_type(
        isolated_db, tenant.id, input_type=AgentInputType.conversation
    )
    session_id = await _job(
        isolated_db, tenant.id, agent_type.id, command=OPTIMIZE_AND_VERIFY_SLUG
    )
    await isolated_db.commit()

    with _as_tenant(tenant):
        context = await get_agent_context(
            agent_type_id=agent_type.id, db=isolated_db, session_id=session_id
        )

    assert context.model_id == AUTHORING_MODEL
    assert context.model_config_id == authoring_config.id


@pytest.mark.asyncio
async def test_other_command_slug_also_uses_the_authoring_model(isolated_db):
    """The override keys off ``__command`` (any command), not one slug."""
    from app.api.v1.internal.agent_data import get_agent_context

    tenant = await _tenant(isolated_db)
    await _enable_model(
        isolated_db, tenant.id, AGENT_RUNTIME_MODEL, display_name="runtime"
    )
    authoring_config = await _enable_model(
        isolated_db, tenant.id, AUTHORING_MODEL, display_name="authoring"
    )
    await set_value(
        isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
    )
    agent_type = await _agent_type(
        isolated_db, tenant.id, input_type=AgentInputType.conversation
    )
    session_id = await _job(
        isolated_db, tenant.id, agent_type.id, command="some-other-command"
    )
    await isolated_db.commit()

    with _as_tenant(tenant):
        context = await get_agent_context(
            agent_type_id=agent_type.id, db=isolated_db, session_id=session_id
        )

    assert context.model_id == AUTHORING_MODEL
    assert context.model_config_id == authoring_config.id


# ── Fail-closed when the authoring model is unusable ───────────────────────


@pytest.mark.asyncio
async def test_command_run_without_authoring_model_fails_closed(isolated_db):
    from app.api.v1.internal.agent_data import get_agent_context

    tenant = await _tenant(isolated_db)
    await _enable_model(
        isolated_db, tenant.id, AGENT_RUNTIME_MODEL, display_name="runtime"
    )
    agent_type = await _agent_type(isolated_db, tenant.id)
    session_id = await _job(
        isolated_db, tenant.id, agent_type.id, command=OPTIMIZE_AND_VERIFY_SLUG
    )
    await isolated_db.commit()

    with _as_tenant(tenant):
        with pytest.raises(HTTPException) as excinfo:
            await get_agent_context(
                agent_type_id=agent_type.id, db=isolated_db, session_id=session_id
            )

    assert excinfo.value.status_code == 412
    detail = excinfo.value.detail
    assert detail["error"] == "authoring_model_unavailable"
    assert detail["reason_code"] == REASON_AUTHORING_MODEL_NOT_CONFIGURED
    assert detail["reason"]


@pytest.mark.asyncio
async def test_command_run_with_stale_authoring_model_fails_closed(isolated_db):
    """A model removed from the catalogue between trigger and execution must
    surface the structured reason — never a silent agent-model run."""
    from app.api.v1.internal.agent_data import get_agent_context

    tenant = await _tenant(isolated_db)
    await _enable_model(
        isolated_db, tenant.id, AGENT_RUNTIME_MODEL, display_name="runtime"
    )
    await set_value(
        isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, STALE_AUTHORING_MODEL
    )
    agent_type = await _agent_type(isolated_db, tenant.id)
    session_id = await _job(
        isolated_db, tenant.id, agent_type.id, command=OPTIMIZE_AND_VERIFY_SLUG
    )
    await isolated_db.commit()

    with _as_tenant(tenant):
        with pytest.raises(HTTPException) as excinfo:
            await get_agent_context(
                agent_type_id=agent_type.id, db=isolated_db, session_id=session_id
            )

    assert excinfo.value.status_code == 412
    detail = excinfo.value.detail
    assert detail["error"] == "authoring_model_unavailable"
    assert detail["reason_code"] == REASON_AUTHORING_MODEL_NOT_ENABLED
    assert STALE_AUTHORING_MODEL in detail["reason"]


# ── Identifiers only ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_response_carries_model_identifiers_only(isolated_db):
    from app.api.v1.internal.agent_data import get_agent_context

    tenant = await _tenant(isolated_db)
    await _enable_model(
        isolated_db, tenant.id, AGENT_RUNTIME_MODEL, display_name="runtime"
    )
    authoring_config = await _enable_model(
        isolated_db, tenant.id, AUTHORING_MODEL, display_name="authoring"
    )
    await set_value(
        isolated_db, tenant.id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL
    )
    agent_type = await _agent_type(
        isolated_db, tenant.id, input_type=AgentInputType.conversation
    )
    session_id = await _job(
        isolated_db, tenant.id, agent_type.id, command=OPTIMIZE_AND_VERIFY_SLUG
    )
    await isolated_db.commit()

    with _as_tenant(tenant):
        context = await get_agent_context(
            agent_type_id=agent_type.id, db=isolated_db, session_id=session_id
        )

    payload = context.model_dump(mode="json")
    serialized = repr(payload)
    # No credential material rides along with the model identifiers.
    assert "gAAAAAB-encrypted-secret-blob" not in serialized
    assert "api_key" not in serialized
    assert "encrypted_api_key" not in serialized
    assert "credential" not in serialized.lower()
    # The identifiers themselves are present and opaque.
    assert context.model_id == AUTHORING_MODEL
    assert context.model_config_id == authoring_config.id
