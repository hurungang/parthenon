"""Scheduling Engine — APScheduler cron manager with PostgreSQL job store."""

import logging
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.scheduling import ExecutionStatus, JobExecution, JobStatus, ScheduledJob

logger = logging.getLogger(__name__)


class SchedulingEngine:
    """
    APScheduler-based cron manager.
    Jobs are stored in the database via ScheduledJob/JobExecution models.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._started = False

    def start(self) -> None:
        """Start the APScheduler background scheduler."""
        if not self._started:
            self._scheduler.start()
            self._started = True
            logger.info("SchedulingEngine started")

    def shutdown(self) -> None:
        """Shutdown the scheduler."""
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            logger.info("SchedulingEngine stopped")

    async def add_job(self, job: ScheduledJob, db_factory: Any) -> str:
        """
        Register a cron job with APScheduler.

        Args:
            job: The ScheduledJob record.
            db_factory: Async session factory for creating DB sessions in the job handler.

        Returns:
            The APScheduler job ID.
        """
        trigger = CronTrigger.from_crontab(job.cron_expression, timezone="UTC")
        scheduler_job = self._scheduler.add_job(
            func=self._execute_job,
            trigger=trigger,
            id=str(job.id),
            replace_existing=True,
            kwargs={"job_id": str(job.id), "db_factory": db_factory},
        )
        logger.info("Scheduled job '%s' (id=%s, cron=%s)", job.name, job.id, job.cron_expression)
        return scheduler_job.id

    async def remove_job(self, scheduler_job_id: str) -> None:
        """Remove a job from APScheduler."""
        try:
            self._scheduler.remove_job(scheduler_job_id)
        except Exception:
            logger.warning("Job %s not found in scheduler", scheduler_job_id)

    async def pause_job(self, scheduler_job_id: str) -> None:
        """Pause a scheduled job."""
        try:
            self._scheduler.pause_job(scheduler_job_id)
        except Exception:
            logger.warning("Failed to pause job %s", scheduler_job_id)

    async def resume_job(self, scheduler_job_id: str) -> None:
        """Resume a paused job."""
        try:
            self._scheduler.resume_job(scheduler_job_id)
        except Exception:
            logger.warning("Failed to resume job %s", scheduler_job_id)

    async def _execute_job(self, job_id: str, db_factory: Any) -> None:
        """Execute a scheduled job and record the result."""
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            job = await db.get(ScheduledJob, job_id)
            if not job or job.status != JobStatus.active:
                return

            execution = JobExecution(
                job_id=job.id,
                status=ExecutionStatus.running,
                started_at=datetime.now(UTC),
            )
            db.add(execution)
            await db.flush()

            try:
                result = await self._dispatch(job, db)
                execution.status = ExecutionStatus.success
                execution.result = result
            except Exception as exc:
                logger.error("Job %s failed: %s", job_id, exc)
                execution.status = ExecutionStatus.failure
                execution.error = str(exc)
            finally:
                execution.finished_at = datetime.now(UTC)
                await db.commit()

    async def _dispatch(self, job: ScheduledJob, db: AsyncSession) -> dict[str, Any]:
        """Dispatch the job to the appropriate target (agent or SOP)."""
        from app.db.models.scheduling import JobTargetType

        if job.target_type == JobTargetType.agent:
            # Spawn a new agent instance and send the scheduled prompt
            from app.db.models.agents import AgentType
            from app.services.agents.instance_manager import AgentInstanceManager
            from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler

            agent_type = await db.get(AgentType, job.target_id)
            if not agent_type:
                raise ValueError(f"Agent type {job.target_id} not found")

            manager = AgentInstanceManager()
            instance = await manager.spawn(job.target_id, "scheduler", db)
            instance = await manager.activate(instance.id, db)

            handler = GatewayLifecycleHandler()
            prompt = (job.payload or {}).get("prompt", "Execute scheduled task")
            result = await handler.request(
                session_handle=instance.session_handle,
                prompt=prompt,
                context=job.payload,
                db=db,
            )
            await manager.close(instance.id, db)
            return result

        elif job.target_type == JobTargetType.sop:
            from app.services.skills.sop_orchestrator import SopOrchestrator

            orchestrator = SopOrchestrator()
            prompt = (job.payload or {}).get("prompt", "Execute scheduled SOP")
            return await orchestrator.execute(
                sop_id=job.target_id,
                prompt=prompt,
                context=job.payload,
                db=db,
            )
        else:
            raise ValueError(f"Unknown job target type: {job.target_type}")


# Singleton
_engine: SchedulingEngine | None = None


def get_scheduling_engine() -> SchedulingEngine:
    """Return the singleton SchedulingEngine."""
    global _engine
    if _engine is None:
        _engine = SchedulingEngine()
    return _engine
