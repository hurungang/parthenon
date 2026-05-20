"""Unit tests for Agent Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

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
