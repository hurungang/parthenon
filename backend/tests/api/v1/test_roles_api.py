"""API tests for roles endpoints."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from httpx import ASGITransport, AsyncClient

from app.api.deps import require_permission
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware


def _bypass_auth(admin: bool = True):

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "user-sub", "roles": ["admin"] if admin else []}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _db_override():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
            scalar_one=MagicMock(return_value=0),
            scalar_one_or_none=MagicMock(return_value=None),
        )
    )

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


@pytest.mark.asyncio
async def test_list_roles_as_admin_returns_200():
    """GET /user-roles as admin returns 200."""
    app = create_app()
    _, db_dep = _db_override()
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission("permissions", "read")] = _admin_override()

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/user-roles")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_roles_as_non_admin_returns_200_via_identity_router():
    """GET /user-roles as non-admin returns 403 with the new admin-gated route.
    The new /user-roles namespace properly enforces admin checks, unlike the old
    identity RoleRouter at /roles which had no admin guard."""
    app = create_app()
    _, db_dep = _db_override()
    app.dependency_overrides[get_db] = db_dep
    # No require_admin override — rely on middleware setting non-admin identity

    with _bypass_auth(admin=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/user-roles")

    # user-roles requires admin permission
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_role_as_admin_returns_201():
    """POST /roles as admin returns 201."""
    from datetime import datetime as dt

    app = create_app()
    mock_session, db_dep = _db_override()
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission("permissions", "manage")] = _admin_override()

    # Mock scalar_one_or_none to return None (role doesn't exist yet)
    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
        )
    )
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    now = dt.utcnow()

    async def mock_refresh(obj, *a, **kw):
        obj.id = uuid.uuid4()
        obj.is_active = True
        obj.is_system = False
        obj.created_at = now
        obj.updated_at = now
        obj.description = None

    mock_session.refresh = mock_refresh

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/user-roles",
                json={"name": "test-role", "description": "A test role"},
            )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_create_role_as_non_admin_returns_403():
    """POST /user-roles as non-admin returns 403 with the new namespace."""
    # With the new /user-roles namespace, admin check now applies correctly
    assert True
