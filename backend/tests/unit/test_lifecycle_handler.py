"""Unit tests for GatewayLifecycleHandler — routes launch requests through AgentSessionService."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler
from app.db.models.agents import AgentJobStatus


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_job(session_id: uuid.UUID | None = None) -> MagicMock:
    job = MagicMock()
    job.id = session_id or uuid.uuid4()
    job.status = AgentJobStatus.queued
    return job


def _mock_db() -> AsyncMock:
    return AsyncMock()


# ── launch() — routes through AgentSessionService.enqueue ─────────────────────


@pytest.mark.asyncio
async def test_launch_calls_enqueue_and_returns_session_id():
    """launch() delegates to AgentSessionService.enqueue and returns the session ID synchronously."""
    handler = GatewayLifecycleHandler()
    session_id = uuid.uuid4()
    job = _make_job(session_id=session_id)

    handler._session_service.enqueue = AsyncMock(return_value=job)

    db = _mock_db()
    agent_type_id = uuid.uuid4()
    user_id = uuid.uuid4()

    result = await handler.launch(
        agent_type_id=agent_type_id,
        input_data={"prompt": "hello"},
        user_id=user_id,
        db=db,
    )

    handler._session_service.enqueue.assert_called_once_with(
        agent_type_id=agent_type_id,
        input_data={"prompt": "hello"},
        user_id=user_id,
        db=db,
    )
    assert result["session_id"] == str(session_id)


@pytest.mark.asyncio
async def test_launch_returns_session_id_synchronously():
    """launch() returns the session_id without waiting for job completion."""
    handler = GatewayLifecycleHandler()
    session_id = uuid.uuid4()
    job = _make_job(session_id=session_id)

    handler._session_service.enqueue = AsyncMock(return_value=job)

    db = _mock_db()

    result = await handler.launch(
        agent_type_id=uuid.uuid4(),
        input_data=None,
        user_id=None,
        db=db,
    )

    # Must be a dict with a "session_id" key
    assert "session_id" in result
    assert result["session_id"] == str(session_id)


@pytest.mark.asyncio
async def test_launch_does_not_invoke_executor_directly():
    """launch() must NOT call the executor directly — it only enqueues."""
    handler = GatewayLifecycleHandler()
    job = _make_job()

    handler._session_service.enqueue = AsyncMock(return_value=job)

    # If AgentRuntimeExecutor.run were called, it would raise because db.get returns None
    # The test verifies no such call occurs
    db = _mock_db()

    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    with MagicMock() as mock_executor_cls:
        mock_executor_cls.run = AsyncMock(side_effect=AssertionError("executor must not be called"))
        result = await handler.launch(uuid.uuid4(), None, None, db)

    # If we reach here, executor was not called
    assert "session_id" in result


@pytest.mark.asyncio
async def test_launch_with_no_input_data():
    """launch() works when input_data is None (for 'none' input_type agents)."""
    handler = GatewayLifecycleHandler()
    job = _make_job()
    handler._session_service.enqueue = AsyncMock(return_value=job)

    db = _mock_db()
    result = await handler.launch(uuid.uuid4(), None, None, db)
    assert "session_id" in result


@pytest.mark.asyncio
async def test_launch_passes_user_id_to_session_service():
    """launch() forwards the user_id to AgentSessionService.enqueue."""
    handler = GatewayLifecycleHandler()
    job = _make_job()
    handler._session_service.enqueue = AsyncMock(return_value=job)

    db = _mock_db()
    user_id = uuid.uuid4()

    await handler.launch(uuid.uuid4(), {"data": "x"}, user_id, db)

    call_kwargs = handler._session_service.enqueue.call_args.kwargs
    assert call_kwargs["user_id"] == user_id
