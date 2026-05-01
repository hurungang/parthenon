"""Pydantic v2 schemas for PlatformUser management."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.perm_roles import PermRoleRead


class PlatformUserRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    sub: str
    email: str
    display_name: str
    first_seen_at: datetime
    last_seen_at: datetime
    direct_role_count: int = 0
    group_count: int = 0


class GroupMembershipRead(BaseModel):
    model_config = {"from_attributes": True}

    group_id: uuid.UUID
    group_name: str
    joined_at: datetime
    join_reason: str | None


class PlatformUserDetail(PlatformUserRead):
    """Full user detail with roles and group memberships."""

    direct_roles: list[PermRoleRead] = Field(default_factory=list)
    group_memberships: list[GroupMembershipRead] = Field(default_factory=list)


class AssignUserRoleBody(BaseModel):
    role_id: uuid.UUID


class AddUserToGroupBody(BaseModel):
    group_id: uuid.UUID
    join_reason: str | None = None
