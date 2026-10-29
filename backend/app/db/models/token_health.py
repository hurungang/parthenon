"""SQLAlchemy models for Token Expiry Alerting.

New entities:
- TokenHealthCheck: pre-execution token health evaluation audit record

Enums:
- TokenHealthState: computed health state (healthy | expiring | expired | unknown)
- TokenRefreshOutcome: outcome of the most recent token refresh (success | failure)
- TokenCheckOutcome: preflight outcome (passed | blocked)
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


# ── Enums ─────────────────────────────────────────────────────────────────────


class TokenHealthState(str, enum.Enum):
    """Computed token health state surfaced on dashboard and topology."""

    healthy = "healthy"
    expiring = "expiring"
    expired = "expired"
    unknown = "unknown"


class TokenRefreshOutcome(str, enum.Enum):
    """Outcome of the most recent automatic token refresh by Control Center.

    Kept name-compatible with ``app.db.models.agent_security.TokenRefreshOutcome``
    for the success/failure subset used by token health fields.
    """

    success = "success"
    failure = "failure"


class TokenCheckOutcome(str, enum.Enum):
    """Outcome of a pre-execution token health check."""

    passed = "passed"
    blocked = "blocked"


class TokenHealthTargetKind(str, enum.Enum):
    """Which kind of token-bearing entity was preflighted."""

    agent_identity = "agent_identity"
    mcp_session = "mcp_session"


# ── Token Health Check ────────────────────────────────────────────────────────


class TokenHealthCheck(Base):
    """One row per pre-execution token health evaluation performed by Control Center.

    Audit trail of preflight checks so "every expired token surfaced before a
    run" is provable and blocked executions are traceable. ``target_id`` is a
    polymorphic reference (see ``target_kind``) and has no database-level FK.
    """

    __tablename__ = "token_health_checks"
    __table_args__ = (
        Index("ix_token_health_checks_tenant_id", "tenant_id"),
        Index("ix_token_health_checks_checked_at", "checked_at"),
        Index("ix_token_health_checks_target", "target_kind", "target_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    agent_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_kind: Mapped[TokenHealthTargetKind] = mapped_column(
        Enum(TokenHealthTargetKind, name="token_health_target_kind_enum"),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    health_state: Mapped[TokenHealthState] = mapped_column(
        Enum(TokenHealthState, name="token_health_state_enum"), nullable=False
    )
    check_outcome: Mapped[TokenCheckOutcome] = mapped_column(
        Enum(TokenCheckOutcome, name="token_check_outcome_enum"), nullable=False
    )
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<TokenHealthCheck id={self.id} target_kind={self.target_kind} "
            f"target_id={self.target_id} state={self.health_state} "
            f"outcome={self.check_outcome}>"
        )
