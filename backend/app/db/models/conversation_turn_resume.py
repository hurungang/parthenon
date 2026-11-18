"""SQLAlchemy models for durably resumable paused conversational turns.

Two entities, deliberately split:

* ``ConversationTurnResume`` — the small, queryable resume index for one paused
  conversational turn. It ties together the conversation session, the paused
  turn, the pending intervene request, and the eventual terminal outcome, and
  owns the exactly-once markers (``idempotency_key`` + ``write_applied``) and
  the instance claim (``claimed_by_instance_id`` + ``claim_expires_at``).
* ``ConversationTurnCheckpoint`` — the opaque, versioned agent-framework payload
  (exactly one per resume record) that lets a *different* instance rebuild the
  paused turn. Never contains identity tokens, credentials, or secrets.

Control Center owns both; Agent Runtime and Communication Hub reach them only
through Control Center internal APIs (mTLS).
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ResumeState(str, enum.Enum):
    """Lifecycle state of a paused conversational turn.

    ``waiting_for_human`` and ``resuming`` are live; ``resolved`` and
    ``unresumable`` are terminal.
    """

    waiting_for_human = "waiting_for_human"
    resuming = "resuming"
    resolved = "resolved"
    unresumable = "unresumable"


TERMINAL_RESUME_STATES = frozenset({ResumeState.resolved, ResumeState.unresumable})


class ResumeOutcome(str, enum.Enum):
    """Why a paused turn reached its terminal state.

    A denial or expiry never sets ``write_applied``.
    """

    approved_applied = "approved_applied"
    denied = "denied"
    cancelled = "cancelled"
    expired = "expired"
    superseded = "superseded"
    resume_failed = "resume_failed"


class CheckpointPayloadKind(str, enum.Enum):
    """Kind of agent-framework payload held by a checkpoint row."""

    agent_turn_state = "agent_turn_state"
    conversation_state = "conversation_state"


class ConversationTurnResume(Base):
    """The durable resume index for one paused conversational turn.

    At most one live (non-terminal) record per conversation session is enforced
    by a partial unique index; a new pause closes the previous live record as
    ``superseded``. ``idempotency_key`` is globally unique so a duplicate or
    re-delivered answer can never apply the confirmed write twice.
    """

    __tablename__ = "conversation_turn_resumes"
    __table_args__ = (
        Index(
            "uq_conversation_turn_resumes_live_session",
            "conversation_session_id",
            unique=True,
            postgresql_where=text("is_terminal = false"),
            sqlite_where=text("is_terminal = false"),
        ),
        Index(
            "ix_conversation_turn_resumes_conversation_session_id",
            "conversation_session_id",
        ),
        Index("ix_conversation_turn_resumes_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    conversation_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_turns.id", ondelete="SET NULL"),
        nullable=True,
    )
    intervene_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("intervene_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    state: Mapped[ResumeState] = mapped_column(
        Enum(ResumeState, name="resume_state_enum"),
        nullable=False,
        default=ResumeState.waiting_for_human,
    )
    resume_outcome: Mapped[ResumeOutcome | None] = mapped_column(
        Enum(ResumeOutcome, name="resume_outcome_enum"), nullable=True
    )
    is_terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Opaque, stable handle any instance can resolve.
    resume_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Globally unique per paused turn — exactly one confirmed write.
    idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    write_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applied_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identities.id", ondelete="SET NULL"), nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # What the confirmed action changed — state context only, never secrets.
    applied_effect_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    outcome_turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_turns.id", ondelete="SET NULL"),
        nullable=True,
    )
    claimed_by_instance_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    # Expiry only frees the turn for another instance; it never changes state.
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terminal_reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    terminal_message_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # End of the answerable window (mirrors InterveneRequest.expires_at).
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    conversation_session: Mapped["ConversationSession"] = relationship(
        "ConversationSession", back_populates="turn_resumes"
    )
    intervene_request: Mapped["InterveneRequest | None"] = relationship(
        "InterveneRequest", back_populates="turn_resume"
    )
    checkpoint: Mapped["ConversationTurnCheckpoint | None"] = relationship(
        "ConversationTurnCheckpoint",
        back_populates="resume",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationTurnResume id={self.id} session_id={self.conversation_session_id} "
            f"state={self.state} outcome={self.resume_outcome} "
            f"is_terminal={self.is_terminal}>"
        )


class ConversationTurnCheckpoint(Base):
    """The opaque, versioned payload that lets another instance rebuild a paused turn.

    Exactly one row per resume record. ``is_consumed`` flips once a successful
    resume rebuilt the turn; ``expires_at`` is the purge horizon. The payload is
    framework-serialised state — the domain model never depends on its shape.
    """

    __tablename__ = "conversation_turn_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    resume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_turn_resumes.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    payload_kind: Mapped[CheckpointPayloadKind] = mapped_column(
        Enum(CheckpointPayloadKind, name="checkpoint_payload_kind_enum"),
        nullable=False,
        default=CheckpointPayloadKind.agent_turn_state,
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    resume: Mapped["ConversationTurnResume"] = relationship(
        "ConversationTurnResume", back_populates="checkpoint"
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationTurnCheckpoint id={self.id} resume_id={self.resume_id} "
            f"kind={self.payload_kind} consumed={self.is_consumed}>"
        )


# Resolve forward references
from app.db.models.conversations import ConversationSession  # noqa: E402, F401
from app.db.models.intervene import InterveneRequest  # noqa: E402, F401
