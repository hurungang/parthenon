"""Unit tests for PlanGenerationService.

Covers:
- _compute_config_hash: deterministic, changes when config changes
- _parse_plan_steps: happy path JSON parsing, fallback step on invalid input
- generate_plan happy path: mocked _resolve_graph + _invoke_llm → success plan
- generate_plan non-blocking failure: _invoke_llm exception caught, failed status
- generate_plan LLM timeout: caught and recorded, exception not propagated
- generate_plan upsert: first save creates row, second save updates (no duplicate)
- generate_plan no role: empty graph handled without crash
- _resolve_graph SOP filtering: by system instruction, default fallback, keep-all
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.agents import AgentPlanStatus, AgentType
from app.services.agents.plan_generation_service import PlanGenerationService


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_agent_type(
    type_id: uuid.UUID | None = None,
    role_id: uuid.UUID | None = None,
    primary_sop_id: uuid.UUID | None = None,
    system_instruction: str | None = None,
    model_id: str | None = None,
) -> MagicMock:
    at = MagicMock(spec=AgentType)
    at.id = type_id or uuid.uuid4()
    at.name = "Test Agent"
    at.description = None
    at.role_id = role_id
    at.primary_sop_id = primary_sop_id
    at.system_instruction = system_instruction
    at.model_id = model_id
    at.sop_bindings = []
    at.skill_bindings = []
    # Mock SQLAlchemy instance state (used by _compute_config_hash to detect unloaded relations)
    instance_state = MagicMock()
    instance_state.unloaded = set()
    at._sa_instance_state = instance_state
    return at


def _make_mock_plan(
    *,
    agent_type_id: uuid.UUID,
    status: AgentPlanStatus = AgentPlanStatus.success,
    plan_steps: list | None = None,
    topology: dict | None = None,
    error: str | None = None,
) -> MagicMock:
    plan = MagicMock()
    plan.id = uuid.uuid4()
    plan.agent_type_id = agent_type_id
    plan.generation_status = status
    plan.plan_steps = plan_steps or []
    plan.topology = topology or {"nodes": [], "edges": []}
    plan.generation_error = error
    plan.agent_config_hash = "abc123"
    plan.generated_at = datetime.now(timezone.utc)
    return plan


def _mock_db_no_existing_plan() -> AsyncMock:
    """DB session mock where no AgentPlan row exists yet."""
    db = AsyncMock()
    result = AsyncMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _llm_response_json(steps: list[dict]) -> str:
    return json.dumps(steps)


# ── _compute_config_hash ──────────────────────────────────────────────────────


def test_compute_config_hash_deterministic():
    """Same agent type config produces the same hash on repeated calls."""
    service = PlanGenerationService()
    at = _make_agent_type(
        role_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        primary_sop_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        system_instruction="Do the task",
    )
    h1 = service._compute_config_hash(at)
    h2 = service._compute_config_hash(at)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_compute_config_hash_changes_with_instruction():
    """Hash changes when system_instruction changes."""
    service = PlanGenerationService()
    role_id = uuid.uuid4()
    at1 = _make_agent_type(role_id=role_id, system_instruction="Instruction A")
    at2 = _make_agent_type(role_id=role_id, system_instruction="Instruction B")
    assert service._compute_config_hash(at1) != service._compute_config_hash(at2)


def test_compute_config_hash_changes_with_role():
    """Hash changes when role_id changes."""
    service = PlanGenerationService()
    at1 = _make_agent_type(role_id=uuid.uuid4(), system_instruction="Same instruction")
    at2 = _make_agent_type(role_id=uuid.uuid4(), system_instruction="Same instruction")
    assert service._compute_config_hash(at1) != service._compute_config_hash(at2)


def test_compute_config_hash_none_values_handled():
    """Hash works when role_id and system_instruction are None."""
    service = PlanGenerationService()
    at = _make_agent_type(role_id=None, primary_sop_id=None, system_instruction=None)
    h = service._compute_config_hash(at)
    assert len(h) == 64


# ── _parse_plan_steps ─────────────────────────────────────────────────────────


def test_parse_plan_steps_valid_json():
    """Valid JSON array is parsed into plan step dicts."""
    service = PlanGenerationService()
    steps = [
        {"order": 1, "type": "sop_invocation", "name": "Step 1", "description": "Do it"},
        {"order": 2, "type": "tool_call", "name": "Step 2", "description": None},
    ]
    result = service._parse_plan_steps(json.dumps(steps))
    assert len(result) == 2
    assert result[0]["order"] == 1
    assert result[0]["type"] == "sop_invocation"
    assert result[0]["name"] == "Step 1"
    assert result[1]["description"] is None


def test_parse_plan_steps_json_embedded_in_text():
    """JSON array embedded in surrounding text (LLM preamble) is extracted correctly."""
    service = PlanGenerationService()
    steps = [{"order": 1, "type": "tool_call", "name": "Step A", "description": "desc"}]
    raw = f"Here is the plan:\n{json.dumps(steps)}\nEnd of plan."
    result = service._parse_plan_steps(raw)
    assert len(result) == 1
    assert result[0]["name"] == "Step A"


def test_parse_plan_steps_empty_array():
    """Empty JSON array returns empty list."""
    service = PlanGenerationService()
    result = service._parse_plan_steps("[]")
    assert result == []


def test_parse_plan_steps_invalid_json_returns_fallback():
    """Invalid JSON returns a single fallback step rather than raising."""
    service = PlanGenerationService()
    result = service._parse_plan_steps("This is not JSON at all.")
    assert len(result) == 1
    assert result[0]["order"] == 1
    assert result[0]["type"] == "tool_call"


def test_parse_plan_steps_missing_fields_use_defaults():
    """Steps with missing fields get sane defaults."""
    service = PlanGenerationService()
    steps = [{"name": "Unnamed Step"}]
    result = service._parse_plan_steps(json.dumps(steps))
    assert len(result) == 1
    assert result[0]["order"] == 1  # default to i+1
    assert result[0]["type"] == "tool_call"  # default


# ── generate_plan happy path ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_plan_happy_path_returns_success_plan():
    """generate_plan with mocked LLM returns a plan with status=success."""
    service = PlanGenerationService()
    at = _make_agent_type(role_id=uuid.uuid4())
    db = _mock_db_no_existing_plan()

    expected_plan = _make_mock_plan(
        agent_type_id=at.id,
        status=AgentPlanStatus.success,
        plan_steps=[{"order": 1, "type": "tool_call", "name": "Step", "description": None}],
    )

    with (
        patch.object(service, "_resolve_graph", new=AsyncMock(return_value={
            "role": {"id": str(uuid.uuid4()), "name": "Role", "description": None},
            "sops": [],
            "skills": [],
            "tools": [],
        })),
        patch.object(service, "_invoke_llm", new=AsyncMock(return_value='[{"order":1,"type":"tool_call","name":"Step","description":null}]')),
        patch.object(service, "_upsert_plan", new=AsyncMock(return_value=expected_plan)),
    ):
        result = await service.generate_plan(at, db)

    assert result.generation_status == AgentPlanStatus.success
    assert result.plan_steps is not None


@pytest.mark.asyncio
async def test_generate_plan_llm_exception_caught_non_blocking():
    """If _invoke_llm raises, generate_plan catches it and returns failed plan without re-raising."""
    service = PlanGenerationService()
    at = _make_agent_type(role_id=uuid.uuid4())
    db = _mock_db_no_existing_plan()

    failed_plan = _make_mock_plan(
        agent_type_id=at.id,
        status=AgentPlanStatus.failed,
        error="LLM connection refused",
    )

    with (
        patch.object(service, "_resolve_graph", new=AsyncMock(return_value={
            "role": {"id": str(uuid.uuid4()), "name": "Role", "description": None},
            "sops": [],
            "skills": [],
            "tools": [],
        })),
        patch.object(service, "_invoke_llm", new=AsyncMock(side_effect=ConnectionError("LLM connection refused"))),
        patch.object(service, "_upsert_plan", new=AsyncMock(return_value=failed_plan)),
    ):
        # Must NOT raise — failure is non-blocking
        result = await service.generate_plan(at, db)

    assert result.generation_status == AgentPlanStatus.failed
    assert result.generation_error is not None


@pytest.mark.asyncio
async def test_generate_plan_timeout_error_caught():
    """LLM timeout (TimeoutError) is caught and recorded as failed status."""
    service = PlanGenerationService()
    at = _make_agent_type(role_id=uuid.uuid4())
    db = _mock_db_no_existing_plan()

    failed_plan = _make_mock_plan(
        agent_type_id=at.id,
        status=AgentPlanStatus.failed,
        error="LLM timeout",
    )

    with (
        patch.object(service, "_resolve_graph", new=AsyncMock(return_value={
            "role": {"id": str(uuid.uuid4()), "name": "Role", "description": None},
            "sops": [],
            "skills": [],
            "tools": [],
        })),
        patch.object(service, "_invoke_llm", new=AsyncMock(side_effect=TimeoutError("LLM timeout"))),
        patch.object(service, "_upsert_plan", new=AsyncMock(return_value=failed_plan)),
    ):
        result = await service.generate_plan(at, db)

    assert result.generation_status == AgentPlanStatus.failed


@pytest.mark.asyncio
async def test_generate_plan_no_role_completes_without_crash():
    """agent_type with no role_id → generate_plan completes without raising."""
    service = PlanGenerationService()
    at = _make_agent_type(role_id=None)  # No role
    db = _mock_db_no_existing_plan()

    empty_plan = _make_mock_plan(
        agent_type_id=at.id,
        plan_steps=[],
        topology={"nodes": [], "edges": []},
    )

    with (
        patch.object(service, "_invoke_llm", new=AsyncMock(return_value="[]")),
        patch.object(service, "_upsert_plan", new=AsyncMock(return_value=empty_plan)),
    ):
        result = await service.generate_plan(at, db)

    # Should complete without raising regardless of status
    assert result is not None


@pytest.mark.asyncio
async def test_generate_plan_upsert_called_on_success():
    """On success, _upsert_plan is called with status=success."""
    service = PlanGenerationService()
    at = _make_agent_type(role_id=uuid.uuid4())
    db = _mock_db_no_existing_plan()

    success_plan = _make_mock_plan(agent_type_id=at.id, status=AgentPlanStatus.success)
    upsert_mock = AsyncMock(return_value=success_plan)

    with (
        patch.object(service, "_resolve_graph", new=AsyncMock(return_value={
            "role": {"id": str(uuid.uuid4()), "name": "Role", "description": None},
            "sops": [],
            "skills": [],
            "tools": [],
        })),
        patch.object(service, "_invoke_llm", new=AsyncMock(return_value='[{"order":1,"type":"tool_call","name":"S","description":null}]')),
        patch.object(service, "_upsert_plan", upsert_mock),
    ):
        await service.generate_plan(at, db)

    upsert_mock.assert_called_once()
    call_kwargs = upsert_mock.call_args.kwargs
    assert call_kwargs["status"] == AgentPlanStatus.success
    assert call_kwargs["error"] is None


@pytest.mark.asyncio
async def test_generate_plan_upsert_called_with_failed_status_on_error():
    """On LLM exception, _upsert_plan is called with status=failed and error message."""
    service = PlanGenerationService()
    at = _make_agent_type(role_id=uuid.uuid4())
    db = _mock_db_no_existing_plan()

    failed_plan = _make_mock_plan(agent_type_id=at.id, status=AgentPlanStatus.failed, error="boom")
    upsert_mock = AsyncMock(return_value=failed_plan)

    with (
        patch.object(service, "_resolve_graph", new=AsyncMock(return_value={
            "role": {"id": str(uuid.uuid4()), "name": "Role", "description": None},
            "sops": [],
            "skills": [],
            "tools": [],
        })),
        patch.object(service, "_invoke_llm", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch.object(service, "_upsert_plan", upsert_mock),
    ):
        await service.generate_plan(at, db)

    upsert_mock.assert_called_once()
    call_kwargs = upsert_mock.call_args.kwargs
    assert call_kwargs["status"] == AgentPlanStatus.failed
    assert "boom" in (call_kwargs["error"] or "")


# ── _upsert_plan: create vs update behaviour ──────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_plan_creates_new_row_when_none_exists():
    """_upsert_plan inserts a new AgentPlan row when none exists for the agent type."""
    service = PlanGenerationService()
    agent_type_id = uuid.uuid4()

    # Simulate: db.execute returns None (no existing plan)
    # Use MagicMock for result — scalar_one_or_none() is synchronous on SQLAlchemy Result
    db = AsyncMock()
    no_result = MagicMock()
    no_result.scalar_one_or_none.return_value = None
    db.execute.return_value = no_result
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    added_objects: list = []
    def capture_add(obj):
        added_objects.append(obj)
    db.add = capture_add

    from app.db.models.agents import AgentPlan

    async def mock_refresh(obj, *args, **kwargs):
        # Simulate refresh populating the ID
        if not hasattr(obj, '_refreshed'):
            obj._refreshed = True

    db.refresh.side_effect = mock_refresh

    await service._upsert_plan(
        agent_type_id=agent_type_id,
        plan_steps=[{"order": 1, "type": "tool_call", "name": "S", "description": None}],
        topology={"nodes": [], "edges": []},
        status=AgentPlanStatus.success,
        error=None,
        config_hash="abc",
        db=db,
    )

    # db.add should have been called with a new AgentPlan
    assert len(added_objects) == 1
    assert isinstance(added_objects[0], AgentPlan)
    assert added_objects[0].generation_status == AgentPlanStatus.success


@pytest.mark.asyncio
async def test_upsert_plan_updates_existing_row():
    """_upsert_plan updates the existing AgentPlan row rather than inserting a new one."""
    from app.db.models.agents import AgentPlan

    service = PlanGenerationService()
    agent_type_id = uuid.uuid4()

    # Simulate: db.execute returns an existing plan
    existing_plan = MagicMock(spec=AgentPlan)
    existing_plan.agent_type_id = agent_type_id
    existing_plan.generation_status = AgentPlanStatus.failed

    db = AsyncMock()
    # Use MagicMock for result — scalar_one_or_none() is synchronous on SQLAlchemy Result
    result_with_plan = MagicMock()
    result_with_plan.scalar_one_or_none.return_value = existing_plan
    db.execute.return_value = result_with_plan
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    await service._upsert_plan(
        agent_type_id=agent_type_id,
        plan_steps=[{"order": 1, "type": "tool_call", "name": "Updated", "description": None}],
        topology={"nodes": [], "edges": []},
        status=AgentPlanStatus.success,
        error=None,
        config_hash="newhash",
        db=db,
    )

    # db.add should NOT have been called — we update the existing row in place
    db.add.assert_not_called()
    # The existing plan should have been mutated
    assert existing_plan.generation_status == AgentPlanStatus.success
    assert existing_plan.plan_steps is not None


# ── _resolve_graph SOP filtering ──────────────────────────────────────────────


def _make_role(role_id: uuid.UUID, name: str = "Test Role") -> MagicMock:
    role = MagicMock()
    role.id = role_id
    role.name = name
    role.description = None
    return role


def _make_sop(sop_id: uuid.UUID, name: str) -> MagicMock:
    sop = MagicMock()
    sop.id = sop_id
    sop.name = name
    sop.description = None
    sop.instructions = None
    sop.steps = []
    return sop


def _make_db_for_resolve_graph(
    role: MagicMock,
    sop_ids: list[uuid.UUID],
    sops: list[MagicMock],
) -> AsyncMock:
    """Build a DB AsyncMock for _resolve_graph with no identity, no skills, no MCP sessions."""
    db = AsyncMock()

    # Call 1: select(AgentRole) → scalar_one_or_none
    role_result = MagicMock()
    role_result.scalar_one_or_none.return_value = role

    # Call 2: select(AgentRoleMcpSession, McpSession) → .all()
    sessions_result = MagicMock()
    sessions_result.all.return_value = []

    # Call 3: select(AgentRoleSOP.sop_id) → .fetchall()
    sop_ids_result = MagicMock()
    sop_ids_result.fetchall.return_value = [(sid,) for sid in sop_ids]

    # Call 4: select(Sop) → .scalars().all()
    sops_scalars = MagicMock()
    sops_scalars.all.return_value = sops
    sops_result = MagicMock()
    sops_result.scalars.return_value = sops_scalars

    # Call 5: select(AgentTypeSopBinding.sop_id) → .fetchall() — called from _get_bound_sop_ids
    #         Conditionally called only when system instruction doesn't mention SOPs
    bind_sop_ids_result = MagicMock()
    bind_sop_ids_result.fetchall.return_value = []

    # Call 6: select(AgentRoleSkill.skill_id) → .fetchall()
    skills_result = MagicMock()
    skills_result.fetchall.return_value = []

    # Call 7: select(AgentTypeSkillBinding.skill_id) → .fetchall()
    bind_skills_result = MagicMock()
    bind_skills_result.fetchall.return_value = []

    db.execute.side_effect = [
        role_result,
        sessions_result,
        sop_ids_result,
        sops_result,
        bind_sop_ids_result,
        skills_result,
        bind_skills_result,
    ]
    return db


@pytest.mark.asyncio
async def test_resolve_graph_filters_sops_by_system_instruction():
    """System instruction names 'query-supabase' → sop_data_list contains only that SOP."""
    service = PlanGenerationService()
    role_id = uuid.uuid4()
    sop1_id = uuid.uuid4()
    sop2_id = uuid.uuid4()

    at = _make_agent_type(
        role_id=role_id,
        system_instruction="Use the query-supabase procedure to retrieve data.",
    )
    at.identity_id = None

    role = _make_role(role_id)
    sop1 = _make_sop(sop1_id, "query-supabase")
    sop2 = _make_sop(sop2_id, "send-email")
    db = _make_db_for_resolve_graph(role, [sop1_id, sop2_id], [sop1, sop2])

    graph = await service._resolve_graph(at, db)

    assert len(graph["sops"]) == 1
    assert graph["sops"][0]["name"] == "query-supabase"


@pytest.mark.asyncio
async def test_resolve_graph_uses_default_sop_as_fallback():
    """System instruction names no SOP, agent has primary_sop_id → only that SOP returned."""
    service = PlanGenerationService()
    role_id = uuid.uuid4()
    sop1_id = uuid.uuid4()
    sop2_id = uuid.uuid4()

    at = _make_agent_type(
        role_id=role_id,
        primary_sop_id=sop1_id,
        system_instruction="Process all incoming requests efficiently.",
    )
    at.identity_id = None

    role = _make_role(role_id)
    sop1 = _make_sop(sop1_id, "query-supabase")
    sop2 = _make_sop(sop2_id, "send-email")
    db = _make_db_for_resolve_graph(role, [sop1_id, sop2_id], [sop1, sop2])

    graph = await service._resolve_graph(at, db)

    # primary_sop_id was removed (replaced by AgentTypeSopBinding).
    # When no SOPs are mentioned and no bindings exist, all role SOPs are kept.
    assert len(graph["sops"]) == 2


@pytest.mark.asyncio
async def test_resolve_graph_keeps_all_sops_when_no_instruction_and_no_default():
    """No system instruction and no primary_sop_id → all role SOPs are kept."""
    service = PlanGenerationService()
    role_id = uuid.uuid4()
    sop1_id = uuid.uuid4()
    sop2_id = uuid.uuid4()

    at = _make_agent_type(
        role_id=role_id,
        primary_sop_id=None,
        system_instruction=None,
    )
    at.identity_id = None

    role = _make_role(role_id)
    sop1 = _make_sop(sop1_id, "query-supabase")
    sop2 = _make_sop(sop2_id, "send-email")
    db = _make_db_for_resolve_graph(role, [sop1_id, sop2_id], [sop1, sop2])

    graph = await service._resolve_graph(at, db)

    assert len(graph["sops"]) == 2
    sop_names = {s["name"] for s in graph["sops"]}
    assert sop_names == {"query-supabase", "send-email"}

