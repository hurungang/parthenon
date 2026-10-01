"""SQLAlchemy models for multi-tenant support: Tenant.

Multi-tenancy is opt-in and disabled by default: while disabled, tenant
references stay empty (or point at the implicit system tenant) and the
platform behaves exactly as the single-tenant product.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class TenantStatus(str, enum.Enum):
    """Lifecycle state of a tenant workspace."""

    active = "active"
    suspended = "suspended"
    deleted = "deleted"


class TenantRole(str, enum.Enum):
    """Tenant-scoped role carried by memberships, invitations, and the first admin."""

    platform_admin = "platform_admin"
    tenant_admin = "tenant_admin"
    member = "member"


class Tenant(Base):
    """An organization workspace; ``slug`` is the unique tenant address (isolation anchor)."""

    __tablename__ = "tenants"
    __table_args__ = (
        # Exactly one tenant adopts pre-existing data when multi-tenancy is
        # enabled: at most one row may carry is_system_tenant = true.
        Index(
            "uq_tenants_single_system_tenant",
            "id",
            unique=True,
            postgresql_where=text("is_system_tenant = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus, name="tenant_status_enum"),
        nullable=False,
        default=TenantStatus.active,
    )
    # Default tenant role for the first admin of this tenant
    admin_contact_role: Mapped[TenantRole] = mapped_column(
        Enum(TenantRole, name="tenant_role_enum"),
        nullable=False,
        default=TenantRole.tenant_admin,
    )
    # Implicit tenant adopting pre-existing data on upgraded deployments
    is_system_tenant: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_onboarded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    admin_contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    admin_contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships (forward refs resolved at mapper configuration time)
    memberships: Mapped[list["TenantUserMembership"]] = relationship(  # type: ignore[name-defined]
        "TenantUserMembership", back_populates="tenant"
    )
    invitations: Mapped[list["TenantInvitation"]] = relationship(  # type: ignore[name-defined]
        "TenantInvitation", back_populates="tenant"
    )

    def __repr__(self) -> str:
        return (
            f"<Tenant id={self.id} name={self.name} slug={self.slug} "
            f"status={self.status}>"
        )
