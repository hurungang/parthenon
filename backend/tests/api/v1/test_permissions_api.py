"""API tests for groups, platform-users, and access-requests endpoints."""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.db.session import get_db
from app.api.deps import require_admin
from app.middleware.auth import JWTAuthMiddleware
from app.services.permissions.permission_engine import AuthorizationResult


def _bypass_auth(admin: bool = True):
    from unittest.mock import patch

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "user-sub", "roles": ["admin"] if admin else []}
        request.state.platform_user_id = uuid.uuid4()
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _db_override():
    mock_session = AsyncMock()
    
    # Mock PlatformUser lookup
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.sub = "user-sub"
    
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_user)
    mock_result.scalars = MagicMock(return_value=MagicMock(
        all=MagicMock(return_value=[]),
        first=MagicMock(return_value=None)
    ))
    mock_result.scalar_one = MagicMock(return_value=0)
    
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    async def override():
        yield mock_session

    return mock_session, override


def _admin_override():
    def override():
        return {"sub": "admin-sub", "roles": ["admin"]}
    return override


def _nonadmin_override():
    def override():
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin access required.")
    return override


def _mock_permission_engine_allow():
    """Mock PermissionEngine.authorize() to always return allowed."""
    async def mock_authorize(*args, **kwargs):
        return AuthorizationResult(allowed=True, reason="Test override")
    
    return patch("app.services.permissions.permission_engine.PermissionEngine.authorize", mock_authorize)


# ──────────────────────────────────────────────────────────────────────────────
# Groups
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_groups_returns_200():
    """GET /user-groups as admin returns 200 with empty list."""
    app = create_app()
    _, db_dep = _db_override()
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_admin] = _admin_override()

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/user-groups")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_create_group_as_non_admin_returns_403():
    """POST /user-groups as non-admin returns 403."""
    app = create_app()
    _, db_dep = _db_override()
    app.dependency_overrides[get_db] = db_dep
    # No require_admin override — rely on middleware setting non-admin identity

    with _bypass_auth(admin=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/user-groups",
                json={"name": "test-group"},
            )

    assert response.status_code == 403


# ──────────────────────────────────────────────────────────────────────────────
# Platform Users
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_platform_users_as_admin_returns_200():
    """GET /platform-users as admin returns 200."""
    app = create_app()
    _, db_dep = _db_override()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_engine_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/platform-users")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_platform_users_as_non_admin_returns_403():
    """GET /platform-users as non-admin returns 403."""
    app = create_app()
    _, db_dep = _db_override()
    app.dependency_overrides[get_db] = db_dep
    # No require_admin override — rely on middleware setting non-admin identity

    with _bypass_auth(admin=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/platform-users")

    assert response.status_code == 403


# ──────────────────────────────────────────────────────────────────────────────
# Access Requests
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_my_access_requests_returns_200():
    """GET /user-access-requests/my returns 200 for authenticated user."""
    from app.middleware.auth import JWTAuthMiddleware

    app = create_app()
    _, db_dep = _db_override()
    app.dependency_overrides[get_db] = db_dep

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "user-sub", "roles": []}
        request.state.platform_user_id = uuid.uuid4()
        return await call_next(request)

    from unittest.mock import patch
    with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/user-access-requests/my")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_reject_access_request_without_reason_returns_422():
    """PATCH /user-access-requests/{id}/reject without rejection_reason returns 422."""
    from app.middleware.auth import JWTAuthMiddleware

    app = create_app()
    _, db_dep = _db_override()
    app.dependency_overrides[get_db] = db_dep

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "user-sub", "roles": ["admin"]}
        request.state.platform_user_id = uuid.uuid4()
        return await call_next(request)

    from unittest.mock import patch
    with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                f"/api/v1/user-access-requests/{uuid.uuid4()}/reject",
                json={},  # missing rejection_reason
            )

    assert response.status_code == 422
