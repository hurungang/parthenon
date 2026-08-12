"""SQLAlchemy model for AgentData."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class AgentData(Base):
    """Mutable named data saved for an agent type and/or execution session."""

    __tablename__ = "agent_data"
    __table_args__ = (
        Index(
            "ix_agent_data_agent_type_id_data_name",
            "agent_type_id",
            "data_name",
        ),
        Index(
            "ix_agent_data_session_id_data_name",
            "session_id",
            "data_name",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_types.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    data_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    data_value: Mapped[dict] = mapped_column(JSON, nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False, default="json")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    agent_type: Mapped["AgentType | None"] = relationship("AgentType")
    session: Mapped["AgentJob | None"] = relationship("AgentJob")

    def __repr__(self) -> str:
        return f"<AgentData id={self.id} data_name={self.data_name}>"