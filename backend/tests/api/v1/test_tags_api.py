"""API tests for tag definitions endpoints."""
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
from app.api.deps import require_admin, require_permission
from app.middleware.auth import JWTAuthMiddleware

_REGISTRY_PATH = "app.api.v1.user_tags.TagRegistry"


def _bypass_auth(admin: bool = True):
    """Context manager patch that bypasses JWT middleware and injects identity."""
    from unittest.mock import patch, AsyncMock

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "user-sub", "roles": ["admin"] if admin else []}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _db_override():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one=MagicMock(return_value=0),
        scalar_one_or_none=MagicMock(return_value=None),
    ))

    async def override():
        yield mock_session

    return mock_session, override


def _admin_override():
    """Return a dependency override that marks the caller as admin."""
    def override():
        return {"sub": "admin-sub", "roles": ["admin"]}
    return override


def _nonadmin_override():
    """Return a dependency override that marks the caller as non-admin."""
    def override():
        raise __import__("fastapi").HTTPException(status_code=403, detail="Admin access required.")
    return override


def _make_tag_read(tag_id=None):
    d = {
        "id": str(tag_id or uuid.uuid4()),
        "key": "env",
        "scope": "Global",
        "resource_type": None,
        "description": "Environment tag",
        "allowed_values": ["dev", "prod"],
    }
    return d


@pytest.mark.asyncio
async def test_list_tag_definitions_returns_200_for_authenticated_user():
    """GET /tags/definitions returns 200 for any authenticated user (admin dependency not required)."""
    app = create_app()
    _, db_dep = _db_override()
    app.dependency_overrides[get_db] = db_dep

    with patch(_REGISTRY_PATH) as MockRegistry:
        mock_reg = MockRegistry.return_value
        mock_reg.list_definitions = AsyncMock(return_value=[])
        with _bypass_auth(admin=False):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/v1/user-tags/definitions")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_create_tag_definition_as_admin_returns_201():
    """POST /tags/definitions as admin returns 201 with the created tag."""
    from datetime import datetime as dt
    from app.schemas.tags import TagDefinitionRead, TagScope

    app = create_app()
    _, db_dep = _db_override()
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission("permissions", "manage")] = _admin_override()

    now = dt.utcnow()
    tag_id = uuid.uuid4()
    mock_result = TagDefinitionRead(
        id=tag_id,
        key="env",
        scope=TagScope.global_scope,
        resource_type=None,
        description="env tag",
        created_at=now,
        updated_at=now,
        allowed_values=[],
    )

    with patch(_REGISTRY_PATH) as MockRegistry, _bypass_auth():
        mock_reg = MockRegistry.return_value
        mock_reg.create_definition = AsyncMock(return_value=mock_result)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/user-tags/definitions",
                json={"key": "env", "scope": "global", "allowed_values": []},
            )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_create_tag_definition_as_non_admin_returns_403():
    """POST /tags/definitions as non-admin returns 403."""
    app = create_app()
    _, db_dep = _db_override()
    app.dependency_overrides[get_db] = db_dep
    # No require_admin override — rely on middleware setting non-admin identity

    with _bypass_auth(admin=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/user-tags/definitions",
                json={"key": "env", "scope": "Global", "allowed_values": []},
            )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_tag_definition_as_admin_returns_204():
    """DELETE /tags/definitions/{id} as admin returns 204."""
    app = create_app()
    _, db_dep = _db_override()
    tag_id = uuid.uuid4()
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission("permissions", "manage")] = _admin_override()

    with patch(_REGISTRY_PATH) as MockRegistry, _bypass_auth():
        mock_reg = MockRegistry.return_value
        mock_reg.delete_definition = AsyncMock(return_value=None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(f"/api/v1/user-tags/definitions/{tag_id}")

    assert response.status_code == 204
