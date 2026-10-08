"""SQLAlchemy models for result records and decision execution results."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ResultRecord(Base):
    """A structured output saved by an agent or SOP via the save_result MCP tool."""

    __tablename__ = "result_records"
    __table_args__ = (
        Index("ix_result_records_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    agent_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_types.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_instances.id", ondelete="SET NULL"),
        nullable=True,
    )
    conversation_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(String(400), nullable=True)
    content_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default="application/json"
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ResultRecord id={self.id} title={self.title}>"


class DecisionOutcome(str, enum.Enum):
    """Computed gate outcome of a decision tool execution."""

    act = "act"
    confirm = "confirm"
    escalate = "escalate"


class DecisionExecutionStatus(str, enum.Enum):
    """Execution status of a decision tool run."""

    completed = "completed"
    failed = "failed"


class DecisionExecutionResult(Base):
    """Persists each decision tool execution: state snapshot, typed answers,
    and the computed gate outcome — auditable alongside existing tool/skill
    executions. Keyed to the DecisionTool (tenant-contained).
    """

    __tablename__ = "decision_execution_results"
    __table_args__ = (
        Index("ix_decision_execution_results_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    decision_tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("decision_tools.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    input_state_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    answers: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Per question: typed value, probabilities, confidence",
    )
    outcome: Mapped[DecisionOutcome] = mapped_column(
        Enum(DecisionOutcome, name="decision_outcome_enum"),
        nullable=False,
    )
    status: Mapped[DecisionExecutionStatus] = mapped_column(
        Enum(DecisionExecutionStatus, name="decision_execution_status_enum"),
        nullable=False,
        default=DecisionExecutionStatus.completed,
    )
    provider_model: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="e.g. jev-latest"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tool: Mapped["DecisionTool"] = relationship(
        "DecisionTool", back_populates="execution_results"
    )

    def __repr__(self) -> str:
        return (
            f"<DecisionExecutionResult id={self.id} "
            f"decision_tool_id={self.decision_tool_id} "
            f"outcome={self.outcome} status={self.status}>"
        )


# Resolve forward reference
from app.db.models.decision_tools import DecisionTool  # noqa: E402, F401
