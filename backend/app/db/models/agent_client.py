"""SQLAlchemy models for third-party agent-integration clients.

AgentClient          — access grant bound to an AgentType (input-interface only).
AgentClientUsageLog  — immutable audit record for each client invocation.

A client is deliberately NOT an identity: unlike an ``AgentApiKey`` (which
authenticates *as* an agent identity + role for MCP tool access), a client
credential grants access only to a single agent type's input interface
(conversation turn or typed submit). The credential value is SHA-256 hashed at
rest; the clear-text key is shown once at creation and never retrievable.
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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


# ── Enums ─────────────────────────────────────────────────────────────────────


class AgentClientKeyType(str, enum.Enum):
    """Whether a client credential is safe to expose in a browser."""

    secret = "secret"
    publishable = "publishable"


class AgentClientStatus(str, enum.Enum):
    """Lifecycle state of a client.

    - ``active``: credential works.
    - ``inactive``: temporarily deactivated (reversible) — credential rejected.
    - ``revoked``: permanently invalidated (kept for audit).
    """

    active = "active"
    inactive = "inactive"
    revoked = "revoked"


class AgentClientRateLimitWindow(str, enum.Enum):
    """Window over which a client's rate limit is enforced."""

    per_minute = "per_minute"
    per_hour = "per_hour"
    per_day = "per_day"


class AgentClientAction(str, enum.Enum):
    """Type of invocation performed with a client credential."""

    conversation_turn = "conversation_turn"
    submit_request = "submit_request"


# ── AgentClient ───────────────────────────────────────────────────────────────


class AgentClient(Base):
    """Tenant-owned access grant bound to exactly one AgentType.

    Business rules:
    - ``key_type`` is immutable once created (secret cannot become publishable).
    - A ``publishable`` client is safe to embed in a browser: it only grants
      access to the target agent type's input interface, never tools or identity.
    - Rate limits are enforced per client; origin checks are a secondary control.
    """

    __tablename__ = "agent_clients"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_agent_clients_tenant_name"),
        UniqueConstraint("tenant_id", "slug", name="uq_agent_clients_tenant_slug"),
        Index("ix_agent_clients_tenant_id", "tenant_id"),
        Index("ix_agent_clients_agent_type_id", "agent_type_id"),
        Index("ix_agent_clients_key_hash", "key_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    agent_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_types.id", ondelete="CASCADE"), nullable=False
    )
    key_type: Mapped[AgentClientKeyType] = mapped_column(
        Enum(AgentClientKeyType, name="agent_client_key_type_enum"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[AgentClientStatus] = mapped_column(
        Enum(AgentClientStatus, name="agent_client_status_enum"),
        nullable=False,
        default=AgentClientStatus.active,
    )
    # Publishable-only exposure config (ignored for secret clients).
    white_label_theme: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    allowed_origins: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rate_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_window: Mapped[AgentClientRateLimitWindow | None] = mapped_column(
        Enum(AgentClientRateLimitWindow, name="agent_client_rate_limit_window_enum"),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identities.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    agent_type: Mapped["AgentType"] = relationship("AgentType", back_populates="clients")
    tenant: Mapped["Tenant | None"] = relationship("Tenant")
    usage_logs: Mapped[list["AgentClientUsageLog"]] = relationship(
        "AgentClientUsageLog", back_populates="client", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AgentClient id={self.id} name={self.name} key_type={self.key_type} status={self.status}>"


# ── AgentClientUsageLog ───────────────────────────────────────────────────────


class AgentClientUsageLog(Base):
    """Immutable audit record for each client invocation.

    Records every client access attempt (success and failure), never the
    credential value. Append-only — never modified or deleted.
    """

    __tablename__ = "agent_client_usage_logs"
    __table_args__ = (
        Index("ix_agent_client_usage_logs_client_id", "client_id"),
        Index("ix_agent_client_usage_logs_timestamp", "timestamp"),
        Index("ix_agent_client_usage_logs_action", "action"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_clients.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[AgentClientAction] = mapped_column(
        Enum(AgentClientAction, name="agent_client_action_enum"), nullable=False
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    client: Mapped["AgentClient"] = relationship("AgentClient", back_populates="usage_logs")

    def __repr__(self) -> str:
        return f"<AgentClientUsageLog id={self.id} action={self.action} client_id={self.client_id}>"


# Resolve forward references
from app.db.models.agents import AgentType  # noqa: E402, F401
from app.db.models.tenant import Tenant  # noqa: E402, F401
