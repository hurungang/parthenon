"""Unit tests for RecursionValidationService — SOP delegation graph cycle detection."""
import uuid
from unittest.mock import AsyncMock, MagicMock
from typing import Any

import pytest

from app.db.models.skills import SopStep, SopStepType
from app.services.control_center.recursion_validation_service import RecursionValidationService


def _mock_db() -> AsyncMock:
    return AsyncMock()


def _make_agent_type(
    agent_type_id: uuid.UUID,
    role_id: uuid.UUID | None = uuid.uuid4(),
    name: str = "test-agent",
) -> MagicMock:
    at = MagicMock()
    at.id = agent_type_id
    at.role_id = role_id
    at.name = name
    at.recursion_validation_mode = MagicMock()
    return at


def _make_delegation_step(
    target_agent_type_id: uuid.UUID,
    sop_id: uuid.UUID,
    step_id: uuid.UUID | None = None,
) -> MagicMock:
    step = MagicMock(spec=SopStep)
    step.id = step_id or uuid.uuid4()
    step.sop_id = sop_id
    step.step_type = SopStepType.agent_delegation
    step.target_agent_type_id = target_agent_type_id
    step.name = None
    step.description = None
    step.order = 0
    return step


@pytest.mark.asyncio
async def test_build_adjacency_skips_self_delegation_edge():
    """Self-delegation edges must be excluded from the graph.

    Regression test: when a role SOP has a delegation step targeting the same
    agent type that is being validated, the edge must be skipped to avoid a
    false-positive cycle detection.
    """
    svc = RecursionValidationService()
    agent_type_id = uuid.uuid4()
    sop_id = uuid.uuid4()
    role_id = uuid.uuid4()

    agent_type = _make_agent_type(agent_type_id, role_id=role_id, name="supabase-get-roles")
    self_step = _make_delegation_step(
        target_agent_type_id=agent_type_id,
        sop_id=sop_id,
    )

    db = _mock_db()
    db.get = AsyncMock(return_value=agent_type)

    # AgentTypeSopBinding query → no explicit bindings
    has_sop_result = MagicMock()
    has_sop_result.first.return_value = None  # no sop bindings

    # AgentTypeSkillBinding query → no skill bindings
    has_skill_result = MagicMock()
    has_skill_result.first.return_value = None  # no skill bindings

    # Role SOP query — returns one SOP
    role_sop_rows = MagicMock()
    role_sop_rows.scalars.return_value.all.return_value = [
        MagicMock(sop_id=sop_id)
    ]

    # Step query — returns the self-delegation step
    step_result = MagicMock()
    step_result.scalars.return_value.all.return_value = [self_step]

    db.execute = AsyncMock(side_effect=[
        has_sop_result,      # AgentTypeSopBinding check
        has_skill_result,    # AgentTypeSkillBinding check
        role_sop_rows,       # AgentRoleSOP fallback
        step_result,         # SopStep delegation steps
    ])

    adjacency: dict[str, list[str]] = {}
    step_map: dict[tuple[str, str], tuple[uuid.UUID | None, uuid.UUID | None]] = {}

    await svc._build_adjacency(
        agent_type_id=agent_type_id,
        db=db,
        adjacency=adjacency,
        step_map=step_map,
        visited_types=set(),
    )

    node_key = str(agent_type_id)
    assert node_key in adjacency, "Agent type should be in adjacency map"
    assert adjacency[node_key] == [], "Self-delegation edge must be excluded"
    assert (node_key, node_key) not in step_map, "Self-delegation must not appear in step_map"


@pytest.mark.asyncio
async def test_build_adjacency_still_detects_indirect_cycle():
    """Indirect cycles between different agent types must still be detected."""
    agent_a_id = uuid.uuid4()
    agent_b_id = uuid.uuid4()
    sop_id = uuid.uuid4()
    role_id = uuid.uuid4()

    agent_a = _make_agent_type(agent_a_id, role_id=role_id, name="agent-a")
    agent_b = _make_agent_type(agent_b_id, role_id=role_id, name="agent-b")

    step_a_to_b = _make_delegation_step(
        target_agent_type_id=agent_b_id,
        sop_id=sop_id,
    )
    step_b_to_a = _make_delegation_step(
        target_agent_type_id=agent_a_id,
        sop_id=sop_id,
    )

    db = _mock_db()

    def _mock_get(model_cls, pk: uuid.UUID) -> Any:
        mapping = {agent_a_id: agent_a, agent_b_id: agent_b}
        return mapping.get(pk)

    db.get = AsyncMock(side_effect=_mock_get)

    # --- First call: validate agent_a ---
    has_sop_a = MagicMock()
    has_sop_a.first.return_value = None
    has_skill_a = MagicMock()
    has_skill_a.first.return_value = None
    role_sop_a = MagicMock()
    role_sop_a.scalars.return_value.all.return_value = [MagicMock(sop_id=sop_id)]
    steps_a = MagicMock()
    steps_a.scalars.return_value.all.return_value = [step_a_to_b]

    # --- Second call (agent_b): validate agent_b ---
    has_sop_b = MagicMock()
    has_sop_b.first.return_value = None
    has_skill_b = MagicMock()
    has_skill_b.first.return_value = None
    role_sop_b = MagicMock()
    role_sop_b.scalars.return_value.all.return_value = [MagicMock(sop_id=sop_id)]
    steps_b = MagicMock()
    steps_b.scalars.return_value.all.return_value = [step_b_to_a]

    db.execute = AsyncMock(side_effect=[
        has_sop_a, has_skill_a, role_sop_a, steps_a,
        has_sop_b, has_skill_b, role_sop_b, steps_b,
    ])

    svc = RecursionValidationService()
    adjacency: dict[str, list[str]] = {}
    step_map: dict[tuple[str, str], tuple[uuid.UUID | None, uuid.UUID | None]] = {}

    await svc._build_adjacency(
        agent_type_id=agent_a_id,
        db=db,
        adjacency=adjacency,
        step_map=step_map,
        visited_types=set(),
    )

    assert str(agent_a_id) in adjacency
    assert str(agent_b_id) in adjacency
    assert str(agent_b_id) in adjacency[str(agent_a_id)]
    assert str(agent_a_id) in adjacency[str(agent_b_id)]


@pytest.mark.asyncio
async def test_build_adjacency_self_edge_does_not_block_other_edges():
    """Self-delegation edge must not prevent other valid delegation edges from being added."""
    agent_self_id = uuid.uuid4()
    child_id = uuid.uuid4()
    sop_id = uuid.uuid4()
    role_id = uuid.uuid4()

    agent_self = _make_agent_type(agent_self_id, role_id=role_id, name="parent-agent")

    self_step = _make_delegation_step(
        target_agent_type_id=agent_self_id,
        sop_id=sop_id,
    )
    child_step = _make_delegation_step(
        target_agent_type_id=child_id,
        sop_id=sop_id,
    )

    db = _mock_db()

    async def _mock_get(model_cls, pk):
        if pk == agent_self_id:
            return agent_self
        return None  # no role_id → adjacency stays empty

    db.get = AsyncMock(side_effect=_mock_get)

    # Executes for agent_self
    has_sop = MagicMock(); has_sop.first.return_value = None
    has_skill = MagicMock(); has_skill.first.return_value = None
    role_sop = MagicMock()
    role_sop.scalars.return_value.all.return_value = [MagicMock(sop_id=sop_id)]
    steps = MagicMock()
    steps.scalars.return_value.all.return_value = [self_step, child_step]

    # Executes for child (no role_id → returns early, no extra queries needed)
    # No additional side_effect entries needed since child returns None from get.

    db.execute = AsyncMock(side_effect=[
        has_sop, has_skill, role_sop, steps,
    ])

    svc = RecursionValidationService()
    adjacency: dict[str, list[str]] = {}
    step_map: dict[tuple[str, str], tuple[uuid.UUID | None, uuid.UUID | None]] = {}

    await svc._build_adjacency(
        agent_type_id=agent_self_id,
        db=db,
        adjacency=adjacency,
        step_map=step_map,
        visited_types=set(),
    )

    node_key = str(agent_self_id)
    assert adjacency[node_key] == [str(child_id)], (
        "Only child edge should be present; self-edge must be excluded"
    )
