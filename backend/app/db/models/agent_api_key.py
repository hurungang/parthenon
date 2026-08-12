"""SQLAlchemy models for API key authentication and audit logging.

AgentApiKey  — API key bound to an AgentIdentity + AgentRole pair.
ApiKeyUsageLog — Immutable audit record for each authenticated operation.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


# ── Enums ─────────────────────────────────────────────────────────────────────


class ApiKeyStatus(str, enum.Enum):
    """Lifecycle state of an API key."""

    active = "active"
    revoked = "revoked"


class ApiKeyUsageAction(str, enum.Enum):
    """Type of operation performed with an API key."""

    validate = "validate"
    load_skills = "load_skills"
    tool_call = "tool_call"


# ── API Key Model ─────────────────────────────────────────────────────────────


class AgentApiKey(Base):
    """API key bound to a specific agent identity and agent role.

    The key value is SHA-256 hashed at rest (``key_hash``). Only the hash and a
    human-readable prefix (``key_prefix``, e.g. ``phn_sk_``) are persisted. The
    clear-text key is displayed once at creation and never retrievable afterward.

    Business rules:
    - One key per identity-role pair (enforced by unique constraint).
    - Keys inherit the full permission set of the bound role.
    - Revocation is immediate — the key becomes unusable on next authentication.
    - Keys are valid until manually revoked; no automatic expiration.
    """

    __tablename__ = "agent_api_keys"
    __table_args__ = (
        UniqueConstraint("agent_identity_id", "agent_role_id", name="uq_agent_api_keys_identity_role"),
        Index("ix_agent_api_keys_key_hash", "key_hash"),
        Index("ix_agent_api_keys_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    agent_identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_identities.id", ondelete="CASCADE"), nullable=False
    )
    agent_role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_roles.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ApiKeyStatus] = mapped_column(
        Enum(ApiKeyStatus, name="api_key_status_enum"), nullable=False, default=ApiKeyStatus.active
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identities.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    identity: Mapped["AgentIdentity"] = relationship("AgentIdentity")
    role: Mapped["AgentRole"] = relationship("AgentRole")
    usage_logs: Mapped[list["ApiKeyUsageLog"]] = relationship(
        "ApiKeyUsageLog", back_populates="api_key", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AgentApiKey id={self.id} name={self.name} status={self.status}>"


# ── Usage Log Model ───────────────────────────────────────────────────────────


class ApiKeyUsageLog(Base):
    """Immutable audit record for each API key operation.

    Captures every MCP hub interaction: authentication (``validate``),
    skill discovery (``load_skills``), and individual tool invocations
    (``tool_call``). Records are append-only — never modified or deleted
    (archival after retention period).
    """

    __tablename__ = "api_key_usage_logs"
    __table_args__ = (
        Index("ix_api_key_usage_logs_api_key_id", "api_key_id"),
        Index("ix_api_key_usage_logs_timestamp", "timestamp"),
        Index("ix_api_key_usage_logs_action", "action"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_api_keys.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[ApiKeyUsageAction] = mapped_column(
        Enum(ApiKeyUsageAction, name="api_key_usage_action_enum"), nullable=False
    )
    tool_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    api_key: Mapped["AgentApiKey"] = relationship("AgentApiKey", back_populates="usage_logs")

    def __repr__(self) -> str:
        return f"<ApiKeyUsageLog id={self.id} action={self.action} api_key_id={self.api_key_id}>"


# Resolve forward references
from app.db.models.agents import AgentIdentity, AgentRole  # noqa: E402, F401
