"""Pydantic v2 schemas for Agent Type SOP/Skill bindings."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SopBindingCreate(BaseModel):
    """Request schema for creating a new SOP binding entry."""

    sop_id: uuid.UUID
    order: int


class SkillBindingCreate(BaseModel):
    """Request schema for creating a new Skill binding entry."""

    skill_id: uuid.UUID
    order: int


class SopBindingResponse(BaseModel):
    """Response schema for an SOP binding entry with denormalized SOP name."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sop_id: uuid.UUID
    sop_name: str
    order: int
    created_at: datetime


class SkillBindingResponse(BaseModel):
    """Response schema for a Skill binding entry with denormalized skill name."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    skill_id: uuid.UUID
    skill_name: str
    order: int
    created_at: datetime
