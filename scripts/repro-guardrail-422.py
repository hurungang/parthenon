"""Reproduce the 422 error on POST /api/v1/agents/guardrails/model-usage-limits.

Mimics the payload the frontend sends based on the current useAvailableModels
hook contract: model_id is the model *name* string (e.g. "gpt-4.1"), not a UUID.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Make sure we resolve `app.*` to the backend, not mcp-demo-app's app
BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("OIDC_PROVIDER_URL", "http://localhost:8080/realms/parthenon")

from httpx import ASGITransport, AsyncClient

from app.db.models.model_guardrail_configuration import (
    ModelGuardrailEnforcementPosture,
    ModelUsageUnit,
)
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


def _fake_config(model_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        model_id=uuid.uuid4(),
        model_name=model_name,
        enforcement_posture=ModelGuardrailEnforcementPosture.terminate,
        unit=ModelUsageUnit.k,
        usage_limit_hour=100,
        usage_limit_day=1000,
        usage_limit_week=None,
        usage_limit_month=None,
        is_active=True,
        details={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


async def main() -> int:
    mock_session = AsyncMock()
    app = _build_test_app(mock_session)

    # This is what the frontend would currently send per the existing hook
    payload = {
        "model_id": "gpt-4.1",   # model NAME, not a UUID
        "model_name": "gpt-4.1",
        "enforcement_posture": "terminate",
        "unit": "k",
        "usage_limit_hour": 100,
        "usage_limit_day": 1000,
        "is_active": True,
    }

    with _bypass_auth(), _mock_permission_allow():
        with patch(
            "app.api.v1.agents._model_usage_guardrail_service.create_configuration",
            new=AsyncMock(return_value=_fake_config(payload["model_name"])),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/agents/guardrails/model-usage-limits",
                    json=payload,
                )

    print(f"Status: {response.status_code}")
    print(f"Body: {response.text}")
    return 0 if response.status_code == 201 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
