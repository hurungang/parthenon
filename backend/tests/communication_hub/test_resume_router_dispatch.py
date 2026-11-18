"""Communication Hub — conversation-scoped resume dispatch (Phase 4.2/4.3).

A conversation-scoped resume is dispatched out of band to Agent Runtime's
durable resume route (any instance can continue the turn), streams its status
events to the live socket and Control Center, closes the turn exactly once, and
de-duplicates repeated operator responses.  A ``paused`` chunk during the
resume delivers no reply.  These tests use a fake AR stream, a fake Control
Center data client and a fake live socket — no service is required.
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
from app.communication_hub.api.internal import agent_resume  # noqa: E402
from app.communication_hub.api.internal.agent_resume import (  # noqa: E402
    AgentResumeRequest,
    forward_resume_session,
    reset_resume_dispatch_state,
)
from app.communication_hub.data_client import ConversationResumeLookup  # noqa: E402

CONV_ID = uuid.uuid4()


# ── Fakes ────────────────────────────────────────────────────────────────────


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    @property
    def agent_replies(self) -> list[dict]:
        return [m for m in self.sent if m.get("sender_role") == "agent"]

    @property
    def statuses(self) -> list[dict]:
        return [m for m in self.sent if m.get("type") == "chat_status"]


class FakeDataClient:
    """Minimal Control Center data client for the resume router."""

    def __init__(
        self,
        *,
        live_record: dict | None = None,
        is_conversation: bool = True,
        activity: dict | None = None,
        complete_error: Exception | None = None,
    ) -> None:
        self.live_record = live_record
        self.is_conversation = is_conversation
        self.activity = activity
        self.complete_error = complete_error
        self.completed: list[dict] = []
        self.appended: list[dict] = []
        self.activity_upserts: list[dict] = []

    async def get_conversation_turn_resume(self, conv_session_id):
        return ConversationResumeLookup(
            is_conversation_session=self.is_conversation,
            record=self.live_record,
        )

    async def get_conversation_activity(self, conv_session_id):
        return self.activity

    async def complete_conversation_turn_resume(self, conv_session_id, body):
        if self.complete_error is not None:
            raise self.complete_error
        self.completed.append(body)
        self.live_record = None  # the record is terminal after the closer
        return {"resume_id": body.get("resume_id"), "state": "resolved"}

    async def append_conversation_turn(self, **kwargs):
        self.appended.append(kwargs)
        return {"title": None}

    async def upsert_conversation_activity(self, conv_session_id, state, **kwargs):
        self.activity_upserts.append({"state": state, **kwargs})
        return {"state": state}


def _record(*, write_applied: bool = True, expires_at: str | None = None) -> dict:
    return {
        "resume_id": str(uuid.uuid4()),
        "conversation_session_id": str(CONV_ID),
        "resume_key": "rk-opaque",
        "state": "waiting_for_human",
        "is_terminal": False,
        "write_applied": write_applied,
        "expires_at": expires_at,
    }


def _ndjson(*chunks: dict) -> bytes:
    return ("".join(json.dumps(c) + "\n" for c in chunks)).encode()


def _install_ar(responder) -> None:
    """Point the router's AR egress at a fake stream (no mTLS)."""

    def factory(**kwargs):
        kwargs.pop("verify", None)
        kwargs.pop("cert", None)
        kwargs["transport"] = httpx.MockTransport(responder)
        return httpx.AsyncClient(**kwargs)

    return patch.object(agent_resume, "internal_httpx_client", factory)


class FakeRequest:
    def __init__(self, data_client) -> None:
        self.app = SimpleNamespace(
            state=SimpleNamespace(data_client=data_client, certificate_manager=None)
        )


async def _settle(conv_id: uuid.UUID, timeout: float = 5.0) -> None:
    """Wait for the background dispatch task to finish."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        dispatch = agent_resume._RESUME_DISPATCHES.get(str(conv_id))
        if dispatch is not None and dispatch.task is not None and dispatch.task.done():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("resume dispatch did not settle")


@pytest.fixture(autouse=True)
def _clean_state():
    chat.ActiveSessionTracker._connections.clear()
    chat.ActiveSessionTracker._intervention_active.clear()
    reset_resume_dispatch_state()
    yield
    reset_resume_dispatch_state()
    chat.ActiveSessionTracker._connections.clear()
    chat.ActiveSessionTracker._intervention_active.clear()


# ── 4.2 — streamed, outcome-persisting, non-blocking dispatch ────────────────


@pytest.mark.asyncio
async def test_final_delivers_one_reply_and_persists_one_outcome():
    socket = FakeSocket()
    chat.ActiveSessionTracker.register(str(CONV_ID), socket)
    data_client = FakeDataClient(live_record=_record(write_applied=True))

    def responder(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/conversation/resume"
        payload = json.loads(request.content)
        assert payload["stream_status_events"] is True
        assert payload["conv_session_id"] == str(CONV_ID)
        return httpx.Response(
            200,
            content=_ndjson(
                {"type": "status_event", "event": {"status": "thinking"}},
                {
                    "type": "status_event",
                    "event": {"status": "using_tool", "tool_name": "cc____create_skill"},
                },
                {
                    "type": "final",
                    "response": "Done — the skill was created.",
                    "guardrail_usage": {"iterations": 2},
                },
            ),
        )

    with _install_ar(responder):
        response = await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )
        await _settle(CONV_ID)

    assert response.status == "resumed"
    # One reply, delivered once, and one terminal status.
    assert [m["content"] for m in socket.agent_replies] == [
        "Done — the skill was created."
    ]
    assert socket.statuses[-1]["status"] == "finished"
    # Exactly one outcome close, carrying the reply as the outcome turn.
    assert len(data_client.completed) == 1
    completed = data_client.completed[0]
    assert completed["outcome"] == "approved_applied"
    assert completed["write_applied"] is True
    assert completed["outcome_turn_content"] == "Done — the skill was created."
    # The stream's activity transitions were persisted (not just pushed).
    assert [u["state"] for u in data_client.activity_upserts] == [
        "thinking",
        "using_tool",
    ]


@pytest.mark.asyncio
async def test_dispatch_returns_before_the_turn_completes():
    """The HTTP call must not hold the connection open for the whole turn."""
    socket = FakeSocket()
    chat.ActiveSessionTracker.register(str(CONV_ID), socket)
    data_client = FakeDataClient(live_record=_record())
    release = asyncio.Event()

    async def responder(request: httpx.Request) -> httpx.Response:
        await release.wait()
        return httpx.Response(
            200, content=_ndjson({"type": "final", "response": "late reply"})
        )

    with _install_ar(responder):
        response = await asyncio.wait_for(
            forward_resume_session(
                CONV_ID,
                AgentResumeRequest(response_value={"approval_value": True}),
                FakeRequest(data_client),
            ),
            timeout=2.0,
        )
        assert response.status == "resumed"
        dispatch = agent_resume._RESUME_DISPATCHES[str(CONV_ID)]
        assert dispatch.state == agent_resume._DISPATCH_IN_FLIGHT
        assert socket.agent_replies == []  # nothing delivered yet
        release.set()
        await _settle(CONV_ID)

    assert [m["content"] for m in socket.agent_replies] == ["late reply"]


@pytest.mark.asyncio
async def test_re_pause_during_resume_is_not_delivered_as_a_reply():
    socket = FakeSocket()
    chat.ActiveSessionTracker.register(str(CONV_ID), socket)
    data_client = FakeDataClient(live_record=_record())

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_ndjson(
                {"type": "status_event", "event": {"status": "thinking"}},
                {
                    "type": "status_event",
                    "event": {"status": "waiting_for_human", "pending_intervention": "true"},
                },
                {
                    "type": "paused",
                    "pause": {"resume_id": str(uuid.uuid4()), "durable": True},
                },
            ),
        )

    with _install_ar(responder):
        await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )
        await _settle(CONV_ID)

    # No reply: the turn waits for the operator again.
    assert socket.agent_replies == []
    assert data_client.completed == []
    # The new pause is shown as waiting (backed by the new live record).
    assert data_client.activity_upserts[-1]["state"] == "waiting_for_human"
    dispatch = agent_resume._RESUME_DISPATCHES[str(CONV_ID)]
    assert dispatch.status == "resumed"
    assert dispatch.reason == "paused_again"


# ── 4.3 — one resume / one outcome under duplicate responses ─────────────────


@pytest.mark.asyncio
async def test_duplicate_responses_produce_one_resume_and_one_outcome():
    socket = FakeSocket()
    chat.ActiveSessionTracker.register(str(CONV_ID), socket)
    data_client = FakeDataClient(live_record=_record(write_applied=True))
    release = asyncio.Event()
    ar_calls: list[str] = []

    async def responder(request: httpx.Request) -> httpx.Response:
        ar_calls.append(request.url.path)
        await release.wait()
        return httpx.Response(
            200, content=_ndjson({"type": "final", "response": "applied once"})
        )

    with _install_ar(responder):
        first = await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )
        # Same answered intervention, twice, while the first is in flight.
        second = await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )
        third = await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )
        assert first.status == "resumed"
        assert second.status == "already_resolved"
        assert second.reason == "in_flight"
        assert third.status == "already_resolved"
        # Let the single in-flight dispatch actually reach Agent Runtime, then
        # confirm the duplicates did not start a second stream.
        for _ in range(200):
            if ar_calls:
                break
            await asyncio.sleep(0.01)
        assert len(ar_calls) == 1, "a duplicate response must not start a second resume"

        release.set()
        await _settle(CONV_ID)

        # After resolution the stored outcome short-circuits too.
        fourth = await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )

    assert len(ar_calls) == 1
    assert len(data_client.completed) == 1
    assert len(socket.agent_replies) == 1
    assert fourth.status == "resumed"
    assert fourth.reason == "approved_applied"
    assert fourth.deduplicated is True


@pytest.mark.asyncio
async def test_concurrent_duplicate_responses_start_one_resume():
    socket = FakeSocket()
    chat.ActiveSessionTracker.register(str(CONV_ID), socket)
    data_client = FakeDataClient(live_record=_record(write_applied=True))
    release = asyncio.Event()
    ar_calls: list[str] = []

    async def responder(request: httpx.Request) -> httpx.Response:
        ar_calls.append(request.url.path)
        await release.wait()
        return httpx.Response(
            200, content=_ndjson({"type": "final", "response": "only once"})
        )

    async def respond():
        return await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )

    with _install_ar(responder):
        first, second = await asyncio.gather(respond(), respond())
        release.set()
        await _settle(CONV_ID)

    statuses = sorted([first.status, second.status])
    assert statuses == ["already_resolved", "resumed"]
    assert len(ar_calls) == 1
    assert len(data_client.completed) == 1
    assert len(socket.agent_replies) == 1


@pytest.mark.asyncio
async def test_dispatch_failure_is_retryable_not_absorbed():
    """An unreachable AR leaves the pause answerable: a retry re-dispatches."""
    data_client = FakeDataClient(live_record=_record())
    calls: list[str] = []
    fail = {"on": True}

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if fail["on"]:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(
            200, content=_ndjson({"type": "final", "response": "retried"})
        )

    with _install_ar(responder):
        await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )
        await _settle(CONV_ID)
        assert agent_resume._RESUME_DISPATCHES[str(CONV_ID)].status == "dispatch_failed"

        fail["on"] = False
        retry = await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )
        await _settle(CONV_ID)

    assert retry.status == "resumed"
    assert len(calls) == 2
    assert len(data_client.completed) == 1


# ── 4.4 — durable-state terminal semantics ──────────────────────────────────


def _durable_unresumable_activity(reason: str = "expired") -> dict:
    return {
        "state": "timed_out",
        "is_terminal": True,
        "active_resume_id": None,
        "terminal_reason_code": reason,
        "terminal_message_key": f"conversation.resume.{reason}",
    }


@pytest.mark.asyncio
async def test_terminal_resume_status_emits_the_reasoned_terminal_message():
    """AR reporting a terminal record (claim → terminal) ends the turn once."""
    socket = FakeSocket()
    chat.ActiveSessionTracker.register(str(CONV_ID), socket)
    data_client = FakeDataClient(live_record=_record())

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_ndjson(
                {
                    "type": "resume_status",
                    "status": "unresumable",
                    "reason": "expired",
                    "write_applied": False,
                }
            ),
        )

    with _install_ar(responder):
        await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )
        await _settle(CONV_ID)

    terminal = [m for m in socket.statuses if m.get("status") in {"timed_out", "failed"}]
    assert len(terminal) == 1
    assert terminal[0]["terminal_reason_code"] == "expired"
    assert socket.agent_replies == []
    assert data_client.completed == []


@pytest.mark.asyncio
async def test_restart_alone_produces_no_terminal_message():
    """No live record + no durable terminal state = nothing to tell the user."""
    socket = FakeSocket()
    chat.ActiveSessionTracker.register(str(CONV_ID), socket)
    data_client = FakeDataClient(live_record=None, activity=None)
    ar_calls: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        ar_calls.append(request.url.path)
        return httpx.Response(200, content=b"")

    with _install_ar(responder):
        response = await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )

    assert response.status == "not_awaiting"
    assert response.reason == "no_live_resume"
    assert socket.statuses == []
    assert ar_calls == []


@pytest.mark.asyncio
async def test_durably_unresumable_turn_emits_exactly_one_reasoned_message():
    socket = FakeSocket()
    chat.ActiveSessionTracker.register(str(CONV_ID), socket)
    data_client = FakeDataClient(
        live_record=None, activity=_durable_unresumable_activity("expired")
    )

    with _install_ar(lambda request: httpx.Response(200, content=b"")):
        first = await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )
        second = await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )

    assert first.status == "unresumable"
    assert first.reason == "expired"
    assert second.status == "unresumable"
    terminal = [m for m in socket.statuses if m.get("status") in {"timed_out", "failed"}]
    assert len(terminal) == 1, "exactly one terminal message per unresumable turn"
    payload = terminal[0]
    assert payload["terminal_reason_code"] == "expired"
    assert payload["resume_state"] == "unresumable"
    assert "expired" in payload["message"].lower()
    assert "restart" not in payload["message"].lower()
    # The durable activity agrees (what a reconnecting client hydrates).
    assert data_client.activity_upserts[-1]["state"] == "timed_out"


@pytest.mark.asyncio
async def test_expired_live_record_is_unresumable_without_dispatch():
    socket = FakeSocket()
    chat.ActiveSessionTracker.register(str(CONV_ID), socket)
    data_client = FakeDataClient(
        live_record=_record(expires_at="2020-01-01T00:00:00+00:00")
    )
    ar_calls: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        ar_calls.append(request.url.path)
        return httpx.Response(200, content=b"")

    with _install_ar(responder):
        response = await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )

    assert response.status == "unresumable"
    assert response.reason == "expired"
    assert ar_calls == []
    assert len(socket.statuses) == 1
    assert socket.statuses[0]["status"] == "timed_out"


@pytest.mark.asyncio
async def test_offline_client_still_persists_the_terminal_state():
    """No live socket: best effort, and the durable activity carries the state."""
    data_client = FakeDataClient(
        live_record=None, activity=_durable_unresumable_activity("resume_failed")
    )

    with _install_ar(lambda request: httpx.Response(200, content=b"")):
        response = await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )

    assert response.status == "unresumable"
    persisted = data_client.activity_upserts[-1]
    assert persisted["state"] == "failed"
    # The reason-keyed projection is persisted so the next hydration agrees.
    assert persisted["detail"]["terminal_reason_code"] == "resume_failed"
    hydrated = chat._activity_state_message(
        {
            "state": "failed",
            "is_terminal": True,
            "active_resume_id": None,
            "detail": persisted["detail"],
        }
    )
    assert hydrated["state"] == "failed"
    assert hydrated["resume_state"] == "unresumable"
    assert hydrated["terminal_reason_code"] == "resume_failed"
    assert "resum" in hydrated["message"].lower()


@pytest.mark.asyncio
async def test_terminal_reason_survives_a_ch_restart():
    """The guard is in-memory; a restart still finds CC's durable reason."""
    reset_resume_dispatch_state()  # simulate a Communication Hub restart
    socket = FakeSocket()
    chat.ActiveSessionTracker.register(str(CONV_ID), socket)
    data_client = FakeDataClient(
        live_record=None,
        activity={
            "state": "failed",
            "is_terminal": True,
            "active_resume_id": None,
            "detail": {
                "resume_state": "unresumable",
                "terminal_reason_code": "checkpoint_unavailable",
            },
        },
    )

    with _install_ar(lambda request: httpx.Response(200, content=b"")):
        response = await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )

    assert response.status == "unresumable"
    assert response.reason == "checkpoint_unavailable"
    terminal = [m for m in socket.statuses if m.get("status") in {"timed_out", "failed"}]
    assert len(terminal) == 1
    assert terminal[0]["terminal_reason_code"] == "checkpoint_unavailable"


@pytest.mark.asyncio
async def test_agent_runtime_resume_failure_emits_one_terminal_message():
    socket = FakeSocket()
    chat.ActiveSessionTracker.register(str(CONV_ID), socket)
    data_client = FakeDataClient(live_record=_record())

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_ndjson({"type": "error", "error_type": "resume_failed"}),
        )

    with _install_ar(responder):
        await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )
        await _settle(CONV_ID)

    terminal = [m for m in socket.statuses if m.get("status") in {"timed_out", "failed"}]
    assert len(terminal) == 1
    assert terminal[0]["terminal_reason_code"] == "resume_failed"
    assert socket.agent_replies == []
    assert data_client.completed == []


# ── Agent-job path is preserved ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_job_resume_keeps_the_legacy_forwarding_path():
    data_client = FakeDataClient(is_conversation=False)
    seen: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        body = json.loads(request.content)
        assert body["session_id"] == str(CONV_ID)
        return httpx.Response(
            200, json={"session_id": str(CONV_ID), "status": "resumed"}
        )

    with _install_ar(responder):
        response = await forward_resume_session(
            CONV_ID,
            AgentResumeRequest(response_value={"approval_value": True}),
            FakeRequest(data_client),
        )

    assert seen == ["/internal/resume"]
    assert response.status == "resumed"
