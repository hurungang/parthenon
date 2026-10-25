"""SQLAlchemy models for LLM mocking: LLMMockRecording.

Recorded LLM request/response pairs captured during a real (or manually
driven) execution, for deterministic replay and prompt assertions in tests.
Tenant-scoped; contains prompt + response payloads only — never API keys or
identity tokens. All data is owned by Control Center (the sole DB gateway);
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
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


# ── Enums ─────────────────────────────────────────────────────────────────────


class MockInteractionKind(str, enum.Enum):
    """Which interaction surface a recorded LLM call belonged to."""

    agent_loop = "agent_loop"
    semantic_bridge = "semantic_bridge"
    decision_step = "decision_step"


# ── LLMMockRecording ──────────────────────────────────────────────────────────


class LLMMockRecording(Base):
    """One recorded LLM request/response pair (test-infrastructure data).

    Replay matching is by ``recording_key`` (a deterministic function of the
    request); identical inputs replay identically. Recordings are keyed by
    request content, not by script — no relationship to ScriptVersion.
    Written only in test/recording modes, but persisted through Control Center
    like all registry data (no Agent Runtime DB access).
    """

    __tablename__ = "llm_mock_recordings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "recording_key",
            "model_identifier",
            name="uq_llm_mock_recordings_tenant_key_model",
        ),
        Index("ix_llm_mock_recordings_tenant_id", "tenant_id"),
        Index("ix_llm_mock_recordings_session_id", "session_id"),
        Index("ix_llm_mock_recordings_recording_key", "recording_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    # AgentJob the recording was captured in (0..1)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Deterministic hash/cue key used to match a call at replay time
    recording_key: Mapped[str] = mapped_column(String(200), nullable=False)
    # Model the call was made against (record-time)
    model_identifier: Mapped[str] = mapped_column(String(200), nullable=False)
    interaction_kind: Mapped[MockInteractionKind] = mapped_column(
        Enum(MockInteractionKind, name="mock_interaction_kind_enum"),
        nullable=False,
    )
    # Messages/tools sent to the LLM — prompt + structure only, no credentials
    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Mocked/recorded completion response
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Token usage of the recorded call (input/output/total)
    usage_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Actor/run that produced the recording
    recorded_by: Mapped[str | None] = mapped_column(String(500), nullable=True)
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
    session: Mapped["AgentJob | None"] = relationship(
        "AgentJob", foreign_keys=[session_id]
    )

    def __repr__(self) -> str:
        return (
            f"<LLMMockRecording id={self.id} key={self.recording_key} "
            f"kind={self.interaction_kind} model={self.model_identifier}>"
        )
