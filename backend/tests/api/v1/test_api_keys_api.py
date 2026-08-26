"""Integration tests for API Key Admin CRUD endpoints.

Tests the complete CRUD lifecycle against a test database with mocked auth.
"""
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
from app.api.deps import require_permission
from app.middleware.auth import JWTAuthMiddleware


def _bypass_auth(admin: bool = True):
    """Context manager that bypasses JWT middleware and injects identity."""
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "admin-sub", "roles": ["admin"] if admin else []}
        request.state.platform_user_id = uuid.uuid4()
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _make_admin_override():
    """Dependency override that returns claims for require_permission."""

    def override():
        return {"sub": "admin-sub", "roles": ["admin"]}

    return override


@pytest.mark.asyncio
async def test_list_api_keys_empty():
    """GET /api-keys returns empty list when no keys exist."""
    app = create_app()

    # Override require_permission for the API keys module
    perm_dep = require_permission("agent::api_keys", "manage")
    app.dependency_overrides[perm_dep] = _make_admin_override()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/api-keys")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_api_keys_requires_auth():
    """GET /api-keys returns 401 without auth."""
    app = create_app()

    # Override require_permission so it's not the cause of rejection
    perm_dep = require_permission("agent::api_keys", "manage")
    app.dependency_overrides[perm_dep] = _make_admin_override()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    # No _bypass_auth — JWT middleware should reject
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/api-keys")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_api_key_success():
    """POST /api-keys creates a key and returns it with clear-text value."""
    app = create_app()
    identity_id = uuid.uuid4()
    role_id = uuid.uuid4()

    perm_dep = require_permission("agent::api_keys", "manage")
    app.dependency_overrides[perm_dep] = _make_admin_override()

    mock_session = AsyncMock()

    # Mock identity lookup (active)
    mock_identity = MagicMock()
    mock_identity.status = "active"
    mock_identity.name = "Agent X"

    # Mock role lookup
    mock_role = MagicMock()
    mock_role.name = "Developer"

    # The api_key record needs proper id and created_at for ApiKeyCreateResponse
    from datetime import datetime, timezone
    new_key_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # Mock AgentApiKey for db.add - we need to capture what gets added
    # and set the id + created_at before refresh
    added_key = [None]

    def _mock_add(obj):
        added_key[0] = obj

    async def _mock_refresh(obj):
        # After commit+refresh, set the id and created_at on the object
        obj.id = new_key_id
        obj.created_at = now

    async def mock_get(model, id_val):
        name = getattr(model, '__name__', '')
        if name == "AgentIdentity":
            return mock_identity
        elif name == "AgentRole":
            return mock_role
        return None

    mock_session.get = mock_get

    # Mock the sequence of execute calls
    call_responses = []

    # Call: check AgentRoleIdentity assignment
    mock_role_check = MagicMock()
    mock_role_check.scalar_one_or_none.return_value = MagicMock()
    call_responses.append(mock_role_check)

    # Call: check duplicate name
    mock_dup = MagicMock()
    mock_dup.scalar_one_or_none.return_value = None
    call_responses.append(mock_dup)

    mock_session.execute = AsyncMock(side_effect=call_responses)
    mock_session.add = _mock_add
    mock_session.commit = AsyncMock()
    mock_session.refresh = _mock_refresh

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/api-keys", json={
                "name": "E2E Test Key",
                "agent_identity_id": str(identity_id),
                "agent_role_id": str(role_id),
            })

    assert response.status_code == 201
    data = response.json()
    assert "api_key" in data
    assert data["api_key"].startswith("phn_sk_")
    assert data["name"] == "E2E Test Key"
    assert data["id"] == str(new_key_id)


@pytest.mark.asyncio
async def test_create_api_key_duplicate_name():
    """POST /api-keys returns 409 when a key with the same name already exists."""
    app = create_app()
    identity_id = uuid.uuid4()
    role_id = uuid.uuid4()

    perm_dep = require_permission("agent::api_keys", "manage")
    app.dependency_overrides[perm_dep] = _make_admin_override()

    mock_session = AsyncMock()

    mock_identity = MagicMock()
    mock_identity.status = "active"
    mock_identity.name = "Agent X"
    mock_session.get = AsyncMock(return_value=mock_identity)

    mock_role_check = MagicMock()
    mock_role_check.scalar_one_or_none.return_value = MagicMock()
    mock_dup = MagicMock()
    mock_dup.scalar_one_or_none.return_value = MagicMock()  # Found a duplicate!

    mock_session.execute = AsyncMock(side_effect=[mock_role_check, mock_dup])

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/api-keys", json={
                "name": "Duplicate Key",
                "agent_identity_id": str(identity_id),
                "agent_role_id": str(role_id),
            })

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_api_key_identity_not_active():
    """POST /api-keys returns 404 when identity is not active."""
    app = create_app()
    identity_id = uuid.uuid4()
    role_id = uuid.uuid4()

    perm_dep = require_permission("agent::api_keys", "manage")
    app.dependency_overrides[perm_dep] = _make_admin_override()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)  # identity not found

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/api-keys", json={
                "name": "Bad Key",
                "agent_identity_id": str(identity_id),
                "agent_role_id": str(role_id),
            })

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_api_key_validation_errors():
    """POST /api-keys returns 422 for invalid request bodies."""
    app = create_app()

    perm_dep = require_permission("agent::api_keys", "manage")
    app.dependency_overrides[perm_dep] = _make_admin_override()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Missing name
            response = await client.post("/api/v1/api-keys", json={
                "agent_identity_id": str(uuid.uuid4()),
                "agent_role_id": str(uuid.uuid4()),
            })
    assert response.status_code == 422

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Name too short (empty)
            response = await client.post("/api/v1/api-keys", json={
                "name": "",
                "agent_identity_id": str(uuid.uuid4()),
                "agent_role_id": str(uuid.uuid4()),
            })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_revoke_api_key_success():
    """POST /api-keys/{id}/revoke revokes an active key."""
    app = create_app()

    perm_dep = require_permission("agent::api_keys", "manage")
    app.dependency_overrides[perm_dep] = _make_admin_override()

    key_id = uuid.uuid4()
    mock_session = AsyncMock()

    mock_key = MagicMock()
    mock_key.id = key_id
    mock_key.name = "Test Key"
    mock_key_status = MagicMock()
    mock_key_status.value = "active"
    mock_key.status = mock_key_status

    mock_session.get = AsyncMock(return_value=mock_key)
    mock_session.commit = AsyncMock()

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/api-keys/{key_id}/revoke")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "revoked"


@pytest.mark.asyncio
async def test_revoke_api_key_not_found():
    """POST /api-keys/{id}/revoke returns 404 for non-existent key."""
    app = create_app()

    perm_dep = require_permission("agent::api_keys", "manage")
    app.dependency_overrides[perm_dep] = _make_admin_override()

    key_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/api-keys/{key_id}/revoke")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_revoke_api_key_idempotent():
    """POST /api-keys/{id}/revoke succeeds on already-revoked key."""
    app = create_app()

    perm_dep = require_permission("agent::api_keys", "manage")
    app.dependency_overrides[perm_dep] = _make_admin_override()

    key_id = uuid.uuid4()
    mock_session = AsyncMock()

    from app.db.models.agent_api_key import ApiKeyStatus

    mock_key = MagicMock()
    mock_key.id = key_id
    mock_key.name = "Test Key"
    mock_key.status = ApiKeyStatus.revoked  # Use real enum value

    mock_session.get = AsyncMock(return_value=mock_key)

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/api-keys/{key_id}/revoke")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "revoked"
    assert "already revoked" in data["message"]


@pytest.mark.asyncio
async def test_list_identities_with_roles():
    """GET /api-keys/identities-with-roles returns identities and their roles."""
    app = create_app()

    perm_dep = require_permission("agent::api_keys", "manage")
    app.dependency_overrides[perm_dep] = _make_admin_override()

    mock_session = AsyncMock()

    mock_identity = MagicMock()
    mock_identity.id = uuid.uuid4()
    mock_identity.name = "Agent X"
    mock_identity.role_assignments = []

    mock_identities_result = MagicMock()
    mock_identities_result.scalars.return_value.unique.return_value.all.return_value = [mock_identity]

    mock_roles_result = MagicMock()
    mock_roles_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[mock_identities_result, mock_roles_result])

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/api-keys/identities-with-roles")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["identity_name"] == "Agent X"


@pytest.mark.asyncio
async def test_list_api_keys_with_status_filter():
    """GET /api-keys?status=active returns only active keys."""
    app = create_app()

    perm_dep = require_permission("agent::api_keys", "manage")
    app.dependency_overrides[perm_dep] = _make_admin_override()

    from app.db.models.agent_api_key import AgentApiKey, ApiKeyStatus

    mock_session = AsyncMock()

    mock_key = MagicMock()
    mock_key.id = uuid.uuid4()
    mock_key.name = "Active Key"
    mock_key.key_prefix = "phn_sk_"
    mock_key.agent_identity_id = uuid.uuid4()
    mock_key.agent_role_id = uuid.uuid4()
    mock_key.status = ApiKeyStatus.active
    mock_key.created_at = "2026-01-01T00:00:00Z"
    mock_key.last_used_at = None
    mock_key.identity = MagicMock()
    mock_key.identity.name = "Agent X"
    mock_key.role = MagicMock()
    mock_key.role.name = "Developer"

    mock_result = MagicMock()
    mock_result.scalars.return_value.unique.return_value.all.return_value = [mock_key]
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/api-keys?status=active")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Active Key"
    assert data[0]["status"] == "active"


@pytest.mark.asyncio
async def test_list_api_keys_invalid_status():
    """GET /api-keys?status=invalid returns 400."""
    app = create_app()

    perm_dep = require_permission("agent::api_keys", "manage")
    app.dependency_overrides[perm_dep] = _make_admin_override()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/api-keys?status=deleted")

    assert response.status_code == 400
