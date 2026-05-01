"""Pydantic v2 schemas for Skills and SOPs."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

from app.db.models.skills import SopStepType


class SkillCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: str | None = None
    tool_ids: list[uuid.UUID] = []


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tool_ids: list[uuid.UUID] | None = None
    is_active: bool | None = None


class SkillRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SopStepCreate(BaseModel):
    order: int
    step_type: SopStepType = SopStepType.skill
    skill_id: uuid.UUID | None = None
    delegate_agent_type_id: uuid.UUID | None = None
    name: str | None = None
    description: str | None = None


class SopStepRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    sop_id: uuid.UUID
    order: int
    step_type: SopStepType
    skill_id: uuid.UUID | None
    delegate_agent_type_id: uuid.UUID | None
    name: str | None
    description: str | None
    created_at: datetime


class SopCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: str | None = None


class SopUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class SopRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SopDetailRead(SopRead):
    steps: list[SopStepRead] = []
