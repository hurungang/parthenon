"""Pydantic v2 schemas for Agent management."""
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, StringConstraints, model_validator
from sqlalchemy import inspect as sa_inspect

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
        """Extract sop_ids / skill_ids without triggering lazy relationship loads."""
        if hasattr(obj, "__tablename__"):
            sop_ids: list[uuid.UUID] = []
            skill_ids: list[uuid.UUID] = []

            try:
                insp = sa_inspect(obj)
                if "sop_assignments" not in insp.unloaded:
                    sop_ids = [a.sop_id for a in obj.sop_assignments]
                if "skill_assignments" not in insp.unloaded:
                    skill_ids = [a.skill_id for a in obj.skill_assignments]
            except Exception:
                # Keep default empty lists when inspection is unavailable.
                pass

            data = {
                "id": obj.id,
                "name": obj.name,
                "description": obj.description,
                "sop_ids": sop_ids,
                "skill_ids": skill_ids,
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


class AgentIdentityCreate(BaseModel):
    name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, pattern=r"^[a-z0-9\-]+$"),
    ]
    identity_type: AgentIdentityType = AgentIdentityType.realm_user
    realm_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    realm_username: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    status: AgentIdentityStatus = AgentIdentityStatus.active


class AgentIdentityUpdate(BaseModel):
    name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, pattern=r"^[a-z0-9\-]+$"),
    ] | None = None
    realm_name: str | None = None
    realm_username: str | None = None
    status: AgentIdentityStatus | None = None

    @model_validator(mode="before")
    @classmethod
    def _compute_has_refresh_token(cls, v: Any) -> Any:
        """Derive has_refresh_token from the ORM model without exposing the encrypted token."""
        if not isinstance(v, dict) and hasattr(v, "refresh_token"):
            return {
                "id": v.id,
                "name": v.name,
                "identity_type": v.identity_type,
                "realm_name": v.realm_name,
                "realm_username": v.realm_username,
                "status": v.status,
                "token_expires_at": v.token_expires_at,
                "has_refresh_token": v.refresh_token is not None,
                "created_at": v.created_at,
                "updated_at": v.updated_at,
            }
        return v


class AgentIdentityRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    identity_type: AgentIdentityType
    realm_name: str | None
    realm_username: str | None
    status: AgentIdentityStatus
    token_expires_at: datetime | None
    has_refresh_token: bool = False  # True when an encrypted refresh token is stored
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _compute_has_refresh_token(cls, v: Any) -> Any:
        """Derive has_refresh_token from the ORM model without exposing the encrypted token."""
        if not isinstance(v, dict) and hasattr(v, "refresh_token"):
            return {
                "id": v.id,
                "name": v.name,
                "identity_type": v.identity_type,
                "realm_name": v.realm_name,
                "realm_username": v.realm_username,
                "status": v.status,
                "token_expires_at": v.token_expires_at,
                "has_refresh_token": v.refresh_token is not None,
                "created_at": v.created_at,
                "updated_at": v.updated_at,
            }
        return v


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


# ── A2A (Agent-to-Agent) Communication Schemas ────────────────────────────────


class A2ARequest(BaseModel):
    """Request to initiate A2A communication through Communication Hub.

    Used by SopOrchestrator to delegate to another agent type.
    """

    target_agent_type_slug: str
    conversation_metadata: dict[str, Any]
    request_payload: dict[str, Any]


class A2AResponse(BaseModel):
    """Response from Communication Hub when A2A request is accepted."""

    receiver_instance_id: str
    session_link_id: str
    status: str  # "accepted" or error message
    receiver_session_id: str | None = None
    response_payload: dict[str, Any] | None = None


class A2ASessionRead(BaseModel):
    """Read schema for agent A2A session records."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    requester_instance_id: str
    receiver_instance_id: str
    receiver_is_dynamic: bool
    session_link_id: str
    status: str
    created_at: datetime
    disconnect_at: datetime | None


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
    name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, pattern=r"^[a-z0-9\-]+$"),
    ]
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
    name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, pattern=r"^[a-z0-9\-]+$"),
    ] | None = None
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
