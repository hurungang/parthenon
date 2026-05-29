"""Reproduction test for FIX-20260521-192300 runtime-boundary violation in chat path."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.api.ws import chat


@pytest.mark.asyncio
async def test_call_llm_chat_path_must_not_instantiate_local_runtime_executor() -> None:
    """Communication Hub chat path must not execute agent runtime logic in-process."""
    conv_session_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "previous reply"},
    ]

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"response": "agent reply"}

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_http_client.__aenter__.return_value = mock_http_client

    app = SimpleNamespace(state=SimpleNamespace(certificate_manager=None))

    with patch("app.api.ws.chat.get_settings",
        return_value=SimpleNamespace(agent_runtime_url="http://localhost:8001"),
    ), patch(
        "app.api.ws.chat.httpx.AsyncClient",
        return_value=mock_http_client,
    ), patch("app.services.agents.runtime_executor.AgentRuntimeExecutor") as runtime_executor_cls:
        response, guardrail_usage, status_events = await chat._call_llm(
            conv_session_id=conv_session_id,
            agent_type_id=agent_type_id,
            messages=messages,
            app=app,
        )

    assert response == "agent reply"
    assert guardrail_usage is None
    assert status_events == []
    runtime_executor_cls.assert_not_called()
    mock_http_client.post.assert_awaited_once()
