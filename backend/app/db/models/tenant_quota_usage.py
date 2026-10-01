"""SQLAlchemy model for TenantQuotaUsage — per-tenant quota counters.

In this epic only ``monthly_executions`` persists counter rows: one row
per tenant per calendar-month bucket (``period_start`` = first day of the
month, UTC).  The counter is incremented exactly once per ACCEPTED
execution at the Control Center enforcement point; a new month starts a
fresh bucket so the reset is implicit, and usage is never refunded on
completion/failure.  ``users`` and ``agent_types`` quotas are derived
live from record counts and never persist rows here.

Phase 10 — additive on the multi-tenancy foundation.
"""
import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class QuotaType(str, enum.Enum):
    """The three governed quotas (only monthly_executions persists rows)."""

    users = "users"
    agent_types = "agent_types"
    monthly_executions = "monthly_executions"


class TenantQuotaUsage(Base):
    """Persistent usage counter for one tenant/quota/month bucket."""

    __tablename__ = "tenant_quota_usage"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "quota_type",
            "period_start",
            name="uq_tenant_quota_usage_tenant_type_period",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    quota_type: Mapped[QuotaType] = mapped_column(
        Enum(QuotaType, name="quota_type_enum"), nullable=False
    )
    # Calendar-month bucket (first day of month, UTC)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    tenant: Mapped["Tenant"] = relationship("Tenant")  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return (
            f"<TenantQuotaUsage id={self.id} tenant_id={self.tenant_id} "
            f"quota_type={self.quota_type} period_start={self.period_start} "
            f"used_count={self.used_count}>"
        )
