"""FIX (conversational resume orphan) — registry miss must never hit the job path.

When backend services restart, the in-process ``conversation_resume`` registry
loses pending conversational HITL entries.  If the operator then approves the
(stale) intervention card, AR's ``POST /internal/resume`` must NOT fall through
to the job path (``mark_session_running`` on a conversation session id fails
and leaves the user's chat stuck in "thinking").  Instead it must return
``status="not_awaiting"`` so CC can unblock the chat with an actionable
message.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent_runtime.api.intervene import resume_router


def _make_app(data_client) -> FastAPI:
    app = FastAPI()
    app.include_router(resume_router)
    app.state.data_client = data_client
    app.state.execution_semaphore = None
    return app


def test_registry_miss_without_job_returns_not_awaiting() -> None:
    """No pending registry entry AND no AgentJob → conversation session:
    must return not_awaiting (200) and never call mark_session_running."""
    conv_id = uuid.uuid4()
    data_client = AsyncMock()
    data_client.get_session = AsyncMock(return_value=None)  # no AgentJob
    data_client.mark_session_running = AsyncMock()

    with patch(
        "app.agent_runtime.api.intervene._execute_session"
    ) as _exec:
        with TestClient(_make_app(data_client)) as client:
            resp = client.post(
                "/internal/resume",
                json={"session_id": str(conv_id), "response_value": {"approval_value": True}},
            )
    assert resp.status_code == 200
    assert resp.json() == {"session_id": str(conv_id), "status": "not_awaiting"}
    data_client.mark_session_running.assert_not_awaited()
    _exec.assert_not_called()


def test_get_session_failure_treated_as_conversation_session() -> None:
    """If verifying the AgentJob raises, the safe path is not_awaiting —
    never mark_session_running on an unverified session id."""
    session_id = uuid.uuid4()
    data_client = AsyncMock()
    data_client.get_session = AsyncMock(side_effect=RuntimeError("data API down"))
    data_client.mark_session_running = AsyncMock()

    with patch("app.agent_runtime.api.intervene._execute_session") as _exec:
        with TestClient(_make_app(data_client)) as client:
            resp = client.post(
                "/internal/resume",
                json={"session_id": str(session_id)},
            )
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_awaiting"
    data_client.mark_session_running.assert_not_awaited()
    _exec.assert_not_called()


def test_job_session_resume_path_unchanged() -> None:
    """A real AgentJob session keeps the genuine resume path:
    mark_session_running + relaunch execution."""
    job_id = uuid.uuid4()
    data_client = AsyncMock()
    data_client.get_session = AsyncMock(return_value={"id": str(job_id), "status": "waiting_for_human"})
    data_client.mark_session_running = AsyncMock()

    with patch(
        "app.agent_runtime.api.intervene._execute_session", new=AsyncMock()
    ) as _exec:
        with TestClient(_make_app(data_client)) as client:
            resp = client.post(
                "/internal/resume",
                json={"session_id": str(job_id), "response_value": {"approval_value": True}},
            )
    assert resp.status_code == 200
    assert resp.json()["status"] == "resumed"
    data_client.mark_session_running.assert_awaited_once()
    _exec.assert_awaited_once()
