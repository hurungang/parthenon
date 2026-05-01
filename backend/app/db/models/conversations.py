"""SQLAlchemy models for Conversations: ConversationSession, ConversationTurn, ToolCallRecord."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ConversationStatus(str, enum.Enum):
    """Status of a conversation session."""

    active = "active"
    closed = "closed"
    error = "error"


class TurnRole(str, enum.Enum):
    """Role of the author of a conversation turn."""

    user = "user"
    agent = "agent"
    tool = "tool"
    system = "system"


class ConversationSession(Base):
    """A bounded interaction context between an initiator and an agent."""

    __tablename__ = "conversation_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_instances.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_type_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    initiator_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    channel: Mapped[str] = mapped_column(String(50), nullable=False, default="web")
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, name="conversation_status_enum"),
        nullable=False,
        default=ConversationStatus.active,
    )
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    turns: Mapped[list["ConversationTurn"]] = relationship(
        "ConversationTurn",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ConversationTurn.created_at",
    )

    def __repr__(self) -> str:
        return f"<ConversationSession id={self.id} status={self.status}>"


class ConversationTurn(Base):
    """A single message in a conversation session."""

    __tablename__ = "conversation_turns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[TurnRole] = mapped_column(Enum(TurnRole, name="turn_role_enum"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    session: Mapped["ConversationSession"] = relationship(
        "ConversationSession", back_populates="turns"
    )
    tool_calls: Mapped[list["ToolCallRecord"]] = relationship(
        "ToolCallRecord", back_populates="turn", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ConversationTurn id={self.id} role={self.role}>"


class ToolCallRecord(Base):
    """Record of a tool invocation within a conversation turn."""

    __tablename__ = "tool_call_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    turn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(400), nullable=False)
    tool_input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    turn: Mapped["ConversationTurn"] = relationship("ConversationTurn", back_populates="tool_calls")

    def __repr__(self) -> str:
        return f"<ToolCallRecord id={self.id} tool_name={self.tool_name}>"
