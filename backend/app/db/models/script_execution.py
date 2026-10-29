"""SQLAlchemy models for compiled script execution: ScriptExecutionRecord.

Execution records are new first-class provenance entities so that LLM-native
run records stay untouched. There is no execution-mode configuration: the
script-vs-LLM distinction is recorded via the referenced script version and
the outcome. All data is owned by Control Center (the sole DB gateway);
Agent Runtime consumes it only via Control Center APIs.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


# ── Enums ─────────────────────────────────────────────────────────────────────


class ScriptExecutionOutcome(str, enum.Enum):
    """Outcome of a script execution."""

    success = "success"
    validation_failure = "validation_failure"
    fell_back = "fell_back"
    partial_failure = "partial_failure"


# ── ScriptExecutionRecord ─────────────────────────────────────────────────────


class ScriptExecutionRecord(Base):
    """One execution of a compiled script (or its fallback run) (G2 audit).

    Relates to the existing AgentJob (agent execution session) — a compiled run
    occurs within or on behalf of a session. LLM-native run records are not
    modified; this is a separate provenance kind. No execution-mode attribute
    exists: script-first execution with unconditional LLM fallback is fixed
    platform behavior (E1–E3).
    """

    __tablename__ = "script_execution_records"
    __table_args__ = (
        Index("ix_script_execution_records_tenant_id", "tenant_id"),
        Index("ix_script_execution_records_script_version_id", "script_version_id"),
        Index("ix_script_execution_records_session_id", "session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    script_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("script_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    outcome: Mapped[ScriptExecutionOutcome] = mapped_column(
        Enum(ScriptExecutionOutcome, name="script_execution_outcome_enum"),
        nullable=False,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Tool calls made, mirroring existing tool-call records (0..many)
    tools_invoked: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Semantic-bridge / decision steps that consumed model capacity (0..many; S3)
    model_backed_steps_used: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Session the run occurred within / on behalf of (G2)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Identity parity (E7/SEC1): confirms the run's tool calls used the same
    # mTLS/CH identity path as the executing agent's own tool calls.
    identity_parity_confirmed: Mapped[bool | None] = mapped_column(nullable=True)
    # LLM tokens not consumed versus the LLM baseline (G3). Retained for
    # historical rows; superseded by tokens_saved_actual going forward.
    tokens_saved_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Real tokens avoided, measured against the reference LLM execution (N5) —
    # not an estimate.
    tokens_saved_actual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # True when the run ended via a CPU/memory/wall-time cap safe-kill (Flow C).
    sandbox_termination: Mapped[bool | None] = mapped_column(nullable=True)
    # Human-readable one-line summary of what failed (disallowed import, cap
    # breach) — no truncated JSON blobs (N5).
    sandbox_violation_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    script_version: Mapped["ScriptVersion | None"] = relationship(
        "ScriptVersion", foreign_keys=[script_version_id]
    )
    session: Mapped["AgentJob | None"] = relationship(
        "AgentJob", foreign_keys=[session_id]
    )
    fallback_events: Mapped[list["FallbackEvent"]] = relationship(
        "FallbackEvent", back_populates="execution_record", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<ScriptExecutionRecord id={self.id} version_id={self.script_version_id} "
            f"outcome={self.outcome}>"
        )
