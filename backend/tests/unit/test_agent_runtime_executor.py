"""Unit tests for AgentRuntimeExecutor — instantiation, required methods, and permission enforcement."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Instantiation ──────────────────────────────────────────────────────────────


def test_executor_can_be_instantiated():
    """AgentRuntimeExecutor can be created without errors."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    assert executor is not None


def test_executor_has_required_methods():
    """AgentRuntimeExecutor exposes the 'run' method required by SessionDispatcher."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    assert callable(getattr(executor, "run", None)), "run() method must exist"


def test_executor_has_permission_manager():
    """AgentRuntimeExecutor holds an AgentPermissionManager instance."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.permission_manager import AgentPermissionManager

    executor = AgentRuntimeExecutor()
    assert isinstance(executor._permission_manager, AgentPermissionManager)


def test_executor_has_session_service():
    """AgentRuntimeExecutor holds an AgentSessionService instance."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.session_service import AgentSessionService

    executor = AgentRuntimeExecutor()
    assert isinstance(executor._session_service, AgentSessionService)


# ── run() — not running status ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_skips_when_job_not_found():
    """run() logs and returns early when the AgentJob is not in the DB."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    # Should not raise
    await executor.run(uuid.uuid4(), db)


@pytest.mark.asyncio
async def test_run_skips_when_status_not_running():
    """run() returns early when the job is not in 'running' state."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.db.models.agents import AgentJobStatus

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    job = MagicMock()
    job.status = AgentJobStatus.queued  # not running

    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    await executor.run(session_id, db)
    # _execute_job should not be called
    executor._execute_job = AsyncMock()
    executor._execute_job.assert_not_called()


# ── Permission boundary enforcement ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_marks_failed_on_permission_denied():
    """When _execute_job raises PermissionDeniedError, session is marked failed."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.permission_manager import PermissionDeniedError
    from app.db.models.agents import AgentJobStatus

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    role_id = uuid.uuid4()

    job = MagicMock()
    job.status = AgentJobStatus.running
    job.id = session_id

    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    perm_error = PermissionDeniedError("evil:drop_db", role_id)
    executor._execute_job = AsyncMock(side_effect=perm_error)
    executor._session_service.mark_failed = AsyncMock(return_value=job)
    executor._persist_result = AsyncMock()

    await executor.run(session_id, db)

    executor._session_service.mark_failed.assert_called_once()
    call_args = executor._session_service.mark_failed.call_args
    assert "Permission denied" in call_args[0][1]


@pytest.mark.asyncio
async def test_run_marks_failed_on_generic_exception():
    """When _execute_job raises an unexpected exception, session is marked failed."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.db.models.agents import AgentJobStatus

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    job = MagicMock()
    job.status = AgentJobStatus.running
    job.id = session_id

    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    executor._execute_job = AsyncMock(side_effect=RuntimeError("Unexpected crash"))
    executor._session_service.mark_failed = AsyncMock(return_value=job)
    executor._persist_result = AsyncMock()

    await executor.run(session_id, db)

    executor._session_service.mark_failed.assert_called_once()
    call_args = executor._session_service.mark_failed.call_args
    assert "Unexpected crash" in call_args[0][1]


@pytest.mark.asyncio
async def test_run_marks_completed_on_success():
    """When _execute_job returns output, session is marked completed with that output."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.db.models.agents import AgentJobStatus

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    job = MagicMock()
    job.status = AgentJobStatus.running
    job.id = session_id

    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    output = {"answer": "42"}
    executor._execute_job = AsyncMock(return_value=output)
    executor._persist_result = AsyncMock()
    executor._session_service.mark_completed = AsyncMock(return_value=job)

    await executor.run(session_id, db)

    executor._session_service.mark_completed.assert_called_once_with(session_id, output, db)
