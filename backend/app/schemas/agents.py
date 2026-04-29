"""Pydantic v2 schemas for Agent management."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated

from app.db.models.agents import AgentMode, AgentInstanceStatus


class AgentTypeCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: str | None = None
    mode: AgentMode
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    llm_api_key: str | None = None  # Plaintext — encrypted before storage
    sop_id: uuid.UUID | None = None
    skill_ids: list[uuid.UUID] = []
    max_instances: int = Field(default=5, ge=1, le=100)
    system_prompt: str | None = None


class AgentTypeUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    sop_id: uuid.UUID | None = None
    skill_ids: list[uuid.UUID] | None = None
    max_instances: int | None = None
    system_prompt: str | None = None
    is_active: bool | None = None


class AgentTypeRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    mode: AgentMode
    llm_provider: str
    llm_model: str
    sop_id: uuid.UUID | None
    max_instances: int
    is_active: bool
    system_prompt: str | None
    identity_subject: str | None
    created_at: datetime
    updated_at: datetime


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
