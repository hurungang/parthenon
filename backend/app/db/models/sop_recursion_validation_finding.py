"""SQLAlchemy model for detailed SOP recursion validation findings."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SopRecursionFindingType(str, enum.Enum):
    """Detailed recursion/dead-loop finding types."""

    cycle_detected = "cycle_detected"
    dead_loop_risk = "dead_loop_risk"
    max_depth_violation = "max_depth_violation"
    repeated_delegation_path = "repeated_delegation_path"


class SopRecursionFindingSeverity(str, enum.Enum):
    """Severity level for recursion findings."""

    warning = "warning"
    error = "error"


class SopRecursionValidationFinding(Base):
    """Detailed findings captured under a recursion validation check."""

    __tablename__ = "sop_recursion_validation_findings"
    __table_args__ = (
        Index("ix_sop_recursion_validation_findings_check", "validation_check_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    validation_check_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sop_recursion_validation_checks.id", ondelete="CASCADE"),
        nullable=False,
    )
    finding_type: Mapped[SopRecursionFindingType] = mapped_column(
        Enum(SopRecursionFindingType, name="sop_recursion_finding_type_enum"),
        nullable=False,
    )
    severity: Mapped[SopRecursionFindingSeverity] = mapped_column(
        Enum(SopRecursionFindingSeverity, name="sop_recursion_finding_severity_enum"),
        nullable=False,
    )
    involved_sop_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sops.id", ondelete="SET NULL"),
        nullable=True,
    )
    involved_sop_step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sop_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    path_signature: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            "<SopRecursionValidationFinding "
            f"id={self.id} check_id={self.validation_check_id} type={self.finding_type}>"
        )
