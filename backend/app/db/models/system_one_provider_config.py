"""SQLAlchemy model for the multi-vendor Decision Model Provider registry.

Conceptually renamed from "System One Provider" to "Decision Model Provider";
the internal table identity (``system_one_provider_configs``) is kept unchanged
to limit migration risk. Multiple providers may be registered per tenant; each
stores encrypted credentials (AES-256, never returned in plaintext) and a
vendor-level ``enabled`` flag that cascades to its per-model availability rows
(see ``decision_model_availability.py``).
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SystemOneProviderType(str, enum.Enum):
    """Supported decision model provider (vendor) types — extensible."""

    typesafe = "typesafe"


class SystemOneProviderConfig(Base):
    """A decision model provider (vendor) with credentials and default model.

    Follows the encrypted-credential pattern used by identity provider configs:
    the API key is AES-256 encrypted at rest and never returned in plaintext.
    Multiple rows per tenant are allowed; display names are unique per vendor
    type within a tenant.
    """

    __tablename__ = "system_one_provider_configs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider_type",
            "display_name",
            name="uq_system_one_providers_tenant_type_display",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Tenant scoping matches other tenant-scoped models (skills, result_records):
    # nullable FK with SET NULL so rows survive tenant deletion.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    provider_type: Mapped[SystemOneProviderType] = mapped_column(
        Enum(SystemOneProviderType, name="system_one_provider_type_enum"),
        nullable=False,
        default=SystemOneProviderType.typesafe,
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    default_model: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="jev-latest",
        server_default="jev-latest",
    )
    encrypted_api_key: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
        comment="AES-256 encrypted API key; never returned in plaintext",
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled_models: Mapped[list | None] = mapped_column(JSON, nullable=True)
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
        return (
            f"<SystemOneProviderConfig id={self.id} "
            f"provider_type={self.provider_type} display_name={self.display_name}>"
        )
