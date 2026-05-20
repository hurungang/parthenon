"""Pydantic v2 schemas for Skills and SOPs."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, StringConstraints, model_validator
from typing import Annotated
from sqlalchemy import inspect as sa_inspect

from app.db.models.skills import SopStepType


class SkillCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: str | None = None
    instructions: str | None = None
    tool_ids: list[uuid.UUID] = []


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    tool_ids: list[uuid.UUID] | None = None
    is_active: bool | None = None


class SkillRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    tool_ids: list[uuid.UUID] = []
    instructions_with_tools: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_tool_ids(cls, data: Any) -> Any:
        if hasattr(data, "tool_bindings"):
            bindings = getattr(data, "tool_bindings", None) or []
            sorted_bindings = sorted(bindings, key=lambda b: b.order)
            data.tool_ids = [b.tool_id for b in sorted_bindings]
        return data


class SkillDetailRead(SkillRead):
    """Extended skill response used by GET /skills/{id}; includes editable instructions field."""

    instructions: str | None = None


class SopStepCreate(BaseModel):
    order: int
    step_type: SopStepType = SopStepType.skill_invocation
    skill_id: uuid.UUID | None = None
    target_agent_type_id: uuid.UUID | None = None
    step_config: dict[str, Any] | None = None
    name: str | None = None
    description: str | None = None


class SopStepRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    sop_id: uuid.UUID
    order: int
    step_type: SopStepType
    skill_id: uuid.UUID | None
    target_agent_type_id: uuid.UUID | None
    step_config: dict[str, Any] | None
    name: str | None
    description: str | None
    created_at: datetime


class SopCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: str | None = None
    instructions: str | None = None


class SopUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    is_active: bool | None = None


class SopRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    instructions: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    required_skill_ids: list[uuid.UUID] = []

    @model_validator(mode="before")
    @classmethod
    def populate_required_skill_ids(cls, data: Any) -> Any:
        """Extract skill IDs from sop steps for frontend SOP-skill auto-selection."""
        if isinstance(data, dict):
            return data

        try:
            insp = sa_inspect(data)
            if "steps" in insp.unloaded:
                return data
        except Exception:
            # If inspection is unavailable, do not risk relationship lazy-load IO.
            return data

        steps = getattr(data, "steps", None) or []
        # Collect unique skill_ids from all steps (excluding None)
        skill_ids = [step.skill_id for step in steps if step.skill_id is not None]
        data.required_skill_ids = list(dict.fromkeys(skill_ids))  # Deduplicate while preserving order
        return data


class SopDetailRead(SopRead):
    steps: list[SopStepRead] = []
