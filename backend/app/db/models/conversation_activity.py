"""SQLAlchemy model for ConversationActivity: the persisted "what is the assistant doing right now" record."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ActivityState(str, enum.Enum):
    """State of the assistant's current activity within a conversation session.

    The last three states are terminal outcomes (finished, failed, timed_out).
    """

    thinking = "thinking"
    using_tool = "using_tool"
    delegating = "delegating"
    waiting_for_human = "waiting_for_human"
    finished = "finished"
    failed = "failed"
    timed_out = "timed_out"


TERMINAL_ACTIVITY_STATES = frozenset(
    {ActivityState.finished, ActivityState.failed, ActivityState.timed_out}
)


class ConversationActivity(Base):
    """The authoritative, persisted record of a conversational agent's current activity.

    Exactly one live record per conversation session (created on first activity,
    updated in place on every state transition). ``last_updated_at`` acts as the
    heartbeat that drives staleness detection; ``current_turn_id`` and
    ``pending_intervene_request_id`` are the resume/checkpoint references.
    """

    __tablename__ = "conversation_activities"
    __table_args__ = (
        Index("ix_conversation_activities_last_updated_at", "last_updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    state: Mapped[ActivityState] = mapped_column(
        Enum(ActivityState, name="activity_state_enum"), nullable=False
    )
    current_turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_turns.id", ondelete="SET NULL"),
        nullable=True,
    )
    pending_intervene_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("intervene_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    tool_name: Mapped[str | None] = mapped_column(String(400), nullable=True)
    target_agent_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_types.id", ondelete="SET NULL"),
        nullable=True,
    )
    # State-specific context only — never credentials, tokens, or secrets.
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    conversation_session: Mapped["ConversationSession"] = relationship(
        "ConversationSession", back_populates="activity"
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationActivity id={self.id} session_id={self.conversation_session_id} "
            f"state={self.state} is_terminal={self.is_terminal}>"
        )


# Resolve forward references
from app.db.models.conversations import ConversationSession  # noqa: E402, F401
