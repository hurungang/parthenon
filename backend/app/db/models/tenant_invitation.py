"""SQLAlchemy model for TenantInvitation.

Pending user onboarding into a tenant; carries the target tenant role and
expiry. Invitations are sent by an existing member (the inviter's membership).
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
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.models.tenant import TenantRole  # noqa: F401


class TenantInvitationStatus(str, enum.Enum):
    """Lifecycle state of a tenant invitation."""

    pending = "pending"
    accepted = "accepted"
    expired = "expired"
    revoked = "revoked"


class TenantInvitation(Base):
    """An outstanding invitation to join a tenant with a target tenant role."""

    __tablename__ = "tenant_invitations"
    __table_args__ = (
        Index("ix_tenant_invitations_tenant_id", "tenant_id"),
        Index("ix_tenant_invitations_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    # Membership of the inviter (null if the inviter's membership is removed)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_user_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # SHA-256 hex of the single-use acceptance token (raw token is shown
    # once at creation and never stored).  Null for admin-created slots.
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Invitation targets tenant-scoped roles only (no platform_admin)
    tenant_role: Mapped[TenantRole] = mapped_column(
        Enum(TenantRole, name="tenant_role_enum"), nullable=False
    )
    status: Mapped[TenantInvitationStatus] = mapped_column(
        Enum(TenantInvitationStatus, name="tenant_invitation_status_enum"),
        nullable=False,
        default=TenantInvitationStatus.pending,
    )
    # Invitation consumed on first acceptance
    is_single_use: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(
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
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="invitations")  # type: ignore[name-defined]
    invited_by: Mapped["TenantUserMembership | None"] = relationship(  # type: ignore[name-defined]
        "TenantUserMembership"
    )

    def __repr__(self) -> str:
        return (
            f"<TenantInvitation id={self.id} tenant_id={self.tenant_id} "
            f"email={self.email} status={self.status}>"
        )
