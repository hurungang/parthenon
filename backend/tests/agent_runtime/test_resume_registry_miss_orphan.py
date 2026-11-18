"""Conversation-scoped resume — durable delegation and orphan semantics.

A conversation session has no AgentJob row, so ``POST /internal/resume`` must
never fall through to the job path for one (that previously failed
``mark_session_running`` on a conversation id and left the chat stuck in
"thinking").  It now delegates to the durable conversational resume service:

* ``not_awaiting`` — no resume record exists (e.g. nothing is paused);
* ``unresumable`` — a record exists but could not be continued (no checkpoint,
  relay unavailable, terminal failure);
* ``already_resolved`` — the turn is already terminal;
* ``resumed`` — the resume was accepted (or another instance holds the claim).

These tests inject a fake resume service — no checkpoint relay is required.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent_runtime.api.intervene import resume_router
from app.agent_runtime.checkpoint_transport import (
    CheckpointTransportUnavailableError,
    ResumeClaimRead,
)
from app.agent_runtime.turn_resume_service import ConversationResumeOutcome


def _make_app(data_client) -> FastAPI:
    app = FastAPI()
    app.include_router(resume_router)
    app.state.data_client = data_client
    app.state.execution_semaphore = None
    return app


class _FakeResumeService:
    """Minimal stand-in for the durable conversational resume service."""

    def __init__(
        self,
        *,
        claim: ResumeClaimRead | None = None,
        outcome: ConversationResumeOutcome | None = None,
        claim_error: Exception | None = None,
    ) -> None:
        self._claim = claim or ResumeClaimRead(status="not_found")
        self._outcome = outcome
        self._claim_error = claim_error
        self.resume_calls = 0

    async def claim(self, conv_session_id):  # noqa: ANN001
        if self._claim_error is not None:
            raise self._claim_error
        return self._claim

    def outcome_for_claim(self, claim):  # noqa: ANN001
        return self._outcome

    async def resume_claimed(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.resume_calls += 1
        return ConversationResumeOutcome(status="resumed", response="ok")


def _post_resume(app: FastAPI, session_id: uuid.UUID) -> dict:
    with TestClient(app) as client:
        resp = client.post(
            "/internal/resume",
            json={
                "session_id": str(session_id),
                "response_value": {"approval_value": True},
            },
        )
    assert resp.status_code == 200
    return resp.json()


def test_no_resume_record_returns_not_awaiting() -> None:
    """No AgentJob, no resume record → not_awaiting, job path never entered."""
    conv_id = uuid.uuid4()
    data_client = AsyncMock()
    data_client.get_session = AsyncMock(return_value=None)
    data_client.mark_session_running = AsyncMock()
    service = _FakeResumeService(
        outcome=ConversationResumeOutcome(status="not_awaiting", reason="no_resume_record")
    )

    with patch(
        "app.agent_runtime.api.intervene.build_resume_service", return_value=service
    ), patch("app.agent_runtime.api.intervene._execute_session") as _exec:
        body = _post_resume(_make_app(data_client), conv_id)

    assert body == {
        "session_id": str(conv_id),
        "status": "not_awaiting",
        "reason": "no_resume_record",
    }
    data_client.mark_session_running.assert_not_awaited()
    _exec.assert_not_called()
    assert service.resume_calls == 0


def test_get_session_failure_treated_as_conversation_session() -> None:
    """If verifying the AgentJob raises, the safe path is the conversation
    resume path — never mark_session_running on an unverified session id."""
    session_id = uuid.uuid4()
    data_client = AsyncMock()
    data_client.get_session = AsyncMock(side_effect=RuntimeError("data API down"))
    data_client.mark_session_running = AsyncMock()
    service = _FakeResumeService(
        outcome=ConversationResumeOutcome(status="unresumable", reason="resume_failed")
    )

    with patch(
        "app.agent_runtime.api.intervene.build_resume_service", return_value=service
    ), patch("app.agent_runtime.api.intervene._execute_session") as _exec:
        body = _post_resume(_make_app(data_client), session_id)

    assert body["status"] == "unresumable"
    data_client.mark_session_running.assert_not_awaited()
    _exec.assert_not_called()


def test_claim_contention_reports_resumed_without_job_path() -> None:
    """Another instance already resuming the turn → ``resumed`` (not a
    terminal/orphan notice), and never the job path."""
    conv_id = uuid.uuid4()
    data_client = AsyncMock()
    data_client.get_session = AsyncMock(return_value=None)
    data_client.mark_session_running = AsyncMock()
    service = _FakeResumeService(
        claim_error=__import__(
            "app.agent_runtime.checkpoint_transport",
            fromlist=["ResumeClaimContentionError"],
        ).ResumeClaimContentionError("held elsewhere", holder_instance_id="ar-2")
    )

    with patch(
        "app.agent_runtime.api.intervene.build_resume_service", return_value=service
    ), patch("app.agent_runtime.api.intervene._execute_session") as _exec:
        body = _post_resume(_make_app(data_client), conv_id)

    assert body["status"] == "resumed"
    assert body["reason"] == "claim_held_elsewhere"
    data_client.mark_session_running.assert_not_awaited()
    _exec.assert_not_called()


def test_relay_unavailable_is_unresumable_not_job_path() -> None:
    """A conversation id whose checkpoint relay is unreachable must NOT be
    forced through the job path; it reports unresumable explicitly."""
    conv_id = uuid.uuid4()
    data_client = AsyncMock()
    data_client.get_session = AsyncMock(return_value=None)
    data_client.mark_session_running = AsyncMock()
    service = _FakeResumeService(
        claim_error=CheckpointTransportUnavailableError("relay down")
    )

    with patch(
        "app.agent_runtime.api.intervene.build_resume_service", return_value=service
    ), patch("app.agent_runtime.api.intervene._execute_session") as _exec:
        body = _post_resume(_make_app(data_client), conv_id)

    assert body["status"] == "unresumable"
    assert body["reason"] == "checkpoint_relay_unavailable"
    data_client.mark_session_running.assert_not_awaited()
    _exec.assert_not_called()


def test_accepted_resume_runs_out_of_band_and_reports_resumed() -> None:
    """An acquired claim returns ``resumed`` immediately; the turn runs in a
    background task (the legacy route must not hold the request open)."""
    conv_id = uuid.uuid4()
    data_client = AsyncMock()
    data_client.get_session = AsyncMock(return_value=None)
    data_client.mark_session_running = AsyncMock()
    service = _FakeResumeService(
        claim=ResumeClaimRead(
            status="acquired",
            resume=__import__(
                "app.agent_runtime.checkpoint_transport", fromlist=["ResumeIndexRead"]
            ).ResumeIndexRead(
                resume_id=uuid.uuid4(),
                conversation_session_id=conv_id,
                resume_key="rk",
                state="waiting_for_human",
            ),
        )
    )

    with patch(
        "app.agent_runtime.api.intervene.build_resume_service", return_value=service
    ), patch("app.agent_runtime.api.intervene._execute_session") as _exec:
        body = _post_resume(_make_app(data_client), conv_id)

    assert body["status"] == "resumed"
    data_client.mark_session_running.assert_not_awaited()
    _exec.assert_not_called()


def test_job_session_resume_path_unchanged() -> None:
    """A real AgentJob session keeps the genuine resume path:
    mark_session_running + relaunch execution (no resume service needed)."""
    job_id = uuid.uuid4()
    data_client = AsyncMock()
    data_client.get_session = AsyncMock(return_value={"id": str(job_id), "status": "waiting_for_human"})
    data_client.mark_session_running = AsyncMock()

    with patch(
        "app.agent_runtime.api.intervene._execute_session", new=AsyncMock()
    ) as _exec:
        body = _post_resume(_make_app(data_client), job_id)

    assert body["status"] == "resumed"
    data_client.mark_session_running.assert_awaited_once()
    _exec.assert_awaited_once()
