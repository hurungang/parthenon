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
        result = await chat._delegate_conversation_turn_to_agent_runtime(
            app=app,
            conv_session_id=conv_session_id,
            agent_type_id=agent_type_id,
            messages=[{"role": "user", "content": "hello"}],
        )

    assert result == "ok"
    assert client_cls.call_args.kwargs["timeout"] == 120.0


@pytest.mark.asyncio
async def test_system_send_notification_missing_required_args_returns_error() -> None:
    body = tool_routing.ToolCallRequest(
        tool_name="system____send_notification",
        tool_args={},
        session_id=str(uuid.uuid4()),
        agent_type_id=str(uuid.uuid4()),
    )

    with patch("app.communication_hub.api.internal.tool_routing.httpx.AsyncClient") as client_cls:
        result = await tool_routing._route_to_system_tool(body)

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

    with patch(
        "app.communication_hub.api.internal.tool_routing.httpx.AsyncClient",
        return_value=mock_http_client,
    ):
        result = await tool_routing._route_to_system_tool(body)

    assert result.error is not None
    assert "HTTP 400" in result.error
    assert "group_slug and body are required" in result.error
