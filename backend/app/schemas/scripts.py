"""Pydantic v2 schemas for the Software 3.0 script registry APIs.

Covers the REST router (`/api/v1/scripts`) and the internal CC↔AR router
(`/api/v1/internal/scripts`). Step graphs are tool-name-only references —
no credentials or tokens may appear anywhere in these payloads (SEC3).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.db.models.script_execution import (
    ScriptExecutionOutcome,
    ScriptExecutionRecord,
)
from app.db.models.script_registry import (
    FallbackEvent,
    FallbackResultingAction,
    FallbackTriggerReason,
    RepairAttempt,
    RepairRetryOutcome,
    SandboxValidationStatus,
    ScriptDefinition,
    ScriptHealthStatus,
    ScriptLifecycleStatus,
    ScriptVersion,
    VerificationComparisonOutcome,
    VerificationRun,
    VerificationVerdict,
)


# ── Script definitions & versions ─────────────────────────────────────────────


class ScriptDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    agent_type_id: uuid.UUID
    description: str | None = None
    source_plan_id: uuid.UUID | None = None
    source_session_id: uuid.UUID | None = None


class ScriptVersionCreate(BaseModel):
    """Candidate version submission (compiler output or operator action)."""

    declarative_step_graph: dict[str, Any] | None = None    # Model-authored sandboxed Python source (immutable per version, N3).
    python_source: str | None = None
    # Per-version sandbox resource caps (N1; platform defaults when null).
    cpu_limit_seconds: int | None = None
    memory_limit_mb: int | None = None
    wall_time_limit_seconds: int | None = None
    # Compiler-as-validator outcome (Phase 2.2).
    sandbox_validation_status: SandboxValidationStatus = (
        SandboxValidationStatus.pending
    )
    sandbox_validation_reason: str | None = None
    version_label: str | None = Field(default=None, max_length=50)
    parent_version_id: uuid.UUID | None = None
    content_reference: str | None = None
    compiled_from_source: str | None = None
    created_by: str | None = None

    @model_validator(mode="after")
    def _require_content(self) -> "ScriptVersionCreate":
        if self.declarative_step_graph is None and self.python_source is None:
            raise ValueError(
                "a candidate requires declarative_step_graph or python_source"
            )
        return self


class ScriptVersionResponse(BaseModel):
    id: uuid.UUID
    script_definition_id: uuid.UUID
    version_label: str
    lifecycle_status: ScriptLifecycleStatus
    declarative_step_graph: dict[str, Any] | None
    python_source: str | None = None
    cpu_limit_seconds: int | None = None
    memory_limit_mb: int | None = None
    wall_time_limit_seconds: int | None = None
    sandbox_validation_status: SandboxValidationStatus = (
        SandboxValidationStatus.pending
    )
    sandbox_validation_reason: str | None = None
    parent_version_id: uuid.UUID | None
    repaired_from_id: uuid.UUID | None
    created_by: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, v: ScriptVersion) -> "ScriptVersionResponse":
        return cls(
            id=v.id,
            script_definition_id=v.script_definition_id,
            version_label=v.version_label,
            lifecycle_status=v.lifecycle_status,
            declarative_step_graph=v.declarative_step_graph,
            python_source=v.python_source,
            cpu_limit_seconds=v.cpu_limit_seconds,
            memory_limit_mb=v.memory_limit_mb,
            wall_time_limit_seconds=v.wall_time_limit_seconds,
            sandbox_validation_status=v.sandbox_validation_status,
            sandbox_validation_reason=v.sandbox_validation_reason,
            parent_version_id=v.parent_version_id,
            repaired_from_id=v.repaired_from_id,
            created_by=v.created_by,
            created_at=v.created_at,
        )


class ScriptDefinitionResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    lifecycle_status: ScriptLifecycleStatus
    health_status: ScriptHealthStatus
    agent_type_id: uuid.UUID
    source_plan_id: uuid.UUID | None
    source_session_id: uuid.UUID | None
    current_version_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    versions: list[ScriptVersionResponse] = Field(default_factory=list)

    @classmethod
    def from_model(cls, d: ScriptDefinition) -> "ScriptDefinitionResponse":
        return cls(
            id=d.id,
            name=d.name,
            description=d.description,
            lifecycle_status=d.lifecycle_status,
            health_status=d.health_status,
            agent_type_id=d.agent_type_id,
            source_plan_id=d.source_plan_id,
            source_session_id=d.source_session_id,
            current_version_id=d.current_version_id,
            created_at=d.created_at,
            updated_at=d.updated_at,
            versions=[ScriptVersionResponse.from_model(v) for v in (d.versions or [])],
        )


class ScriptDefinitionListResponse(BaseModel):
    items: list[ScriptDefinitionResponse]
    total: int


class LifecycleTransitionRequest(BaseModel):
    target_status: ScriptLifecycleStatus


class VersionDiffResponse(BaseModel):
    version_id: uuid.UUID
    against_version_id: uuid.UUID
    steps_added: list[str]
    steps_removed: list[str]
    steps_changed: list[dict[str, Any]]
    tolerance_changed: bool


# ── Verification ──────────────────────────────────────────────────────────────


class VerificationRunResponse(BaseModel):
    id: uuid.UUID
    script_version_id: uuid.UUID
    reference_execution_id: uuid.UUID | None
    comparison_outcome: VerificationComparisonOutcome
    verdict: VerificationVerdict
    verdict_reason: str | None
    input_context: dict[str, Any] | None
    expected_output: dict[str, Any] | None
    actual_output: dict[str, Any] | None
    # Sandbox-compliance evidence (N3).
    sandbox_check_passed: bool | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, r: VerificationRun) -> "VerificationRunResponse":
        return cls(
            id=r.id,
            script_version_id=r.script_version_id,
            reference_execution_id=r.reference_execution_id,
            comparison_outcome=r.comparison_outcome,
            verdict=r.verdict,
            verdict_reason=r.verdict_reason,
            input_context=r.input_context,
            expected_output=r.expected_output,
            actual_output=r.actual_output,
            sandbox_check_passed=r.sandbox_check_passed,
            created_at=r.created_at,
        )


class VerificationRunListResponse(BaseModel):
    items: list[VerificationRunResponse]
    total: int


class PromoteVersionRequest(BaseModel):
    """Internal: AR promotes a verified script version to compiled (serving)."""

    script_version_id: uuid.UUID
    actor: str | None = "agent-runtime-autocompile"


class VerificationSubmitRequest(BaseModel):
    """Internal: AR Verification Engine submits evidence + outcome (V2)."""

    script_version_id: uuid.UUID
    comparison_outcome: VerificationComparisonOutcome
    verdict_reason: str | None = None
    input_context: dict[str, Any] | None = None
    expected_output: dict[str, Any] | None = None
    actual_output: dict[str, Any] | None = None
    reference_execution_id: uuid.UUID | None = None
    # Sandbox-compliance evidence (N3).
    sandbox_check_passed: bool | None = None


# ── Fallbacks & executions ────────────────────────────────────────────────────


class FallbackEventResponse(BaseModel):
    id: uuid.UUID
    execution_record_id: uuid.UUID
    script_version_id: uuid.UUID | None
    trigger_reason: FallbackTriggerReason
    resulting_action: FallbackResultingAction
    failure_detail: str | None
    script_health_impact: int
    repaired_version_id: uuid.UUID | None
    created_at: datetime

    @classmethod
    def from_model(cls, e: FallbackEvent) -> "FallbackEventResponse":
        return cls(
            id=e.id,
            execution_record_id=e.execution_record_id,
            script_version_id=e.script_version_id,
            trigger_reason=e.trigger_reason,
            resulting_action=e.resulting_action,
            failure_detail=e.failure_detail,
            script_health_impact=e.script_health_impact,
            repaired_version_id=e.repaired_version_id,
            created_at=e.created_at,
        )


class FallbackEventListResponse(BaseModel):
    items: list[FallbackEventResponse]
    total: int


class FallbackReportRequest(BaseModel):
    """Internal: AR Fallback Controller reports a fallback (F2)."""

    execution_record_id: uuid.UUID
    script_version_id: uuid.UUID | None = None
    trigger_reason: FallbackTriggerReason
    resulting_action: FallbackResultingAction
    failure_detail: str | None = None
    repaired_version_id: uuid.UUID | None = None


class ExecutionRecordResponse(BaseModel):
    id: uuid.UUID
    script_version_id: uuid.UUID | None
    outcome: ScriptExecutionOutcome
    duration_ms: int | None
    tools_invoked: list[Any] | None
    model_backed_steps_used: list[Any] | None
    session_id: uuid.UUID | None
    identity_parity_confirmed: bool | None
    tokens_saved_estimate: int | None
    # Measured accounting + sandbox failure evidence (N5/Flow C).
    tokens_saved_actual: int | None = None
    sandbox_termination: bool | None = None
    sandbox_violation_detail: str | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, r: ScriptExecutionRecord) -> "ExecutionRecordResponse":
        return cls(
            id=r.id,
            script_version_id=r.script_version_id,
            outcome=r.outcome,
            duration_ms=r.duration_ms,
            tools_invoked=r.tools_invoked,
            model_backed_steps_used=r.model_backed_steps_used,
            session_id=r.session_id,
            identity_parity_confirmed=r.identity_parity_confirmed,
            tokens_saved_estimate=r.tokens_saved_estimate,
            tokens_saved_actual=r.tokens_saved_actual,
            sandbox_termination=r.sandbox_termination,
            sandbox_violation_detail=r.sandbox_violation_detail,
            created_at=r.created_at,
        )


class ExecutionRecordListResponse(BaseModel):
    items: list[ExecutionRecordResponse]
    total: int


class ExecutionReportRequest(BaseModel):
    """Internal: AR reports a compiled/fallback execution record (G2)."""

    script_version_id: uuid.UUID | None = None
    outcome: ScriptExecutionOutcome
    duration_ms: int | None = None
    tools_invoked: list[dict[str, Any]] | None = None
    model_backed_steps_used: list[dict[str, Any]] | None = None
    session_id: uuid.UUID | None = None
    identity_parity_confirmed: bool | None = None
    tokens_saved_estimate: int | None = None
    # Measured accounting + sandbox failure evidence (N5/Flow C).
    tokens_saved_actual: int | None = None
    sandbox_termination: bool | None = None
    sandbox_violation_detail: str | None = None


# ── Health ────────────────────────────────────────────────────────────────────


class HealthSummaryResponse(BaseModel):
    script_definition_id: uuid.UUID
    health_status: ScriptHealthStatus
    lifecycle_status: ScriptLifecycleStatus
    recent_fallback_count: int
    total_fallback_count: int
    latest_fallback: dict[str, Any] | None


# ── Candidates, repair & reports ──────────────────────────────────────────────


class CandidateSubmitRequest(BaseModel):
    """Internal: AR compiler submits a candidate step graph (C2)."""

    agent_type_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    declarative_step_graph: dict[str, Any] | None = None
    # Model-authored sandboxed Python source + caps + validation outcome.
    python_source: str | None = None
    cpu_limit_seconds: int | None = None
    memory_limit_mb: int | None = None
    wall_time_limit_seconds: int | None = None
    sandbox_validation_status: SandboxValidationStatus = (
        SandboxValidationStatus.pending
    )
    sandbox_validation_reason: str | None = None
    description: str | None = None
    source_plan_id: uuid.UUID | None = None
    source_session_id: uuid.UUID | None = None
    parent_version_id: uuid.UUID | None = None
    version_label: str | None = Field(default=None, max_length=50)
    created_by: str | None = None
    # Execution semantics: fully_scripted candidates are served directly by
    # the dispatcher (zero-LLM); others are invocable virtual tools only.
    fully_scripted: bool = False

    @model_validator(mode="after")
    def _require_content(self) -> "CandidateSubmitRequest":
        if self.declarative_step_graph is None and self.python_source is None:
            raise ValueError(
                "a candidate requires declarative_step_graph or python_source"
            )
        return self


class RepairCandidateRequest(BaseModel):
    """Internal: AR reports a repair attempt + repaired candidate (E9/E10, F3).

    CC persists the RepairAttempt record (defect diagnosis, diff, retry
    outcome) and spawns the repaired candidate as a new draft ScriptVersion
    with ``repaired_from`` lineage.
    """

    script_version_id: uuid.UUID
    declarative_step_graph: dict[str, Any]
    defect_diagnosis: str = Field(min_length=1)
    diff_applied: str | None = None
    attempt_number: int = Field(default=1, ge=1)
    retry_outcome: RepairRetryOutcome = RepairRetryOutcome.pending
    created_by: str | None = None


class RepairAttemptResponse(BaseModel):
    id: uuid.UUID
    fallback_event_id: uuid.UUID
    script_version_id: uuid.UUID | None
    repaired_version_id: uuid.UUID | None
    defect_diagnosis: str
    diff_applied: str | None
    retry_outcome: RepairRetryOutcome
    created_at: datetime

    @classmethod
    def from_model(cls, r: RepairAttempt) -> "RepairAttemptResponse":
        return cls(
            id=r.id,
            fallback_event_id=r.fallback_event_id,
            script_version_id=r.script_version_id,
            repaired_version_id=r.repaired_version_id,
            defect_diagnosis=r.defect_diagnosis,
            diff_applied=r.diff_applied,
            retry_outcome=r.retry_outcome,
            created_at=r.created_at,
        )


class RepairAttemptListResponse(BaseModel):
    items: list[RepairAttemptResponse]
    total: int


class ServingVersionResponse(BaseModel):
    """Internal: current serving script version for a workflow (script-first
    dispatch lookup; absent → LLM path). No mode is returned."""

    script_definition_id: uuid.UUID | None
    # Definition name — legacy auto-compiled scripts use ``auto-<id8>``;
    # command-authored optimized scripts carry agent-chosen names.
    script_definition_name: str | None = None
    # Lineage: set when the definition was authored/linked by an optimized
    # plan — the authoritative optimized-artifact signal for the dispatcher.
    source_optimized_plan_id: uuid.UUID | None = None
    script_version_id: uuid.UUID | None
    script_version_label: str | None
    declarative_step_graph: dict[str, Any] | None
    # Model-authored sandboxed source + caps + validator outcome (N3).
    python_source: str | None = None
    sandbox_validation_status: SandboxValidationStatus | None = None
    cpu_limit_seconds: int | None = None
    memory_limit_mb: int | None = None
    wall_time_limit_seconds: int | None = None
    # Measured reference-run token usage for tokens_saved_actual (N5).
    reference_tokens: int | None = None
    # Execution semantics: only fully_scripted versions are served directly
    # by the dispatcher; others are invocable ``script____<name>`` tools.
    fully_scripted: bool = False


class InvocableScriptResponse(BaseModel):
    """Internal: one compiled script exposed as a ``script____<name>`` virtual
    tool. Consumed by the Agent Runtime tool surface and execution endpoint."""

    script_definition_id: uuid.UUID
    script_version_id: uuid.UUID
    script_version_label: str | None = None
    name: str
    description: str | None = None
    declarative_step_graph: dict[str, Any] | None = None
    python_source: str | None = None
    sandbox_validation_status: SandboxValidationStatus | None = None
    cpu_limit_seconds: int | None = None
    memory_limit_mb: int | None = None
    wall_time_limit_seconds: int | None = None
    fully_scripted: bool = False


class CostReportResponse(BaseModel):
    total_executions: int
    script_runs: int
    llm_runs: int
    fallback_runs: int
    script_hit_rate: float
    fallback_rate: float
    tokens_saved_total: int
    residual_model_backed_steps: int
