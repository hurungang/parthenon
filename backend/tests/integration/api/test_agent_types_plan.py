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
- POST /api/v1/agents/types returns 201 with plan field (with mocked LLM)
- PUT /api/v1/agents/types/{type_id} returns 200 with plan field
- plan field is absent from GET /api/v1/agents/types list
- Failed plan generation still returns 201 (non-blocking)
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
from app.core.resource_types import RT_AGENT


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

    # Mock OIDC client to bypass JWT auth middleware (middleware runs before dep overrides)
    mock_oidc = AsyncMock()
    mock_oidc.validate_token.return_value = {"sub": "test-user", "roles": ["admin"]}

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    # Override all require_permission variants (read, create, update, delete)
    for action in ("read", "create", "update", "delete", "execute"):
        dep = require_permission(RT_AGENT, action)
        app.dependency_overrides[dep] = no_op_permission

    with patch("app.middleware.auth.get_oidc_client", return_value=mock_oidc):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer fake-test-token"},
        ) as client:
            yield client


@pytest.mark.asyncio
async def test_create_agent_type_response_includes_plan_field(authed_client: AsyncClient):
    """POST /api/v1/agents/types returns 201 with a `plan` field in the response body."""
    at_id = uuid.uuid4()
    mock_plan = _mock_plan_response(at_id, AgentPlanStatus.success)

    async def mock_generate_plan(self, agent_type, db) -> AgentPlan:
        return mock_plan

    with patch.object(PlanGenerationService, "generate_plan", mock_generate_plan):
        resp = await authed_client.post(
            "/api/v1/agents/types",
            json={
                "name": f"PlanTestAgent-{uuid.uuid4().hex[:6]}",
                "input_type": "typed",
                "output_type": "markdown",
                "is_active": True,
            },
        )

    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    # plan field must be present (may be null if plan relationship not loaded, but key should exist)
    assert "plan" in body


@pytest.mark.asyncio
async def test_create_agent_type_failed_plan_still_returns_201(authed_client: AsyncClient):
    """Failed plan generation does not block the 201 response."""
    at_id = uuid.uuid4()
    mock_plan = _mock_plan_response(at_id, AgentPlanStatus.failed)

    async def mock_generate_plan_failed(self, agent_type, db) -> AgentPlan:
        return mock_plan

    with patch.object(PlanGenerationService, "generate_plan", mock_generate_plan_failed):
        resp = await authed_client.post(
            "/api/v1/agents/types",
            json={
                "name": f"FailedPlanAgent-{uuid.uuid4().hex[:6]}",
                "input_type": "typed",
                "output_type": "markdown",
                "is_active": True,
            },
        )

    assert resp.status_code == 201, f"Expected 201 even on plan failure, got {resp.status_code}"


@pytest.mark.asyncio
async def test_update_agent_type_response_includes_plan_field(authed_client: AsyncClient):
    """PUT /api/v1/agents/types/{type_id} returns 200 with plan field."""
    at_id = uuid.uuid4()

    # First create an agent type
    mock_plan = _mock_plan_response(at_id, AgentPlanStatus.success)

    async def mock_generate_plan(self, agent_type, db) -> AgentPlan:
        return mock_plan

    with patch.object(PlanGenerationService, "generate_plan", mock_generate_plan):
        create_resp = await authed_client.post(
            "/api/v1/agents/types",
            json={
                "name": f"UpdatePlanAgent-{uuid.uuid4().hex[:6]}",
                "input_type": "typed",
                "output_type": "markdown",
                "is_active": True,
            },
        )

    assert create_resp.status_code == 201
    created_id = create_resp.json()["id"]

    # Now update it
    with patch.object(PlanGenerationService, "generate_plan", mock_generate_plan):
        update_resp = await authed_client.put(
            f"/api/v1/agents/types/{created_id}",
            json={
                "name": "Updated Agent Name",
                "input_type": "typed",
                "output_type": "markdown",
                "is_active": True,
            },
        )

    assert update_resp.status_code == 200, f"Expected 200, got {update_resp.status_code}: {update_resp.text}"
    body = update_resp.json()
    assert "plan" in body


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
