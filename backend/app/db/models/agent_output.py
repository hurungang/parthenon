"""SQLAlchemy model for AgentOutput."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class AgentOutputValidationStatus(str, enum.Enum):
    """Validation status of an AgentOutput against its data type schema."""

    valid = "valid"
    validation_error = "validation_error"


class AgentOutput(Base):
    """Immutable record of a single typed agent execution result.

    Links the agent type, execution session, and data type schema together with
    the validated field values.
    """

    __tablename__ = "agent_outputs"
    __table_args__ = (
        Index(
            "ix_agent_outputs_data_type_id_created_at",
            "data_type_id",
            "created_at",
        ),
        Index(
            "ix_agent_outputs_agent_type_id_created_at",
            "agent_type_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    data_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_data_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_status: Mapped[AgentOutputValidationStatus] = mapped_column(
        Enum(
            AgentOutputValidationStatus, name="agent_output_validation_status_enum"
        ),
        nullable=False,
    )
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    data_type: Mapped["AgentDataType"] = relationship(
        "AgentDataType", foreign_keys=[data_type_id]
    )
    agent_type: Mapped["AgentType"] = relationship(
        "AgentType", foreign_keys=[agent_type_id]
    )
    execution_session: Mapped["AgentJob"] = relationship(
        "AgentJob", foreign_keys=[execution_session_id]
    )
    # Back-populate for AgentJob.output convenience link
    agent_jobs: Mapped[list["AgentJob"]] = relationship(
        "AgentJob",
        back_populates="output",
        foreign_keys="AgentJob.output_id",
    )

    def __repr__(self) -> str:
        return (
            f"<AgentOutput id={self.id} "
            f"data_type_id={self.data_type_id} "
            f"validation_status={self.validation_status}>"
        )
