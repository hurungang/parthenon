"""FIX-20261031-071721 (defect 1 follow-up) — reply routing after WS reconnect.

Resumed-session assistant turns are long agentic turns; the chat WebSocket
can close mid-turn and the frontend reconnects with the SAME session id.
``websocket_chat`` used to send the agent's reply through the socket object
captured at connection start — after a reconnect that send targeted the
stale socket (``RuntimeError: Unexpected ASGI 'websocket.send' after
websocket.close``) and the reconnecting client never received the live
reply.

The fix routes ALL reply/turn sends through ``ActiveSessionTracker`` (the
same registry used for intervention routing): at send time the CURRENT live
socket for the session id is resolved, falling back to the captured socket
when the tracker has no entry. Send failures are logged and swallowed — a
send to a dead socket must never crash the turn pipeline. Persistence is
unchanged; only the delivery socket changes.

Also guards the tracker unregister race: the old connection's cleanup must
not evict the NEW connection's registration for the same session id.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.websockets import WebSocketDisconnect

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.api.ws import chat  # noqa: E402


class _FakeOIDCGateway:
    async def validate_token(self, token):
        return {"sub": "ws-user", "email": "ws@example.test", "tenant": ""}


class FakeWS:
    """Minimal stand-in for the server-side WebSocket in websocket_chat."""

    def __init__(self, name: str):
        self.name = name
        self.sent: list[dict] = []
        self.accepted = False
        self.closed = False
        self.app = SimpleNamespace(state=SimpleNamespace(data_client=None))
        self.query_params = {"token": "tok"}
        self._on_send: dict[str, asyncio.Event] = {}

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed = True

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)
        event = self._on_send.get(str(message.get("type", "reply")))
        if event is not None:
            event.set()

    async def receive_text(self) -> str:
        raise NotImplementedError


async def _wait_for(condition, timeout: float = 5.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not condition():
        if asyncio.get_event_loop().time() > deadline:
            raise asyncio.TimeoutError("condition not met")
        await asyncio.sleep(0.01)


@pytest.fixture(autouse=True)
def _clean_tracker():
    chat.ActiveSessionTracker._connections.clear()
    chat.ActiveSessionTracker._intervention_active.clear()
    yield
    chat.ActiveSessionTracker._connections.clear()
    chat.ActiveSessionTracker._intervention_active.clear()


@pytest.mark.asyncio
async def test_reply_delivered_to_reconnected_socket():
    """Reply completion AFTER the original socket closed and a NEW socket is
    registered for the same session id → the reply goes to the NEW socket,
    no send-to-dead-socket crash, and the new registration survives the old
    connection's cleanup."""
    session_id = str(uuid.uuid4())
    old_ws = FakeWS("old")
    new_ws = FakeWS("new")
    reply_event = asyncio.Event()
    new_ws._on_send["reply"] = reply_event

    user_msg = '{"message": "do a long agentic turn"}'

    async def fake_receive_text():
        # First call: the user message that kicks off the turn.
        if not fake_receive_text.called:  # type: ignore[attr-defined]
            fake_receive_text.called = True  # type: ignore[attr-defined]
            return user_msg
        # Subsequent calls: block until the reply was delivered to the NEW
        # socket (simulating the turn finishing while the loop waits), then
        # surface the disconnect of the ORIGINAL socket.
        await _wait_for(reply_event.is_set)
        raise WebSocketDisconnect(code=1001)

    fake_receive_text.called = False  # type: ignore[attr-defined]
    old_ws.receive_text = fake_receive_text  # type: ignore[method-assign]

    async def fake_process_message(**kwargs):
        # Mid-turn: the old client socket dies, the frontend reconnects with
        # the SAME session id → a NEW socket is registered in the tracker.
        chat.ActiveSessionTracker.register(session_id, new_ws)
        return "agent reply", "Session Title", None, []

    async def fake_bind(claims):
        return None

    with patch.object(chat, "get_oidc_client", lambda: _FakeOIDCGateway()), \
            patch.object(chat, "_bind_connection_tenant_context", fake_bind), \
            patch.object(chat, "_process_message", fake_process_message):
        await asyncio.wait_for(chat.websocket_chat(old_ws, session_id), timeout=10)

    # The reply, title update and guardrail-free flow all landed on the NEW
    # socket — never on the stale captured one.
    reply_payloads = [m for m in new_ws.sent if m.get("sender_role") == "agent"]
    assert reply_payloads and reply_payloads[0]["content"] == "agent reply"
    assert any(m.get("type") == "title_update" for m in new_ws.sent)
    assert not any(
        m.get("sender_role") == "agent" and m.get("content") == "agent reply"
        for m in old_ws.sent
    )
    # Old connection cleanup must NOT have evicted the NEW connection's
    # registration for the same session id.
    assert chat.ActiveSessionTracker.get_ws(session_id) is new_ws


@pytest.mark.asyncio
async def test_reply_still_goes_to_original_socket_when_no_reconnect():
    """Tracker holds the SAME socket (the normal case) → behaviour
    unchanged: the reply arrives on that socket."""
    session_id = str(uuid.uuid4())
    ws = FakeWS("only")
    reply_event = asyncio.Event()
    ws._on_send["reply"] = reply_event

    async def fake_receive_text():
        if not fake_receive_text.called:  # type: ignore[attr-defined]
            fake_receive_text.called = True  # type: ignore[attr-defined]
            return '{"message": "hello"}'
        await _wait_for(reply_event.is_set)
        raise WebSocketDisconnect(code=1001)

    fake_receive_text.called = False  # type: ignore[attr-defined]
    ws.receive_text = fake_receive_text  # type: ignore[method-assign]

    async def fake_process_message(**kwargs):
        return "direct reply", None, None, []

    async def fake_bind(claims):
        return None

    with patch.object(chat, "get_oidc_client", lambda: _FakeOIDCGateway()), \
            patch.object(chat, "_bind_connection_tenant_context", fake_bind), \
            patch.object(chat, "_process_message", fake_process_message):
        await asyncio.wait_for(chat.websocket_chat(ws, session_id), timeout=10)

    reply_payloads = [m for m in ws.sent if m.get("sender_role") == "agent"]
    assert reply_payloads and reply_payloads[0]["content"] == "direct reply"
    # Same-socket unregister still cleans the registry entry.
    assert chat.ActiveSessionTracker.get_ws(session_id) is None


@pytest.mark.asyncio
async def test_send_to_dead_socket_is_swallowed():
    """A send failure against a dead socket is logged and swallowed — the
    turn pipeline never crashes on transport errors."""
    session_id = str(uuid.uuid4())
    dead_ws = FakeWS("dead")

    async def exploding_send_json(message):
        raise RuntimeError("Unexpected ASGI 'websocket.send' after websocket.close")

    dead_ws.send_json = exploding_send_json  # type: ignore[method-assign]
    chat.ActiveSessionTracker.register(session_id, dead_ws)

    # Must not raise.
    await chat._send_to_live_socket(
        session_id, dead_ws, {"sender_role": "agent", "content": "x"}
    )


@pytest.mark.asyncio
async def test_send_falls_back_to_captured_socket_when_tracker_empty():
    """No tracker entry for the session (e.g. flows that never register) →
    the captured socket is used, preserving prior behaviour."""
    session_id = str(uuid.uuid4())
    fallback = FakeWS("fallback")
    fallback.sent = []
    await chat._send_to_live_socket(
        session_id, fallback, {"type": "chat_status", "status": "thinking"}
    )
    assert fallback.sent == [{"type": "chat_status", "status": "thinking"}]
