"""Scheduling API router — CRUD, pause, resume, and execution history."""
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import require_permission
from app.core.resource_types import RT_SCHEDULING
from app.db.session import DbSession
from app.db.models.scheduling import ExecutionStatus, JobExecution, JobStatus, ScheduledJob
from app.schemas.scheduling import JobExecutionRead, ScheduledJobCreate, ScheduledJobRead, ScheduledJobUpdate
from app.services.scheduling.scheduler import get_scheduling_engine

logger = logging.getLogger(__name__)

ScheduleRouter = APIRouter(prefix="/schedules", tags=["Scheduling"])


@ScheduleRouter.get("", response_model=list[ScheduledJobRead])
async def list_schedules(
    db: DbSession,
    _: dict = Depends(require_permission(RT_SCHEDULING, "read")),
) -> list[ScheduledJob]:
    result = await db.execute(
        select(ScheduledJob)
        .where(ScheduledJob.status != JobStatus.deleted)
        .order_by(ScheduledJob.name)
    )
    return list(result.scalars().all())


@ScheduleRouter.post("", response_model=ScheduledJobRead, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: ScheduledJobCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SCHEDULING, "create")),
) -> ScheduledJob:
    job = ScheduledJob(**body.model_dump())
    db.add(job)
    await db.flush()

    # Register with APScheduler
    engine = get_scheduling_engine()
    from app.db.session import AsyncSessionLocal
    scheduler_job_id = await engine.add_job(job, AsyncSessionLocal)
    job.scheduler_job_id = scheduler_job_id
    await db.flush()
    await db.refresh(job)
    return job


@ScheduleRouter.get("/{job_id}", response_model=ScheduledJobRead)
async def get_schedule(
    job_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SCHEDULING, "read")),
) -> ScheduledJob:
    job = await db.get(ScheduledJob, job_id)
    if not job or job.status == JobStatus.deleted:
        raise HTTPException(status_code=404, detail="Scheduled job not found")
    return job


@ScheduleRouter.put("/{job_id}", response_model=ScheduledJobRead)
async def update_schedule(
    job_id: uuid.UUID,
    body: ScheduledJobUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SCHEDULING, "update")),
) -> ScheduledJob:
    job = await db.get(ScheduledJob, job_id)
    if not job or job.status == JobStatus.deleted:
        raise HTTPException(status_code=404, detail="Scheduled job not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(job, field, value)
    await db.flush()

    # Re-register with updated cron expression
    if body.cron_expression and job.scheduler_job_id:
        engine = get_scheduling_engine()
        await engine.remove_job(job.scheduler_job_id)
        from app.db.session import AsyncSessionLocal
        scheduler_job_id = await engine.add_job(job, AsyncSessionLocal)
        job.scheduler_job_id = scheduler_job_id
        await db.flush()

    await db.refresh(job)
    return job


@ScheduleRouter.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    job_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SCHEDULING, "delete")),
) -> None:
    job = await db.get(ScheduledJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found")
    if job.scheduler_job_id:
        engine = get_scheduling_engine()
        await engine.remove_job(job.scheduler_job_id)
    job.status = JobStatus.deleted
    await db.flush()


@ScheduleRouter.post("/{job_id}/pause", response_model=ScheduledJobRead)
async def pause_schedule(
    job_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SCHEDULING, "update")),
) -> ScheduledJob:
    job = await db.get(ScheduledJob, job_id)
    if not job or job.status == JobStatus.deleted:
        raise HTTPException(status_code=404, detail="Scheduled job not found")
    if job.scheduler_job_id:
        engine = get_scheduling_engine()
        await engine.pause_job(job.scheduler_job_id)
    job.status = JobStatus.paused
    await db.flush()
    await db.refresh(job)
    return job


@ScheduleRouter.post("/{job_id}/resume", response_model=ScheduledJobRead)
async def resume_schedule(
    job_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SCHEDULING, "update")),
) -> ScheduledJob:
    job = await db.get(ScheduledJob, job_id)
    if not job or job.status == JobStatus.deleted:
        raise HTTPException(status_code=404, detail="Scheduled job not found")
    if job.scheduler_job_id:
        engine = get_scheduling_engine()
        await engine.resume_job(job.scheduler_job_id)
    job.status = JobStatus.active
    await db.flush()
    await db.refresh(job)
    return job


@ScheduleRouter.get("/{job_id}/executions", response_model=list[JobExecutionRead])
async def list_executions(
    job_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SCHEDULING, "read")),
) -> list[JobExecution]:
    job = await db.get(ScheduledJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found")
    result = await db.execute(
        select(JobExecution)
        .where(JobExecution.job_id == job_id)
        .order_by(JobExecution.started_at.desc())
        .limit(100)
    )
    return list(result.scalars().all())
