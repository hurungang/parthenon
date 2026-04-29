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
