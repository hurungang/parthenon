"""SQLAlchemy model for execution log entries produced by AgentRuntimeExecutor."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ExecutionEventCategory(str, enum.Enum):
    """Broad category used for runtime observability and filtering."""

    functional = "functional"
    guardrail = "guardrail"
    posture = "posture"
    termination = "termination"
    validation = "validation"
    # Phase 3.10: per-model and per-vendor availability blocks
    # are tagged with dedicated event categories so the operator UI
    # and audit log views can distinguish them from functional failures
    # and other guardrail events.
    model_disabled = "model_disabled"
    vendor_disabled = "vendor_disabled"
    # Phase 3.11: a guardrail (token/usage/etc) has a posture of
    # ``breached`` and ``enforcement_posture=terminate``, so the pre-
    # execution check blocked dispatch. Distinct from ``model_disabled``
    # because the model itself is enabled — only the guardrail is on fire.
    guardrail_breached = "guardrail_breached"


class ExecutionActorType(str, enum.Enum):
    """Originator of an execution event."""

    system = "system"
    user = "user"
    operator = "operator"


class ExecutionLogEntry(Base):
    """Individual log entry for an agent session execution.

    Captures LLM calls, tool calls, system events and errors so operators can
    observe what happened inside a session without relying on external log
    aggregators.
    """

    __tablename__ = "execution_log_entries"
    __table_args__ = (
        Index("ix_execution_log_entries_session_id", "session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    log_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="INFO"
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    event_category: Mapped[ExecutionEventCategory] = mapped_column(
        Enum(ExecutionEventCategory, name="execution_event_category_enum"),
        nullable=False,
        default=ExecutionEventCategory.functional,
        server_default=ExecutionEventCategory.functional.value,
    )
    correlation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor_type: Mapped[ExecutionActorType] = mapped_column(
        Enum(ExecutionActorType, name="execution_actor_type_enum"),
        nullable=False,
        default=ExecutionActorType.system,
        server_default=ExecutionActorType.system.value,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:
        return (
            f"<ExecutionLogEntry id={self.id} session_id={self.session_id}"
            f" event_type={self.event_type}>"
        )
