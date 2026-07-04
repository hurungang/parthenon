"""Scheduling API router — CRUD, pause, resume, and execution history."""
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT_SCHEDULES
from app.db.session import DbSession
from app.db.models.scheduling import ExecutionStatus, JobExecution, JobStatus, ScheduledJob
from app.schemas.scheduling import JobExecutionRead, ScheduledJobCreate, ScheduledJobRead, ScheduledJobUpdate
from app.services.scheduling.scheduler import get_scheduling_engine

logger = logging.getLogger(__name__)

ScheduleRouter = APIRouter(prefix="/schedules", tags=["Scheduling"])


@ScheduleRouter.get("", response_model=list[ScheduledJobRead])
async def list_schedules(
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SCHEDULES, "read")),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ScheduledJob]:
    result = await db.execute(
        select(ScheduledJob)
        .where(ScheduledJob.status != JobStatus.deleted)
        .order_by(ScheduledJob.name)
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


@ScheduleRouter.post("", response_model=ScheduledJobRead, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: ScheduledJobCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_AGENT_SCHEDULES, "create")),
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
    _: dict = Depends(require_permission(RT_AGENT_SCHEDULES, "read")),
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
    _: dict = Depends(require_permission(RT_AGENT_SCHEDULES, "update")),
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
    _: dict = Depends(require_permission(RT_AGENT_SCHEDULES, "delete")),
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
    _: dict = Depends(require_permission(RT_AGENT_SCHEDULES, "update")),
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
    _: dict = Depends(require_permission(RT_AGENT_SCHEDULES, "update")),
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
    _: dict = Depends(require_permission(RT_AGENT_SCHEDULES, "read")),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[JobExecution]:
    job = await db.get(ScheduledJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found")
    stmt = (
        select(JobExecution)
        .where(JobExecution.job_id == job_id)
        .order_by(JobExecution.started_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    executions = list(result.scalars().all())

    # Enrich with linked AgentJob session data when available
    from app.db.models.agents import AgentJob
    session_ids = [
        uuid.UUID(exec.result["session_id"])
        for exec in executions
        if exec.result and isinstance(exec.result, dict) and "session_id" in exec.result
    ]
    if session_ids:
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import joinedload
        agent_stmt = (
            sa_select(AgentJob)
            .options(joinedload(AgentJob.agent_type))
            .where(AgentJob.id.in_(session_ids))
        )
        agent_result = await db.execute(agent_stmt)
        sessions = {s.id: s for s in agent_result.unique().scalars().all()}
        for exec in executions:
            if exec.result and isinstance(exec.result, dict) and "session_id" in exec.result:
                sid = uuid.UUID(exec.result["session_id"])
                session = sessions.get(sid)
                if session:
                    exec.agent_session = dict(
                        id=session.id,
                        status=session.status,
                        output_data=session.output_data,
                        error_message=session.error_message,
                        started_at=session.started_at,
                        completed_at=session.completed_at,
                        agent_type_name=session.agent_type.name if session.agent_type else None,
                    )
    return executions
