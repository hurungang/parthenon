"""SQLAlchemy model for model guardrail evaluation records."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ModelGuardrailEvaluationPeriod(str, enum.Enum):
    """Configured period evaluated for a usage limit check."""

    hour = "hour"
    day = "day"
    week = "week"
    month = "month"


class ModelGuardrailPolicyMode(str, enum.Enum):
    """Policy mode active during evaluation."""

    terminate = "terminate"
    observe_only = "observe_only"


class ModelGuardrailEvaluationOutcome(str, enum.Enum):
    """Decision result of a policy evaluation."""

    pass_ = "pass"
    threshold_reached = "threshold_reached"
    blocked = "blocked"


class ModelGuardrailPostureState(str, enum.Enum):
    """Usage state relative to threshold."""

    within_limit = "within_limit"
    approaching_limit = "approaching_limit"
    breached = "breached"


class ModelGuardrailEvaluation(Base):
    """Per-run evaluation outcome for model guardrail policy checks."""

    __tablename__ = "model_guardrail_evaluations"
    __table_args__ = (
        Index("ix_model_guardrail_evaluations_configuration", "model_guardrail_configuration_id"),
        Index("ix_model_guardrail_evaluations_agent_job", "agent_job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    model_guardrail_configuration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_guardrail_configurations.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    policy_name: Mapped[str] = mapped_column(String(200), nullable=False)
    evaluated_period: Mapped[ModelGuardrailEvaluationPeriod] = mapped_column(
        Enum(ModelGuardrailEvaluationPeriod, name="model_guardrail_evaluated_period_enum"),
        nullable=False,
    )
    policy_mode: Mapped[ModelGuardrailPolicyMode] = mapped_column(
        Enum(ModelGuardrailPolicyMode, name="model_guardrail_policy_mode_enum"),
        nullable=False,
    )
    evaluation_outcome: Mapped[ModelGuardrailEvaluationOutcome] = mapped_column(
        Enum(
            ModelGuardrailEvaluationOutcome,
            name="model_guardrail_evaluation_outcome_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    threshold_value: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_value: Mapped[int] = mapped_column(Integer, nullable=False)
    posture_state: Mapped[ModelGuardrailPostureState] = mapped_column(
        Enum(ModelGuardrailPostureState, name="model_guardrail_posture_state_enum"),
        nullable=False,
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:
        return (
            "<ModelGuardrailEvaluation "
            f"id={self.id} agent_job_id={self.agent_job_id} outcome={self.evaluation_outcome}>"
        )
