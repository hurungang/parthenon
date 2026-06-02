"""Tests for ``update_session_status`` terminal-state guards.

Phase 3.11: the endpoint now refuses to overwrite a terminal session
status (``completed``/``failed``) with a non-terminal ``running`` and
refuses to clear the ``stop_category``/``stop_reason``/``stop_details``
fields when the session was previously terminated by the operator
(``termination_category`` is ``user_requested`` or
``cascade_parent_terminated``).  This is the last line of defence
against the agent's late "I'm done!" call racing the operator's
"Terminate" request.
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
    AgentJobStatus,
    AgentTerminationCategory,
)


def _make_session(
    *,
    status: AgentJobStatus,
    termination_category: AgentTerminationCategory = AgentTerminationCategory.none,
    output_data: dict | None = None,
    error_message: str | None = None,
    stop_category=None,
    stop_reason=None,
    stop_details=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        error_message=error_message,
        output_data=output_data,
        termination_category=termination_category,
        stop_category=stop_category,
        stop_reason=stop_reason,
        stop_details=stop_details,
    )


@pytest.mark.asyncio
async def test_completed_status_does_not_clear_stop_fields_for_terminated_session():
    """A late ``completed`` call for a session that was previously
    terminated by the operator must NOT change the status from
    ``failed`` to ``completed`` and must NOT clear the
    ``stop_category``/``stop_reason``/``stop_details`` fields.
    The output_data IS still recorded so the operator can see what
    the agent would have produced.
    """
    from app.api.v1.internal.session_data import (
        SessionStatusUpdateRequest,
        update_session_status,
    )

    session_id = uuid.uuid4()
    session = _make_session(
        status=AgentJobStatus.failed,
        termination_category=AgentTerminationCategory.user_requested,
        error_message="Terminated by operator request",
        stop_category="user_action",
        stop_reason="terminated_by_operator",
        stop_details={"requested_by": "user-123"},
    )

    db = AsyncMock()
    db.get = AsyncMock(return_value=session)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    body = SessionStatusUpdateRequest(
        status="completed", output_data={"result": "would have been good"}
    )

    with patch(
        "app.api.v1.internal.session_data._dispatch_result_to_comm_hub",
        AsyncMock(),
    ):
        response = await update_session_status(
            session_id=session_id, body=body, db=db
        )

    # The status MUST remain "failed", not "completed"
    assert response.status == "failed"
    # The output_data IS recorded (so the operator can see what the
    # agent would have produced)
    assert session.output_data == {"result": "would have been good"}
    # The termination_category is preserved
    assert session.termination_category == AgentTerminationCategory.user_requested
    # The stop fields are preserved (NOT cleared)
    assert session.stop_category == "user_action"
    assert session.stop_reason == "terminated_by_operator"
    assert session.stop_details == {"requested_by": "user-123"}
    # The error message is preserved
    assert session.error_message == "Terminated by operator request"


@pytest.mark.asyncio
async def test_completed_status_clears_stop_fields_for_natural_completion():
    """A natural ``completed`` call for a session that was NOT
    terminated by the operator must still clear the
    ``stop_category``/``stop_reason``/``stop_details`` fields.  This
    is the original behaviour, preserved for the non-termination path.
    """
    from app.api.v1.internal.session_data import (
        SessionStatusUpdateRequest,
        update_session_status,
    )

    session_id = uuid.uuid4()
    session = _make_session(
        status=AgentJobStatus.running,
        termination_category=AgentTerminationCategory.none,
        stop_category="model_quota",
        stop_reason="rate_limited",
        stop_details={"retry_after": 60},
    )

    db = AsyncMock()
    db.get = AsyncMock(return_value=session)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    body = SessionStatusUpdateRequest(
        status="completed", output_data={"result": "good"}
    )

    with patch(
        "app.api.v1.internal.session_data._dispatch_result_to_comm_hub",
        AsyncMock(),
    ):
        response = await update_session_status(
            session_id=session_id, body=body, db=db
        )

    # Status transitions to "completed"
    assert response.status == "completed"
    # Natural completion: stop fields are cleared (preserved old behaviour)
    assert session.stop_category is None
    assert session.stop_reason is None
    assert session.stop_details is None
    # output_data is recorded
    assert session.output_data == {"result": "good"}


@pytest.mark.asyncio
async def test_running_status_ignored_for_already_completed_session():
    """A late ``running`` status update for an already-completed
    session must be ignored.
    """
    from app.api.v1.internal.session_data import (
        SessionStatusUpdateRequest,
        update_session_status,
    )

    session_id = uuid.uuid4()
    session = _make_session(
        status=AgentJobStatus.completed,
        termination_category=AgentTerminationCategory.none,
    )

    db = AsyncMock()
    db.get = AsyncMock(return_value=session)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    body = SessionStatusUpdateRequest(status="running")

    response = await update_session_status(
        session_id=session_id, body=body, db=db
    )

    # Session stays "completed"
    assert response.status == "completed"
    # No flush/commit happened
    db.flush.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_running_status_ignored_for_already_failed_session():
    """A late ``running`` status update for an already-failed
    session (terminated by operator) must be ignored — the
    agent's heartbeat after operator termination.
    """
    from app.api.v1.internal.session_data import (
        SessionStatusUpdateRequest,
        update_session_status,
    )

    session_id = uuid.uuid4()
    session = _make_session(
        status=AgentJobStatus.failed,
        termination_category=AgentTerminationCategory.user_requested,
    )

    db = AsyncMock()
    db.get = AsyncMock(return_value=session)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    body = SessionStatusUpdateRequest(status="running")

    response = await update_session_status(
        session_id=session_id, body=body, db=db
    )

    # Session stays "failed"
    assert response.status == "failed"
    db.flush.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_cascade_parent_terminated_session_preserves_stop_fields():
    """The same guard applies when the session was terminated by a
    cascade (a parent session was terminated, which terminated this
    child session by cascade).
    """
    from app.api.v1.internal.session_data import (
        SessionStatusUpdateRequest,
        update_session_status,
    )

    session_id = uuid.uuid4()
    session = _make_session(
        status=AgentJobStatus.failed,
        termination_category=AgentTerminationCategory.cascade_parent_terminated,
        stop_category="user_action",
        stop_reason="parent_session_terminated",
        stop_details={"parent_session_id": "abc-123"},
    )

    db = AsyncMock()
    db.get = AsyncMock(return_value=session)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    body = SessionStatusUpdateRequest(
        status="completed", output_data={"partial": "result"}
    )

    with patch(
        "app.api.v1.internal.session_data._dispatch_result_to_comm_hub",
        AsyncMock(),
    ):
        response = await update_session_status(
            session_id=session_id, body=body, db=db
        )

    # Status remains "failed"
    assert response.status == "failed"
    # Stop fields are preserved
    assert session.stop_category == "user_action"
    assert session.stop_reason == "parent_session_terminated"
    assert session.stop_details == {"parent_session_id": "abc-123"}
    # output_data IS still recorded
    assert session.output_data == {"partial": "result"}


@pytest.mark.asyncio
async def test_session_not_found_returns_404():
    """If the session doesn't exist, the endpoint returns 404.
    """
    from app.api.v1.internal.session_data import (
        SessionStatusUpdateRequest,
        update_session_status,
    )
    from fastapi import HTTPException

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    body = SessionStatusUpdateRequest(status="running")

    with pytest.raises(HTTPException) as exc_info:
        await update_session_status(
            session_id=uuid.uuid4(), body=body, db=db
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_terminated_session_refuses_late_running():
    """A late ``running`` status update for a session that was
    operator-terminated (state=``terminated``) must be ignored —
    the new distinct terminal state behaves the same as ``failed``
    for terminal-state guards.
    """
    from app.api.v1.internal.session_data import (
        SessionStatusUpdateRequest,
        update_session_status,
    )

    session_id = uuid.uuid4()
    session = _make_session(
        status=AgentJobStatus.terminated,
        termination_category=AgentTerminationCategory.user_requested,
    )

    db = AsyncMock()
    db.get = AsyncMock(return_value=session)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    body = SessionStatusUpdateRequest(status="running")

    response = await update_session_status(
        session_id=session_id, body=body, db=db
    )

    # Session stays "terminated"
    assert response.status == "terminated"
    db.flush.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_terminated_session_refuses_late_completed():
    """A late ``completed`` call from Agent Runtime for a session
    that was operator-terminated (state=``terminated``) must be
    refused: the output_data IS still recorded, but the status,
    termination_category, and stop fields are preserved.
    """
    from app.api.v1.internal.session_data import (
        SessionStatusUpdateRequest,
        update_session_status,
    )

    session_id = uuid.uuid4()
    session = _make_session(
        status=AgentJobStatus.terminated,
        termination_category=AgentTerminationCategory.user_requested,
        error_message="Terminated by operator request",
        stop_category="user_action",
        stop_reason="terminated_by_operator",
        stop_details={"requested_by": "user-456"},
    )

    db = AsyncMock()
    db.get = AsyncMock(return_value=session)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    body = SessionStatusUpdateRequest(
        status="completed", output_data={"partial": "result"}
    )

    with patch(
        "app.api.v1.internal.session_data._dispatch_result_to_comm_hub",
        AsyncMock(),
    ):
        response = await update_session_status(
            session_id=session_id, body=body, db=db
        )

    # Status remains "terminated"
    assert response.status == "terminated"
    # Stop fields are preserved
    assert session.stop_category == "user_action"
    assert session.stop_reason == "terminated_by_operator"
    assert session.stop_details == {"requested_by": "user-456"}
    # Termination category is preserved
    assert session.termination_category == AgentTerminationCategory.user_requested
    # output_data IS still recorded
    assert session.output_data == {"partial": "result"}
    # Error message preserved
    assert session.error_message == "Terminated by operator request"
