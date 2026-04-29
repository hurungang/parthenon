"""
Test GatewayLifecycleHandler: init, close, invalid handle, question/answer cycle.
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_gateway_init_returns_session_handle():
    """GatewayLifecycleHandler.init() returns a dict with a session_handle."""
    from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler
    from app.db.models.agents import AgentInstanceStatus

    agent_type_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    session_handle = str(uuid.uuid4())

    mock_instance = MagicMock()
    mock_instance.id = instance_id
    mock_instance.session_handle = session_handle
    mock_instance.status = AgentInstanceStatus.active

    mock_manager = AsyncMock()
    mock_manager.spawn = AsyncMock(return_value=mock_instance)
    mock_manager.activate = AsyncMock(return_value=mock_instance)

    handler = GatewayLifecycleHandler()
    handler._instance_manager = mock_manager

    mock_db = AsyncMock()
    result = await handler.init(agent_type_id, "user@example.com", mock_db)

    assert "session_handle" in result
    assert result["session_handle"] == session_handle


@pytest.mark.asyncio
async def test_gateway_close_marks_instance_closed():
    """GatewayLifecycleHandler.close() delegates to instance manager close."""
    from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler, _pending_questions, _pending_answers
    from app.db.models.agents import AgentInstanceStatus
    import asyncio

    instance_id = uuid.uuid4()
    session_handle = str(uuid.uuid4())

    mock_instance = MagicMock()
    mock_instance.id = instance_id
    mock_instance.session_handle = session_handle
    mock_instance.status = AgentInstanceStatus.active

    mock_manager = AsyncMock()
    mock_manager.spawn = AsyncMock(return_value=mock_instance)
    mock_manager.activate = AsyncMock(return_value=mock_instance)
    mock_manager.close = AsyncMock(return_value=MagicMock(status=AgentInstanceStatus.closed))

    handler = GatewayLifecycleHandler()
    handler._instance_manager = mock_manager

    # Manually set up the pending queues as init would
    _pending_questions[session_handle] = asyncio.Queue()
    _pending_answers[session_handle] = asyncio.Queue()

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_instance))
    )

    result = await handler.close(session_handle, mock_db)
    assert result["closed"] is True


@pytest.mark.asyncio
async def test_gateway_invalid_session_handle_raises():
    """GatewayLifecycleHandler.close() raises ValueError for an unknown handle."""
    from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler

    handler = GatewayLifecycleHandler()
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    with pytest.raises(ValueError, match="not found"):
        await handler.close("non-existent-handle", mock_db)
