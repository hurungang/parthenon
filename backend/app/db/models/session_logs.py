"""SQLAlchemy model for execution log entries produced by AgentRuntimeExecutor."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


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
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:
        return (
            f"<ExecutionLogEntry id={self.id} session_id={self.session_id}"
            f" event_type={self.event_type}>"
        )
