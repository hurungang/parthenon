"""API tests for Agent session log endpoint.

Reproduces the 500 Internal Server Error on:
    GET /api/v1/agents/sessions/{session_id}/logs

Root cause:
    The route decorator uses a string forward reference in its response_model:

        @AgentJobRouter.get("/{session_id}/logs", response_model=list["ExecutionLogEntryRead"])

    `ExecutionLogEntryRead` is NOT imported at the top of app/api/v1/agents.py —
    it is only imported inside the function body.  FastAPI/Pydantic v2 therefore
    cannot resolve the forward reference when it builds the TypeAdapter for the
    response_model, and raises:

        PydanticUserError: `TypeAdapter[list['ExecutionLogEntryRead']]` is not
        fully defined; you should define `ExecutionLogEntryRead` and all
        referenced types, then call `.rebuild()` on the instance.

Expected behaviour:
    GET /api/v1/agents/sessions/{session_id}/logs returns HTTP 200 with a JSON
    array of execution-log objects (empty list when no logs exist).

This test currently FAILS with the Pydantic forward-reference error described
above.  Once the bug is fixed (by importing `ExecutionLogEntryRead` at module
scope in agents.py and removing the quotes from the response_model), this test
should pass.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Env defaults must be set before app imports
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.db.session import get_db
from app.middleware.auth import JWTAuthMiddleware


# ── Auth / DB helpers (same pattern as test_model_configs_api.py) ──────────────


def _bypass_auth():
    """Patch JWTAuthMiddleware so every request carries a valid admin identity."""

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "admin-sub", "roles": ["admin"]}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _mock_permission_allow():
    """Patch PermissionEngine.authorize to unconditionally allow all actions."""
    from app.services.permissions.permission_engine import AuthorizationResult

    async def mock_authorize(*args, **kwargs):
        return AuthorizationResult(allowed=True, reason="Test override")

    return patch(
        "app.services.permissions.permission_engine.PermissionEngine.authorize",
        mock_authorize,
    )


def _db_with_empty_log_query(mock_job):
    """Build a mock AsyncSession that:

    * resolves permission-check queries (scalar_one_or_none → MagicMock)
    * returns *mock_job* for session.get() calls
    * returns an empty list for the ExecutionLogEntry scalars query
    """
    mock_session = AsyncMock()

    # Tracks how many execute() calls have been made so we can distinguish the
    # permission-check execute from the log-entry execute.
    call_count = 0

    def _result(scalar_val=None, scalars_list=None):
        res = MagicMock()
        res.scalar_one_or_none = MagicMock(return_value=scalar_val)
        res.scalar_one = MagicMock(return_value=scalar_val)
        res.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=scalars_list or []))
        )
        return res

    async def execute_side_effect(query, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: permission-check user-lookup
            return _result(scalar_val=MagicMock())
        # Subsequent calls: ExecutionLogEntry query → empty list
        return _result(scalars_list=[])

    mock_session.execute = AsyncMock(side_effect=execute_side_effect)
    mock_session.get = AsyncMock(return_value=mock_job)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.delete = AsyncMock()

    async def override():
        yield mock_session

    return mock_session, override


# ── Test ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_logs_returns_200_with_empty_list():
    """GET /api/v1/agents/sessions/{session_id}/logs should return 200 + [].

    BUG REPRODUCED: This test currently fails with:
        PydanticUserError: `TypeAdapter[typing.Annotated[list['ExecutionLogEntryRead'],
        FieldInfo(annotation=NoneType, required=True)]]` is not fully defined …

    The fix is to import ExecutionLogEntryRead at module scope in agents.py and
    change the response_model annotation from list["ExecutionLogEntryRead"] to
    list[ExecutionLogEntryRead] (without the quotes).
    """
    session_id = uuid.uuid4()

    # Build a minimal mock AgentJob that satisfies the ownership check in the
    # endpoint (triggered_by_user_id=None skips the ownership comparison).
    mock_job = MagicMock()
    mock_job.id = session_id
    mock_job.triggered_by_user_id = None

    _, db_override = _db_with_empty_log_query(mock_job)

    app = create_app()
    app.dependency_overrides[get_db] = db_override

    with _bypass_auth(), _mock_permission_allow():
        with patch(
            "app.services.agents.session_service.AgentSessionService.get_session",
            AsyncMock(return_value=mock_job),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/v1/agents/sessions/{session_id}/logs")

    # This assertion currently fails: the endpoint returns 500 instead of 200
    # because FastAPI cannot resolve the 'ExecutionLogEntryRead' forward reference
    # in the response_model at request time.
    assert resp.status_code == 200, (
        f"Expected 200 but got {resp.status_code}.\n"
        f"Response body: {resp.text}\n\n"
        "This is the known bug: response_model=list['ExecutionLogEntryRead'] uses a "
        "forward reference that Pydantic cannot resolve because ExecutionLogEntryRead "
        "is not imported at module scope in app/api/v1/agents.py."
    )
    data = resp.json()
    assert isinstance(data, list), f"Expected a list, got {type(data)}: {data}"
    assert data == [], f"Expected empty list for session with no logs, got: {data}"


# ── Validation: none-input agent type requires a role with SOPs ─────────────────


@pytest.mark.asyncio
async def test_create_no_input_agent_without_sop_fails():
    """POST /api/v1/agents/types with input_type=none and no primary_sop_id must return 400."""
    role_id = uuid.uuid4()

    mock_session = AsyncMock()

    def _result(scalar_val=None, scalars_list=None):
        res = MagicMock()
        res.scalar_one_or_none = MagicMock(return_value=scalar_val)
        res.scalar_one = MagicMock(return_value=scalar_val)
        res.scalars = MagicMock(
            return_value=MagicMock(
                all=MagicMock(return_value=scalars_list or []),
                first=MagicMock(return_value=scalars_list[0] if scalars_list else None),
            )
        )
        res.first = MagicMock(return_value=scalars_list[0] if scalars_list else None)
        return res

    async def execute_side_effect(query, *args, **kwargs):
        # Permission check: user lookup — allow
        return _result(scalar_val=MagicMock())

    mock_session.execute = AsyncMock(side_effect=execute_side_effect)
    mock_session.get = AsyncMock(return_value=None)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()

    async def db_override():
        yield mock_session

    app = create_app()
    app.dependency_overrides[get_db] = db_override

    payload = {
        "name": "AutoSopAgent",
        "model_id": "gpt-4o-mini",
        "input_type": "none",
        "output_type": "auto",
        "role_id": str(role_id),
        # primary_sop_id intentionally omitted
    }

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/v1/agents/types", json=payload)

    assert resp.status_code == 400, (
        f"Expected 400 when creating none-input agent without primary_sop_id, "
        f"got {resp.status_code}.\nBody: {resp.text}"
    )
    detail = resp.json().get("detail", "")
    assert "primary_sop_id" in detail, (
        f"Expected 400 error message to mention 'primary_sop_id'. Got: {detail!r}"
    )
