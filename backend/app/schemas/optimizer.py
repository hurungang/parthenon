"""Pydantic v2 schemas for the conversational optimizer (optimization mode).

Security invariant: **no endpoint accepts a scope or a second agent type.**
The subject is the conversation's own ``agent_type_id`` and is never
re-supplied by a client after creation.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.db.models.agents import ModelProvider
from app.schemas.conversations import ConversationSessionRead


# ── Optimizer model configuration (workspace-scoped) ─────────────────────────


class OptimizerModelOptionRead(BaseModel):
    """One selectable model from the session tenant's enabled catalogue."""

    model_id: str
    config_id: uuid.UUID
    config_display_name: str
    provider_type: ModelProvider


class OptimizerModelConfigRead(BaseModel):
    """Workspace optimizer-model selection + derived (read-time) state.

    ``selected_model_id`` echoes the RAW stored value (a stale value stays
    visible so the UI can ask for a re-select); ``effective_model_id`` is the
    model optimization would actually run on (the selection, or the inherited
    plan-authoring model).
    """

    selected_model_id: str | None = None
    effective_model_id: str | None = None
    source: str | None = None  # "optimizer" | "authoring" | None
    configured: bool = False
    enabled: bool = False
    reason_code: str | None = None
    options: list[OptimizerModelOptionRead] = Field(default_factory=list)


class OptimizerModelConfigUpdate(BaseModel):
    """Set the workspace optimizer model; ``null`` clears (inherit authoring)."""

    model_id: str | None = None


# ── Optimization conversation ────────────────────────────────────────────────


class OptimizationConversationCreate(BaseModel):
    """Request body for ``POST /conversations/optimization`` (subject only)."""

    agent_type_id: uuid.UUID


class OptimizationSubjectRead(BaseModel):
    """The conversation's subject agent type (the agent being optimized)."""

    agent_type_id: uuid.UUID
    name: str
    input_type: str
    is_conversational: bool


class OptimizerModelStateRead(BaseModel):
    """Optimizer-model projection inside an availability payload."""

    model_id: str | None = None
    effective_model_id: str | None = None
    source: str | None = None
    configured: bool = False
    enabled: bool = False
    reason_code: str | None = None


class OptimizationAvailabilityRead(BaseModel):
    """Computed (never stored) availability of the optimization conversation.

    Opening the conversation always succeeds; ``available`` answers "may
    optimization WORK start now?". A missing optimized plan is informational
    (``plan_present``), never a block.
    """

    available: bool
    reason_code: str | None = None
    reason: str | None = None
    can_start_work: bool = False
    plan_present: bool = False
    optimized_plan_status: str | None = None
    successful_executions: int = 0
    optimizer_model: OptimizerModelStateRead


class OptimizationAuditRead(BaseModel):
    """Replay-vs-live audit projection for a conversation.

    ``replay_verifications`` counts ``execute_script`` replay calls;
    ``live_operations`` counts tool calls flagged with an approved live-test
    pointer. ``replay_only`` is true while nothing has run live.
    """

    replay_verifications: int = 0
    live_operations: int = 0
    last_live_at: datetime | None = None
    replay_only: bool = True


class OptimizationConversationRead(BaseModel):
    """Created/read optimization conversation with subject + availability."""

    conversation: ConversationSessionRead
    subject: OptimizationSubjectRead
    availability: OptimizationAvailabilityRead


class OptimizationConversationDetailRead(OptimizationConversationRead):
    """Optimization conversation read payload used on open/resume/reconnect."""

    audit: OptimizationAuditRead


# ── Live-test ledger reads (state machine lands in a later chunk) ────────────


class LiveTestOperationRead(BaseModel):
    """One entry of the tool-call PREVIEW of the script that will run.

    Derived server-side from the approved version's ``tools.call(...)`` lines;
    it is evidence for the approval card, not the unit of execution.
    """

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    purpose: str | None = None


class LiveTestDecisionRead(BaseModel):
    """Decision attribution read from the linked ``InterveneResponse``."""

    approval_value: bool | None = None
    operator_user_id: uuid.UUID | None = None
    responded_at: datetime | None = None


class LiveTestRequestRead(BaseModel):
    """One live-test ledger row for a conversation (newest first in lists)."""

    id: uuid.UUID
    status: str
    target_agent_type_id: uuid.UUID
    script_version_id: uuid.UUID | None = None
    script_name: str | None = None
    script_version_label: str | None = None
    requested_operations: list[LiveTestOperationRead] = Field(default_factory=list)
    executed_operations: list[dict[str, Any]] | None = None
    expires_at: datetime | None = None
    execution_started_at: datetime | None = None
    execution_finished_at: datetime | None = None
    decision: LiveTestDecisionRead | None = None
    created_at: datetime | None = None
