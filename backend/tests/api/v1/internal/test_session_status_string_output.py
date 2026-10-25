"""Regression tests: PATCH /internal/data/sessions/{id}/status with non-dict output_data.

Root cause (2026-10-20 production incident): Agent Runtime sends
``output_data`` as a plain string (or a list of structured parts) from the
string-output path, while the status-update schema only accepted
``dict | str | None`` — a LIST payload was rejected with 422 (``dict_type``),
marking live sessions as failed.

The schema now accepts ``dict | str | list | None`` everywhere in the string
path (status PATCH, result POST, session GET response).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import pytest

from app.db.models.agents import AgentJobStatus


def _make_session(status: AgentJobStatus = AgentJobStatus.running) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agent_type_id=uuid.uuid4(),
        triggered_by_user_id=None,
        status=status,
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        error_message=None,
        output_data=None,
        termination_category=None,
        stop_category=None,
        stop_reason=None,
        stop_details=None,
        conversation_history=None,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_status_patch_accepts_string_output_data():
    """PATCH status with a STRING output_data must return 200 and store the string."""
    from app.api.v1.internal.session_data import (
        SessionStatusUpdateRequest,
        update_session_status,
    )

    session = _make_session()
    db = AsyncMock()
    db.get = AsyncMock(return_value=session)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    body = SessionStatusUpdateRequest(
        status="completed",
        output_data="# Report\n\nAll done.",
    )
    with patch(
        "app.api.v1.internal.session_data._dispatch_result_to_comm_hub",
        AsyncMock(),
    ):
        response = await update_session_status(session_id=session.id, body=body, db=db)

    assert response.status == "completed"
    assert session.status == AgentJobStatus.completed
    assert session.output_data == "# Report\n\nAll done."
    assert isinstance(session.output_data, str)


@pytest.mark.asyncio
async def test_status_patch_accepts_list_output_data():
    """PATCH status with a LIST output_data (observed production payload shape)
    must return 200 and store the list instead of failing with 422 dict_type."""
    from app.api.v1.internal.session_data import (
        SessionStatusUpdateRequest,
        update_session_status,
    )

    session = _make_session()
    db = AsyncMock()
    db.get = AsyncMock(return_value=session)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    payload = [
        {"report": "# Supabase comparison report"},
        {"duration_ms": 1471, "sandboxed": True},
    ]
    body = SessionStatusUpdateRequest(status="completed", output_data=payload)
    with patch(
        "app.api.v1.internal.session_data._dispatch_result_to_comm_hub",
        AsyncMock(),
    ):
        response = await update_session_status(session_id=session.id, body=body, db=db)

    assert response.status == "completed"
    assert session.output_data == payload


def test_status_request_schema_rejects_nothing_from_runtime_shapes():
    """The Pydantic schema itself must accept dict, str, list and None."""
    from app.api.v1.internal.session_data import SessionStatusUpdateRequest

    for value in (
        {"result": "ok"},
        "plain string output",
        [{"part": 1}, {"part": 2}],
        None,
    ):
        req = SessionStatusUpdateRequest(status="completed", output_data=value)
        assert req.output_data == value


@pytest.mark.asyncio
async def test_result_endpoint_accepts_string_output_data():
    """POST /sessions/{id}/result with a STRING output_data stores the string
    and the ResultStore safety net extracts the string as content."""
    from app.api.v1.internal.session_data import (
        SessionResultRequest,
        post_session_result,
    )

    session = _make_session(status=AgentJobStatus.running)
    db = AsyncMock()
    db.get = AsyncMock(
        side_effect=lambda model, pk: session if model.__name__ == "AgentJob" else None
    )
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    body = SessionResultRequest(output_data="final markdown report")
    with patch(
        "app.api.v1.internal.session_data._dispatch_result_to_comm_hub",
        AsyncMock(),
    ), patch(
        "app.services.results.store.ResultStore.save", AsyncMock()
    ) as mock_save:
        response = await post_session_result(session_id=session.id, body=body, db=db)

    assert response.status == "completed"
    assert session.status == AgentJobStatus.completed
    assert session.output_data == "final markdown report"
    # The safety-net ResultRecord must carry the raw string as content
    assert mock_save.await_args.kwargs["payload"] == {
        "content": "final markdown report"
    }
    assert mock_save.await_args.kwargs["title"] is None
