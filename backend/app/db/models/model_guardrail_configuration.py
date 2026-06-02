"""SQLAlchemy model for model-level guardrail configurations.

Restructured in Phase 3.7 to one row per (model, period). The previous flat
per-model row with four period-limit columns is replaced by:

- ``period`` (enum) — exactly one period per row (hour/day/week/month)
- ``limit_value`` (int) — single numeric limit for this guardrail
- ``unit`` (enum) — unit for the limit and rollups (tokens / k)
- ``enforcement_posture`` (enum) — default terminate for new configurations
- ``is_active`` (bool) — per-guardrail enable/disable toggle
- ``model_id`` / ``model_name`` — FK + denormalised name (the name is the
  canonical identifier the frontend carries; the FK is the resolved UUID)

A unique constraint on (model_id, period) prevents two guardrails on the same
(model, period) pair.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ModelGuardrailEnforcementPosture(str, enum.Enum):
    """Default enforcement behavior for a model guardrail profile."""

    terminate = "terminate"
    observe_only = "observe_only"


class ModelUsageUnit(str, enum.Enum):
    """Unit of measure for model-usage numeric limits and rollups."""

    tokens = "tokens"
    k = "k"


class ModelGuardrailPeriod(str, enum.Enum):
    """Time bucket represented by this guardrail row.

    One period per row — the dashboard and posture rollups group guardrails
    by (model, period).
    """

    hour = "hour"
    day = "day"
    week = "week"
    month = "month"


class ModelGuardrailConfiguration(Base):
    """Per-period model-usage guardrail configuration.

    One row covers a single (model, period) pair; each model can have up to
    four rows (one per period).  Operators may configure only the periods
    they want — no forced four-period entry.
    """

    __tablename__ = "model_guardrail_configurations"
    __table_args__ = (
        UniqueConstraint("model_id", "period", name="uq_guardrail_model_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_configs.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String(500), nullable=False)
    period: Mapped[ModelGuardrailPeriod] = mapped_column(
        Enum(
            ModelGuardrailPeriod,
            name="model_guardrail_period_enum",
        ),
        nullable=False,
    )
    limit_value: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[ModelUsageUnit] = mapped_column(
        Enum(ModelUsageUnit, name="model_usage_unit_enum"),
        nullable=False,
        default=ModelUsageUnit.k,
        server_default=ModelUsageUnit.k.value,
    )
    enforcement_posture: Mapped[ModelGuardrailEnforcementPosture] = mapped_column(
        Enum(
            ModelGuardrailEnforcementPosture,
            name="model_guardrail_enforcement_posture_enum",
        ),
        nullable=False,
        default=ModelGuardrailEnforcementPosture.terminate,
        server_default=ModelGuardrailEnforcementPosture.terminate.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
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
            f"<ModelGuardrailConfiguration id={self.id} model_name={self.model_name} "
            f"period={self.period} limit={self.limit_value}{self.unit.value}>"
        )
