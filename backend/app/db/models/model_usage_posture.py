"""SQLAlchemy model for dashboard-facing model usage posture snapshots."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ModelUsagePosturePeriod(str, enum.Enum):
    """Time bucket represented by this posture snapshot."""

    hour = "hour"
    day = "day"
    week = "week"
    month = "month"


class ModelUsagePostureState(str, enum.Enum):
    """Current usage state relative to configured limit."""

    within_limit = "within_limit"
    approaching_limit = "approaching_limit"
    breached = "breached"


class ModelUsagePosture(Base):
    """Current runtime dashboard posture per model and period."""

    __tablename__ = "model_usage_postures"
    __table_args__ = (
        UniqueConstraint(
            "model_guardrail_configuration_id",
            "posture_period",
            name="uq_model_usage_posture_configuration_period",
        ),
        Index("ix_model_usage_postures_model", "model_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    model_guardrail_configuration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_guardrail_configurations.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    posture_period: Mapped[ModelUsagePosturePeriod] = mapped_column(
        Enum(ModelUsagePosturePeriod, name="model_usage_posture_period_enum"),
        nullable=False,
    )
    usage_value: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_value: Mapped[int] = mapped_column(Integer, nullable=False)
    posture_state: Mapped[ModelUsagePostureState] = mapped_column(
        Enum(ModelUsagePostureState, name="model_usage_posture_state_enum"),
        nullable=False,
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:
        return f"<ModelUsagePosture id={self.id} model_id={self.model_id} period={self.posture_period}>"
