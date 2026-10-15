"""SQLAlchemy model for per-model availability under a Decision Model Provider.

Mirrors the existing LLM ``model_availability`` pattern: each
(system_one_provider_config, model_name) pair can be individually disabled
with ``is_disabled`` and a ``disabled_reason`` recording the source:

- ``manual`` — operator toggled the per-model row directly.
- ``vendor_cascaded`` — the parent provider's ``enabled`` is false and this
  row mirrors the vendor-level cascade.

When the provider is re-enabled, cascaded rows are cleared but rows that were
manually disabled preserve their prior state.
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


class DecisionModelAvailabilityDisabledReason(str, enum.Enum):
    """Why this decision model is currently disabled.

    The cascade source is preserved so the operator UI and execution logs
    can show *why* a model is unavailable, not just that it is.
    """

    manual = "manual"
    vendor_cascaded = "vendor_cascaded"


class DecisionModelAvailability(Base):
    """Per-model availability row under a Decision Model Provider."""

    __tablename__ = "decision_model_availability"
    __table_args__ = (
        UniqueConstraint(
            "decision_model_provider_id",
            "model_name",
            name="uq_decision_model_availability_provider_model",
        ),
        Index("ix_decision_model_availability_provider", "decision_model_provider_id"),
        Index("ix_decision_model_availability_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    model_name: Mapped[str] = mapped_column(String(500), nullable=False)
    decision_model_provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("system_one_provider_configs.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    disabled_reason: Mapped[DecisionModelAvailabilityDisabledReason] = mapped_column(
        Enum(
            DecisionModelAvailabilityDisabledReason,
            name="decision_model_availability_disabled_reason_enum",
        ),
        nullable=False,
        default=DecisionModelAvailabilityDisabledReason.manual,
        server_default=DecisionModelAvailabilityDisabledReason.manual.value,
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
            f"<DecisionModelAvailability id={self.id} "
            f"provider={self.decision_model_provider_id} "
            f"model_name={self.model_name} is_disabled={self.is_disabled} "
            f"reason={self.disabled_reason}>"
        )
