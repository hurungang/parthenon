"""SQLAlchemy model for TenantSetting.

Tenant-scoped key/value configuration store. Unlike ``PlatformSetting``
(which is tenant-AGNOSTIC and globally unique by key), each tenant owns
its own row per key — e.g. the per-tenant workflow-generation model
selection (``workflow_generation_model_id``).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TenantSetting(Base):
    """Key/value configuration scoped to a single tenant."""

    __tablename__ = "tenant_settings"
    __table_args__ = (
        Index("uq_tenant_settings_tenant_key", "tenant_id", "key", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<TenantSetting id={self.id} tenant_id={self.tenant_id} key={self.key}>"
