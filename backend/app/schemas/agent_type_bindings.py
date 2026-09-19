"""Pydantic v2 schemas for Agent Type SOP/Skill bindings."""
import uuid
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SopBindingCreate(BaseModel):
    """Request schema for creating a new SOP binding entry."""

    sop_id: uuid.UUID
    order: int


class SkillBindingCreate(BaseModel):
    """Request schema for creating a new Skill binding entry."""

    skill_id: uuid.UUID
    order: int


class BindingResourceType(str, Enum):
    """Resource kind a binding error refers to."""

    ROLE = "role"
    SOP = "sop"
    SKILL = "skill"


class BindingRule(str, Enum):
    """Validation rule that produced a binding error."""

    ROLE_REQUIRED = "role_required"
    ROLE_ACCESS = "role_access"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"


class BindingError(BaseModel):
    """One structured binding-validation/conflict failure.

    ``message`` is the human-readable sentence (also exposed in the
    ``messages`` list for backwards compatibility); the other fields let the
    UI pinpoint exactly which role/skill/SOP failed and why.
    """

    resource_type: BindingResourceType
    resource_id: uuid.UUID | None = None
    rule: BindingRule
    message: str


class BindingValidationFailureDetail(BaseModel):
    """422 response detail shape when binding validation fails."""

    error: Literal["binding_validation_failed"]
    messages: list[str]
    errors: list[BindingError]


class BindingConflictFailureDetail(BaseModel):
    """409 response detail shape when a binding write hits a unique constraint."""

    error: Literal["binding_conflict"]
    messages: list[str]
    errors: list[BindingError]


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
