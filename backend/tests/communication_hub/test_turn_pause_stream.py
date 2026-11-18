"""Communication Hub — a durable pause ends the conversational turn cleanly.

Agent Runtime now ends a paused conversational turn with a ``paused`` chunk
(the checkpoint + resume index are persisted) instead of a reply.  The CH turn
pipeline must therefore:

* hand the pause to the caller (``on_pause``) instead of treating the empty
  response as an agent message;
* deliver no reply, append no agent turn and emit no ``finished`` status — the
  turn waits for the operator and ``waiting_for_human`` was already streamed.

Without this, a pause would be rendered as an empty agent reply and the UI
would clear its processing state while the turn is still awaiting confirmation.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.api.ws import chat  # noqa: E402


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


class PausedDataClient:
    """CC data client stub: prepare a turn, persist nothing else."""

    def __init__(self) -> None:
        self.prepared = 0
        self.appended: list[dict] = []
        self.activity: list[dict] = []

    async def prepare_conversation_turn(self, conv_session_id, user_message):
        self.prepared += 1
        return {
            "agent_type_id": str(uuid.uuid4()),
            "messages": [{"role": "user", "content": user_message}],
            "no_agent_message": None,
        }

    async def append_conversation_turn(self, **kwargs):
        self.appended.append(kwargs)
        return {"title": "unexpected"}

    async def upsert_conversation_activity(self, conv_session_id, state, **kwargs):
        self.activity.append({"state": state, **kwargs})
        return {"state": state}


class PausedDelegate:
    """Stands in for the AR streaming delegation: one status event + a pause."""

    def __init__(self, pause: dict) -> None:
        self.pause = pause
        self.calls = 0

    async def __call__(
        self,
        *,
        app,
        conv_session_id,
        agent_type_id,
        messages,
        on_status_event=None,
        on_pause=None,
    ):
        self.calls += 1
        if on_status_event is not None:
            await on_status_event({"status": "waiting_for_human"})
        if on_pause is not None:
            await on_pause(self.pause)
        return "", None, []


@pytest.mark.asyncio
async def test_paused_turn_delivers_no_reply_and_persists_no_agent_turn():
    data_client = PausedDataClient()
    app = SimpleNamespace(state=SimpleNamespace(data_client=data_client))
    replies: list[str] = []
    delegate = PausedDelegate({"resume_id": str(uuid.uuid4())})

    with patch.object(
        chat, "_delegate_conversation_turn_to_agent_runtime", delegate
    ):
        reply, title, _guardrail, _events = await chat._process_message(
            conv_session_id=uuid.uuid4(),
            user_message="create a skill",
            is_first_message=True,
            app=app,
            on_reply=lambda text: replies.append(text) or asyncio.sleep(0),
        )

    assert reply == ""
    assert title is None
    assert replies == []  # no (empty) reply pushed to the client
    assert data_client.appended == []  # nothing persisted as an agent turn
    assert delegate.calls == 1


@pytest.mark.asyncio
async def test_run_conversation_turn_does_not_finish_a_paused_turn():
    socket = FakeSocket()
    chat.ActiveSessionTracker.register(str(uuid.uuid4()), socket)
    conv_id = uuid.uuid4()
    chat.ActiveSessionTracker.register(str(conv_id), socket)
    data_client = PausedDataClient()
    app = SimpleNamespace(state=SimpleNamespace(data_client=data_client))
    delegate = PausedDelegate({"resume_id": str(uuid.uuid4())})

    with patch.object(
        chat, "_delegate_conversation_turn_to_agent_runtime", delegate
    ):
        await chat.run_conversation_turn(
            session_id=str(conv_id),
            conv_session_id=conv_id,
            user_message="create a skill",
            is_first_message=True,
            app=app,
            websocket=socket,
            message_count=1,
        )

    statuses = [m for m in socket.sent if m.get("type") == "chat_status"]
    assert [s["status"] for s in statuses] == ["waiting_for_human"]
    assert not any(m.get("sender_role") == "agent" for m in socket.sent)
    assert data_client.appended == []


@pytest.mark.asyncio
async def test_streaming_paused_chunk_is_forwarded_to_on_pause():
    """The real streaming delegation recognizes the ``paused`` chunk."""
    pauses: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            json.dumps({"type": "status_event", "event": {"status": "waiting_for_human"}})
            + "\n"
            + json.dumps({"type": "paused", "pause": {"resume_id": "r-1"}})
            + "\n"
        )
        return httpx.Response(200, content=body.encode())

    original = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.pop("verify", None)
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(**kwargs)

    app = SimpleNamespace(state=SimpleNamespace(certificate_manager=None))
    streamed: list[dict] = []

    async def on_status_event(event: dict) -> None:
        streamed.append(event)

    with patch.object(chat.httpx, "AsyncClient", factory):
        reply, _guardrail, events = await chat._delegate_conversation_turn_to_agent_runtime(
            app=app,
            conv_session_id=uuid.uuid4(),
            agent_type_id=uuid.uuid4(),
            messages=[{"role": "user", "content": "hi"}],
            on_status_event=on_status_event,
            on_pause=lambda pause: pauses.append(pause) or asyncio.sleep(0),
        )

    assert reply == ""
    assert pauses == [{"resume_id": "r-1"}]
    assert [e["status"] for e in streamed] == ["waiting_for_human"]
    assert [e["status"] for e in events] == ["waiting_for_human"]
