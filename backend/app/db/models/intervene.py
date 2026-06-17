"""SQLAlchemy models for agent-initiated human intervene requests and responses."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class InterveneRequestStatus(str, enum.Enum):
    """Lifecycle status of an intervene request."""

    pending = "pending"
    responded = "responded"
    cancelled = "cancelled"
    expired = "expired"


class InterventionType(str, enum.Enum):
    """Type of human input requested by the agent."""

    approval = "approval"
    choice = "choice"
    text = "text"


class InterveneRequest(Base):
    """An agent-initiated request for human intervention during execution.

    Created when an agent calls the system____human_intervene tool.
    Supports three intervention types: approval (yes/no), choice (select one
    from a list), and text (free-form input). Tracks lifecycle from pending
    through responded, cancelled, or expired.
    """

    __tablename__ = "intervene_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agent_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    intervention_type: Mapped[InterventionType] = mapped_column(
        Enum(InterventionType, name="intervention_type_enum"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    choices: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[InterveneRequestStatus] = mapped_column(
        Enum(InterveneRequestStatus, name="intervene_request_status_enum"),
        nullable=False,
        default=InterveneRequestStatus.pending,
    )
    delegation_depth: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    agent_session: Mapped["AgentJob"] = relationship(
        "AgentJob", back_populates="intervene_requests"
    )
    conversation_session: Mapped["ConversationSession | None"] = relationship(
        "ConversationSession", back_populates="intervene_requests"
    )
    response: Mapped["InterveneResponse | None"] = relationship(
        "InterveneResponse", back_populates="request", uselist=False, cascade="all, delete-orphan"
    )
    conversation_turns: Mapped[list["ConversationTurn"]] = relationship(
        "ConversationTurn", back_populates="intervene_request"
    )

    def __repr__(self) -> str:
        return (
            f"<InterveneRequest id={self.id} session_id={self.agent_session_id} "
            f"type={self.intervention_type} status={self.status}>"
        )


class InterveneResponse(Base):
    """The operator's response to an intervene request.

    Exactly one response per request. The response field populated depends on
    the intervention type: approval_value (boolean) for approval requests,
    selected_choice (string) for choice requests, text_value (string) for
    text requests.
    """

    __tablename__ = "intervene_responses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("intervene_requests.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    operator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identities.id", ondelete="SET NULL"),
        nullable=False,
    )
    approval_value: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    selected_choice: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    request: Mapped["InterveneRequest"] = relationship(
        "InterveneRequest", back_populates="response"
    )

    def __repr__(self) -> str:
        return f"<InterveneResponse id={self.id} request_id={self.request_id}>"


# Resolve forward references
from app.db.models.agents import AgentJob  # noqa: E402, F401
from app.db.models.conversations import ConversationSession, ConversationTurn  # noqa: E402, F401
