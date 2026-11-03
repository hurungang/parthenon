"""FIX-20261031-091657 (Defect B.1) — session termination covers conversation turns.

Agent Runtime's ``/terminate/{session_id}`` must also cancel in-flight
CONVERSATION turn tasks (registered under the conversation session id), so
``POST /conversations/{id}/end`` can stop a hung/slow turn through the
existing CC → CH → AR termination machinery.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent_runtime.api.terminate import terminate_router


def _app_with_conversation_task(session_id: uuid.UUID) -> tuple[FastAPI, asyncio.Task]:
    app = FastAPI()
    app.include_router(terminate_router)
    app.state.session_tasks = {}

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _hung() -> None:
        await asyncio.sleep(120)

    task = loop.create_task(_hung())
    app.state.conversation_tasks = {session_id: task}
    return app, task


def test_terminate_cancels_in_flight_conversation_turn_task() -> None:
    session_id = uuid.uuid4()
    app, task = _app_with_conversation_task(session_id)
    client = TestClient(app)

    response = client.post(f"/terminate/{session_id}", json={"reason": "conversation ended"})

    assert response.status_code == 200
    assert response.json()["cancelled"] is True
    with pytest.raises(asyncio.CancelledError):
        task.cancel()
        asyncio.get_event_loop().run_until_complete(asyncio.wait_for(task, timeout=2))


def test_terminate_still_404s_when_no_task_registered() -> None:
    session_id = uuid.uuid4()
    app = FastAPI()
    app.include_router(terminate_router)
    app.state.session_tasks = {}
    app.state.conversation_tasks = {}
    client = TestClient(app)

    response = client.post(f"/terminate/{session_id}", json={})
    assert response.status_code == 404
