"""SQLAlchemy model for user-requested termination actions."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TerminationScope(str, enum.Enum):
    """Requested scope for a termination action."""

    node_only = "node_only"
    cascade_subtree = "cascade_subtree"


class TerminationPermissionEvaluationOutcome(str, enum.Enum):
    """Permission check result for a termination request."""

    allowed = "allowed"
    denied = "denied"


class TerminationRequestStatus(str, enum.Enum):
    """Lifecycle status of a termination request."""

    accepted = "accepted"
    rejected = "rejected"
    completed = "completed"
    partially_completed = "partially_completed"
    failed = "failed"


class TerminationRequest(Base):
    """Request record capturing permission evaluation and execution lifecycle."""

    __tablename__ = "termination_requests"
    __table_args__ = (
        Index("ix_termination_requests_target_agent_job", "target_agent_job_id"),
        Index("ix_termination_requests_requested_by", "requested_by_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identities.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_agent_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    termination_scope: Mapped[TerminationScope] = mapped_column(
        Enum(TerminationScope, name="termination_scope_enum"),
        nullable=False,
    )
    permission_evaluation_outcome: Mapped[TerminationPermissionEvaluationOutcome] = mapped_column(
        Enum(
            TerminationPermissionEvaluationOutcome,
            name="termination_permission_evaluation_outcome_enum",
        ),
        nullable=False,
    )
    permission_evaluation_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    request_status: Mapped[TerminationRequestStatus] = mapped_column(
        Enum(TerminationRequestStatus, name="termination_request_status_enum"),
        nullable=False,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<TerminationRequest id={self.id} target_agent_job_id={self.target_agent_job_id}>"
