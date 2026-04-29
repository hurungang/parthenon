"""SQLAlchemy models for Scheduling: ScheduledJob, JobExecution."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class JobStatus(str, enum.Enum):
    """Status of a scheduled job."""

    active = "active"
    paused = "paused"
    deleted = "deleted"


class JobTargetType(str, enum.Enum):
    """What the scheduled job triggers."""

    agent = "agent"
    sop = "sop"


class ExecutionStatus(str, enum.Enum):
    """Outcome of a single job execution."""

    success = "success"
    failure = "failure"
    running = "running"


class ScheduledJob(Base):
    """A cron-based schedule for a prompt or SOP."""

    __tablename__ = "scheduled_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[JobTargetType] = mapped_column(
        Enum(JobTargetType, name="job_target_type_enum"), nullable=False
    )
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Prompt or parameters passed to the target
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status_enum"), nullable=False, default=JobStatus.active
    )
    # APScheduler job ID for persistence correlation
    scheduler_job_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    executions: Mapped[list["JobExecution"]] = relationship(
        "JobExecution", back_populates="job", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ScheduledJob id={self.id} name={self.name} status={self.status}>"


class JobExecution(Base):
    """A record of a single scheduled job run."""

    __tablename__ = "job_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scheduled_jobs.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, name="execution_status_enum"),
        nullable=False,
        default=ExecutionStatus.running,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    job: Mapped["ScheduledJob"] = relationship("ScheduledJob", back_populates="executions")

    def __repr__(self) -> str:
        return f"<JobExecution id={self.id} job_id={self.job_id} status={self.status}>"
