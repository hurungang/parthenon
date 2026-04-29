"""Pydantic v2 schemas for Scheduling."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, StringConstraints
from typing import Annotated

from app.db.models.scheduling import ExecutionStatus, JobStatus, JobTargetType


class ScheduledJobCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: str | None = None
    cron_expression: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    target_type: JobTargetType
    target_id: uuid.UUID
    payload: dict[str, Any] | None = None


class ScheduledJobUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    cron_expression: str | None = None
    payload: dict[str, Any] | None = None


class ScheduledJobRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    cron_expression: str
    target_type: JobTargetType
    target_id: uuid.UUID
    payload: dict[str, Any] | None
    status: JobStatus
    scheduler_job_id: str | None
    created_at: datetime
    updated_at: datetime


class JobExecutionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    job_id: uuid.UUID
    status: ExecutionStatus
    error: str | None
    result: dict[str, Any] | None
    started_at: datetime
    finished_at: datetime | None
