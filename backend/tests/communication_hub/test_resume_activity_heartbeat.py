"""A resumed conversational turn keeps its activity heartbeat fresh.

Control Center's activity staleness bound is deliberately short (a dead turn must
resolve within minutes). A first turn stays fresh through the WebSocket
heartbeat; a **resumed** turn streams in a background dispatch with no such loop,
so a quiet-but-live resumed turn would otherwise be resolved to a terminal state
by the reaper mid-turn. ``_activity_heartbeat_loop`` closes that gap.
"""
import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.communication_hub.api.internal import agent_resume as resume_module
from app.communication_hub.api.internal.agent_resume import (
    ConversationResumeOutcome,
    ResumeDispatch,
    _activity_heartbeat_loop,
    _dispatch_conversation_resume,
)


@pytest.mark.asyncio
async def test_loop_touches_the_activity_until_stopped(monkeypatch):
    import app.api.ws.chat as chat_module

    monkeypatch.setattr(
        chat_module, "CONVERSATION_HEARTBEAT_INTERVAL_SECONDS", 0.01
    )
    touched: list[uuid.UUID] = []

    async def fake_touch(_app, conv_session_id):
        touched.append(conv_session_id)

    monkeypatch.setattr(chat_module, "_touch_activity_heartbeat", fake_touch)

    conv_session_id = uuid.uuid4()
    stop = asyncio.Event()
    task = asyncio.create_task(
        _activity_heartbeat_loop(
            SimpleNamespace(state=SimpleNamespace()), conv_session_id, stop
        )
    )
    try:
        for _ in range(200):
            if touched:
                break
            await asyncio.sleep(0.01)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=5)

    assert touched and set(touched) == {conv_session_id}


@pytest.mark.asyncio
async def test_dispatch_beats_while_the_resume_streams_and_stops_after(monkeypatch):
    import app.api.ws.chat as chat_module

    monkeypatch.setattr(
        chat_module, "CONVERSATION_HEARTBEAT_INTERVAL_SECONDS", 0.01
    )
    touched: list[uuid.UUID] = []

    async def fake_touch(_app, conv_session_id):
        touched.append(conv_session_id)

    monkeypatch.setattr(chat_module, "_touch_activity_heartbeat", fake_touch)

    async def fake_stream(**_kwargs):
        await asyncio.sleep(0.06)
        return ConversationResumeOutcome(status="resumed", response="done")

    monkeypatch.setattr(resume_module, "_stream_conversation_resume", fake_stream)

    conv_session_id = uuid.uuid4()
    dispatch = ResumeDispatch(
        conversation_session_id=conv_session_id,
        resume_id=None,
        intervention_id=None,
        started_at=0.0,
    )

    await asyncio.wait_for(
        _dispatch_conversation_resume(
            app=SimpleNamespace(state=SimpleNamespace()),
            conversation_session_id=conv_session_id,
            response_value={"approval_value": True},
            record={},
            dispatch=dispatch,
        ),
        timeout=10,
    )

    assert dispatch.state == resume_module._DISPATCH_COMPLETED
    assert touched, "a resumed turn must keep its persisted activity fresh"
    # The beat stops with the dispatch — no background task is left running.
    count = len(touched)
    await asyncio.sleep(0.05)
    assert len(touched) == count


@pytest.mark.asyncio
async def test_dispatch_stops_the_beat_when_the_stream_fails(monkeypatch):
    import app.api.ws.chat as chat_module

    monkeypatch.setattr(
        chat_module, "CONVERSATION_HEARTBEAT_INTERVAL_SECONDS", 0.01
    )
    touched: list[uuid.UUID] = []

    async def fake_touch(_app, conv_session_id):
        touched.append(conv_session_id)

    monkeypatch.setattr(chat_module, "_touch_activity_heartbeat", fake_touch)

    async def failing_stream(**_kwargs):
        raise RuntimeError("ar unreachable")

    monkeypatch.setattr(resume_module, "_stream_conversation_resume", failing_stream)

    conv_session_id = uuid.uuid4()
    dispatch = ResumeDispatch(
        conversation_session_id=conv_session_id,
        resume_id=None,
        intervention_id=None,
        started_at=0.0,
    )

    await asyncio.wait_for(
        _dispatch_conversation_resume(
            app=SimpleNamespace(state=SimpleNamespace()),
            conversation_session_id=conv_session_id,
            response_value={},
            record={},
            dispatch=dispatch,
        ),
        timeout=10,
    )

    assert dispatch.state == resume_module._DISPATCH_COMPLETED
    assert dispatch.status == "dispatch_failed"
    count = len(touched)
    await asyncio.sleep(0.05)
    assert len(touched) == count
