from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.main import create_app
from app.db.session import get_db
from app.middleware.auth import JWTAuthMiddleware


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


def _db_override():
    mock_db = AsyncMock()
    db_result = MagicMock()
    db_result.scalar_one_or_none = MagicMock(return_value=MagicMock(id="user-1"))
    mock_db.execute = AsyncMock(return_value=db_result)

    async def dep():
        yield mock_db

    return dep


@pytest.mark.asyncio
async def test_generate_sop_workflow_success():
    app = create_app()
    app.dependency_overrides[get_db] = _db_override()

    payload = {
        "description": "Handle onboarding",
        "steps": [
            {
                "order": 0,
                "step_type": "skill_invocation",
                "skill_id": None,
                "target_agent_type_id": None,
                "name": "Collect documents",
                "description": "Gather input docs",
            }
        ],
    }

    with (
        _bypass_auth(),
        _mock_permission_allow(),
        patch("app.api.v1.sops.get_workflow_generation_model_id", return_value="gpt-4o-mini"),
        patch("app.api.v1.sops.resolve_model_config_for_generation", new=AsyncMock(return_value=MagicMock())),
        patch("app.api.v1.sops.generate_workflow_text", new=AsyncMock(return_value="1. Collect docs\n2. Process")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/sops/workflow/generate", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["workflow"] == "1. Collect docs\n2. Process"
    assert body["model_id"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_generate_sop_workflow_missing_model_returns_422():
    app = create_app()
    app.dependency_overrides[get_db] = _db_override()

    payload = {
        "description": "Handle onboarding",
        "steps": [{"order": 0, "step_type": "skill_invocation"}],
    }

    with _bypass_auth(), _mock_permission_allow(), patch("app.api.v1.sops.get_workflow_generation_model_id", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/sops/workflow/generate", json=payload)

    assert resp.status_code == 422
    assert "not configured" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_preview_sop_workflow_returns_instruction_file():
    app = create_app()
    app.dependency_overrides[get_db] = _db_override()

    payload = {
        "workflow": "Do A then B",
        "description": "desc",
        "steps": [{"order": 0, "step_type": "skill_invocation", "name": "Step A"}],
    }

    with (
        _bypass_auth(),
        _mock_permission_allow(),
        patch("app.api.v1.sops.get_workflow_generation_model_id", return_value="gpt-4o-mini"),
        patch("app.api.v1.sops.resolve_model_config_for_generation", new=AsyncMock(return_value=MagicMock())),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/sops/workflow/preview", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["model_id"] == "gpt-4o-mini"
    assert "SOP Workflow Instruction File" in body["instruction_file"]


@pytest.mark.asyncio
async def test_generate_sop_workflow_missing_input_returns_422():
    app = create_app()
    app.dependency_overrides[get_db] = _db_override()

    payload = {
        "description": "   ",
        "steps": [],
    }

    with _bypass_auth(), _mock_permission_allow(), patch("app.api.v1.sops.get_workflow_generation_model_id", return_value="gpt-4o-mini"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/sops/workflow/generate", json=payload)

    assert resp.status_code == 422
