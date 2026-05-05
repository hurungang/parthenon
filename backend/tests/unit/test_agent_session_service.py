"""Unit tests for AgentSessionService state machine: enqueue, status transitions, list, result."""
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.services.agents.session_service import AgentSessionService
from app.db.models.agents import AgentJob, AgentJobStatus


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_job(
    job_id: uuid.UUID | None = None,
    status: AgentJobStatus = AgentJobStatus.queued,
    agent_type_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> AgentJob:
    job = MagicMock(spec=AgentJob)
    job.id = job_id or uuid.uuid4()
    job.status = status
    job.agent_type_id = agent_type_id or uuid.uuid4()
    job.triggered_by_user_id = user_id
    job.input_data = {}
    job.started_at = None
    job.completed_at = None
    job.output_data = None
    job.error_message = None
    job.created_at = datetime.now(timezone.utc)
    return job


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


# ── Enqueue ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enqueue_creates_job_with_queued_status():
    """enqueue() creates an AgentJob with status=queued and returns it immediately."""
    from unittest.mock import patch

    service = AgentSessionService()
    agent_type_id = uuid.uuid4()
    user_id = uuid.uuid4()
    job = _make_job(status=AgentJobStatus.queued, agent_type_id=agent_type_id, user_id=user_id)
    db = _mock_db()

    with patch("app.services.agents.session_service.AgentJob", return_value=job):
        result = await service.enqueue(
            agent_type_id=agent_type_id,
            input_data={"key": "value"},
            user_id=user_id,
            db=db,
        )

    assert result.status == AgentJobStatus.queued
    assert result.agent_type_id == agent_type_id
    db.flush.assert_called_once()
    db.refresh.assert_called_once()


@pytest.mark.asyncio
async def test_enqueue_with_no_user():
    """enqueue() works when user_id is None (anonymous session)."""
    from unittest.mock import patch

    service = AgentSessionService()
    job = _make_job(user_id=None)
    db = _mock_db()

    with patch("app.services.agents.session_service.AgentJob", return_value=job):
        result = await service.enqueue(
            agent_type_id=uuid.uuid4(),
            input_data=None,
            user_id=None,
            db=db,
        )

    assert result.triggered_by_user_id is None


# ── State transitions ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_running_transitions_status():
    """mark_running() transitions queued → running and sets started_at."""
    service = AgentSessionService()
    session_id = uuid.uuid4()
    job = _make_job(job_id=session_id, status=AgentJobStatus.queued)

    db = _mock_db()
    db.get = AsyncMock(return_value=job)

    result = await service.mark_running(session_id, db)

    assert result.status == AgentJobStatus.running
    assert result.started_at is not None


@pytest.mark.asyncio
async def test_mark_completed_transitions_status_and_stores_output():
    """mark_completed() transitions running → completed and stores output_data."""
    service = AgentSessionService()
    session_id = uuid.uuid4()
    job = _make_job(job_id=session_id, status=AgentJobStatus.running)

    db = _mock_db()
    db.get = AsyncMock(return_value=job)

    output = {"result": "success", "count": 42}
    result = await service.mark_completed(session_id, output, db)

    assert result.status == AgentJobStatus.completed
    assert result.output_data == output
    assert result.completed_at is not None


@pytest.mark.asyncio
async def test_mark_failed_transitions_status_and_stores_error():
    """mark_failed() transitions running → failed and persists error_message."""
    service = AgentSessionService()
    session_id = uuid.uuid4()
    job = _make_job(job_id=session_id, status=AgentJobStatus.running)

    db = _mock_db()
    db.get = AsyncMock(return_value=job)

    result = await service.mark_failed(session_id, "Something went wrong", db)

    assert result.status == AgentJobStatus.failed
    assert result.error_message == "Something went wrong"
    assert result.completed_at is not None


@pytest.mark.asyncio
async def test_state_machine_queued_to_running_to_completed():
    """Full happy-path: queued → running → completed."""
    service = AgentSessionService()
    session_id = uuid.uuid4()

    job = _make_job(job_id=session_id, status=AgentJobStatus.queued)
    db = _mock_db()
    db.get = AsyncMock(return_value=job)

    running = await service.mark_running(session_id, db)
    assert running.status == AgentJobStatus.running

    completed = await service.mark_completed(session_id, {"res": "ok"}, db)
    assert completed.status == AgentJobStatus.completed


@pytest.mark.asyncio
async def test_state_machine_queued_to_running_to_failed():
    """Error path: queued → running → failed."""
    service = AgentSessionService()
    session_id = uuid.uuid4()

    job = _make_job(job_id=session_id, status=AgentJobStatus.queued)
    db = _mock_db()
    db.get = AsyncMock(return_value=job)

    await service.mark_running(session_id, db)
    failed = await service.mark_failed(session_id, "Executor crashed", db)

    assert failed.status == AgentJobStatus.failed
    assert "Executor crashed" in failed.error_message


# ── List sessions ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_sessions_returns_only_own_sessions():
    """list_sessions filters by user_id when provided."""
    service = AgentSessionService()
    user_id = uuid.uuid4()
    own_job = _make_job(user_id=user_id)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [own_job]

    db = _mock_db()
    db.execute = AsyncMock(return_value=mock_result)

    result = await service.list_sessions(user_id, db)

    assert len(result) == 1
    assert result[0].triggered_by_user_id == user_id


@pytest.mark.asyncio
async def test_list_sessions_returns_all_when_no_user():
    """list_sessions returns all sessions when user_id is None."""
    service = AgentSessionService()
    job_a = _make_job(user_id=uuid.uuid4())
    job_b = _make_job(user_id=uuid.uuid4())

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [job_a, job_b]

    db = _mock_db()
    db.execute = AsyncMock(return_value=mock_result)

    result = await service.list_sessions(None, db)
    assert len(result) == 2


# ── Get session ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_returns_none_when_missing():
    """get_session returns None when no AgentJob with that ID exists."""
    service = AgentSessionService()
    db = _mock_db()
    db.get = AsyncMock(return_value=None)

    result = await service.get_session(uuid.uuid4(), db)
    assert result is None


@pytest.mark.asyncio
async def test_get_session_returns_job():
    """get_session returns the AgentJob when it exists."""
    service = AgentSessionService()
    session_id = uuid.uuid4()
    job = _make_job(job_id=session_id)

    db = _mock_db()
    db.get = AsyncMock(return_value=job)

    result = await service.get_session(session_id, db)
    assert result.id == session_id
