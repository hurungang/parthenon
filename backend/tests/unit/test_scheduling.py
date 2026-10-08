"""
Test SchedulingEngine: job add, pause/resume via ScheduledJob status changes.
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_scheduling_engine_starts_and_shuts_down():
    """SchedulingEngine can start and shutdown without errors."""
    from app.services.scheduling.scheduler import SchedulingEngine

    with patch("app.services.scheduling.scheduler.AsyncIOScheduler") as mock_scheduler_cls:
        mock_scheduler = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler

        engine = SchedulingEngine()
        engine.start()
        assert engine._started is True

        engine.shutdown()
        assert engine._started is False
        mock_scheduler.shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_scheduling_engine_add_job_registers_with_apscheduler():
    """SchedulingEngine.add_job() registers a cron job with APScheduler."""
    from app.services.scheduling.scheduler import SchedulingEngine
    from app.db.models.scheduling import ScheduledJob, JobStatus

    mock_job = MagicMock(spec=ScheduledJob)
    mock_job.id = uuid.uuid4()
    mock_job.name = "daily-report"
    mock_job.cron_expression = "0 9 * * *"
    mock_job.status = JobStatus.active
    mock_job.prompt = "Run the daily report"

    with patch("app.services.scheduling.scheduler.AsyncIOScheduler") as mock_scheduler_cls:
        mock_scheduler = MagicMock()
        mock_scheduler.add_job = MagicMock(return_value=MagicMock(id="apscheduler-job-id"))
        mock_scheduler_cls.return_value = mock_scheduler

        engine = SchedulingEngine()
        engine._started = True
        engine._scheduler = mock_scheduler

        job_id = await engine.add_job(mock_job, AsyncMock())

    assert job_id is not None
    mock_scheduler.add_job.assert_called_once()


# ── Trigger provenance dispatch (agent-runtime-monitor) ────────────────────────


def _make_scheduled_job(
    target_id: uuid.UUID | None = None,
    scheduled_by_user_id: uuid.UUID | None = None,
    payload: dict | None = None,
    tenant_id: uuid.UUID | None = None,
) -> MagicMock:
    from app.db.models.scheduling import JobTargetType

    job = MagicMock()
    job.id = uuid.uuid4()
    job.name = "test-schedule"
    job.target_id = target_id or uuid.uuid4()
    job.target_type = JobTargetType.agent
    job.scheduled_by_user_id = scheduled_by_user_id
    job.payload = payload if payload is not None else {"query": "test"}
    # Tenant-bound job (post-adoption every schedule carries its owning
    # tenant — NULL-tenant dispatch is a hard skip).
    job.tenant_id = tenant_id if tenant_id is not None else uuid.uuid4()
    return job


def _make_dispatch_db() -> AsyncMock:
    """AsyncMock db whose execute() resolves to a result with NO rows.

    Keeps the platform-settings read (quota gate) on the built-in default
    (tenancy off → gate inert) instead of returning AsyncMock coroutines.
    """
    db = AsyncMock()
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    db.execute.return_value = empty_result
    return db


@pytest.mark.asyncio
async def test_dispatch_passes_scheduled_by_user_id_to_launch():
    """`SchedulingEngine._dispatch` forwards ``scheduled_by_user_id`` as the
    ``user_id`` argument to ``GatewayLifecycleHandler.launch`` for
    agent-target schedules.
    """
    from app.services.scheduling.scheduler import SchedulingEngine

    scheduled_by = uuid.uuid4()
    job = _make_scheduled_job(scheduled_by_user_id=scheduled_by)

    db = _make_dispatch_db()

    tenant_id = job.tenant_id
    agent_type = MagicMock()
    agent_type.tenant_id = tenant_id
    tenant = MagicMock()
    tenant.id = tenant_id
    tenant.slug = "test-tenant"
    tenant.name = "Test Tenant"
    tenant.is_system_tenant = False

    async def fake_get(model_cls, record_id):
        from app.db.models.agents import AgentType as AgentTypeModel
        from app.db.models.tenant import Tenant as TenantModel

        if model_cls is AgentTypeModel:
            return agent_type
        if model_cls is TenantModel:
            return tenant
        return None

    db.get = AsyncMock(side_effect=fake_get)

    captured: dict = {}

    async def fake_launch(agent_type_id, input_data, user_id, db, tenant_context=None):
        captured["user_id"] = user_id
        return {"session_id": str(uuid.uuid4())}

    with patch(
        "app.services.gateway.lifecycle_handler.GatewayLifecycleHandler"
    ) as mock_handler_cls:
        mock_handler = MagicMock()
        mock_handler.launch = AsyncMock(side_effect=fake_launch)
        mock_handler_cls.return_value = mock_handler

        result = await SchedulingEngine()._dispatch(job, db)

    assert captured["user_id"] == scheduled_by
    assert "session_id" in result


@pytest.mark.asyncio
async def test_dispatch_null_scheduled_by_user_id_does_not_crash():
    """A legacy schedule with ``scheduled_by_user_id=None`` dispatches cleanly,
    passing ``user_id=None`` to launch without raising.
    """
    from app.services.scheduling.scheduler import SchedulingEngine

    job = _make_scheduled_job(scheduled_by_user_id=None)

    db = _make_dispatch_db()

    tenant_id = job.tenant_id
    agent_type = MagicMock()
    agent_type.tenant_id = tenant_id
    tenant = MagicMock()
    tenant.id = tenant_id
    tenant.slug = "test-tenant"
    tenant.name = "Test Tenant"
    tenant.is_system_tenant = False

    async def fake_get(model_cls, record_id):
        from app.db.models.agents import AgentType as AgentTypeModel
        from app.db.models.tenant import Tenant as TenantModel

        if model_cls is AgentTypeModel:
            return agent_type
        if model_cls is TenantModel:
            return tenant
        return None

    db.get = AsyncMock(side_effect=fake_get)

    captured: dict = {}

    async def fake_launch(agent_type_id, input_data, user_id, db, tenant_context=None):
        captured["user_id"] = user_id
        return {"session_id": str(uuid.uuid4())}

    with patch(
        "app.services.gateway.lifecycle_handler.GatewayLifecycleHandler"
    ) as mock_handler_cls:
        mock_handler = MagicMock()
        mock_handler.launch = AsyncMock(side_effect=fake_launch)
        mock_handler_cls.return_value = mock_handler

        result = await SchedulingEngine()._dispatch(job, db)

    assert captured["user_id"] is None
    assert "session_id" in result


@pytest.mark.asyncio
async def test_dispatch_null_tenant_is_hard_skip():
    """A NULL-tenant scheduled job is skipped (logged, never dispatched) —
    there is no unscoped dispatch path (strict tenant isolation)."""
    from app.services.scheduling.scheduler import SchedulingEngine

    job = _make_scheduled_job()
    job.tenant_id = None  # explicit NULL-tenant job (pre-adoption legacy row)

    db = _make_dispatch_db()
    agent_type = MagicMock()
    agent_type.tenant_id = uuid.uuid4()  # no fallback to the agent type's tenant
    db.get = AsyncMock(return_value=agent_type)

    with patch(
        "app.services.gateway.lifecycle_handler.GatewayLifecycleHandler"
    ) as mock_handler_cls:
        mock_handler = MagicMock()
        mock_handler.launch = AsyncMock()
        mock_handler_cls.return_value = mock_handler

        result = await SchedulingEngine()._dispatch(job, db)

    assert result["status"] == "skipped"
    assert result["reason"] == "missing_tenant"
    mock_handler.launch.assert_not_called()
