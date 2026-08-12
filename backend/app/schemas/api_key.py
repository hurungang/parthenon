"""Pydantic v2 schemas for API key CRUD and internal validation."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Admin CRUD Schemas ────────────────────────────────────────────────────────


class ApiKeyCreate(BaseModel):
    """Request body for creating a new API key."""

    name: str = Field(..., min_length=1, max_length=128, description="Human-readable key name/label")
    agent_identity_id: uuid.UUID = Field(..., description="UUID of the agent identity this key is bound to")
    agent_role_id: uuid.UUID = Field(..., description="UUID of the agent role this key is bound to")


class ApiKeyCreateResponse(BaseModel):
    """Response for API key creation — includes the clear-text key shown once."""

    id: uuid.UUID
    name: str
    key_prefix: str
    api_key: str = Field(..., description="Clear-text key value — shown once, never stored")
    agent_identity_id: uuid.UUID
    agent_identity_name: str = Field(..., description="Name of the bound agent identity")
    agent_role_id: uuid.UUID
    agent_role_name: str = Field(..., description="Name of the bound agent role")
    created_at: datetime


class ApiKeyRead(BaseModel):
    """Response for API key list items — metadata only, never includes the secret."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    key_prefix: str
    agent_identity_id: uuid.UUID
    agent_identity_name: str | None = None
    agent_role_id: uuid.UUID
    agent_role_name: str | None = None
    status: str
    created_at: datetime
    last_used_at: datetime | None = None


class ApiKeyListItem(BaseModel):
    """API key list item with denormalized identity and role names."""

    id: uuid.UUID
    name: str
    key_prefix: str
    agent_identity_id: uuid.UUID
    agent_identity_name: str
    agent_role_id: uuid.UUID
    agent_role_name: str
    status: str
    created_at: datetime
    last_used_at: datetime | None = None


class IdentityWithRoles(BaseModel):
    """Agent identity with its available roles for dropdown population."""

    identity_id: uuid.UUID
    identity_name: str
    roles: list[RoleItem] = []


class RoleItem(BaseModel):
    """Agent role summary for identity dropdown."""

    role_id: uuid.UUID
    role_name: str


class ApiKeyRevokeResponse(BaseModel):
    """Response for API key revocation."""

    id: uuid.UUID
    status: str
    message: str = "API key revoked successfully"


# ── Internal Validation Schemas (CH → CC) ────────────────────────────────────


class ApiKeyValidateRequest(BaseModel):
    """Request from CH to validate a hashed API key."""

    key_hash: str = Field(..., min_length=1, description="SHA-256 hash of the API key")
    since: datetime | None = Field(None, description="Optional timestamp for incremental skill sync")


class ApiKeyValidateResponse(BaseModel):
    """Response for successful API key validation — includes identity token and permissions."""

    valid: bool = True
    agent_identity_id: uuid.UUID
    agent_role_id: uuid.UUID
    agent_role_name: str | None = None
    identity_token: str = Field(..., description="Decrypted identity token held by CH, never exposed externally")
    permissions: list[str] = Field(default_factory=list, description="List of allowed tool identifiers")
    skills: list[SkillWithVersion] = Field(default_factory=list, description="Accessible skills with version info")
    api_key_name: str | None = None


class SkillWithVersion(BaseModel):
    """Skill definition with version timestamp and tool schemas for MCP clients."""

    skill_id: uuid.UUID
    name: str
    description: str | None = None
    instructions: str | None = None
    is_active: bool
    is_system: bool = False
    updated_at: datetime | None = None
    tools: list[ToolDefinition] = Field(default_factory=list, description="MCP tool definitions included in this skill")


class ToolDefinition(BaseModel):
    """MCP tool definition with name, description, and input/output schemas."""

    tool_id: uuid.UUID
    name: str = Field(..., description="Canonical tool name (e.g. server_slug____tool_name)")
    description: str | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None


class SkillResolveInternalRequest(BaseModel):
    """Request from CH to resolve accessible skills for a role."""

    agent_role_id: uuid.UUID = Field(..., description="Agent role UUID to resolve skills for")
    since: datetime | None = Field(None, description="Only return skills updated after this timestamp")


class SkillResolveInternalResponse(BaseModel):
    """Response with resolved skills and their tool definitions."""

    skills: list[SkillWithVersion] = Field(default_factory=list)
