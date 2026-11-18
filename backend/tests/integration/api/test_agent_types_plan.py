"""Integration tests for agent_plans table schema and plan-related API behaviour.

Tests (all using SQLite in-memory via the shared StaticPool conftest):

Schema verification:
- agent_plans table exists (Base.metadata.create_all equivalent to migration)
- Expected columns present: id, agent_type_id, plan_steps, topology, generation_status,
  generation_error, agent_config_hash, generated_at, created_at, updated_at
- generation_error column is nullable
- agent_type_id column is NOT nullable
- Unique constraint on agent_type_id (second insert for same type raises IntegrityError)
- CASCADE delete: deleting AgentType removes AgentPlan row
- AgentType with no plan can be deleted without FK error

Plan service behaviour:
- PlanGenerationService._upsert_plan creates a new row on first call
- PlanGenerationService._upsert_plan updates the existing row on second call (no duplicate)
- Failed status is persisted correctly (generation_error non-empty)

API endpoint responses:
- POST /api/v1/agents/types returns 201 and NEVER schedules plan generation
  (the response has no plan; no model time is spent)
- PUT /api/v1/agents/types/{type_id} returns 200 and never regenerates an
  existing plan (the last successful plan is untouched)
- plan field is absent from GET /api/v1/agents/types list
- POST /api/v1/agents/types/{type_id}/regenerate-plan is the ONLY authoring
  path: it is gated (conversational / unusable authoring model → structured
  412 with no plan write and no serving-version retirement), authors on the
  workspace authoring model, returns the refreshed plan, and a failed attempt
  records generation_status/generation_error while preserving the last
  successful plan.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func as sqlfunc, select
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models.agents import (
    AgentInputType,
    AgentOutputType,
    AgentPlan,
    AgentPlanStatus,
    AgentType,
)
from app.db.session import Base, get_db
from app.main import create_app
from app.services.agents.plan_generation_service import PlanGenerationService
from app.core.resource_types import RT_AGENT, RT_AGENT_MANAGEMENT


# ── Fixture: shared SQLite engine (reuses integration conftest's engine) ───────
# The module-level conftest.py in backend/tests/integration/ already provides
# `test_engine`, `db_session`, and `async_client` fixtures using StaticPool.
# We reuse those fixtures here.


# ── Schema Verification ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_plans_table_exists(db_session: AsyncSession):
    """agent_plans table must exist (migration applied via Base.metadata.create_all)."""
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_plans'")
    )
    row = result.fetchone()
    assert row is not None, "agent_plans table is missing — migration not applied"


@pytest.mark.asyncio
async def test_agent_plans_expected_columns_present(db_session: AsyncSession):
    """All expected columns must exist in agent_plans."""
    result = await db_session.execute(text("PRAGMA table_info(agent_plans)"))
    columns = {row[1] for row in result.fetchall()}  # row[1] is column name

    required = {
        "id",
        "agent_type_id",
        "plan_steps",
        "topology",
        "generation_status",
        "generation_error",
        "agent_config_hash",
        "generated_at",
        "created_at",
        "updated_at",
    }
    missing = required - columns
    assert not missing, f"Missing columns in agent_plans: {missing}"


@pytest.mark.asyncio
async def test_agent_plans_generation_error_is_nullable(db_session: AsyncSession):
    """generation_error column must be nullable."""
    result = await db_session.execute(text("PRAGMA table_info(agent_plans)"))
    rows = result.fetchall()
    gen_error_col = next((r for r in rows if r[1] == "generation_error"), None)
    assert gen_error_col is not None, "generation_error column not found"
    # In SQLite PRAGMA table_info: row[3] is "notnull" (1 = NOT NULL, 0 = nullable)
    assert gen_error_col[3] == 0, "generation_error should be nullable (notnull=0)"


@pytest.mark.asyncio
async def test_agent_plans_agent_type_id_is_not_nullable(db_session: AsyncSession):
    """agent_type_id column must be NOT NULL."""
    result = await db_session.execute(text("PRAGMA table_info(agent_plans)"))
    rows = result.fetchall()
    col = next((r for r in rows if r[1] == "agent_type_id"), None)
    assert col is not None, "agent_type_id column not found"
    assert col[3] == 1, "agent_type_id should be NOT NULL (notnull=1)"


# ── Unique constraint and CASCADE delete ───────────────────────────────────────


@pytest.mark.asyncio
async def test_unique_constraint_on_agent_type_id(db_session: AsyncSession):
    """Inserting two AgentPlan rows with the same agent_type_id raises IntegrityError."""
    from sqlalchemy.exc import IntegrityError

    # Create an AgentType to reference
    agent_type = AgentType(
        id=uuid.uuid4(),
        name=f"UniqueConstraintAgent-{uuid.uuid4().hex[:6]}",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.markdown,
        is_active=True,
    )
    db_session.add(agent_type)
    await db_session.flush()

    # First plan — should succeed
    plan_1 = AgentPlan(
        id=uuid.uuid4(),
        agent_type_id=agent_type.id,
        generation_status=AgentPlanStatus.success,
        generated_at=datetime.now(timezone.utc),
    )
    db_session.add(plan_1)
    await db_session.flush()

    # Second plan for same agent_type_id — must raise unique violation
    plan_2 = AgentPlan(
        id=uuid.uuid4(),
        agent_type_id=agent_type.id,  # same FK — violates unique constraint
        generation_status=AgentPlanStatus.failed,
        generated_at=datetime.now(timezone.utc),
    )
    db_session.add(plan_2)

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_cascade_delete_removes_agent_plan(db_session: AsyncSession):
    """Deleting an AgentType also deletes its AgentPlan (CASCADE)."""
    agent_type = AgentType(
        id=uuid.uuid4(),
        name=f"CascadeAgent-{uuid.uuid4().hex[:6]}",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.markdown,
        is_active=True,
    )
    db_session.add(agent_type)
    await db_session.flush()

    plan = AgentPlan(
        id=uuid.uuid4(),
        agent_type_id=agent_type.id,
        generation_status=AgentPlanStatus.success,
        plan_steps=[{"order": 1, "type": "tool_call", "name": "Step", "description": None}],
        generated_at=datetime.now(timezone.utc),
    )
    db_session.add(plan)
    await db_session.flush()

    plan_id = plan.id

    # Enable FK enforcement in SQLite for this connection
    await db_session.execute(text("PRAGMA foreign_keys = ON"))

    # Delete the agent type — plan should cascade
    await db_session.delete(agent_type)
    await db_session.flush()

    # Verify the plan is gone
    result = await db_session.execute(
        text("SELECT id FROM agent_plans WHERE id = :plan_id"),
        {"plan_id": str(plan_id)},
    )
    row = result.fetchone()
    # SQLite CASCADE should have removed the plan row
    # (note: SQLite cascade requires foreign_keys pragma ON per connection)
    assert row is None, f"AgentPlan row {plan_id} was not deleted when AgentType was deleted"


@pytest.mark.asyncio
async def test_delete_agent_type_with_no_plan_succeeds(db_session: AsyncSession):
    """Deleting an AgentType that has no associated AgentPlan succeeds cleanly."""
    agent_type = AgentType(
        id=uuid.uuid4(),
        name=f"NoPlanAgent-{uuid.uuid4().hex[:6]}",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.markdown,
        is_active=True,
    )
    db_session.add(agent_type)
    await db_session.flush()

    # Delete without ever creating a plan
    await db_session.delete(agent_type)
    await db_session.flush()  # Must not raise any FK violation


# ── PlanGenerationService upsert behaviour ────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_plan_creates_row_on_first_call(db_session: AsyncSession):
    """_upsert_plan creates a new AgentPlan row when none exists."""
    service = PlanGenerationService()
    agent_type_id = uuid.uuid4()

    # Create owning agent type
    at = AgentType(
        id=agent_type_id,
        name=f"UpsertCreateAgent-{uuid.uuid4().hex[:6]}",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.markdown,
        is_active=True,
    )
    db_session.add(at)
    await db_session.flush()

    plan = await service._upsert_plan(
        agent_type_id=agent_type_id,
        plan_steps=[{"order": 1, "type": "tool_call", "name": "S", "description": None}],
        topology={"nodes": [], "edges": []},
        status=AgentPlanStatus.success,
        error=None,
        config_hash="hash1",
        db=db_session,
    )
    await db_session.flush()

    assert plan.id is not None
    assert plan.generation_status == AgentPlanStatus.success
    assert plan.agent_config_hash == "hash1"

    # Verify single row in DB using ORM (avoids SQLite UUID storage format issues)
    count_result = await db_session.execute(
        select(sqlfunc.count()).select_from(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
    )
    count = count_result.scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_upsert_plan_updates_row_on_second_call(db_session: AsyncSession):
    """_upsert_plan updates existing row on second call — does NOT create a duplicate."""
    service = PlanGenerationService()
    agent_type_id = uuid.uuid4()

    at = AgentType(
        id=agent_type_id,
        name=f"UpsertUpdateAgent-{uuid.uuid4().hex[:6]}",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.markdown,
        is_active=True,
    )
    db_session.add(at)
    await db_session.flush()

    # First upsert
    plan_v1 = await service._upsert_plan(
        agent_type_id=agent_type_id,
        plan_steps=[],
        topology={"nodes": [], "edges": []},
        status=AgentPlanStatus.failed,
        error="LLM timeout",
        config_hash="hash_v1",
        db=db_session,
    )
    await db_session.flush()

    # Second upsert — should update, not insert
    plan_v2 = await service._upsert_plan(
        agent_type_id=agent_type_id,
        plan_steps=[{"order": 1, "type": "tool_call", "name": "Updated Step", "description": None}],
        topology={"nodes": [{"id": "role:x", "type": "role", "label": "Role", "meta": None}], "edges": []},
        status=AgentPlanStatus.success,
        error=None,
        config_hash="hash_v2",
        db=db_session,
    )
    await db_session.flush()

    # Same plan ID — same row updated
    assert plan_v1.id == plan_v2.id

    # Verify only ONE row in DB using ORM (avoids SQLite UUID storage format issues)
    count_result = await db_session.execute(
        select(sqlfunc.count()).select_from(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
    )
    count = count_result.scalar()
    assert count == 1, f"Expected 1 plan row after upsert, found {count}"

    # Status and hash must reflect second call
    assert plan_v2.generation_status == AgentPlanStatus.success
    assert plan_v2.agent_config_hash == "hash_v2"


# ── API endpoint tests ─────────────────────────────────────────────────────────

# We override require_permission and generate_plan to avoid auth + LLM dependencies.

def _mock_plan_response(agent_type_id: uuid.UUID, status: AgentPlanStatus = AgentPlanStatus.success) -> AgentPlan:
    """Create a mock AgentPlan for use in API test patches."""
    plan = AgentPlan(
        id=uuid.uuid4(),
        agent_type_id=agent_type_id,
        plan_steps=[{"order": 1, "type": "tool_call", "name": "Test Step", "description": "desc"}] if status == AgentPlanStatus.success else None,
        topology={"nodes": [{"id": "role:x", "type": "role", "label": "R", "meta": None}], "edges": []} if status == AgentPlanStatus.success else None,
        generation_status=status,
        generation_error="LLM error" if status == AgentPlanStatus.failed else None,
        agent_config_hash="abc123",
        generated_at=datetime.now(timezone.utc),
    )
    return plan


@pytest_asyncio.fixture
async def authed_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client with auth middleware bypassed and plan generation mocked out."""
    from app.api.deps import require_permission

    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def no_op_permission() -> dict:
        return {"sub": "test-user", "roles": ["admin"]}

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    # Override all require_permission variants (read, create, update, delete)
    for action in ("read", "create", "update", "delete", "execute"):
        dep = require_permission(RT_AGENT_MANAGEMENT, action)
        app.dependency_overrides[dep] = no_op_permission
        dep = require_permission(RT_AGENT, action)
        app.dependency_overrides[dep] = no_op_permission

    # Mock OIDC auth middleware to bypass JWT validation (middleware runs before dep overrides).
    # The middleware delegates to the module-level validate_raw_token pipeline.
    import app.middleware.auth as auth_middleware

    with patch.object(
        auth_middleware,
        "validate_raw_token",
        new=AsyncMock(return_value=({"sub": "test-user", "roles": ["admin"]}, False)),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer fake-test-token"},
        ) as client:
            yield client


@pytest.mark.asyncio
async def test_list_agent_types_does_not_include_plan_field(authed_client: AsyncClient):
    """GET /api/v1/agents/types (list) does not include plan in each item."""
    # Create an agent type first so the list is non-empty
    mock_plan = _mock_plan_response(uuid.uuid4(), AgentPlanStatus.success)

    async def mock_generate_plan(self, agent_type, db) -> AgentPlan:
        return mock_plan

    with patch.object(PlanGenerationService, "generate_plan", mock_generate_plan):
        await authed_client.post(
            "/api/v1/agents/types",
            json={
                "name": f"ListPlanCheckAgent-{uuid.uuid4().hex[:6]}",
                "input_type": "typed",
                "output_type": "markdown",
                "is_active": True,
            },
        )

    list_resp = await authed_client.get("/api/v1/agents/types")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert isinstance(items, list)
    # All list items must have plan=null (relationship not eagerly loaded for list)
    for item in items:
        # Plan field may be absent or null in list responses
        plan_val = item.get("plan", None)
        assert plan_val is None, f"List endpoint should not return plan data, got: {plan_val}"


# ── Explicit-only generation + gated regenerate-plan ──────────────────────────
#
# Plan authoring is EXPLICIT ONLY (the workspace authoring model authors the
# plan, never the agent runtime model) and both create/update must never spend
# model time. The regenerate endpoint checks its preconditions BEFORE any
# side effect (no plan write, no serving-version retirement).

AUTHORING_MODEL_ID = "plan-authoring-model"
STALE_MODEL_ID = "plan-removed-model"
_CONFIG_PREFIX = "plan-authoring-"


def _api_session_factory(test_engine):
    return async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )


async def _root_tenant_id(test_engine) -> uuid.UUID:
    from app.services.tenancy.root_tenant import get_root_tenant_id

    async with _api_session_factory(test_engine)() as session:
        tenant_id = await get_root_tenant_id(session)
    assert tenant_id is not None
    return tenant_id


async def _clear_authoring_model(test_engine) -> None:
    from sqlalchemy import delete

    from app.db.models.agents import ModelConfig
    from app.db.models.tenant_setting import TenantSetting
    from app.services.agents.workflow_generation_settings import (
        WORKFLOW_GENERATION_MODEL_KEY,
    )

    async with _api_session_factory(test_engine)() as session:
        await session.execute(
            delete(TenantSetting).where(
                TenantSetting.key == WORKFLOW_GENERATION_MODEL_KEY
            )
        )
        await session.execute(
            delete(ModelConfig).where(
                ModelConfig.display_name.like(f"{_CONFIG_PREFIX}%")
            )
        )
        await session.commit()


async def _configure_authoring_model(test_engine) -> None:
    from app.db.models.agents import ModelConfig, ModelProvider
    from app.services.agents.workflow_generation_settings import (
        WORKFLOW_GENERATION_MODEL_KEY,
    )
    from app.services.tenancy.tenant_settings_service import set_value

    root_id = await _root_tenant_id(test_engine)
    async with _api_session_factory(test_engine)() as session:
        session.add(
            ModelConfig(
                id=uuid.uuid4(),
                tenant_id=root_id,
                display_name=f"{_CONFIG_PREFIX}{AUTHORING_MODEL_ID}",
                provider_type=ModelProvider.openai,
                api_base_url="http://localhost:9999/v1",
                enabled_models=[AUTHORING_MODEL_ID],
            )
        )
        await session.flush()
        await set_value(
            session, root_id, WORKFLOW_GENERATION_MODEL_KEY, AUTHORING_MODEL_ID
        )
        await session.commit()


async def _select_stale_authoring_model(test_engine) -> None:
    from app.services.agents.workflow_generation_settings import (
        WORKFLOW_GENERATION_MODEL_KEY,
    )
    from app.services.tenancy.tenant_settings_service import set_value

    root_id = await _root_tenant_id(test_engine)
    async with _api_session_factory(test_engine)() as session:
        await set_value(session, root_id, WORKFLOW_GENERATION_MODEL_KEY, STALE_MODEL_ID)
        await session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _isolated_authoring_model(test_engine):
    """Each test starts and ends with NO workspace authoring model."""
    await _clear_authoring_model(test_engine)
    yield
    await _clear_authoring_model(test_engine)


async def _seed_agent_type(
    test_engine,
    *,
    input_type: AgentInputType = AgentInputType.typed,
    plan_status: AgentPlanStatus | None = None,
) -> uuid.UUID:
    """Create an agent type (+ one skill binding) directly in the DB.

    The binding satisfies the update endpoint's "at least one SOP or Skill"
    contract without going through role-permission wiring.
    """
    from app.db.models.agents import AgentTypeSkillBinding
    from app.db.models.skills import Skill

    agent_type_id = uuid.uuid4()
    async with _api_session_factory(test_engine)() as session:
        skill = Skill(
            id=uuid.uuid4(), name=f"plan-skill-{uuid.uuid4().hex[:8]}"
        )
        session.add(skill)
        session.add(
            AgentType(
                id=agent_type_id,
                name=f"plan-agent-{agent_type_id.hex[:8]}",
                input_type=input_type,
                output_type=(
                    AgentOutputType.auto
                    if input_type == AgentInputType.conversation
                    else AgentOutputType.markdown
                ),
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            AgentTypeSkillBinding(
                id=uuid.uuid4(),
                agent_type_id=agent_type_id,
                skill_id=skill.id,
                order=1,
            )
        )
        if plan_status is not None:
            session.add(
                AgentPlan(
                    id=uuid.uuid4(),
                    agent_type_id=agent_type_id,
                    plan_steps=[
                        {
                            "order": 1,
                            "type": "tool_call",
                            "name": "Previous Step",
                            "description": "kept",
                        }
                    ],
                    topology={
                        "nodes": [
                            {
                                "id": "role:old",
                                "type": "role",
                                "label": "Old Role",
                                "meta": None,
                            }
                        ],
                        "edges": [],
                    },
                    generation_status=plan_status,
                    generation_error=None,
                    agent_config_hash="previous-hash",
                    generated_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                )
            )
        await session.commit()
    return agent_type_id


async def _plan_row_count(test_engine, agent_type_id: uuid.UUID) -> int:
    async with _api_session_factory(test_engine)() as session:
        return int(
            (
                await session.execute(
                    select(sqlfunc.count())
                    .select_from(AgentPlan)
                    .where(AgentPlan.agent_type_id == agent_type_id)
                )
            ).scalar_one()
        )


def _fake_do_generate(steps: list[dict]):
    async def fake(self, agent_type, db, *, user_requirement=None):
        return steps, {"nodes": [], "edges": []}, False

    return fake


async def _seed_role_with_skill(test_engine) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a role that grants one skill (for API-level create payloads)."""
    from app.db.models.agents import AgentRole, AgentRoleSkill
    from app.db.models.skills import Skill

    role_id = uuid.uuid4()
    skill_id = uuid.uuid4()
    async with _api_session_factory(test_engine)() as session:
        session.add(
            AgentRole(id=role_id, name=f"plan-role-{role_id.hex[:8]}", description=None)
        )
        session.add(Skill(id=skill_id, name=f"plan-role-skill-{skill_id.hex[:8]}"))
        await session.flush()
        session.add(AgentRoleSkill(role_id=role_id, skill_id=skill_id))
        await session.commit()
    return role_id, skill_id


@pytest.mark.asyncio
async def test_create_agent_type_never_schedules_plan_generation(
    authed_client: AsyncClient, test_engine
):
    """POST /agents/types authors nothing — no model time, no plan row."""
    role_id, skill_id = await _seed_role_with_skill(test_engine)

    with patch.object(
        PlanGenerationService, "generate_plan", new=AsyncMock()
    ) as generate:
        resp = await authed_client.post(
            "/api/v1/agents/types",
            json={
                "name": f"no-autogen-{uuid.uuid4().hex[:8]}",
                "role_id": str(role_id),
                "skill_bindings": [{"skill_id": str(skill_id), "order": 1}],
                "input_type": "typed",
                "output_type": "markdown",
                "is_active": True,
            },
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["plan"] is None
    generate.assert_not_awaited()
    assert await _plan_row_count(test_engine, uuid.UUID(body["id"])) == 0


@pytest.mark.asyncio
async def test_no_plan_generation_hook_exists_in_agent_api():
    """The create/update background-generation helper is gone for good."""
    from app.api.v1 import agents as agents_module

    assert not hasattr(agents_module, "_run_plan_generation_bg")


@pytest.mark.asyncio
async def test_update_agent_type_never_regenerates_plan(
    authed_client: AsyncClient, test_engine
):
    """PUT leaves the last successful plan and its generated_at untouched."""
    agent_type_id = await _seed_agent_type(
        test_engine, plan_status=AgentPlanStatus.success
    )

    with patch.object(
        PlanGenerationService, "generate_plan", new=AsyncMock()
    ) as generate:
        resp = await authed_client.put(
            f"/api/v1/agents/types/{agent_type_id}",
            json={"name": f"renamed-{uuid.uuid4().hex[:8]}"},
        )

    assert resp.status_code == 200, resp.text
    generate.assert_not_awaited()

    # The stored plan is untouched (the update response does not eagerly load
    # the plan relationship, so assert the persisted state).
    async with _api_session_factory(test_engine)() as session:
        plan = (
            await session.execute(
                select(AgentPlan).where(AgentPlan.agent_type_id == agent_type_id)
            )
        ).scalar_one()
    assert plan.generation_status == AgentPlanStatus.success
    assert plan.plan_steps[0]["name"] == "Previous Step"
    assert plan.agent_config_hash == "previous-hash"
    assert plan.generation_error is None


@pytest.mark.asyncio
async def test_regenerate_plan_authors_and_returns_refreshed_plan(
    authed_client: AsyncClient, test_engine
):
    """The explicit request is the only authoring path: it retires serving
    versions, authors, and returns the refreshed plan."""
    from app.services.script_registry import ScriptRegistryService

    await _configure_authoring_model(test_engine)
    agent_type_id = await _seed_agent_type(test_engine)

    steps = [{"order": 1, "type": "tool_call", "name": "Fresh Step", "description": None}]

    with (
        patch.object(
            ScriptRegistryService, "retire_serving_versions", new=AsyncMock()
        ) as retire,
        patch.object(
            PlanGenerationService, "_do_generate", new=_fake_do_generate(steps)
        ),
    ):
        resp = await authed_client.post(
            f"/api/v1/agents/types/{agent_type_id}/regenerate-plan"
        )

    assert resp.status_code == 200, resp.text
    retire.assert_awaited_once()
    body = resp.json()
    assert body["plan"] is not None
    assert body["plan"]["generation_status"] == "success"
    assert body["plan"]["plan_steps"][0]["name"] == "Fresh Step"
    assert await _plan_row_count(test_engine, agent_type_id) == 1


@pytest.mark.asyncio
async def test_regenerate_plan_blocked_when_authoring_model_unset(
    authed_client: AsyncClient, test_engine
):
    """No authoring model → structured 412, no plan write, no retirement."""
    from app.services.script_registry import ScriptRegistryService

    agent_type_id = await _seed_agent_type(test_engine)

    with (
        patch.object(
            ScriptRegistryService, "retire_serving_versions", new=AsyncMock()
        ) as retire,
        patch.object(
            PlanGenerationService, "generate_plan", new=AsyncMock()
        ) as generate,
    ):
        resp = await authed_client.post(
            f"/api/v1/agents/types/{agent_type_id}/regenerate-plan"
        )

    assert resp.status_code == 412, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "plan_generation_unavailable"
    assert detail["reason_code"] == "authoring_model_not_configured"
    assert detail["reason"]
    retire.assert_not_awaited()
    generate.assert_not_awaited()
    assert await _plan_row_count(test_engine, agent_type_id) == 0


@pytest.mark.asyncio
async def test_regenerate_plan_blocked_when_authoring_model_not_enabled(
    authed_client: AsyncClient, test_engine
):
    from app.services.script_registry import ScriptRegistryService

    await _select_stale_authoring_model(test_engine)
    agent_type_id = await _seed_agent_type(test_engine)

    with (
        patch.object(
            ScriptRegistryService, "retire_serving_versions", new=AsyncMock()
        ) as retire,
        patch.object(
            PlanGenerationService, "generate_plan", new=AsyncMock()
        ) as generate,
    ):
        resp = await authed_client.post(
            f"/api/v1/agents/types/{agent_type_id}/regenerate-plan"
        )

    assert resp.status_code == 412, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "plan_generation_unavailable"
    assert detail["reason_code"] == "authoring_model_not_enabled"
    assert STALE_MODEL_ID in detail["reason"]
    retire.assert_not_awaited()
    generate.assert_not_awaited()
    assert await _plan_row_count(test_engine, agent_type_id) == 0


@pytest.mark.asyncio
async def test_regenerate_plan_blocked_for_conversational_agent(
    authed_client: AsyncClient, test_engine
):
    """Conversational agents have no plan — rejected before any side effect."""
    from app.services.script_registry import ScriptRegistryService

    await _configure_authoring_model(test_engine)
    agent_type_id = await _seed_agent_type(
        test_engine, input_type=AgentInputType.conversation
    )

    with (
        patch.object(
            ScriptRegistryService, "retire_serving_versions", new=AsyncMock()
        ) as retire,
        patch.object(
            PlanGenerationService, "generate_plan", new=AsyncMock()
        ) as generate,
    ):
        resp = await authed_client.post(
            f"/api/v1/agents/types/{agent_type_id}/regenerate-plan"
        )

    assert resp.status_code == 412, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "plan_generation_unavailable"
    assert detail["reason_code"] == "conversational_agent"
    retire.assert_not_awaited()
    generate.assert_not_awaited()
    assert await _plan_row_count(test_engine, agent_type_id) == 0


@pytest.mark.asyncio
async def test_regenerate_plan_failure_preserves_last_successful_plan(
    authed_client: AsyncClient, test_engine
):
    """A model failure is recorded (status/error) but never discards the last
    successful steps/topology/hash/generated_at."""
    from app.services.script_registry import ScriptRegistryService

    await _configure_authoring_model(test_engine)
    agent_type_id = await _seed_agent_type(
        test_engine, plan_status=AgentPlanStatus.success
    )

    async def exploding_do_generate(self, agent_type, db, *, user_requirement=None):
        raise RuntimeError("provider exploded")

    with (
        patch.object(
            ScriptRegistryService, "retire_serving_versions", new=AsyncMock()
        ),
        patch.object(
            PlanGenerationService, "_do_generate", new=exploding_do_generate
        ),
    ):
        resp = await authed_client.post(
            f"/api/v1/agents/types/{agent_type_id}/regenerate-plan"
        )

    assert resp.status_code == 200, resp.text
    plan = resp.json()["plan"]
    assert plan is not None
    assert plan["generation_status"] == "failed"
    assert "provider exploded" in (plan["generation_error"] or "")
    # The last successful authoring is still readable.
    assert plan["plan_steps"][0]["name"] == "Previous Step"
    assert plan["agent_config_hash"] == "previous-hash"
    assert plan["topology_nodes"][0]["id"] == "role:old"
    assert plan["generated_at"].startswith("2026-01-01")

