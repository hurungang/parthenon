"""SQLAlchemy model for per-run outcomes of termination cascades."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TerminationOutcome(str, enum.Enum):
    """Outcome for an affected run in a termination cascade."""

    terminated = "terminated"
    already_completed = "already_completed"
    not_found = "not_found"
    permission_denied = "permission_denied"
    failed = "failed"


class TerminationCascadeOutcome(Base):
    """Per-run processing outcomes for a termination request across a run tree."""

    __tablename__ = "termination_cascade_outcomes"
    __table_args__ = (
        Index("ix_termination_cascade_outcomes_request", "termination_request_id"),
        Index("ix_termination_cascade_outcomes_agent_job", "affected_agent_job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    termination_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("termination_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    affected_agent_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    cascade_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    termination_outcome: Mapped[TerminationOutcome] = mapped_column(
        Enum(TerminationOutcome, name="termination_outcome_enum"),
        nullable=False,
    )
    outcome_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            "<TerminationCascadeOutcome "
            f"id={self.id} request_id={self.termination_request_id} outcome={self.termination_outcome}>"
        )
