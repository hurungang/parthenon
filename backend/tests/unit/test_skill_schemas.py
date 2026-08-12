"""Unit tests for skill/SOP schemas."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy.exc import MissingGreenlet

from app.schemas.skills import SopRead


class _Step:
    def __init__(self, skill_id: uuid.UUID | None) -> None:
        self.skill_id = skill_id


def test_sop_read_populates_required_skill_ids_when_steps_loaded() -> None:
    now = datetime.now(timezone.utc)
    skill_a = uuid.uuid4()
    skill_b = uuid.uuid4()

    class FakeSop:
        __tablename__ = "sops"
        id = uuid.uuid4()
        name = "SOP A"
        description = "desc"
        instructions = "instr"
        is_active = True
        created_at = now
        updated_at = now
        steps = [_Step(skill_a), _Step(skill_b), _Step(skill_a), _Step(None)]

    class _InspectionResult:
        unloaded = set()

    with patch("app.schemas.skills.sa_inspect", return_value=_InspectionResult()):
        read = SopRead.model_validate(FakeSop())

    assert read.required_skill_ids == [skill_a, skill_b]


def test_sop_read_skips_unloaded_steps_without_missing_greenlet() -> None:
    now = datetime.now(timezone.utc)

    class FakeSop:
        __tablename__ = "sops"
        id = uuid.uuid4()
        name = "SOP B"
        description = "desc"
        instructions = "instr"
        is_active = True
        created_at = now
        updated_at = now

        @property
        def steps(self):
            raise MissingGreenlet("greenlet_spawn has not been called")

    class _InspectionResult:
        unloaded = {"steps"}

    with patch("app.schemas.skills.sa_inspect", return_value=_InspectionResult()):
        read = SopRead.model_validate(FakeSop())

    assert read.required_skill_ids == []
