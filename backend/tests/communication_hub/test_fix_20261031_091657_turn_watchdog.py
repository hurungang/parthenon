"""FIX-20261031-091657 (Defect A) — Communication Hub turn watchdog + liveness.

The WHOLE turn must be bounded by ``agent_question_timeout_seconds`` even on
the streaming path (where the AR HTTP timeout is deliberately disabled), so a
hung Agent Runtime cannot leave a turn awaiting forever. On watchdog fire the
turn pipeline must emit ``timeout_or_failed``, deliver a clear error message
and persist the error turn exactly once. Additionally the WebSocket loop must
log disconnect code+reason and emit a ``thinking_heartbeat`` keepalive.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import WebSocketDisconnect

from app.api.ws import chat


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.query_params: dict[str, str] = {}

    async def accept(self) -> None:  # noqa: D105
        return None

    async def send_json(self, payload) -> None:  # noqa: ANN001
        self.sent.append(payload)


def _make_app() -> SimpleNamespace:
    data_client = SimpleNamespace()
    data_client.prepare_conversation_turn = AsyncMock(
        return_value={"agent_type_id": str(uuid.uuid4()), "messages": [{"role": "user", "content": "hi"}]}
    )
    data_client.append_conversation_turn = AsyncMock(return_value={"title": None})
    return SimpleNamespace(state=SimpleNamespace(data_client=data_client, certificate_manager=None))


@pytest.mark.asyncio
async def test_hung_turn_completes_within_watchdog_bound() -> None:
    conv_session_id = uuid.uuid4()
    app = _make_app()
    ws = _FakeWebSocket()
    chat.ActiveSessionTracker.register(str(conv_session_id), ws)
    settings = SimpleNamespace(agent_runtime_url="http://localhost:8001", agent_question_timeout_seconds=1)

    async def hanging_process_message(**kwargs):  # noqa: ANN001
        await asyncio.sleep(120)

    started = time.monotonic()
    with patch.object(chat, "get_settings", return_value=settings), \
         patch.object(chat, "_process_message", hanging_process_message):
        await chat.run_conversation_turn(
            session_id=str(conv_session_id),
            conv_session_id=conv_session_id,
            user_message="hi",
            is_first_message=True,
            app=app,
            websocket=ws,
            message_count=1,
        )
    elapsed = time.monotonic() - started

    assert elapsed < 30  # bounded, not hung forever

    statuses = [m.get("status") for m in ws.sent if m.get("type") == "chat_status"]
    assert "timeout_or_failed" in statuses

    error_messages = [m for m in ws.sent if m.get("sender_role") == "agent"]
    assert error_messages and "timed out" in error_messages[-1]["content"].lower()

    # Error turn persisted exactly once for history
    app.state.data_client.append_conversation_turn.assert_awaited_once()
    kwargs = app.state.data_client.append_conversation_turn.await_args.kwargs
    assert "timed out" in str(kwargs.get("agent_reply", "")).lower()
    chat.ActiveSessionTracker.unregister(str(conv_session_id), ws)


@pytest.mark.asyncio
async def test_successful_turn_does_not_persist_duplicate_error() -> None:
    conv_session_id = uuid.uuid4()
    app = _make_app()
    ws = _FakeWebSocket()
    chat.ActiveSessionTracker.register(str(conv_session_id), ws)
    settings = SimpleNamespace(agent_runtime_url="http://localhost:8001", agent_question_timeout_seconds=30)

    async def fast_process_message(**kwargs):  # noqa: ANN001
        return ("the answer", None, None, [])

    with patch.object(chat, "get_settings", return_value=settings), \
         patch.object(chat, "_process_message", fast_process_message):
        await chat.run_conversation_turn(
            session_id=str(conv_session_id),
            conv_session_id=conv_session_id,
            user_message="hi",
            is_first_message=True,
            app=app,
            websocket=ws,
            message_count=1,
        )

    # Only the real reply is persisted by _process_message (mocked away here);
    # the watchdog must NOT persist an extra error turn.
    app.state.data_client.append_conversation_turn.assert_not_awaited()
    replies = [m for m in ws.sent if m.get("sender_role") == "agent"]
    assert replies and replies[-1]["content"] == "the answer"
    chat.ActiveSessionTracker.unregister(str(conv_session_id), ws)


@pytest.mark.asyncio
async def test_turn_emits_thinking_heartbeat_keepalive() -> None:
    conv_session_id = uuid.uuid4()
    app = _make_app()
    ws = _FakeWebSocket()
    chat.ActiveSessionTracker.register(str(conv_session_id), ws)
    settings = SimpleNamespace(agent_runtime_url="http://localhost:8001", agent_question_timeout_seconds=30)

    async def slowish_process_message(**kwargs):  # noqa: ANN001
        await asyncio.sleep(0.3)
        return ("late answer", None, None, [])

    with patch.object(chat, "get_settings", return_value=settings), \
         patch.object(chat, "_process_message", slowish_process_message), \
         patch.object(chat, "CONVERSATION_HEARTBEAT_INTERVAL_SECONDS", 0.05):
        await chat.run_conversation_turn(
            session_id=str(conv_session_id),
            conv_session_id=conv_session_id,
            user_message="hi",
            is_first_message=True,
            app=app,
            websocket=ws,
            message_count=1,
        )

    heartbeats = [m for m in ws.sent if m.get("status") == "thinking_heartbeat"]
    assert heartbeats, "expected at least one thinking_heartbeat keepalive during a long turn"
    chat.ActiveSessionTracker.unregister(str(conv_session_id), ws)


@pytest.mark.asyncio
async def test_websocket_disconnect_logs_code_and_reason(caplog) -> None:
    session_id = str(uuid.uuid4())

    class _DisconnectingWebSocket(_FakeWebSocket):
        async def receive_text(self) -> str:  # noqa: D105
            raise WebSocketDisconnect(code=3001, reason="proxy-idle-timeout")

    ws = _DisconnectingWebSocket()

    with patch.object(chat.WebSocketServer, "authenticate", AsyncMock(return_value={"sub": "user"})), \
         patch.object(chat, "_bind_connection_tenant_context", AsyncMock(return_value=None)):
        with caplog.at_level(logging.INFO, logger="app.api.ws.chat"):
            await chat.websocket_chat(ws, session_id)

    close_logs = [r for r in caplog.records if "proxy-idle-timeout" in r.getMessage()]
    assert close_logs, "disconnect reason must be logged"
    assert any("3001" in r.getMessage() for r in close_logs), "disconnect code must be logged"
