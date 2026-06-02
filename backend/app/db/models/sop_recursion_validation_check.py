"""SQLAlchemy model for SOP recursion validation checks."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SopRecursionCheckContext(str, enum.Enum):
    """Execution context where validation was requested."""

    create = "create"
    update = "update"
    run = "run"


class SopRecursionCheckOutcome(str, enum.Enum):
    """Result of recursion validation."""

    pass_ = "pass"
    fail = "fail"


class SopRecursionValidationCheck(Base):
    """Validation summary produced during create/update/run recursion checks."""

    __tablename__ = "sop_recursion_validation_checks"
    __table_args__ = (
        Index("ix_sop_recursion_validation_checks_agent_type", "checked_agent_type_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    checked_agent_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    check_context: Mapped[SopRecursionCheckContext] = mapped_column(
        Enum(SopRecursionCheckContext, name="sop_recursion_check_context_enum"),
        nullable=False,
    )
    check_outcome: Mapped[SopRecursionCheckOutcome] = mapped_column(
        Enum(
            SopRecursionCheckOutcome,
            name="sop_recursion_check_outcome_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    checked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identities.id", ondelete="SET NULL"),
        nullable=True,
    )
    summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    def __repr__(self) -> str:
        return (
            "<SopRecursionValidationCheck "
            f"id={self.id} agent_type={self.checked_agent_type_id} outcome={self.check_outcome}>"
        )
