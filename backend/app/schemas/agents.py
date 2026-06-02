"""Pydantic v2 schemas for Agent management."""
import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import inspect as sa_inspect

from app.db.models.agents import (
    AgentIdentityStatus,
    AgentIdentityType,
    AgentInputType,
    AgentInstanceStatus,
    AgentJobStatus,
    AgentOutputType,
    AgentPlanStatus,
    GuardrailConversationalContinuationPolicy,
    GuardrailConversationalTokenVisibilityMode,
    GuardrailTokenEnforcementMode,
    GuardrailTokenFallbackMode,
    SessionStopCategory,
    SessionStopReason,
    ModelProvider,
)
from app.db.models.model_guardrail_configuration import (
    ModelGuardrailEnforcementPosture,
    ModelGuardrailPeriod,
    ModelUsageUnit,
)
from app.db.models.model_availability import ModelAvailabilityDisabledReason
from app.db.models.model_usage_posture import ModelUsagePosturePeriod, ModelUsagePostureState
from app.db.models.session_logs import ExecutionActorType, ExecutionEventCategory
from app.db.models.termination_cascade_outcome import TerminationOutcome
from app.db.models.termination_request import (
    TerminationPermissionEvaluationOutcome,
    TerminationRequestStatus,
    TerminationScope,
)

_MIN_MAX_ITERATIONS = 1
_MAX_MAX_ITERATIONS = 1000
_MIN_MAX_DELEGATION_DEPTH = 0
_MAX_MAX_DELEGATION_DEPTH = 32
_MIN_MAX_DELEGATED_STEPS = 0
_MAX_MAX_DELEGATED_STEPS = 5000
_MIN_EXECUTION_TIMEOUT_SECONDS = 1
_MAX_EXECUTION_TIMEOUT_SECONDS = 86400
_MIN_TOKEN_BUDGET = 1
_MAX_TOKEN_BUDGET = 10_000_000


def _validate_guardrail_contract(
    *,
    input_type: AgentInputType,
    guardrail_max_iterations: int,
    guardrail_max_delegation_depth: int,
    guardrail_max_delegated_steps: int,
    guardrail_execution_timeout_seconds: int,
    guardrail_token_budget: int | None,
    guardrail_token_enforcement_mode: GuardrailTokenEnforcementMode,
) -> None:
    if not (_MIN_MAX_ITERATIONS <= guardrail_max_iterations <= _MAX_MAX_ITERATIONS):
        raise ValueError(
            f"guardrail_max_iterations must be between {_MIN_MAX_ITERATIONS} and {_MAX_MAX_ITERATIONS}"
        )
    if not (
        _MIN_MAX_DELEGATION_DEPTH
        <= guardrail_max_delegation_depth
        <= _MAX_MAX_DELEGATION_DEPTH
    ):
        raise ValueError(
            f"guardrail_max_delegation_depth must be between {_MIN_MAX_DELEGATION_DEPTH} and {_MAX_MAX_DELEGATION_DEPTH}"
        )
    if not (
        _MIN_MAX_DELEGATED_STEPS
        <= guardrail_max_delegated_steps
        <= _MAX_MAX_DELEGATED_STEPS
    ):
        raise ValueError(
            f"guardrail_max_delegated_steps must be between {_MIN_MAX_DELEGATED_STEPS} and {_MAX_MAX_DELEGATED_STEPS}"
        )
    if not (
        _MIN_EXECUTION_TIMEOUT_SECONDS
        <= guardrail_execution_timeout_seconds
        <= _MAX_EXECUTION_TIMEOUT_SECONDS
    ):
        raise ValueError(
            "guardrail_execution_timeout_seconds must be between "
            f"{_MIN_EXECUTION_TIMEOUT_SECONDS} and {_MAX_EXECUTION_TIMEOUT_SECONDS}"
        )
    if guardrail_token_budget is not None and not (
        _MIN_TOKEN_BUDGET <= guardrail_token_budget <= _MAX_TOKEN_BUDGET
    ):
        raise ValueError(
            f"guardrail_token_budget must be between {_MIN_TOKEN_BUDGET} and {_MAX_TOKEN_BUDGET} when provided"
        )

    if (
        input_type == AgentInputType.conversation
        and guardrail_token_enforcement_mode == GuardrailTokenEnforcementMode.enforce
    ):
        raise ValueError(
            "Conversational agent types cannot use hard token enforcement mode; use observe mode"
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


class WorkflowGenerationModelOption(BaseModel):
    model_id: str
    config_id: uuid.UUID
    config_display_name: str
    provider_type: ModelProvider


class WorkflowGenerationModelConfigRead(BaseModel):
    selected_model_id: str | None = None
    options: list[WorkflowGenerationModelOption]


class WorkflowGenerationModelConfigUpdate(BaseModel):
    model_id: str | None = None


# ── Agent Job Schemas ──────────────────────────────────────────────────────────


class AgentJobCreate(BaseModel):
    agent_type_id: uuid.UUID
    input_data: dict[str, Any] | None = None


class AgentJobStatusRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    agent_type_id: uuid.UUID
    status: AgentJobStatus
    stop_category: SessionStopCategory | None = None
    stop_reason: SessionStopReason | None = None
    stop_details: dict[str, Any] | None = None
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
    stop_category: SessionStopCategory | None = None
    stop_reason: SessionStopReason | None = None
    stop_details: dict[str, Any] | None = None
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
    is_disabled: bool = False
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
                "is_disabled": bool(getattr(obj, "is_disabled", False)),
                "created_at": obj.created_at,
                "updated_at": obj.updated_at,
            }
            return super().model_validate(data, **kwargs)
        return super().model_validate(obj, **kwargs)


# ── Model Usage Guardrail Schemas ───────────────────────────────────────────
#
# Phase 3.7 rework: the previous flat per-model row with four period-limit
# columns is replaced by ONE row per (model, period). The body shape below
# creates exactly one guardrail per call. The frontend passes the model
# NAME (the canonical provider-scoped identifier, e.g. "gpt-4.1-nano") as
# ``model_id``; ``model_config_id`` is the resolved vendor UUID so the API
# contract can carry both shapes for backwards compatibility with the
# existing `useAvailableModels` hook. The service resolves the name to a
# ModelConfig in-Python (see ``ModelUsageGuardrailService``).


class ModelUsageGuardrailLimitCreate(BaseModel):
    """Create a single per-period guardrail row.

    The service resolves ``model_id`` (the provider-scoped model name) to a
    ModelConfig UUID and stores the FK + the human-friendly name. Callers
    MAY also pass ``model_config_id`` directly if they already know the
    vendor UUID.
    """

    model_id: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    model_config_id: uuid.UUID | None = None
    period: ModelGuardrailPeriod
    limit_value: int = Field(ge=0)
    unit: ModelUsageUnit = ModelUsageUnit.k
    enforcement_posture: ModelGuardrailEnforcementPosture = (
        ModelGuardrailEnforcementPosture.terminate
    )
    is_active: bool = True
    details: dict[str, Any] | None = None


class ModelUsageGuardrailLimitUpdate(BaseModel):
    """Partial update of a single per-period guardrail row.

    ``model_id`` and ``period`` are immutable (use delete + create to change
    them); everything else can be updated independently.
    """

    limit_value: int | None = Field(default=None, ge=0)
    unit: ModelUsageUnit | None = None
    enforcement_posture: ModelGuardrailEnforcementPosture | None = None
    is_active: bool | None = None
    details: dict[str, Any] | None = None


class ModelUsageGuardrailLimitRead(BaseModel):
    """Read shape for a single per-period guardrail row."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    model_id: uuid.UUID
    model_name: str
    period: ModelGuardrailPeriod
    limit_value: int
    unit: ModelUsageUnit
    enforcement_posture: ModelGuardrailEnforcementPosture
    is_active: bool
    details: dict[str, Any]
    created_at: datetime
    updated_at: datetime


# ── Model Availability Schemas ──────────────────────────────────────────────


class ModelAvailabilityCreate(BaseModel):
    """Create a per-model availability row under a vendor."""

    model_name: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    vendor_model_config_id: uuid.UUID
    is_disabled: bool = False
    disabled_reason: ModelAvailabilityDisabledReason = (
        ModelAvailabilityDisabledReason.manual
    )


class ModelAvailabilityRead(BaseModel):
    """Read shape for a per-model availability row."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    model_name: str
    vendor_model_config_id: uuid.UUID
    is_disabled: bool
    disabled_reason: ModelAvailabilityDisabledReason
    created_at: datetime
    updated_at: datetime


class ModelAvailabilityUpdate(BaseModel):
    """Update payload for a per-model availability row.

    Operators can also use the ``reason`` field to record why a vendor or
    model was disabled, surfacing in the dashboard and execution logs.
    """

    is_disabled: bool
    reason: Annotated[str | None, StringConstraints(max_length=500)] = None


class VendorDisabledUpdate(BaseModel):
    """Update payload for the vendor-level ``ModelConfig.is_disabled`` toggle."""

    is_disabled: bool
    reason: Annotated[str | None, StringConstraints(max_length=500)] = None


class PreflightAvailabilityRequest(BaseModel):
    """Request shape for the Agent Runtime pre-execution availability check.

    ``model_id`` is the provider-scoped model name (e.g. "gpt-4o"); the
    service resolves it to a vendor ModelConfig to evaluate the cascade
    state. ``vendor_model_config_id`` is optional — when omitted, the
    service considers all vendors that offer the model.
    """

    model_id: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    vendor_model_config_id: uuid.UUID | None = None


class PreflightAvailabilityResponse(BaseModel):
    """Response shape for the pre-execution availability check."""

    allowed: bool
    reason: str | None = None
    disabled_reason: ModelAvailabilityDisabledReason | None = None
    blocked_by: Annotated[
        str | None,
        StringConstraints(max_length=64),
    ] = None  # "model_disabled" | "vendor_disabled" | "model_not_found"


class ModelAvailabilityGuardrailSummary(BaseModel):
    """One guardrail row summary as embedded in the hierarchy view."""

    id: uuid.UUID
    period: ModelGuardrailPeriod
    limit_value: int
    unit: ModelUsageUnit
    enforcement_posture: ModelGuardrailEnforcementPosture
    is_active: bool
    usage_value: int | None = None
    posture_state: ModelUsagePostureState | None = None


class ModelAvailabilityModelRead(BaseModel):
    """One model row in the vendor → model hierarchy."""

    model_name: str
    # Effective disable state for this (vendor, model_name) pair —
    # true when the per-model row is disabled OR the vendor is disabled
    # (vendor cascade). Frontend-facing field name is ``is_disabled``
    # so it can be treated as a simple on/off flag in the UI.
    is_disabled: bool
    disabled_reason: ModelAvailabilityDisabledReason
    guardrails: list[ModelAvailabilityGuardrailSummary] = []


class ModelAvailabilityVendorRead(BaseModel):
    """One vendor row in the vendor → model hierarchy.

    Field names are aligned with the frontend
    ``ModelAvailabilityHierarchy = VendorAvailabilityNode[]`` type so
    the dashboard's ``hierarchy.map(vendor => ...)`` and switch handlers
    work without ad-hoc renames.
    """

    vendor_config_id: uuid.UUID
    vendor_display_name: str
    is_disabled: bool
    models: list[ModelAvailabilityModelRead] = []


class ModelUsagePostureRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    model_guardrail_configuration_id: uuid.UUID
    model_id: uuid.UUID
    posture_period: ModelUsagePosturePeriod
    usage_value: int
    limit_value: int
    posture_state: ModelUsagePostureState
    observed_at: datetime
    details: dict[str, Any]


# ── Runtime Control Schemas ────────────────────────────────────────────────


class RuntimeTopologyNodeRead(BaseModel):
    session_id: uuid.UUID
    agent_type_id: uuid.UUID
    agent_type_name: str | None = None
    # Phase 3.13/3.16: ``status`` is a free-form string.  For
    # ``kind="agent"`` nodes it carries the ``AgentJobStatus``
    # value (queued/running/completed/failed/terminated).  For
    # ``kind="instance"`` nodes it carries the
    # ``AgentInstanceStatus`` value (created/active/closed/error).
    # For ``kind="conversation"`` nodes it carries the effective
    # *runtime* status — either the literal ``ConversationStatus``
    # value (closed/archived/error) or one of the synthetic runtime
    # values:
    #   - "active" — a backing AgentJob is in {queued, running}
    #   - "sleep"  — the session is open but no agent is currently
    #               driving it (e.g. user opened the chat but hasn't
    #               sent a message yet, or the previous turn's agent
    #               has finished and a new one hasn't started)
    # Frontend renders it via the appropriate i18n key based on
    # ``kind``.
    status: str
    depth_from_root: int
    parent_session_id: uuid.UUID | None = None
    started_at: datetime | None = None
    created_at: datetime
    termination_category: str | None = None
    # Phase 3.13/3.16: distinguishes agent runs ("agent"),
    # conversation sessions ("conversation"), and agent instances
    # ("instance").  Defaults to "agent" for backwards
    # compatibility.
    kind: str = "agent"
    title: str | None = None


class RuntimeTopologyEdgeRead(BaseModel):
    parent_session_id: uuid.UUID
    child_session_id: uuid.UUID
    depth_from_root: int


class RuntimeTopologyRead(BaseModel):
    nodes: list[RuntimeTopologyNodeRead]
    edges: list[RuntimeTopologyEdgeRead]
    root_session_ids: list[uuid.UUID]


class RuntimeTerminalJobPurgeRead(BaseModel):
    """Result of purging completed/failed agent jobs to release resources."""

    purged_count: int
    remaining_terminal_count: int
    cutoff: datetime
    statuses: list[AgentJobStatus]


class RuntimeTerminateRequest(BaseModel):
    target_session_id: uuid.UUID
    termination_scope: TerminationScope = TerminationScope.cascade_subtree
    operator_reason: Annotated[str | None, StringConstraints(max_length=1000)] = None


class TerminationRequestRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    requested_by_user_id: uuid.UUID
    target_agent_job_id: uuid.UUID
    termination_scope: TerminationScope
    permission_evaluation_outcome: TerminationPermissionEvaluationOutcome
    permission_evaluation_reason: str | None = None
    request_status: TerminationRequestStatus
    requested_at: datetime
    completed_at: datetime | None = None


class TerminationCascadeOutcomeRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    termination_request_id: uuid.UUID
    affected_agent_job_id: uuid.UUID
    cascade_level: int
    termination_outcome: TerminationOutcome
    outcome_reason: str | None = None
    processed_at: datetime


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
    guardrail_max_iterations: int = 10
    guardrail_max_delegation_depth: int = 3
    guardrail_max_delegated_steps: int = 20
    guardrail_execution_timeout_seconds: int = 300
    guardrail_token_budget: int | None = None
    guardrail_token_enforcement_mode: GuardrailTokenEnforcementMode = (
        GuardrailTokenEnforcementMode.observe
    )
    guardrail_token_fallback_mode: GuardrailTokenFallbackMode = (
        GuardrailTokenFallbackMode.observe_and_log
    )
    guardrail_conversational_token_visibility_mode: GuardrailConversationalTokenVisibilityMode = (
        GuardrailConversationalTokenVisibilityMode.enabled
    )
    guardrail_conversational_continuation_policy: GuardrailConversationalContinuationPolicy = (
        GuardrailConversationalContinuationPolicy.allow
    )

    @model_validator(mode="after")
    def _validate_guardrails(self) -> "AgentTypeCreate":
        _validate_guardrail_contract(
            input_type=self.input_type,
            guardrail_max_iterations=self.guardrail_max_iterations,
            guardrail_max_delegation_depth=self.guardrail_max_delegation_depth,
            guardrail_max_delegated_steps=self.guardrail_max_delegated_steps,
            guardrail_execution_timeout_seconds=self.guardrail_execution_timeout_seconds,
            guardrail_token_budget=self.guardrail_token_budget,
            guardrail_token_enforcement_mode=self.guardrail_token_enforcement_mode,
        )
        return self


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
    guardrail_max_iterations: int | None = None
    guardrail_max_delegation_depth: int | None = None
    guardrail_max_delegated_steps: int | None = None
    guardrail_execution_timeout_seconds: int | None = None
    guardrail_token_budget: int | None = None
    guardrail_token_enforcement_mode: GuardrailTokenEnforcementMode | None = None
    guardrail_token_fallback_mode: GuardrailTokenFallbackMode | None = None
    guardrail_conversational_token_visibility_mode: GuardrailConversationalTokenVisibilityMode | None = None
    guardrail_conversational_continuation_policy: GuardrailConversationalContinuationPolicy | None = None


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
    guardrail_max_iterations: int
    guardrail_max_delegation_depth: int
    guardrail_max_delegated_steps: int
    guardrail_execution_timeout_seconds: int
    guardrail_token_budget: int | None
    guardrail_token_enforcement_mode: GuardrailTokenEnforcementMode
    guardrail_token_fallback_mode: GuardrailTokenFallbackMode
    guardrail_conversational_token_visibility_mode: GuardrailConversationalTokenVisibilityMode
    guardrail_conversational_continuation_policy: GuardrailConversationalContinuationPolicy
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
                "guardrail_max_iterations": obj.guardrail_max_iterations,
                "guardrail_max_delegation_depth": obj.guardrail_max_delegation_depth,
                "guardrail_max_delegated_steps": obj.guardrail_max_delegated_steps,
                "guardrail_execution_timeout_seconds": obj.guardrail_execution_timeout_seconds,
                "guardrail_token_budget": obj.guardrail_token_budget,
                "guardrail_token_enforcement_mode": obj.guardrail_token_enforcement_mode,
                "guardrail_token_fallback_mode": obj.guardrail_token_fallback_mode,
                "guardrail_conversational_token_visibility_mode": obj.guardrail_conversational_token_visibility_mode,
                "guardrail_conversational_continuation_policy": obj.guardrail_conversational_continuation_policy,
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
    event_category: ExecutionEventCategory
    correlation_id: str | None = None
    actor_type: ExecutionActorType
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
