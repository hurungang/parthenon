"""SQLAlchemy model for parent-child runtime topology edges."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AgentRunRelationshipType(str, enum.Enum):
    """Type of runtime relationship between agent runs."""

    delegation = "delegation"


class AgentRunRelationship(Base):
    """Stores runtime parent-child delegation edges for execution tree reconstruction."""

    __tablename__ = "agent_run_relationships"
    __table_args__ = (
        UniqueConstraint(
            "parent_agent_job_id",
            "child_agent_job_id",
            "relationship_type",
            name="uq_agent_run_relationship_edge",
        ),
        Index("ix_agent_run_relationships_parent", "parent_agent_job_id"),
        Index("ix_agent_run_relationships_child", "child_agent_job_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    parent_agent_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    child_agent_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_type: Mapped[AgentRunRelationshipType] = mapped_column(
        Enum(AgentRunRelationshipType, name="agent_run_relationship_type_enum"),
        nullable=False,
        default=AgentRunRelationshipType.delegation,
    )
    delegated_via_sop_step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sop_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    depth_from_root: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            "<AgentRunRelationship "
            f"id={self.id} parent={self.parent_agent_job_id} child={self.child_agent_job_id}>"
        )
