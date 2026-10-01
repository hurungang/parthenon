"""SQLAlchemy model for PlatformSetting.

Tenant-agnostic platform configuration store. Home of the
``multi_tenancy_enabled`` switch (default ``false``): platform scope — only
the platform admin reads/writes it.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class PlatformSettingCategory(str, enum.Enum):
    """Scope of a platform setting."""

    tenancy = "tenancy"
    platform = "platform"


class PlatformSetting(Base):
    """Key/value platform configuration applied across all tenants."""

    __tablename__ = "platform_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Unique setting name (e.g. multi_tenancy_enabled)
    key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Operator-facing description
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[PlatformSettingCategory] = mapped_column(
        Enum(PlatformSettingCategory, name="platform_setting_category_enum"),
        nullable=False,
        default=PlatformSettingCategory.tenancy,
    )
    # Always true: platform scope, applies to all tenants
    is_tenant_agnostic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
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

    def __repr__(self) -> str:
        return f"<PlatformSetting id={self.id} key={self.key} category={self.category}>"
