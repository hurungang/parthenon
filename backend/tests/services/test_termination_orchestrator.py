"""Tests for ``TerminationOrchestrator`` with the Phase 3.11 cross-process cancellation flow.

Before Phase 3.11, the orchestrator only wrote to the Control Center's
``AgentJob`` row.  The Agent Runtime kept running the in-memory
``asyncio.Task``, which would eventually call
``mark_session_completed`` and overwrite the operator's
``failed``/``terminated`` state with ``completed``.

These tests verify the new two-phase termination:

  1. The orchestrator calls ``AgentRuntimeClient.terminate_session`` for
     every session in the cascade.
  2. The DB transition to ``failed`` + ``termination_category`` is
     persisted BEFORE the agent's late "completed" call would land.
  3. A 404 from the Agent Runtime (no in-flight task — already
     finished) is treated as a success no-op so the orchestrator
     doesn't fail the whole request when the agent had already
     finished naturally.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import pytest

from app.db.models.agents import (
    AgentJob,
    AgentJobStatus,
    AgentTerminationCategory,
)
from app.db.models.termination_cascade_outcome import (
    TerminationCascadeOutcome,
    TerminationOutcome,
)
from app.db.models.termination_request import (
    TerminationRequest,
    TerminationRequestStatus,
    TerminationScope,
)
from app.services.control_center.termination_orchestrator import (
    TerminationOrchestrator,
)


def _make_running_job(*, session_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=session_id or uuid.uuid4(),
        status=AgentJobStatus.running,
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        error_message=None,
        termination_category=AgentTerminationCategory.none,
    )


@pytest.mark.asyncio
async def test_request_termination_calls_agent_runtime_per_session():
    """Orchestrator must call ``terminate_session`` on Agent Runtime for
    every session in the cascade.  The DB transition happens
    *after* the runtime call so a late ``mark_session_completed``
    cannot overwrite the operator's terminal state.
    """
    job = _make_running_job()
    db = AsyncMock()
    db.get = AsyncMock(return_value=job)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()  # not used here but set for completeness

    orchestrator = TerminationOrchestrator()
    runtime_calls: list[uuid.UUID] = []

    async def _fake_terminate_session(*, session_id, reason=None):
        runtime_calls.append(session_id)
        return {"session_id": str(session_id), "cancelled": True}

    with patch(
        "app.services.control_center.termination_orchestrator._agent_runtime_client.terminate_session",
        AsyncMock(side_effect=_fake_terminate_session),
    ):
        request = await orchestrator.request_termination(
            target_session_id=job.id,
            requested_by_user_id=uuid.uuid4(),
            scope=TerminationScope.node_only,
            operator_reason="Test termination",
            db=db,
        )

    # Exactly one runtime call (single-node scope)
    assert len(runtime_calls) == 1
    assert runtime_calls[0] == job.id
    # The DB transition happened
    assert job.status == AgentJobStatus.terminated
    assert job.termination_category == AgentTerminationCategory.user_requested
    assert request.request_status == TerminationRequestStatus.completed


@pytest.mark.asyncio
async def test_request_termination_records_terminated_outcome():
    """The cascade outcome for the cancelled session must be
    ``terminated`` (not ``already_completed`` or ``not_found``) so
    the UI's termination status badge reflects the operator's
    intent.
    """
    job = _make_running_job()
    db = AsyncMock()
    db.get = AsyncMock(return_value=job)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    orchestrator = TerminationOrchestrator()
    captured_outcomes: list[TerminationCascadeOutcome] = []

    def _capture_add(obj):
        if isinstance(obj, TerminationCascadeOutcome):
            captured_outcomes.append(obj)

    db.add.side_effect = _capture_add

    async def _fake_terminate_session(*, session_id, reason=None):
        return {"session_id": str(session_id), "cancelled": True}

    with patch(
        "app.services.control_center.termination_orchestrator._agent_runtime_client.terminate_session",
        AsyncMock(side_effect=_fake_terminate_session),
    ):
        await orchestrator.request_termination(
            target_session_id=job.id,
            requested_by_user_id=uuid.uuid4(),
            scope=TerminationScope.node_only,
            operator_reason="Test",
            db=db,
        )

    assert len(captured_outcomes) == 1
    outcome = captured_outcomes[0]
    assert outcome.termination_outcome == TerminationOutcome.terminated
    assert "operator request" in (outcome.outcome_reason or "")
    # The outcome should mention the runtime cancellation so the
    # audit log shows both sides of the action.
    assert "Agent Runtime task cancelled" in (outcome.outcome_reason or "")


@pytest.mark.asyncio
async def test_request_termination_404_from_runtime_is_success():
    """If Agent Runtime returns 404 (no in-flight task — the session
    already finished naturally), the orchestrator must still mark
    the DB row as terminated and record a successful outcome.  The
    operator's intent is satisfied either way.
    """
    job = _make_running_job()
    db = AsyncMock()
    db.get = AsyncMock(return_value=job)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    orchestrator = TerminationOrchestrator()
    captured_outcomes: list[TerminationCascadeOutcome] = []

    def _capture_add(obj):
        if isinstance(obj, TerminationCascadeOutcome):
            captured_outcomes.append(obj)

    db.add.side_effect = _capture_add

    async def _fake_terminate_session(*, session_id, reason=None):
        return None  # 404 -> None in the client

    with patch(
        "app.services.control_center.termination_orchestrator._agent_runtime_client.terminate_session",
        AsyncMock(side_effect=_fake_terminate_session),
    ):
        request = await orchestrator.request_termination(
            target_session_id=job.id,
            requested_by_user_id=uuid.uuid4(),
            scope=TerminationScope.node_only,
            operator_reason="Test",
            db=db,
        )

    # DB transition still happened
    assert job.status == AgentJobStatus.terminated
    assert job.termination_category == AgentTerminationCategory.user_requested
    # The outcome reason should NOT mention runtime cancellation
    # because we never got confirmation from the runtime.
    assert len(captured_outcomes) == 1
    outcome_text = captured_outcomes[0].outcome_reason or ""
    assert "runtime" not in outcome_text.lower() or (
        "cancelled" not in outcome_text.lower()
    )
    assert request.request_status == TerminationRequestStatus.completed


@pytest.mark.asyncio
async def test_request_termination_runtime_error_still_persists_db():
    """If the runtime call raises (network down, etc.), the DB
    transition must still happen so the operator's intent is
    recorded.  The late agent task will unwind naturally and
    notice the session is already failed.
    """
    job = _make_running_job()
    db = AsyncMock()
    db.get = AsyncMock(return_value=job)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    from app.services.control_center.agent_runtime_client import (
        AgentRuntimeClientError,
    )

    orchestrator = TerminationOrchestrator()

    async def _failing_terminate(*, session_id, reason=None):
        raise AgentRuntimeClientError("Agent Runtime unreachable")

    with patch(
        "app.services.control_center.termination_orchestrator._agent_runtime_client.terminate_session",
        AsyncMock(side_effect=_failing_terminate),
    ):
        request = await orchestrator.request_termination(
            target_session_id=job.id,
            requested_by_user_id=uuid.uuid4(),
            scope=TerminationScope.node_only,
            operator_reason="Test",
            db=db,
        )

    # DB transition still happened
    assert job.status == AgentJobStatus.terminated
    assert job.termination_category == AgentTerminationCategory.user_requested
    assert request.request_status == TerminationRequestStatus.completed


@pytest.mark.asyncio
async def test_request_termination_skips_already_completed_sessions():
    """If the session is already in a terminal state, the
    orchestrator must NOT call Agent Runtime (the agent has
    nothing to cancel) and must record ``already_completed``
    instead of ``terminated``.
    """
    job = _make_running_job()
    job.status = AgentJobStatus.completed  # already terminal
    db = AsyncMock()
    db.get = AsyncMock(return_value=job)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    orchestrator = TerminationOrchestrator()
    captured_outcomes: list[TerminationCascadeOutcome] = []

    def _capture_add(obj):
        if isinstance(obj, TerminationCascadeOutcome):
            captured_outcomes.append(obj)

    db.add.side_effect = _capture_add

    runtime_called = False

    async def _fake_terminate_session(*, session_id, reason=None):
        nonlocal runtime_called
        runtime_called = True
        return {"session_id": str(session_id), "cancelled": True}

    with patch(
        "app.services.control_center.termination_orchestrator._agent_runtime_client.terminate_session",
        AsyncMock(side_effect=_fake_terminate_session),
    ):
        request = await orchestrator.request_termination(
            target_session_id=job.id,
            requested_by_user_id=uuid.uuid4(),
            scope=TerminationScope.node_only,
            operator_reason="Test",
            db=db,
        )

    # Runtime was NOT called
    assert runtime_called is False
    # Status unchanged
    assert job.status == AgentJobStatus.completed
    # Outcome was already_completed
    assert len(captured_outcomes) == 1
    assert captured_outcomes[0].termination_outcome == TerminationOutcome.already_completed
    assert request.request_status == TerminationRequestStatus.completed
