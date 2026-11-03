"""Structured chat error surfacing when an agent type has no model configured.

Mirrors ``test_fix_20260521_192300_ws_chat_runtime_boundary.py``: Agent Runtime
rejects a conversation turn with 400 "Agent model is not configured" (checked
BEFORE any model call); the Communication Hub WebSocket path must surface the
structured ``assistant_model_not_configured`` payload instead of a generic
error string, and configured agents must keep working unchanged.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import httpx
import pytest

from app.api.ws import chat


def _make_http_status_error(status_code: int, detail: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://localhost:8001/internal/conversation/turn")
    response = httpx.Response(status_code, json={"detail": detail}, request=request)
    return httpx.HTTPStatusError(
        f"{status_code} {response.reason_phrase}", request=request, response=response
    )


@pytest.mark.asyncio
async def test_call_llm_raises_structured_error_when_model_not_configured() -> None:
    """A turn against an agent type with model_id=None surfaces the typed code."""
    conv_session_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()  # agent type has model_id=None on AR side
    messages = [{"role": "user", "content": "hello"}]

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(
        side_effect=_make_http_status_error(400, "Agent model is not configured")
    )
    mock_http_client.__aenter__.return_value = mock_http_client

    app = SimpleNamespace(state=SimpleNamespace(certificate_manager=None))

    with patch(
        "app.api.ws.chat.get_settings",
        return_value=SimpleNamespace(agent_runtime_url="http://localhost:8001"),
    ), patch(
        "app.api.ws.chat.httpx.AsyncClient",
        return_value=mock_http_client,
    ):
        with pytest.raises(chat.ConversationTurnError) as exc_info:
            await chat._call_llm(
                conv_session_id=conv_session_id,
                agent_type_id=agent_type_id,
                messages=messages,
                app=app,
            )

    assert exc_info.value.code == chat.ERROR_CODE_ASSISTANT_MODEL_NOT_CONFIGURED
    assert "No model is configured" in exc_info.value.message


@pytest.mark.asyncio
async def test_call_llm_generic_400_does_not_use_assistant_code() -> None:
    """Unrelated 400 rejections stay generic (no structured code, friendly text)."""
    conv_session_id = uuid.uuid4()
    messages = [{"role": "user", "content": "hello"}]

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(
        side_effect=_make_http_status_error(400, "Agent type is not active")
    )
    mock_http_client.__aenter__.return_value = mock_http_client

    app = SimpleNamespace(state=SimpleNamespace(certificate_manager=None))

    with patch(
        "app.api.ws.chat.get_settings",
        return_value=SimpleNamespace(agent_runtime_url="http://localhost:8001"),
    ), patch(
        "app.api.ws.chat.httpx.AsyncClient",
        return_value=mock_http_client,
    ):
        reply, _guardrail, status_events = await chat._call_llm(
            conv_session_id=conv_session_id,
            agent_type_id=uuid.uuid4(),
            messages=messages,
            app=app,
        )

    assert "error occurred" in reply.lower()
    assert status_events and status_events[0]["status"] == "timeout_or_failed"


@pytest.mark.asyncio
async def test_call_llm_configured_agent_still_returns_reply() -> None:
    """Correctly-configured agents are unaffected by the guard."""
    conv_session_id = uuid.uuid4()
    messages = [{"role": "user", "content": "hello"}]

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"response": "agent reply"}

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_http_client.__aenter__.return_value = mock_http_client

    app = SimpleNamespace(state=SimpleNamespace(certificate_manager=None))

    with patch(
        "app.api.ws.chat.get_settings",
        return_value=SimpleNamespace(agent_runtime_url="http://localhost:8001"),
    ), patch(
        "app.api.ws.chat.httpx.AsyncClient",
        return_value=mock_http_client,
    ):
        reply, guardrail_usage, status_events = await chat._call_llm(
            conv_session_id=conv_session_id,
            agent_type_id=uuid.uuid4(),
            messages=messages,
            app=app,
        )

    assert reply == "agent reply"
    assert guardrail_usage is None
    assert status_events == []


@pytest.mark.asyncio
async def test_streaming_path_maps_model_not_configured_to_structured_error() -> None:
    """The NDJSON streaming path maps the same 400 rejection onto the typed code."""
    conv_session_id = uuid.uuid4()
    messages = [{"role": "user", "content": "hello"}]

    def _raise_for_status() -> None:
        raise _make_http_status_error(400, "Agent model is not configured")

    mock_stream_response = MagicMock()
    mock_stream_response.raise_for_status = _raise_for_status

    mock_stream_cm = AsyncMock()
    mock_stream_cm.__aenter__.return_value = mock_stream_response

    mock_http_client = AsyncMock()
    mock_http_client.stream = MagicMock(return_value=mock_stream_cm)
    mock_http_client.__aenter__.return_value = mock_http_client

    app = SimpleNamespace(state=SimpleNamespace(certificate_manager=None))

    async def on_status_event(event: dict[str, str]) -> None:
        return None

    with patch(
        "app.api.ws.chat.get_settings",
        return_value=SimpleNamespace(agent_runtime_url="http://localhost:8001"),
    ), patch(
        "app.api.ws.chat.httpx.AsyncClient",
        return_value=mock_http_client,
    ):
        with pytest.raises(chat.ConversationTurnError) as exc_info:
            await chat._call_llm(
                conv_session_id=conv_session_id,
                agent_type_id=uuid.uuid4(),
                messages=messages,
                app=app,
                on_status_event=on_status_event,
            )

    assert exc_info.value.code == chat.ERROR_CODE_ASSISTANT_MODEL_NOT_CONFIGURED
