"""Unit tests for Agent Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.exc import MissingGreenlet

from app.schemas.agents import AgentRoleRead


class _Assignment:
    def __init__(self, sop_id: uuid.UUID | None = None, skill_id: uuid.UUID | None = None) -> None:
        self.sop_id = sop_id
        self.skill_id = skill_id


def test_agent_role_read_extracts_loaded_assignments() -> None:
    now = datetime.now(timezone.utc)
    sop_id = uuid.uuid4()
    skill_id = uuid.uuid4()

    class FakeRole:
        __tablename__ = "agent_roles"
        id = uuid.uuid4()
        name = "Analyst"
        description = "Role with loaded assignments"
        sop_assignments = [_Assignment(sop_id=sop_id)]
        skill_assignments = [_Assignment(skill_id=skill_id)]
        created_at = now
        updated_at = now

    class _InspectionResult:
        unloaded = set()

    with patch("app.schemas.agents.sa_inspect", return_value=_InspectionResult()):
        read = AgentRoleRead.model_validate(FakeRole())

    assert read.sop_ids == [sop_id]
    assert read.skill_ids == [skill_id]


def test_agent_role_read_does_not_lazy_load_unloaded_relationships() -> None:
    """Regression for MissingGreenlet when relationship attributes are not preloaded."""
    now = datetime.now(timezone.utc)

    class FakeRole:
        __tablename__ = "agent_roles"
        id = uuid.uuid4()
        name = "Analyst"
        description = "Role with unloaded relationships"
        created_at = now
        updated_at = now

        @property
        def sop_assignments(self):
            raise MissingGreenlet("greenlet_spawn has not been called")

        @property
        def skill_assignments(self):
            raise MissingGreenlet("greenlet_spawn has not been called")

    read = AgentRoleRead.model_validate(FakeRole())

    assert read.sop_ids == []
    assert read.skill_ids == []


# ── Guardrail contract: Max Delegation Depth has no platform ceiling ──────────


def _make_agent_type_create_kwargs(**overrides):
    from app.schemas.agents import AgentTypeCreate

    kwargs = {
        "name": "guardrail-probe",
        "guardrail_max_iterations": 10,
        "guardrail_max_delegation_depth": 3,
        "guardrail_max_delegated_steps": 20,
        "guardrail_execution_timeout_seconds": 300,
    }
    kwargs.update(overrides)
    return AgentTypeCreate(**kwargs)


@pytest.mark.parametrize("depth", [0, 1, 32, 33, 64, 1000])
def test_agent_type_create_accepts_any_non_negative_delegation_depth(depth: int) -> None:
    """Values at and above the former 32 ceiling are accepted unchanged."""
    created = _make_agent_type_create_kwargs(guardrail_max_delegation_depth=depth)
    assert created.guardrail_max_delegation_depth == depth


@pytest.mark.parametrize("depth", [-1, -32])
def test_agent_type_create_rejects_negative_delegation_depth(depth: int) -> None:
    with pytest.raises(ValueError) as exc_info:
        _make_agent_type_create_kwargs(guardrail_max_delegation_depth=depth)
    assert "guardrail_max_delegation_depth" in str(exc_info.value)


@pytest.mark.parametrize("input_type", ["none", "typed", "conversation"])
def test_delegation_depth_ceiling_removed_for_every_input_type(input_type: str) -> None:
    created = _make_agent_type_create_kwargs(
        input_type=input_type,
        guardrail_max_delegation_depth=64,
    )
    assert created.guardrail_max_delegation_depth == 64


@pytest.mark.parametrize("depth", [0, 1, 32, 33, 64, 1000])
def test_agent_type_update_accepts_any_non_negative_delegation_depth(depth: int) -> None:
    """The update path (the operator's main edit entry point) has no ceiling."""
    from app.schemas.agents import AgentTypeUpdate

    updated = AgentTypeUpdate(guardrail_max_delegation_depth=depth)
    assert updated.guardrail_max_delegation_depth == depth


@pytest.mark.parametrize("depth", [-1, -32])
def test_agent_type_update_rejects_negative_delegation_depth(depth: int) -> None:
    from app.schemas.agents import AgentTypeUpdate

    with pytest.raises(ValueError) as exc_info:
        AgentTypeUpdate(guardrail_max_delegation_depth=depth)
    assert "guardrail_max_delegation_depth" in str(exc_info.value)


def test_agent_type_update_without_depth_unchanged() -> None:
    """A partial update that omits the depth field is not affected."""
    from app.schemas.agents import AgentTypeUpdate

    updated = AgentTypeUpdate(name="renamed-agent")
    assert updated.guardrail_max_delegation_depth is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("guardrail_max_iterations", 0),
        ("guardrail_max_iterations", 1001),
        ("guardrail_max_delegated_steps", -1),
        ("guardrail_max_delegated_steps", 5001),
        ("guardrail_execution_timeout_seconds", 0),
        ("guardrail_execution_timeout_seconds", 86401),
    ],
)
def test_other_guardrail_bounds_are_unchanged(field: str, value: int) -> None:
    """Only the delegation-depth ceiling was removed; the rest still reject."""
    with pytest.raises(ValueError):
        _make_agent_type_create_kwargs(**{field: value})
