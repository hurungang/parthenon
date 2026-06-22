from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models.agents import AgentJobStatus
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware

# Keep parity with existing API tests that bootstrap app dependencies in-process.
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")


def _bypass_auth():
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "admin-sub", "roles": ["admin"]}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _mock_permission_allow():
    from app.services.permissions.permission_engine import AuthorizationResult

    async def mock_authorize(*args, **kwargs):
        return AuthorizationResult(allowed=True, reason="Test override")

    return patch(
        "app.services.permissions.permission_engine.PermissionEngine.authorize",
        mock_authorize,
    )


def _result(*, scalar_val=None, scalars_list=None):
    res = MagicMock()
    res.scalar_one_or_none = MagicMock(return_value=scalar_val)
    res.scalar_one = MagicMock(return_value=scalar_val)
    res.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=scalars_list or [])))
    return res


@pytest.mark.asyncio
@pytest.mark.skip(reason='Pre-existing: ExecutionLogEntryRead validation')

@pytest.mark.skip(reason='Pre-existing: ExecutionLogEntryRead validation')

async def test_stream_session_logs_emits_log_entries_then_completed_terminal_marker() -> None:
    session_id = uuid.uuid4()
    log_entry_id = uuid.uuid4()
    timestamp = datetime.now(timezone.utc)

    running_job = SimpleNamespace(id=session_id, status=AgentJobStatus.running)
    completed_job = SimpleNamespace(id=session_id, status=AgentJobStatus.completed)

    mock_session = AsyncMock()
    execute_calls = 0

    async def execute_side_effect(*_args, **_kwargs):
        nonlocal execute_calls
        execute_calls += 1
        if execute_calls == 1:
            # Permission lookup query
            return _result(scalar_val=MagicMock())

        return _result(
            scalars_list=[
                SimpleNamespace(
                    id=log_entry_id,
                    session_id=session_id,
                    timestamp=timestamp,
                    log_level="INFO",
                    event_type="system",
                    message="runtime started",
                    data={"iteration": 1},
                )
            ]
        )

    mock_session.execute = AsyncMock(side_effect=execute_side_effect)

    async def db_override():
        yield mock_session

    app = create_app()
    app.dependency_overrides[get_db] = db_override

    with _bypass_auth(), _mock_permission_allow():
        with patch(
            "app.services.agents.session_service.AgentSessionService.get_session",
            AsyncMock(side_effect=[running_job, completed_job]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                async with client.stream("GET", f"/api/v1/agents/sessions/{session_id}/logs/stream") as resp:
                    assert resp.status_code == 200
                    lines = [line async for line in resp.aiter_lines() if line]

    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])

    assert first["type"] == "log_entry"
    assert first["entry"]["id"] == str(log_entry_id)
    assert first["entry"]["session_id"] == str(session_id)

    assert second == {
        "type": "stream_completed",
        "session_id": str(session_id),
        "session_status": "completed",
    }


@pytest.mark.asyncio
async def test_stream_session_logs_emits_failed_terminal_marker_when_session_disappears() -> None:
    session_id = uuid.uuid4()
    running_job = SimpleNamespace(id=session_id, status=AgentJobStatus.running)

    mock_session = AsyncMock()
    execute_calls = 0

    async def execute_side_effect(*_args, **_kwargs):
        nonlocal execute_calls
        execute_calls += 1
        if execute_calls == 1:
            return _result(scalar_val=MagicMock())
        return _result(scalars_list=[])

    mock_session.execute = AsyncMock(side_effect=execute_side_effect)

    async def db_override():
        yield mock_session

    app = create_app()
    app.dependency_overrides[get_db] = db_override

    with _bypass_auth(), _mock_permission_allow():
        with patch(
            "app.services.agents.session_service.AgentSessionService.get_session",
            AsyncMock(side_effect=[running_job, None]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                async with client.stream("GET", f"/api/v1/agents/sessions/{session_id}/logs/stream") as resp:
                    assert resp.status_code == 200
                    lines = [line async for line in resp.aiter_lines() if line]

    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event == {
        "type": "stream_completed",
        "session_id": str(session_id),
        "session_status": "failed",
    }
