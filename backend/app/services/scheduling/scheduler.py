"""Scheduling Engine — APScheduler cron manager with PostgreSQL job store."""
import logging
from datetime import datetime, timezone
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
        logger.info(
            "Scheduled job '%s' (id=%s, cron=%s)", job.name, job.id, job.cron_expression
        )
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
                started_at=datetime.now(timezone.utc),
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
                execution.finished_at = datetime.now(timezone.utc)
                await db.commit()

    async def _dispatch(
        self, job: ScheduledJob, db: AsyncSession
    ) -> dict[str, Any]:
        """Dispatch the job to the appropriate target.

        For agent targets, enqueues a new AgentJob session via the
        GatewayLifecycleHandler (async launch path) and returns the
        session_id. The agent runtime executes asynchronously in the
        background.
        """
        from app.db.models.scheduling import JobTargetType

        if job.target_type == JobTargetType.agent:
            from app.core.tenant_context import TenantContext
            from app.db.models.agents import AgentType
            from app.db.models.tenant import Tenant
            from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler

            agent_type = await db.get(AgentType, job.target_id)
            if not agent_type:
                raise ValueError(f"Agent type {job.target_id} not found")

            # Multi-tenancy: scheduled jobs adopt their OWNING tenant's
            # context for the whole dispatch chain (CC → CH → AR), so the
            # triggered execution stays tenant-bound end to end.  Jobs
            # without a tenant (pre-adoption rows) keep the legacy
            # single-tenant behaviour.
            tenant_context = None
            owning_tenant_id = getattr(job, "tenant_id", None) or getattr(
                agent_type, "tenant_id", None
            )
            if owning_tenant_id is not None:
                tenant = await db.get(Tenant, owning_tenant_id)
                if tenant is not None:
                    tenant_context = TenantContext(
                        tenant_id=tenant.id,
                        slug=tenant.slug,
                        name=tenant.name,
                        is_system_tenant=bool(tenant.is_system_tenant),
                    )

            # Quota gate (Phase 10): schedule-triggered executions consult
            # the owning tenant's monthly execution quota at DISPATCH time.
            # An exhausted quota skips this dispatch (the job stays
            # scheduled for future fires), records ``quota_exhausted`` with
            # tenant attribution, and never crashes the scheduler loop.
            # Within-quota dispatches increment the counter exactly like
            # user-initiated submissions (no double counting).  Inert with
            # the switch off.
            if tenant_context is not None:
                from app.db.models.tenant_audit_event import TenantAuditActorType
                from app.services.tenancy.quota_service import get_tenant_quota_service

                quota = get_tenant_quota_service()
                check = await quota.check_executions(db, tenant_context.tenant_id)
                if not check.allowed:
                    assert check.payload is not None
                    await quota.record_quota_exhausted(
                        db,
                        tenant_context.tenant_id,
                        check.payload,
                        actor_type=TenantAuditActorType.system,
                        target_resource=f"scheduled_job:{job.id}",
                    )
                    logger.warning(
                        "Dispatch skipped (quota exhausted): job=%s tenant=%s "
                        "used=%d limit=%d",
                        job.id, tenant_context.slug, check.used, check.limit,
                    )
                    return {
                        "status": "skipped",
                        "reason": "quota_exhausted",
                        "quota_type": check.payload.quota_type,
                        "tier": check.payload.tier,
                        "limit": check.limit,
                        "used": check.used,
                        "session_id": None,
                    }
                await quota.increment_executions(db, tenant_context.tenant_id)

            handler = GatewayLifecycleHandler()
            result = await handler.launch(
                agent_type_id=job.target_id,
                input_data=job.payload,
                user_id=job.scheduled_by_user_id,
                db=db,
                tenant_context=tenant_context,
            )
            return result

        else:
            raise ValueError(f"Unknown job target type: {job.target_type}")


    async def recover_schedules(self, db_factory: Any) -> int:
        """Load all active jobs from DB and register with APScheduler."""
        from sqlalchemy import select
        async with db_factory() as db:
            result = await db.execute(
                select(ScheduledJob).where(ScheduledJob.status == JobStatus.active)
            )
            jobs = list(result.scalars().all())
        for job in jobs:
            await self.add_job(job, db_factory)
        logger.info("Recovered %d schedule(s) from database", len(jobs))
        return len(jobs)


# Singleton
_engine: SchedulingEngine | None = None


def get_scheduling_engine() -> SchedulingEngine:
    """Return the singleton SchedulingEngine."""
    global _engine
    if _engine is None:
        _engine = SchedulingEngine()
    return _engine
