"""Pydantic v2 schemas for Identity & Auth API."""
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints

from app.db.models.identity import IdentityType, RoleType


# ── Permission schemas ─────────────────────────────────────────────────────────

class PermissionCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    resource: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    action: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    description: str | None = None


class PermissionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    resource: str
    action: str
    description: str | None
    created_at: datetime


# ── Role schemas ───────────────────────────────────────────────────────────────

class RoleCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    description: str | None = None
    role_type: RoleType = RoleType.user


class RoleUpdate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    description: str | None = None
    role_type: RoleType | None = None
    is_active: bool | None = None


class RoleRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    role_type: RoleType
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RolePermissionAssign(BaseModel):
    permission_id: uuid.UUID


# ── Identity schemas ───────────────────────────────────────────────────────────

class IdentityCreate(BaseModel):
    subject: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    email: str | None = None
    display_name: str | None = None
    identity_type: IdentityType = IdentityType.user
    role_id: uuid.UUID | None = None


class IdentityRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    subject: str
    email: str | None
    display_name: str | None
    identity_type: IdentityType
    role_id: uuid.UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ── Setup schemas ──────────────────────────────────────────────────────────────

class SetupInitResponse(BaseModel):
    message: str
    admin_role_id: uuid.UUID
    admin_identity_id: uuid.UUID
    already_initialized: bool
