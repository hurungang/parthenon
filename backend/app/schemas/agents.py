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
    AgentPlanStatus,
    ModelProvider,
)


# ── Plan / Topology Schemas ────────────────────────────────────────────────────


class PlanStepRead(BaseModel):
    model_config = {"from_attributes": True}

    order: int
    type: str
    name: str
    description: str | None = None


class TopologyNodeRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    type: str
    label: str
    meta: dict[str, Any] | None = None
    usage: str | None = None


class TopologyEdgeRead(BaseModel):
    model_config = {"from_attributes": True}

    source: str
    target: str
    label: str | None = None
    style: str | None = None


class AgentPlanRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    agent_type_id: uuid.UUID
    plan_steps: list[PlanStepRead] = []
    topology_nodes: list[TopologyNodeRead] = []
    topology_edges: list[TopologyEdgeRead] = []
    generation_status: AgentPlanStatus
    generation_error: str | None = None
    agent_config_hash: str | None = None
    generated_at: datetime | None = None

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "AgentPlanRead":  # type: ignore[override]
        """Extract topology_nodes/topology_edges from the JSON topology column."""
        if hasattr(obj, "topology"):  # ORM AgentPlan object
            topology: dict[str, Any] = obj.topology or {}
            data = {
                "id": obj.id,
                "agent_type_id": obj.agent_type_id,
                "plan_steps": obj.plan_steps or [],
                "topology_nodes": topology.get("nodes", []),
                "topology_edges": topology.get("edges", []),
                "generation_status": obj.generation_status,
                "generation_error": obj.generation_error,
                "agent_config_hash": obj.agent_config_hash,
                "generated_at": obj.generated_at,
            }
            return super().model_validate(data, **kwargs)
        return super().model_validate(obj, **kwargs)


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


class AgentRoleIdentityAssignment(BaseModel):
    """Request body for bulk-assigning identities to a role (or roles to an identity)."""

    identity_ids: list[uuid.UUID] = []


class AgentRoleAssignment(BaseModel):
    """Request body for bulk-assigning roles to an identity."""

    role_ids: list[uuid.UUID] = []


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
    conversation_history: list[dict[str, Any]] | None = None
    created_at: datetime


# ── ModelConfig Schemas ────────────────────────────────────────────────────


class ModelConfigCreate(BaseModel):
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    provider_type: ModelProvider
    api_base_url: str | None = None
    api_key: str | None = None  # Plaintext — encrypted before storage
    enabled_models: list[str] = []  # Allowlist of model IDs; empty = all models allowed


class ModelConfigUpdate(BaseModel):
    display_name: str | None = None
    provider_type: ModelProvider | None = None
    api_base_url: str | None = None
    api_key: str | None = None  # When omitted, existing credential is unchanged
    enabled_models: list[str] | None = None  # None = leave unchanged; [] = clear allowlist


class ModelConfigRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    display_name: str
    provider_type: ModelProvider
    api_base_url: str | None
    has_credentials: bool
    enabled_models: list[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "ModelConfigRead":  # type: ignore[override]
        """Derive has_credentials from encrypted_api_key presence."""
        if hasattr(obj, "encrypted_api_key"):
            data = {
                "id": obj.id,
                "display_name": obj.display_name,
                "provider_type": obj.provider_type,
                "api_base_url": obj.api_base_url,
                "has_credentials": bool(obj.encrypted_api_key),
                "enabled_models": obj.enabled_models or [],
                "created_at": obj.created_at,
                "updated_at": obj.updated_at,
            }
            return super().model_validate(data, **kwargs)
        return super().model_validate(obj, **kwargs)


# ── Agent Type Schemas ─────────────────────────────────────────────────────────────────────────────────


class AgentTypeCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: str | None = None
    identity_id: uuid.UUID | None = None
    role_id: uuid.UUID | None = None
    model_id: str | None = None  # Provider-scoped model identifier (e.g., "gpt-4o")
    system_instruction: str | None = None
    input_type: AgentInputType = AgentInputType.none
    input_schema: dict[str, Any] | None = None
    output_type: AgentOutputType = AgentOutputType.auto
    output_schema: dict[str, Any] | None = None
    primary_sop_id: uuid.UUID | None = None


class AgentTypeUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    identity_id: uuid.UUID | None = None
    role_id: uuid.UUID | None = None
    model_id: str | None = None  # Provider-scoped model identifier
    is_active: bool | None = None
    system_instruction: str | None = None
    input_type: AgentInputType | None = None
    input_schema: dict[str, Any] | None = None
    output_type: AgentOutputType | None = None
    output_schema: dict[str, Any] | None = None
    primary_sop_id: uuid.UUID | None = None


class AgentTypeRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    identity_id: uuid.UUID | None
    role_id: uuid.UUID | None
    model_id: str | None
    is_active: bool
    system_instruction: str | None
    input_type: AgentInputType
    input_schema: dict[str, Any] | None
    output_type: AgentOutputType
    output_schema: dict[str, Any] | None
    primary_sop_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    plan: AgentPlanRead | None = None

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "AgentTypeRead":  # type: ignore[override]
        """Build from ORM object, safely loading the plan relationship only when available."""
        if hasattr(obj, "__tablename__"):  # SQLAlchemy ORM instance
            from sqlalchemy import inspect as sa_inspect

            plan: AgentPlanRead | None = None
            try:
                insp = sa_inspect(obj)
                # Only access the plan relationship if it has already been loaded
                if "plan" not in insp.unloaded:
                    plan_orm = obj.plan
                    if plan_orm is not None:
                        plan = AgentPlanRead.model_validate(plan_orm)
            except Exception:
                pass  # Relationship not loaded or inspect failed — leave plan as None

            data = {
                "id": obj.id,
                "name": obj.name,
                "description": obj.description,
                "identity_id": obj.identity_id,
                "role_id": obj.role_id,
                "model_id": obj.model_id,
                "is_active": obj.is_active,
                "system_instruction": obj.system_instruction,
                "input_type": obj.input_type,
                "input_schema": obj.input_schema,
                "output_type": obj.output_type,
                "output_schema": obj.output_schema,
                "primary_sop_id": obj.primary_sop_id,
                "created_at": obj.created_at,
                "updated_at": obj.updated_at,
                "plan": plan,
            }
            return super().model_validate(data, **kwargs)
        return super().model_validate(obj, **kwargs)


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


# ── Session Execution Log Schemas ──────────────────────────────────────────────


class ExecutionLogEntryRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    session_id: uuid.UUID
    timestamp: datetime
    log_level: str
    event_type: str
    message: str
    data: dict[str, Any]


class ExecutionLogRead(BaseModel):
    """Prompt log entry — system instruction and user prompt captured before the first LLM call."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    session_id: uuid.UUID
    system_instruction: str | None
    user_prompt: str | None
    logged_at: datetime
