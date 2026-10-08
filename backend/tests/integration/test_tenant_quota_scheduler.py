"""Scheduler quota-gate integration tests (Phase 10.18, CS-40).

Schedule-triggered executions consult the owning tenant's monthly
execution quota at DISPATCH time (``SchedulingEngine._dispatch``):

- within quota: the dispatch proceeds and the counter increments
  EXACTLY like a user-submitted execution (shared bucket, no double
  counting);
- over quota: the dispatch is SKIPPED (nothing reaches the gateway
  lifecycle handler → never dispatched to CH/AR), a tenant-attributed
  ``quota_exhausted`` audit event is recorded targeting the scheduled
  job, and the job STAYS scheduled for future fires;
- jobs without a tenant (pre-adoption rows) keep the legacy behaviour
  (no quota consultation);
- the full ``_execute_job`` loop records the skip as a successful
  JobExecution (the scheduler never crashes on an exhausted quota).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.models.agents import AgentJob, AgentType  # noqa: E402
from app.db.models.platform_user import PlatformUser  # noqa: E402
from app.db.models.scheduling import (  # noqa: E402
    JobStatus,
    JobTargetType,
    ScheduledJob,
)
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_audit_event import TenantAuditEvent  # noqa: E402
from app.db.models.tenant_membership import TenantUserMembership  # noqa: E402
from app.db.models.tenant_quota_usage import QuotaType, TenantQuotaUsage  # noqa: E402
from app.services.scheduling.scheduler import SchedulingEngine  # noqa: E402
from app.services.tenancy.licensing_service import (  # noqa: E402
    get_tenant_licensing_service,
)
from app.services.tenancy.quota_service import get_tenant_quota_service  # noqa: E402

_TS_HOLDER = {"v": uuid.uuid4().hex[:8]}


def _ts() -> str:
    return _TS_HOLDER["v"]


@pytest.fixture(autouse=True)
def _fresh_suffix():
    _TS_HOLDER["v"] = uuid.uuid4().hex[:8]
    yield


@pytest_asyncio.fixture(autouse=True)
async def _fresh_state(test_engine):
    """Reset the settings singleton + switch row (engine is session-scoped)."""
    import app.services.tenancy.platform_settings_service as settings_module

    from app.db.models.platform_setting import PlatformSetting

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    settings_module._service = None
    async with SessionLocal() as db:
        await db.execute(
            PlatformSetting.__table__.delete().where(
                PlatformSetting.key == "multi_tenancy_enabled"
            )
        )
        await db.commit()
    settings_module._service = None
    yield
    settings_module._service = None


async def _enable_tenancy(test_engine) -> None:
    from app.db.models.platform_setting import PlatformSetting

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(PlatformSetting).where(
                    PlatformSetting.key == "multi_tenancy_enabled"
                )
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(
                PlatformSetting(
                    key="multi_tenancy_enabled",
                    value={"enabled": True},
                    category="tenancy",
                    is_tenant_agnostic=True,
                )
            )
        else:
            row.value = {"enabled": True}
        await db.commit()
    import app.services.tenancy.platform_settings_service as settings_module

    settings_module._service = None


@pytest_asyncio.fixture
async def world(test_engine):
    """Tenant + root member + agent type + scheduled job targeting it."""
    await _enable_tenancy(test_engine)
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as db:
        tenant = Tenant(name=f"Sched Org {_ts()}", slug=f"sched-{_ts()}")
        owner = PlatformUser(
            sub=f"sched-root-{_ts()}", email=f"sched-{_ts()}@t.dev",
            display_name="Owner",
        )
        db.add_all([tenant, owner])
        await db.flush()
        db.add(
            TenantUserMembership(
                tenant_id=tenant.id, user_id=owner.id,
                tenant_role="tenant_admin", is_root=True,
            )
        )
        agent_type = AgentType(
            name=f"sched-type-{_ts()}", tenant_id=tenant.id
        )
        db.add(agent_type)
        await db.flush()
        job = ScheduledJob(
            tenant_id=tenant.id,
            name=f"sched-job-{_ts()}",
            cron_expression="*/5 * * * *",
            target_type=JobTargetType.agent,
            target_id=agent_type.id,
            payload={"prompt": "scheduled run"},
            status=JobStatus.active,
            scheduled_by_user_id=owner.id,
        )
        db.add(job)
        await db.commit()
        return {
            "tenant": tenant,
            "owner": owner,
            "agent_type": agent_type,
            "job": job,
            "sf": SessionLocal,
            "engine": test_engine,
        }


async def _bucket(world) -> int:
    SessionLocal = world["sf"]
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(TenantQuotaUsage).where(
                    TenantQuotaUsage.tenant_id == world["tenant"].id,
                    TenantQuotaUsage.quota_type == QuotaType.monthly_executions,
                )
            )
        )
        return sum(r.used_count for r in row.scalars().all())


async def _seed_full_bucket(world, limit: int) -> None:
    SessionLocal = world["sf"]
    async with SessionLocal() as db:
        db.add(
            TenantQuotaUsage(
                tenant_id=world["tenant"].id,
                quota_type=QuotaType.monthly_executions,
                period_start=datetime.now(timezone.utc).date().replace(day=1),
                used_count=limit,
            )
        )
        await db.commit()


@pytest.fixture
def mock_launch():
    """Patch the gateway lifecycle handler so no real dispatch happens."""
    with patch(
        "app.services.gateway.lifecycle_handler.GatewayLifecycleHandler.launch",
        new=AsyncMock(return_value={"session_id": str(uuid.uuid4())}),
    ) as m:
        yield m


# ── CS-40: dispatch-time quota consultation ──────────────────────────────────


class TestSchedulerQuotaGate:
    async def test_within_quota_dispatch_counts_like_user_submission(
        self, world, mock_launch
    ):
        """CS-40: within quota the dispatch proceeds and increments the
        counter EXACTLY like a user-submitted execution."""
        engine = SchedulingEngine()
        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            job = await db.get(ScheduledJob, world["job"].id)
            result = await engine._dispatch(job, db)
            await db.commit()

        assert "session_id" in result  # dispatched, not skipped
        assert await _bucket(world) == 1
        mock_launch.assert_awaited_once()

    async def test_user_submission_and_scheduler_share_one_counter(
        self, world, mock_launch
    ):
        """CS-40: scheduler dispatches count in the SAME bucket as user
        submissions — one increment each, no double counting."""
        engine = SchedulingEngine()
        SessionLocal = world["sf"]

        # Simulate a user-submitted execution (the API gate's contract).
        async with SessionLocal() as db:
            await get_tenant_quota_service().increment_executions(
                db, world["tenant"].id
            )
            await db.commit()

        async with SessionLocal() as db:
            job = await db.get(ScheduledJob, world["job"].id)
            await engine._dispatch(job, db)
            await db.commit()

        assert await _bucket(world) == 2  # 1 user + 1 scheduled
        mock_launch.assert_awaited_once()

    async def test_exhausted_quota_skips_dispatch_and_audits(
        self, world, mock_launch
    ):
        """CS-40: exhausted quota → dispatch skipped, nothing launched,
        ``quota_exhausted`` audit recorded with the job attribution, and
        the job stays scheduled."""
        await _seed_full_bucket(world, limit=100)  # free-tier limit
        engine = SchedulingEngine()
        SessionLocal = world["sf"]

        async with SessionLocal() as db:
            job = await db.get(ScheduledJob, world["job"].id)
            result = await engine._dispatch(job, db)
            await db.commit()

        assert result["status"] == "skipped"
        assert result["reason"] == "quota_exhausted"
        assert result["quota_type"] == "monthly_executions"
        assert result["tier"] == "free"
        assert result["limit"] == 100
        assert result["used"] == 100
        assert result["session_id"] is None
        mock_launch.assert_not_awaited()  # nothing reached the gateway
        assert await _bucket(world) == 100  # counter NOT incremented

        async with SessionLocal() as db:
            events = (
                (
                    await db.execute(
                        select(TenantAuditEvent).where(
                            TenantAuditEvent.event_type == "quota_exhausted",
                            TenantAuditEvent.tenant_id == world["tenant"].id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(events) == 1
            assert events[0].target_resource == f"scheduled_job:{world['job'].id}"
            assert events[0].detail["code"] == "quota_exhausted"

            # The job stays scheduled for future fires.
            refreshed = await db.get(ScheduledJob, world["job"].id)
            assert refreshed.status == JobStatus.active

    async def test_job_without_tenant_keeps_legacy_behaviour(
        self, world, mock_launch
    ):
        """strict-tenant-isolation (B4): the legacy NULL-tenant dispatch
        path is REMOVED.  A job without a tenant binding (and its agent
        type) is HARD-SKIPPED at dispatch — never executed tenant-less,
        and the quota is never consulted."""
        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            job = await db.get(ScheduledJob, world["job"].id)
            job.tenant_id = None
            agent_type = await db.get(AgentType, world["agent_type"].id)
            agent_type.tenant_id = None
            await db.commit()

        engine = SchedulingEngine()
        async with SessionLocal() as db:
            job = await db.get(ScheduledJob, world["job"].id)
            result = await engine._dispatch(job, db)
            await db.commit()

        assert result == {
            "status": "skipped",
            "reason": "missing_tenant",
            "session_id": None,
        }
        mock_launch.assert_not_awaited()
        assert await _bucket(world) == 0  # no quota consultation


class TestSchedulerExecuteJobLoop:
    async def test_execute_job_records_skip_and_stays_scheduled(
        self, world, mock_launch, test_engine
    ):
        """The full ``_execute_job`` loop completes NORMALLY on an
        exhausted quota: the JobExecution records the skip as a success
        result and the scheduled job remains active."""
        await _seed_full_bucket(world, limit=100)

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        engine = SchedulingEngine()

        with patch("app.db.session.AsyncSessionLocal", SessionLocal):
            # NOTE: the UUID object is passed directly (the production
            # APScheduler path hands over a string, which asyncpg accepts
            # for uuid columns; sqlite requires the UUID instance).
            await engine._execute_job(
                job_id=world["job"].id, db_factory=SessionLocal
            )

        SessionLocal2 = world["sf"]
        async with SessionLocal2() as db:
            from app.db.models.scheduling import JobExecution

            executions = (
                (
                    await db.execute(
                        select(JobExecution).where(
                            JobExecution.job_id == world["job"].id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(executions) == 1
            assert executions[0].status.value == "success"
            assert executions[0].result["reason"] == "quota_exhausted"

            refreshed = await db.get(ScheduledJob, world["job"].id)
            assert refreshed.status == JobStatus.active  # still scheduled
