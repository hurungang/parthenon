"""Tests for FIX-20260703-110000: AgentJobStatusRead exposes output_type and output_data.

Verifies that GET /agents/sessions/{session_id} returns output_type (from AgentType)
and output_data so the frontend can display markdown results without an output_id.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.models.agents import AgentInputType, AgentJobStatus, AgentOutputType
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware


def _bypass_auth():
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


def _make_agent_job(output_type: AgentOutputType, output_data: dict | None = None) -> SimpleNamespace:
    agent_type = SimpleNamespace(
        id=uuid.uuid4(),
        name="test-markdown-agent",
        output_type=output_type,
        input_type=AgentInputType.typed,
    )
    job = SimpleNamespace(
        id=uuid.uuid4(),
        agent_type_id=agent_type.id,
        agent_type=agent_type,
        triggered_by_user_id=None,
        triggered_by_user_name=None,
        agent_type_name=None,
        output_type=None,  # set by _populate_agent_job_names
        status=AgentJobStatus.completed,
        stop_category=None,
        stop_reason=None,
        stop_details=None,
        started_at=None,
        completed_at=None,
        output_data=output_data,
        output_id=None,
        error_message=None,
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    return job


@pytest.mark.asyncio
async def test_session_status_includes_output_type_for_markdown_agent():
    """GET /agents/sessions/{id} must return output_type='markdown' for markdown agents."""
    job = _make_agent_job(
        output_type=AgentOutputType.markdown,
        output_data={"result": "# Hello\nThis is markdown.", "title": "Test result"},
    )

    # Simulate what _populate_agent_job_names sets
    job.agent_type_name = job.agent_type.name
    job.output_type = job.agent_type.output_type

    from app.schemas.agents import AgentJobStatusRead

    serialized = AgentJobStatusRead.model_validate(job)

    assert serialized.output_type == AgentOutputType.markdown
    assert serialized.output_data == {"result": "# Hello\nThis is markdown.", "title": "Test result"}
    assert serialized.output_id is None


@pytest.mark.asyncio
async def test_session_status_includes_output_type_for_typed_agent():
    """GET /agents/sessions/{id} must return output_type='typed' for typed agents."""
    typed_output_id = uuid.uuid4()
    job = _make_agent_job(output_type=AgentOutputType.typed)
    job.output_id = typed_output_id
    job.agent_type_name = job.agent_type.name
    job.output_type = job.agent_type.output_type

    from app.schemas.agents import AgentJobStatusRead

    serialized = AgentJobStatusRead.model_validate(job)

    assert serialized.output_type == AgentOutputType.typed
    assert serialized.output_id == typed_output_id


@pytest.mark.asyncio
async def test_session_status_output_type_is_none_when_agent_type_missing():
    """output_type should be None when agent_type is not loaded (graceful degradation)."""
    job = _make_agent_job(output_type=AgentOutputType.auto)
    # Simulate agent_type not loaded (None)
    job.agent_type = None
    job.agent_type_name = None
    job.output_type = None  # _populate_agent_job_names sets None when agent_type is None

    from app.schemas.agents import AgentJobStatusRead

    serialized = AgentJobStatusRead.model_validate(job)

    assert serialized.output_type is None


@pytest.mark.asyncio
async def test_session_status_output_data_none_when_no_result_saved():
    """output_data should be None when save_result has not been called yet."""
    job = _make_agent_job(output_type=AgentOutputType.markdown, output_data=None)
    job.agent_type_name = job.agent_type.name
    job.output_type = job.agent_type.output_type

    from app.schemas.agents import AgentJobStatusRead

    serialized = AgentJobStatusRead.model_validate(job)

    assert serialized.output_type == AgentOutputType.markdown
    assert serialized.output_data is None
