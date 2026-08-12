"""SQLAlchemy model for observe-only threshold events."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class GuardrailThresholdEventType(str, enum.Enum):
    """User-visible threshold events produced by guardrail observe-only mode."""

    observe_only_threshold_reached = "observe_only_threshold_reached"


class GuardrailThresholdSeverity(str, enum.Enum):
    """Threshold event severity used by dashboard/UI alerts."""

    info = "info"
    warning = "warning"
    critical = "critical"


class GuardrailThresholdEvent(Base):
    """Operational events emitted when observe-only threshold is reached."""

    __tablename__ = "guardrail_threshold_events"
    __table_args__ = (
        Index("ix_guardrail_threshold_events_agent_job", "agent_job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    model_guardrail_evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_guardrail_evaluations.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[GuardrailThresholdEventType] = mapped_column(
        Enum(GuardrailThresholdEventType, name="guardrail_threshold_event_type_enum"),
        nullable=False,
    )
    severity: Mapped[GuardrailThresholdSeverity] = mapped_column(
        Enum(GuardrailThresholdSeverity, name="guardrail_threshold_severity_enum"),
        nullable=False,
    )
    display_message: Mapped[str] = mapped_column(String(1000), nullable=False)
    emitted_to_execution_log: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    emitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<GuardrailThresholdEvent id={self.id} agent_job_id={self.agent_job_id}>"
