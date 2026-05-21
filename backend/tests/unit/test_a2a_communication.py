"""Unit tests for Communication Hub A2A API (DB-free boundary)."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.communication_hub.api import a2a as a2a_module
from app.communication_hub.data_client import ControlCenterDataError
from app.schemas.agents import A2ARequest
from app.services.comm_hub.broker import BrokerMessage


def _make_http_request(data_client: object) -> object:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(data_client=data_client)))


class _StubBroker:
    def __init__(self, messages: list[BrokerMessage]) -> None:
        self._messages = messages

    async def subscribe(self, session_id: str):
        for message in self._messages:
            yield message


class _IdleBroker:
    async def subscribe(self, session_id: str):
        while True:
            await asyncio.sleep(60)
            yield BrokerMessage(
                session_id=session_id,
                sender_role="agent",
                content="{}",
                metadata={"message_type": "agent_result"},
            )


@pytest.mark.asyncio
async def test_wait_for_receiver_result_returns_completed_agent_result() -> None:
    receiver_session_id = uuid.uuid4()
    broker = _StubBroker(
        [
            BrokerMessage(
                session_id=str(receiver_session_id),
                sender_role="agent",
                content='{"progress": 50}',
                metadata={"message_type": "progress"},
            ),
            BrokerMessage(
                session_id=str(receiver_session_id),
                sender_role="agent",
                content='{"status":"completed","output_data":{"result":"done"}}',
                metadata={"message_type": "agent_result"},
            ),
        ]
    )

    result = await a2a_module._wait_for_receiver_result(
        receiver_session_id=receiver_session_id,
        timeout_seconds=1.0,
        broker=broker,
    )

    assert result == {"status": "completed", "output_data": {"result": "done"}}


@pytest.mark.asyncio
async def test_wait_for_receiver_result_times_out_without_agent_result() -> None:
    result = await a2a_module._wait_for_receiver_result(
        receiver_session_id=uuid.uuid4(),
        timeout_seconds=0.5,
        broker=_IdleBroker(),
    )

    assert result == {
        "status": "timeout",
        "error": "Timed out waiting for receiver response",
    }


@pytest.mark.asyncio
async def test_request_a2a_success_with_wait_for_response() -> None:
    session_id = uuid.uuid4()
    data_client = MagicMock()
    data_client.prepare_a2a_request = AsyncMock(
        return_value={
            "receiver_instance_id": "receiver-live-001",
            "session_link_id": "session-link-001",
            "status": "accepted",
            "receiver_session_id": str(session_id),
        }
    )

    body = A2ARequest(
        target_agent_type_slug="reviewer-agent",
        conversation_metadata={
            "requester_instance_id": "req-1",
            "wait_for_response": True,
            "wait_timeout_seconds": 15,
        },
        request_payload={"prompt": "hello"},
    )

    wait_payload = {"status": "completed", "output_data": {"result": "ok"}}
    with patch.object(
        a2a_module,
        "_wait_for_receiver_result",
        AsyncMock(return_value=wait_payload),
    ):
        response = await a2a_module.request_a2a(body, _make_http_request(data_client))

    assert response.status == "accepted"
    assert response.receiver_instance_id == "receiver-live-001"
    assert response.session_link_id == "session-link-001"
    assert response.response_payload == wait_payload


@pytest.mark.asyncio
async def test_request_a2a_maps_control_center_403() -> None:
    data_client = MagicMock()
    data_client.prepare_a2a_request = AsyncMock(
        side_effect=ControlCenterDataError("CC POST /internal/data/a2a/request returned 403: denied")
    )

    body = A2ARequest(
        target_agent_type_slug="restricted-agent",
        conversation_metadata={"requester_instance_id": "req-2"},
        request_payload={"prompt": "x"},
    )

    with pytest.raises(HTTPException) as exc_info:
        await a2a_module.request_a2a(body, _make_http_request(data_client))

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_disconnect_a2a_maps_control_center_404() -> None:
    data_client = MagicMock()
    data_client.disconnect_a2a_session = AsyncMock(
        side_effect=ControlCenterDataError("CC POST /internal/data/a2a/sessions/abc/disconnect returned 404: missing")
    )

    with pytest.raises(HTTPException) as exc_info:
        await a2a_module.disconnect_a2a("abc", _make_http_request(data_client))

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_disconnect_a2a_success() -> None:
    data_client = MagicMock()
    data_client.disconnect_a2a_session = AsyncMock(
        return_value={"status": "disconnected", "session_link_id": "xyz"}
    )

    response = await a2a_module.disconnect_a2a("xyz", _make_http_request(data_client))

    assert response == {"status": "disconnected", "session_link_id": "xyz"}
