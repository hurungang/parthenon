"""SQLAlchemy models for tenant licensing: TenantLicense.

A license grants a tenant a tier (free / team / enterprise) with explicit
growth limits (max users, max agent types, monthly agent executions).
Supersede semantics: assigning a new license deactivates the previous
active one (``is_active = false`` + ``unassigned_at`` set) — the full
history is retained and the latest active row wins.  A tenant with no
active license falls back to the built-in free-tier default limits owned
by :class:`~app.services.tenancy.licensing_service.TenantLicensingService`.

Phase 10 — Self-Serve Registration, Tenant Root & Licensing (additive on
the multi-tenancy foundation; inert until the tenancy switch is on).
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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class LicenseTier(str, enum.Enum):
    """Commercial tier of a tenant license."""

    free = "free"
    team = "team"
    enterprise = "enterprise"


class TenantLicense(Base):
    """A tier license assigned to a tenant (latest active wins).

    At most ONE active license per tenant is enforced by a partial unique
    index (``uq_tenant_license_single_active``); superseded rows keep
    ``is_active = false`` and their ``unassigned_at`` timestamp so the
    assignment history is preserved for auditing.
    """

    __tablename__ = "tenant_licenses"
    __table_args__ = (
        Index(
            "uq_tenant_license_single_active",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = true"),
        ),
        Index("ix_tenant_licenses_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    tier: Mapped[LicenseTier] = mapped_column(
        Enum(LicenseTier, name="license_tier_enum"), nullable=False
    )
    # Growth limits carried by the license (positive integers)
    max_users: Mapped[int] = mapped_column(Integer, nullable=False)
    max_agent_types: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_agent_executions: Mapped[int] = mapped_column(Integer, nullable=False)
    # Supersede lifecycle: exactly one row per tenant has is_active = true
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Set when the license is superseded or removed (history retention)
    unassigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant")  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return (
            f"<TenantLicense id={self.id} tenant_id={self.tenant_id} "
            f"tier={self.tier} max_users={self.max_users} is_active={self.is_active}>"
        )
