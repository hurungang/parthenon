"""Pydantic v2 schemas for Group management."""
import uuid
from datetime import datetime
from typing import List

from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated


class GroupCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    description: str | None = None
    owner_id: uuid.UUID | None = None
    idp_claim_value: str | None = Field(default=None, max_length=255)
    role_ids: List[uuid.UUID] = Field(default_factory=list)


class GroupUpdate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    description: str | None = None
    owner_id: uuid.UUID | None = None
    idp_claim_value: str | None = None


class GroupRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    owner_id: uuid.UUID | None
    owner_display_name: str | None = None
    idp_claim_value: str | None
    created_at: datetime
    updated_at: datetime
    member_count: int = 0
    role_count: int = 0


class GroupMemberRead(BaseModel):
    model_config = {"from_attributes": True}

    user_id: uuid.UUID
    group_id: uuid.UUID
    display_name: str
    email: str
    joined_at: datetime
    join_reason: str | None


class GroupMembershipRead(BaseModel):
    """Represents a single group membership for a user."""

    model_config = {"from_attributes": True}

    group_id: uuid.UUID
    group_name: str
    joined_at: datetime
    join_reason: str | None = None


class AddGroupMemberBody(BaseModel):
    user_id: uuid.UUID
    join_reason: str | None = None


class AssignGroupRoleBody(BaseModel):
    role_id: uuid.UUID
