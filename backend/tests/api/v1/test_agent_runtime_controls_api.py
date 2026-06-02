from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.models.agents import AgentInputType, AgentOutputType
from app.db.models.sop_recursion_validation_check import SopRecursionCheckContext
from app.db.models.sop_recursion_validation_finding import (
    SopRecursionFindingSeverity,
    SopRecursionFindingType,
)
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware
from app.services.control_center.recursion_validation_service import (
    RecursionFinding,
    RecursionValidationError,
)


def _bypass_auth_with_claims():
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "admin-sub", "roles": ["admin"]}
        request.state.claims = {"platform_user_id": str(uuid.uuid4())}
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


def _fake_agent_type(agent_type_id: uuid.UUID | None = None):
    return SimpleNamespace(
        id=agent_type_id or uuid.uuid4(),
        name="runtime-agent",
        description=None,
        identity_id=None,
        role_id=None,
        model_id="gpt-4o-mini",
        is_active=True,
        system_instruction="run",
        input_type=AgentInputType.typed,
        input_schema=None,
        output_type=AgentOutputType.auto,
        output_schema=None,
        primary_sop_id=None,
        guardrail_max_iterations=10,
        guardrail_max_delegation_depth=3,
        guardrail_max_delegated_steps=20,
        guardrail_execution_timeout_seconds=300,
        guardrail_token_budget=None,
        guardrail_token_enforcement_mode="observe",
        guardrail_token_fallback_mode="observe_and_log",
        guardrail_conversational_token_visibility_mode="enabled",
        guardrail_conversational_continuation_policy="allow",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        plan=None,
    )


def _fake_agent_job(session_id: uuid.UUID | None = None, agent_type_id: uuid.UUID | None = None):
    return SimpleNamespace(
        id=session_id or uuid.uuid4(),
        agent_type_id=agent_type_id or uuid.uuid4(),
        status="queued",
        created_at=datetime.now(timezone.utc),
        started_at=None,
        completed_at=None,
        output_data=None,
        error_message=None,
    )


def _build_test_app(mock_session: AsyncMock):
    permission_result = MagicMock()
    permission_result.scalar_one_or_none = MagicMock(
        return_value=SimpleNamespace(id=uuid.uuid4())
    )
    mock_session.execute = AsyncMock(return_value=permission_result)

    async def override_get_db():
        yield mock_session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    return app


def _recursion_error() -> RecursionValidationError:
    finding = RecursionFinding(
        finding_type=SopRecursionFindingType.cycle_detected,
        severity=SopRecursionFindingSeverity.error,
        involved_sop_id=None,
        involved_sop_step_id=None,
        path_signature="root -> child -> root",
        recommendation="Break delegation cycle",
    )
    return RecursionValidationError(
        summary="Cycle detected in delegation graph",
        findings=[finding],
    )


@pytest.mark.asyncio
async def test_create_agent_type_returns_422_on_recursion_validation_failure():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()

    app = _build_test_app(mock_session)

    payload = {
        "name": "runtime-agent",
        "model_id": "gpt-4o-mini",
        "input_type": "typed",
        "output_type": "auto",
    }

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents.get_recursion_validation_service",
            return_value=SimpleNamespace(validate_agent_type=AsyncMock(side_effect=_recursion_error())),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/api/v1/agents/types", json=payload)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "recursion_validation_failed"
    assert "Cycle detected" in detail["summary"]
    assert detail["findings"][0]["type"] == "cycle_detected"


@pytest.mark.asyncio
async def test_update_agent_type_returns_422_on_recursion_validation_failure():
    agent_type = _fake_agent_type()
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=agent_type)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()

    app = _build_test_app(mock_session)

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents.get_recursion_validation_service",
            return_value=SimpleNamespace(validate_agent_type=AsyncMock(side_effect=_recursion_error())),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.put(
                    f"/api/v1/agents/types/{agent_type.id}",
                    json={"system_instruction": "updated"},
                )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "recursion_validation_failed"
    assert detail["findings"][0]["recommendation"] == "Break delegation cycle"


@pytest.mark.asyncio
async def test_launch_session_returns_422_on_run_context_recursion_failure():
    agent_type = _fake_agent_type()
    job = _fake_agent_job(agent_type_id=agent_type.id)
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(side_effect=[agent_type, job])
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    app = _build_test_app(mock_session)

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents.get_recursion_validation_service",
            return_value=SimpleNamespace(validate_agent_type=AsyncMock(side_effect=_recursion_error())),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/agents/sessions",
                    json={"agent_type_id": str(agent_type.id), "input_data": {"prompt": "run"}},
                )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "recursion_validation_failed"
    assert detail["findings"][0]["type"] == "cycle_detected"


@pytest.mark.asyncio
async def test_terminate_agent_instance_returns_404_when_instance_missing():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    instance_id = uuid.uuid4()

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents.AgentInstanceManager.close",
            new=AsyncMock(side_effect=ValueError("Instance not found")),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.delete(f"/api/v1/agents/instances/{instance_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Instance not found"


@pytest.mark.asyncio
async def test_terminate_agent_instance_returns_204_when_manager_succeeds():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)
    instance_id = uuid.uuid4()

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents.AgentInstanceManager.close",
            new=AsyncMock(return_value=None),
        ) as close_mock:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.delete(f"/api/v1/agents/instances/{instance_id}")

    assert response.status_code == 204
    close_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_terminate_returns_404_when_request_not_found():
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)

    with _bypass_auth_with_claims(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._termination_orchestrator.get_termination_request",
            new=AsyncMock(return_value=None),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/api/v1/agents/runtime/terminate/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Termination request not found"


@pytest.mark.asyncio
async def test_runtime_purge_terminal_jobs_deletes_completed_and_failed():
    """POST /api/v1/agents/runtime/terminal-jobs/purge removes all
    completed/failed AgentJob rows to release database resources.

    The endpoint must work for the configured admin operator without
    requiring a body (older_than_hours is a query param, default 24h).
    """
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    app = _build_test_app(mock_session)

    # `_build_test_app` installs its own `mock_session.execute` for the
    # permission middleware's lookup query. Re-install ours AFTER the
    # build so it owns all subsequent calls: permission lookup first
    # (scalar_one_or_none), then the endpoint's count() and delete().
    call_index = {"n": 0}
    permission_result = SimpleNamespace(
        scalar_one_or_none=lambda: SimpleNamespace(id=uuid.uuid4())
    )
    count_result = SimpleNamespace(scalar_one=lambda: 7)
    delete_result = SimpleNamespace(rowcount=7)

    async def _route_execute(_stmt):
        idx = call_index["n"]
        call_index["n"] += 1
        if idx == 0:
            return permission_result
        if idx == 1:
            return count_result
        if idx == 2:
            return delete_result
        return MagicMock()

    mock_session.execute = AsyncMock(side_effect=_route_execute)

    with _bypass_auth_with_claims(), _mock_permission_allow():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/agents/runtime/terminal-jobs/purge"
                "?older_than_hours=0"
            )

    assert response.status_code == 200
    body = response.json()
    assert body["purged_count"] == 7
    assert body["remaining_terminal_count"] == 0
    assert "completed" in body["statuses"]
    assert "failed" in body["statuses"]
    assert "cutoff" in body
    mock_session.commit.assert_awaited_once()
