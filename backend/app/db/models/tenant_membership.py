"""SQLAlchemy model for TenantUserMembership.

A user's presence in a tenant with a tenant-scoped role. One session is bound
to exactly one tenant; ``is_default`` pre-selects the tenant at sign-in for
multi-tenant users. ``platform_admin`` is a platform-level role surfaced
through membership so platform governance stays auditable.
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.models.tenant import TenantRole  # noqa: F401


class TenantUserMembershipStatus(str, enum.Enum):
    """Lifecycle state of a user's membership in a tenant."""

    active = "active"
    suspended = "suspended"
    removed = "removed"


class TenantUserMembership(Base):
    """Links a PlatformUser to a Tenant with a tenant-scoped role."""

    __tablename__ = "tenant_user_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_membership_tenant_user"),
        # At most one root (owner) membership per tenant — the "exactly
        # one root" invariant is completed by the creation paths, which
        # always provision exactly one.  Partial index on both dialects
        # (SQLite ignores postgresql_where and would otherwise index the
        # whole tenant_id column).
        Index(
            "uq_tenant_membership_single_root",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_root = true"),
            sqlite_where=text("is_root = true"),
        ),
        Index("ix_tenant_user_memberships_tenant_id", "tenant_id"),
        Index("ix_tenant_user_memberships_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("platform_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_role: Mapped[TenantRole] = mapped_column(
        Enum(TenantRole, name="tenant_role_enum"), nullable=False
    )
    status: Mapped[TenantUserMembershipStatus] = mapped_column(
        Enum(TenantUserMembershipStatus, name="tenant_membership_status_enum"),
        nullable=False,
        default=TenantUserMembershipStatus.active,
    )
    # Tenant chosen by default for this user at sign-in
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Immutable root/owner membership (Phase 10): exactly one per tenant
    # (partial unique index ``uq_tenant_membership_single_root``); grants
    # ALL tenant permissions and can never be demoted/suspended/removed.
    is_root: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
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
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="memberships")  # type: ignore[name-defined]
    user: Mapped["PlatformUser"] = relationship(  # type: ignore[name-defined]
        "PlatformUser", back_populates="tenant_memberships"
    )

    def __repr__(self) -> str:
        return (
            f"<TenantUserMembership id={self.id} tenant_id={self.tenant_id} "
            f"user_id={self.user_id} role={self.tenant_role} status={self.status}>"
        )
