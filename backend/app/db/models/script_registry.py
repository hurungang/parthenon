"""SQLAlchemy models for the Software 3.0 script registry: ScriptDefinition, ScriptVersion, VerificationRun, FallbackEvent, RepairAttempt.

All registry data is owned by Control Center (the sole DB gateway); Agent
Runtime consumes it only via Control Center APIs.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


# ── Enums ─────────────────────────────────────────────────────────────────────


class ScriptLifecycleStatus(str, enum.Enum):
    """Lifecycle status of a script definition or an individual script version.

    Allowed progression: draft -> verified -> compiled -> retired.
    """

    draft = "draft"
    verified = "verified"
    compiled = "compiled"
    retired = "retired"


class ScriptHealthStatus(str, enum.Enum):
    """Aggregate health of a script derived from recent fallback behavior (F4)."""

    healthy = "healthy"
    degraded = "degraded"
    unhealthy = "unhealthy"


class VerificationComparisonOutcome(str, enum.Enum):
    """Outcome of comparing a script version's output to the reference LLM run."""

    match = "match"
    match_within_tolerance = "match_within_tolerance"
    mismatch = "mismatch"


class VerificationVerdict(str, enum.Enum):
    """Verdict of a verification run (V3): promote to compiled, or reject to draft."""

    promoted = "promoted"
    rejected = "rejected"


class FallbackTriggerReason(str, enum.Enum):
    """Why a compiled run fell back to the LLM path (F1).

    Extended for sandboxed scripting: fail-closed sandbox violations and
    resource-cap terminations are safe fallback triggers (Flow C).
    """

    execution_error = "execution_error"
    tool_schema_mismatch = "tool_schema_mismatch"
    output_validation_failure = "output_validation_failure"
    sandbox_violation = "sandbox_violation"
    resource_limit_exceeded = "resource_limit_exceeded"


class SandboxValidationStatus(str, enum.Enum):
    """Compiler-as-validator outcome for sandboxed Python script source (N3).

    ``failed`` keeps the version in draft with ``sandbox_validation_reason``.
    """

    pending = "pending"
    passed = "passed"
    failed = "failed"


class FallbackResultingAction(str, enum.Enum):
    """What happened after a fallback was triggered (F2)."""

    llm_completed = "llm_completed"
    repaired_candidate_produced = "repaired_candidate_produced"
    repair_not_produced = "repair_not_produced"


class RepairRetryOutcome(str, enum.Enum):
    """Outcome of retrying the repaired candidate script version (E10)."""

    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


# ── ScriptDefinition ──────────────────────────────────────────────────────────


class ScriptDefinition(Base):
    """A versioned, named bridge script compiled from an agent workflow.

    Owned by exactly one AgentType whose identity/permissions bound the
    script; carries lineage to the AgentPlan (and optionally the observed
    session) it was compiled from (G1).
    """

    __tablename__ = "script_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_script_definitions_tenant_name"),
        Index("ix_script_definitions_tenant_id", "tenant_id"),
        Index("ix_script_definitions_agent_type_id", "agent_type_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_status: Mapped[ScriptLifecycleStatus] = mapped_column(
        Enum(ScriptLifecycleStatus, name="script_lifecycle_status_enum"),
        nullable=False,
        default=ScriptLifecycleStatus.draft,
    )
    # Owning agent type — script inherits its identity and permissions
    agent_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Source lineage (G1): the plan and/or observed session it was compiled from
    source_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Optimized-plan lineage: the OptimizedImplementationPlan that authored this
    # script (set when a script is produced by the "Optimize & Verify" flow).
    source_optimized_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("optimized_implementation_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Pointer to the version currently serving compiled runs (absent while draft/unverified).
    # use_alter avoids the circular FK dependency between script_definitions and script_versions.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("script_versions.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    health_status: Mapped[ScriptHealthStatus] = mapped_column(
        Enum(ScriptHealthStatus, name="script_health_status_enum"),
        nullable=False,
        default=ScriptHealthStatus.healthy,
    )
    # Execution semantics (product decision): only a fully_scripted script is
    # served directly by the dispatcher (zero-LLM "software mode"). All other
    # scripts are invocable virtual tools (``script____<name>``) the agent LLM
    # orchestrates. Set from the plan's ``fully_scripted`` mark at promotion.
    fully_scripted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    agent_type: Mapped["AgentType"] = relationship(
        "AgentType", back_populates="script_definitions"
    )
    source_plan: Mapped["AgentPlan | None"] = relationship(
        "AgentPlan", back_populates="script_definitions", foreign_keys=[source_plan_id]
    )
    optimized_source_plan: Mapped["OptimizedImplementationPlan | None"] = relationship(
        "OptimizedImplementationPlan",
        back_populates="script_definitions",
        foreign_keys=[source_optimized_plan_id],
    )
    versions: Mapped[list["ScriptVersion"]] = relationship(
        "ScriptVersion",
        back_populates="script_definition",
        cascade="all, delete-orphan",
        foreign_keys="ScriptVersion.script_definition_id",
    )
    current_version: Mapped["ScriptVersion | None"] = relationship(
        "ScriptVersion", foreign_keys=[current_version_id], post_update=True
    )

    def __repr__(self) -> str:
        return (
            f"<ScriptDefinition id={self.id} name={self.name} "
            f"status={self.lifecycle_status} health={self.health_status}>"
        )


# ── ScriptVersion ─────────────────────────────────────────────────────────────


class ScriptVersion(Base):
    """An immutable revision of a Script Definition (V4).

    Each version carries its own lifecycle, verification evidence, and audit
    history. Content is stored by reference via Control Center — never in
    Agent Runtime.
    """

    __tablename__ = "script_versions"
    __table_args__ = (
        UniqueConstraint(
            "script_definition_id", "version_label", name="uq_script_versions_label"
        ),
        Index("ix_script_versions_tenant_id", "tenant_id"),
        Index("ix_script_versions_script_definition_id", "script_definition_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    script_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("script_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_label: Mapped[str] = mapped_column(String(50), nullable=False)
    lifecycle_status: Mapped[ScriptLifecycleStatus] = mapped_column(
        Enum(ScriptLifecycleStatus, name="script_lifecycle_status_enum"),
        nullable=False,
        default=ScriptLifecycleStatus.draft,
    )
    # Declarative step graph: tool calls, transforms, model-backed steps.
    # Deprecated-but-retained: optional now — model-authored versions may carry
    # only python_source plus step design (backward-compatible reads).
    declarative_step_graph: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Model-authored sandboxed Python source (N3). Nullable: legacy
    # declarative-only versions keep it empty.
    python_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-version sandbox resource caps (N1): platform defaults apply when null,
    # so caps are versioned and auditable with the content they govern.
    cpu_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_limit_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wall_time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Compiler-as-validator outcome: syntax + sandbox-compliance check
    # (allowlist-only imports, I/O attempts rejected).
    sandbox_validation_status: Mapped[SandboxValidationStatus] = mapped_column(
        Enum(SandboxValidationStatus, name="sandbox_validation_status_enum"),
        nullable=False,
        default=SandboxValidationStatus.pending,
    )
    # Recorded rejection reason for failed validation (stays in draft).
    sandbox_validation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reference to the compiled artifact/source (stored via Control Center)
    content_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    compiled_from_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Prior version this was repaired/re-verified from (0..1)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("script_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Repair lineage (E9/E10): set when this version was produced by a repair
    # attempt, pointing at the defective version it repaired.
    repaired_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("script_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The run or actor that produced this version
    created_by: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    script_definition: Mapped["ScriptDefinition"] = relationship(
        "ScriptDefinition",
        back_populates="versions",
        foreign_keys=[script_definition_id],
    )
    parent_version: Mapped["ScriptVersion | None"] = relationship(
        "ScriptVersion", remote_side=[id], foreign_keys=[parent_version_id]
    )
    # Repair lineage (E9/E10)
    repaired_from: Mapped["ScriptVersion | None"] = relationship(
        "ScriptVersion", remote_side=[id], foreign_keys=[repaired_from_id]
    )
    repair_attempts: Mapped[list["RepairAttempt"]] = relationship(
        "RepairAttempt",
        back_populates="repaired_version",
        foreign_keys="RepairAttempt.repaired_version_id",
        viewonly=True,
    )
    verification_runs: Mapped[list["VerificationRun"]] = relationship(
        "VerificationRun", back_populates="script_version", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<ScriptVersion id={self.id} definition_id={self.script_definition_id} "
            f"label={self.version_label} status={self.lifecycle_status}>"
        )


# ── VerificationRun ───────────────────────────────────────────────────────────


class VerificationRun(Base):
    """Evidence record of shadow-running a Script Version against an LLM execution (V1, V2)."""

    __tablename__ = "verification_runs"
    __table_args__ = (
        Index("ix_verification_runs_tenant_id", "tenant_id"),
        Index("ix_verification_runs_script_version_id", "script_version_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    script_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("script_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Recorded LLM run used as ground truth (reference to session logs / execution records)
    reference_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    input_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expected_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    actual_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    comparison_outcome: Mapped[VerificationComparisonOutcome] = mapped_column(
        Enum(VerificationComparisonOutcome, name="verification_comparison_outcome_enum"),
        nullable=False,
    )
    # Verdict (V3): promoted to compiled, or rejected back to draft with a recorded reason
    verdict: Mapped[VerificationVerdict] = mapped_column(
        Enum(VerificationVerdict, name="verification_verdict_enum"),
        nullable=False,
    )
    verdict_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Sandbox-compliance evidence: the shadow-run comparison was executed on a
    # sandbox-compliant candidate (complements comparison_outcome/verdict).
    sandbox_check_passed: Mapped[bool | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    script_version: Mapped["ScriptVersion"] = relationship(
        "ScriptVersion", back_populates="verification_runs"
    )

    def __repr__(self) -> str:
        return (
            f"<VerificationRun id={self.id} version_id={self.script_version_id} "
            f"outcome={self.comparison_outcome} verdict={self.verdict}>"
        )


# ── FallbackEvent ─────────────────────────────────────────────────────────────


class FallbackEvent(Base):
    """Recorded whenever a compiled run fell back to the LLM path (F1, F2).

    Each event belongs to exactly one execution record and contributes to the
    owning script's health degradation (F4). Repair may spawn a successor
    Script Version (0..1).
    """

    __tablename__ = "fallback_events"
    __table_args__ = (
        Index("ix_fallback_events_tenant_id", "tenant_id"),
        Index("ix_fallback_events_execution_record_id", "execution_record_id"),
        Index("ix_fallback_events_script_version_id", "script_version_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    execution_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("script_execution_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    script_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("script_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    trigger_reason: Mapped[FallbackTriggerReason] = mapped_column(
        Enum(FallbackTriggerReason, name="fallback_trigger_reason_enum"),
        nullable=False,
    )
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    resulting_action: Mapped[FallbackResultingAction] = mapped_column(
        Enum(FallbackResultingAction, name="fallback_resulting_action_enum"),
        nullable=False,
    )
    # Contribution to the owning script's health degradation (F4)
    script_health_impact: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Successor Script Version, if repair produced one (0..1)
    repaired_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("script_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    execution_record: Mapped["ScriptExecutionRecord"] = relationship(
        "ScriptExecutionRecord", back_populates="fallback_events"
    )
    script_version: Mapped["ScriptVersion | None"] = relationship(
        "ScriptVersion", foreign_keys=[script_version_id]
    )
    repaired_version: Mapped["ScriptVersion | None"] = relationship(
        "ScriptVersion", foreign_keys=[repaired_version_id]
    )
    repair_attempts: Mapped[list["RepairAttempt"]] = relationship(
        "RepairAttempt", back_populates="fallback_event", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<FallbackEvent id={self.id} execution_id={self.execution_record_id} "
            f"reason={self.trigger_reason} action={self.resulting_action}>"
        )


# ── RepairAttempt ─────────────────────────────────────────────────────────────


class RepairAttempt(Base):
    """One bounded, agent-driven repair cycle within a fallback episode (E9, E10).

    Records the defect diagnosis, the diff applied to produce a repaired
    candidate (a successor ScriptVersion with ``repaired_from`` lineage), and
    the retry outcome. Attempts are bounded by an execution guardrail budget;
    exhaustion triggers unconditional fallback with reason capture (E2).
    """

    __tablename__ = "repair_attempts"
    __table_args__ = (
        Index("ix_repair_attempts_tenant_id", "tenant_id"),
        Index("ix_repair_attempts_fallback_event_id", "fallback_event_id"),
        Index("ix_repair_attempts_script_version_id", "script_version_id"),
        Index("ix_repair_attempts_repaired_version_id", "repaired_version_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    fallback_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fallback_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The defective version being repaired
    script_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("script_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The successor candidate produced by this attempt (0..1); must re-verify (V1)
    repaired_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("script_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The agent's recorded diagnosis of the script defect
    defect_diagnosis: Mapped[str] = mapped_column(Text, nullable=False)
    # The change applied to produce the candidate (structural diff summary)
    diff_applied: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Success or failure of the retried script version (E10)
    retry_outcome: Mapped[RepairRetryOutcome] = mapped_column(
        Enum(RepairRetryOutcome, name="repair_retry_outcome_enum"),
        nullable=False,
        default=RepairRetryOutcome.pending,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    fallback_event: Mapped["FallbackEvent"] = relationship(
        "FallbackEvent", back_populates="repair_attempts"
    )
    script_version: Mapped["ScriptVersion | None"] = relationship(
        "ScriptVersion", foreign_keys=[script_version_id]
    )
    repaired_version: Mapped["ScriptVersion | None"] = relationship(
        "ScriptVersion", foreign_keys=[repaired_version_id]
    )

    def __repr__(self) -> str:
        return (
            f"<RepairAttempt id={self.id} fallback_event_id={self.fallback_event_id} "
            f"retry_outcome={self.retry_outcome}>"
        )
