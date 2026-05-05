"""Pydantic v2 schemas for Agent management."""
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, StringConstraints

from app.db.models.agents import (
    AgentIdentityStatus,
    AgentIdentityType,
    AgentInputType,
    AgentInstanceStatus,
    AgentJobStatus,
    AgentOutputType,
)


# ── Agent Role Schemas ─────────────────────────────────────────────────────────


class AgentRoleCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: str | None = None
    sop_ids: list[uuid.UUID] = []
    skill_ids: list[uuid.UUID] = []


class AgentRoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    sop_ids: list[uuid.UUID] | None = None
    skill_ids: list[uuid.UUID] | None = None


class AgentRoleRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    sop_ids: list[uuid.UUID] = []
    skill_ids: list[uuid.UUID] = []
    created_at: datetime
    updated_at: datetime

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "AgentRoleRead":  # type: ignore[override]
        """Extract sop_ids / skill_ids from ORM relationship lists."""
        if hasattr(obj, "sop_assignments") and hasattr(obj, "skill_assignments"):
            data = {
                "id": obj.id,
                "name": obj.name,
                "description": obj.description,
                "sop_ids": [a.sop_id for a in obj.sop_assignments],
                "skill_ids": [a.skill_id for a in obj.skill_assignments],
                "created_at": obj.created_at,
                "updated_at": obj.updated_at,
            }
            return super().model_validate(data, **kwargs)
        return super().model_validate(obj, **kwargs)


# ── Agent Identity Schemas ─────────────────────────────────────────────────────


class AgentIdentityCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    identity_type: AgentIdentityType = AgentIdentityType.realm_user
    realm_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    realm_username: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    status: AgentIdentityStatus = AgentIdentityStatus.active


class AgentIdentityUpdate(BaseModel):
    name: str | None = None
    realm_name: str | None = None
    realm_username: str | None = None
    status: AgentIdentityStatus | None = None


class AgentIdentityRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    identity_type: AgentIdentityType
    realm_name: str | None
    realm_username: str | None
    status: AgentIdentityStatus
    token_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentIdentityOAuthAuthorizeResponse(BaseModel):
    """Response from the OAuth authorize endpoint — contains the IdP redirect URL."""

    authorization_url: str


# ── Agent Job Schemas ──────────────────────────────────────────────────────────


class AgentJobCreate(BaseModel):
    agent_type_id: uuid.UUID
    input_data: dict[str, Any] | None = None


class AgentJobStatusRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    agent_type_id: uuid.UUID
    status: AgentJobStatus
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime


class AgentJobRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    agent_type_id: uuid.UUID
    triggered_by_user_id: uuid.UUID | None
    input_data: dict[str, Any] | None
    status: AgentJobStatus
    started_at: datetime | None
    completed_at: datetime | None
    output_data: dict[str, Any] | None
    error_message: str | None
    created_at: datetime


# ── Agent Type Schemas ─────────────────────────────────────────────────────────


class AgentTypeCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: str | None = None
    identity_id: uuid.UUID | None = None
    role_id: uuid.UUID | None = None
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    llm_api_key: str | None = None  # Plaintext — encrypted before storage
    system_instruction: str | None = None
    input_type: AgentInputType = AgentInputType.none
    input_schema: dict[str, Any] | None = None
    output_type: AgentOutputType = AgentOutputType.auto
    output_schema: dict[str, Any] | None = None


class AgentTypeUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    identity_id: uuid.UUID | None = None
    role_id: uuid.UUID | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    is_active: bool | None = None
    system_instruction: str | None = None
    input_type: AgentInputType | None = None
    input_schema: dict[str, Any] | None = None
    output_type: AgentOutputType | None = None
    output_schema: dict[str, Any] | None = None


class AgentTypeRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    identity_id: uuid.UUID | None
    role_id: uuid.UUID | None
    llm_provider: str
    llm_model: str
    is_active: bool
    system_instruction: str | None
    input_type: AgentInputType
    input_schema: dict[str, Any] | None
    output_type: AgentOutputType
    output_schema: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


# ── Agent Instance Schemas (legacy) ───────────────────────────────────────────


class AgentInstanceRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    agent_type_id: uuid.UUID
    status: AgentInstanceStatus
    session_handle: str
    initiator_subject: str | None
    created_at: datetime
    closed_at: datetime | None


class AgentInitResponse(BaseModel):
    session_handle: str
    instance_id: uuid.UUID
    agent_type_id: uuid.UUID
