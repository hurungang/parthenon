"""SQLAlchemy model for per-model availability under a vendor.

Per Phase 3.8 / 3.9, each (vendor ModelConfig, model_name) pair can be
individually disabled with ``is_disabled`` and a ``disabled_reason`` that
records the source of the disable state:

- ``manual`` — operator toggled the per-model row directly.
- ``vendor_cascaded`` — the parent ``ModelConfig.is_disabled`` is true and
  this row mirrors the cascade.

When the vendor is re-enabled, cascaded rows are removed/cleared but rows
that were manually disabled preserve their prior state.
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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ModelAvailabilityDisabledReason(str, enum.Enum):
    """Why this model is currently disabled.

    The cascade source is preserved so the operator UI and execution logs
    can show *why* a model is unavailable, not just that it is.
    """

    manual = "manual"
    vendor_cascaded = "vendor_cascaded"


class ModelAvailability(Base):
    """Per-model availability row under a vendor (ModelConfig)."""

    __tablename__ = "model_availability"
    __table_args__ = (
        UniqueConstraint(
            "vendor_model_config_id",
            "model_name",
            name="uq_availability_vendor_model",
        ),
        Index("ix_model_availability_vendor", "vendor_model_config_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    model_name: Mapped[str] = mapped_column(String(500), nullable=False)
    vendor_model_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_configs.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    disabled_reason: Mapped[ModelAvailabilityDisabledReason] = mapped_column(
        Enum(
            ModelAvailabilityDisabledReason,
            name="model_availability_disabled_reason_enum",
        ),
        nullable=False,
        default=ModelAvailabilityDisabledReason.manual,
        server_default=ModelAvailabilityDisabledReason.manual.value,
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
        return (
            f"<ModelAvailability id={self.id} vendor={self.vendor_model_config_id} "
            f"model_name={self.model_name} is_disabled={self.is_disabled} "
            f"reason={self.disabled_reason}>"
        )
