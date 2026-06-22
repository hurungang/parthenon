from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import httpx
import pytest

from app.api.ws import chat
from app.communication_hub.api.internal import tool_routing


@pytest.mark.asyncio
async def test_delegate_conversation_turn_uses_agent_question_timeout() -> None:
    conv_session_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    app = SimpleNamespace(state=SimpleNamespace(certificate_manager=None))

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"response": "ok"}

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_http_client.__aenter__.return_value = mock_http_client

    with patch(
        "app.api.ws.chat.get_settings",
        return_value=SimpleNamespace(
            agent_runtime_url="http://localhost:8001",
            agent_question_timeout_seconds=120,
        ),
    ), patch("app.api.ws.chat.httpx.AsyncClient", return_value=mock_http_client) as client_cls:
        result, guardrail_usage, status_events = await chat._delegate_conversation_turn_to_agent_runtime(
            app=app,
            conv_session_id=conv_session_id,
            agent_type_id=agent_type_id,
            messages=[{"role": "user", "content": "hello"}],
        )

    assert result == "ok"
    assert guardrail_usage is None
    assert status_events == []
    assert client_cls.call_args.kwargs["timeout"] == 120.0


@pytest.mark.asyncio
async def test_delegate_conversation_turn_preserves_tool_name_in_status_events() -> None:
    conv_session_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    app = SimpleNamespace(state=SimpleNamespace(certificate_manager=None))

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "response": "ok",
        "status_events": [
            {
                "status": "using_tool",
                "tool_name": "send_notification",
            }
        ],
    }

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_http_client.__aenter__.return_value = mock_http_client

    with patch(
        "app.api.ws.chat.get_settings",
        return_value=SimpleNamespace(
            agent_runtime_url="http://localhost:8001",
            agent_question_timeout_seconds=120,
        ),
    ), patch("app.api.ws.chat.httpx.AsyncClient", return_value=mock_http_client):
        result, guardrail_usage, status_events = await chat._delegate_conversation_turn_to_agent_runtime(
            app=app,
            conv_session_id=conv_session_id,
            agent_type_id=agent_type_id,
            messages=[{"role": "user", "content": "hello"}],
        )

    assert result == "ok"
    assert guardrail_usage is None
    assert len(status_events) == 1
    assert status_events[0]["status"] == "using_tool"
    assert status_events[0]["tool_name"] == "send_notification"


@pytest.mark.asyncio
async def test_delegate_conversation_turn_streams_status_events_to_callback() -> None:
    conv_session_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    app = SimpleNamespace(state=SimpleNamespace(certificate_manager=None))

    streamed_lines = [
        '{"type":"status_event","event":{"status":"delegating","agent_type":"research-agent"}}',
        '{"type":"status_event","event":{"status":"waiting","agent_type":"research-agent"}}',
        '{"type":"final","response":"ok","guardrail_usage":null,"status_events":[]}',
    ]

    async def iter_lines():
        for line in streamed_lines:
            yield line

    mock_stream_response = MagicMock()
    mock_stream_response.raise_for_status.return_value = None
    mock_stream_response.aiter_lines = MagicMock(return_value=iter_lines())

    mock_stream_cm = AsyncMock()
    mock_stream_cm.__aenter__.return_value = mock_stream_response
    mock_stream_cm.__aexit__.return_value = None

    mock_http_client = AsyncMock()
    mock_http_client.stream = MagicMock(return_value=mock_stream_cm)
    mock_http_client.__aenter__.return_value = mock_http_client

    emitted: list[dict[str, str]] = []

    async def on_status_event(event: dict[str, str]) -> None:
        emitted.append(event)

    with patch(
        "app.api.ws.chat.get_settings",
        return_value=SimpleNamespace(
            agent_runtime_url="http://localhost:8001",
            agent_question_timeout_seconds=120,
        ),
    ), patch("app.api.ws.chat.httpx.AsyncClient", return_value=mock_http_client):
        result, guardrail_usage, status_events = await chat._delegate_conversation_turn_to_agent_runtime(
            app=app,
            conv_session_id=conv_session_id,
            agent_type_id=agent_type_id,
            messages=[{"role": "user", "content": "hello"}],
            on_status_event=on_status_event,
        )

    assert result == "ok"
    assert guardrail_usage is None
    assert len(status_events) == 2
    assert status_events[0]["status"] == "delegating"
    assert status_events[0]["agent_type"] == "research-agent"
    assert status_events[1]["status"] == "waiting"
    assert status_events[1]["agent_type"] == "research-agent"
    assert len(emitted) == 2
    assert emitted[0] == status_events[0]
    assert emitted[1] == status_events[1]


@pytest.mark.asyncio
async def test_system_send_notification_missing_required_args_returns_error() -> None:
    body = tool_routing.ToolCallRequest(
        tool_name="system____send_notification",
        tool_args={},
        session_id=str(uuid.uuid4()),
        agent_type_id=str(uuid.uuid4()),
    )

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(certificate_manager=None)))

    with patch("app.communication_hub.api.internal.tool_routing.httpx.AsyncClient") as client_cls:
        result = await tool_routing._route_to_system_tool(body, request)

    assert result.error == "Invalid send_notification args: group_slug and body are required"
    client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_system_tool_control_center_400_is_not_masked_as_502() -> None:
    body = tool_routing.ToolCallRequest(
        tool_name="system____send_notification",
        tool_args={"group_slug": "ops", "body": "hello"},
        session_id=str(uuid.uuid4()),
        agent_type_id=str(uuid.uuid4()),
    )

    cc_response = MagicMock()
    cc_response.status_code = 400
    cc_response.text = '{"detail":"group_slug and body are required parameters"}'

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "bad request",
            request=MagicMock(),
            response=cc_response,
        )
    )
    mock_http_client.__aenter__.return_value = mock_http_client

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(certificate_manager=None)))

    with patch(
        "app.communication_hub.api.internal.tool_routing.httpx.AsyncClient",
        return_value=mock_http_client,
    ), patch(
        "app.communication_hub.api.internal.tool_routing._build_control_center_auth",
        return_value=({}, {}),
    ):
        result = await tool_routing._route_to_system_tool(body, request)

    assert result.error is not None
    assert "HTTP 400" in result.error
    assert "group_slug and body are required" in result.error
