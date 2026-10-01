"""SQLAlchemy model for TenantAuditEvent.

Tenant lifecycle actions and security-relevant cross-tenant access attempts,
visible to the platform admin. ``tenant_id`` is null for platform-level
events; tenant attribution keeps audit trails traceable end to end.
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
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class TenantAuditEventType(str, enum.Enum):
    """Type of tenancy-related audit event."""

    tenant_created = "tenant_created"
    tenant_updated = "tenant_updated"
    tenant_suspended = "tenant_suspended"
    tenant_resumed = "tenant_resumed"
    tenant_deleted = "tenant_deleted"
    cross_tenant_access_denied = "cross_tenant_access_denied"
    tenant_boundary_violation = "tenant_boundary_violation"
    platform_setting_updated = "platform_setting_updated"
    # Phase 10 — self-serve registration, tenant root, licensing & quotas
    self_serve_registration = "self_serve_registration"
    root_protection_rejected = "root_protection_rejected"
    license_assigned = "license_assigned"
    license_changed = "license_changed"
    license_removed = "license_removed"
    quota_exhausted = "quota_exhausted"


class TenantAuditActorType(str, enum.Enum):
    """Kind of principal that performed the audited action."""

    platform_admin = "platform_admin"
    tenant_admin = "tenant_admin"
    tenant_user = "tenant_user"
    tenant_agent = "tenant_agent"
    api_key = "api_key"
    system = "system"


class TenantAuditEvent(Base):
    """Append-only audit record for tenant lifecycle and security events."""

    __tablename__ = "tenant_audit_events"
    __table_args__ = (
        Index("ix_tenant_audit_events_tenant_id", "tenant_id"),
        Index("ix_tenant_audit_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Null for platform-level events
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[TenantAuditEventType] = mapped_column(
        Enum(TenantAuditEventType, name="tenant_audit_event_type_enum"), nullable=False
    )
    actor_type: Mapped[TenantAuditActorType] = mapped_column(
        Enum(TenantAuditActorType, name="tenant_audit_actor_type_enum"), nullable=False
    )
    # Platform user or membership id of the actor
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    # Resource type and identifier that was addressed
    target_resource: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Structured event payload
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Surfaces to the platform admin security view
    is_security_relevant: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    tenant: Mapped["Tenant | None"] = relationship("Tenant")  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return (
            f"<TenantAuditEvent id={self.id} tenant_id={self.tenant_id} "
            f"event_type={self.event_type} actor_type={self.actor_type}>"
        )
