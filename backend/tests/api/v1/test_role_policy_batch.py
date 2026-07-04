"""API tests for the batch policy save endpoint: PUT /user-roles/{role_id}/policies/batch."""
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
from app.core.resource_types import RT_SYSTEM_PERMISSIONS


def _bypass_auth(admin: bool = True):
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "user-sub", "roles": ["admin"] if admin else []}
        request.state.platform_user_id = uuid.uuid4()
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _make_role(role_id: str = None, is_system: bool = False):
    """Create a minimal mock Role for db.get to return."""
    if role_id is None:
        role_id = str(uuid.uuid4())
    role = MagicMock()
    role.id = role_id
    role.is_system = is_system
    return role


def _setup_batch_mock_db(role_id: str, existing_stmts: list | None = None):
    """Set up a mock DB session tailored for the batch save endpoint flow."""
    mock_session = AsyncMock()

    # Store policies that will be "persisted"
    saved_policies = []

    # db.get(Role, role_id) — returns the role
    mock_role = _make_role(role_id)

    async def mock_get(model, ident):
        if model.__name__ == "Role":
            return mock_role
        return None

    mock_session.get = AsyncMock(side_effect=mock_get)

    # First execute: SELECT PolicyStatement WHERE role_id — returns existing statements
    existing_result = MagicMock()
    existing_result.scalars = MagicMock(return_value=MagicMock(
        all=MagicMock(return_value=existing_stmts or [])
    ))
    mock_session.execute = AsyncMock(return_value=existing_result)

    mock_session.add = MagicMock()
    mock_session.delete = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    async def override():
        yield mock_session

    return mock_session, override


def _admin_override():
    def override():
        return {"sub": "admin-sub", "roles": ["admin"]}
    return override


def _deny_override():
    def override():
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Permission denied.")
    return override


# ── Batch Save Endpoint Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_save_replaces_all_policies():
    """PUT /user-roles/{id}/policies/batch replaces all existing policies with the new set."""
    role_id = str(uuid.uuid4())
    app = create_app()
    mock_session, db_dep = _setup_batch_mock_db(role_id)
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission(RT_SYSTEM_PERMISSIONS, "manage")] = _admin_override()

    # Setup: return 2 existing policy stmts that will be deleted
    existing_stmt_1 = MagicMock()
    existing_stmt_2 = MagicMock()

    # The endpoint does two execute calls: delete existing, then re-query at end
    # We need the second execute to return the new policies
    def execute(*args, **kwargs):
        # First call: delete existing policies query
        # Second call: final re-query after insert
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        return result

    mock_session.execute = AsyncMock(side_effect=execute)

    # Override the delete to use the mock
    mock_session.delete = AsyncMock()

    batch_payload = {
        "policies": [
            {
                "module": "agent::roles",
                "effect": "allow",
                "actions": [{"action": "read"}],
                "resources": [],
                "tag_conditions": [],
            },
            {
                "module": "system::permissions",
                "effect": "allow",
                "actions": [{"action": "manage"}],
                "resources": [],
                "tag_conditions": [],
            },
        ]
    }

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/user-roles/{role_id}/policies/batch",
                json=batch_payload,
            )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_batch_save_empty_policies_clears_all():
    """PUT /user-roles/{id}/policies/batch with empty policies array clears all policies."""
    role_id = str(uuid.uuid4())
    app = create_app()
    mock_session, db_dep = _setup_batch_mock_db(role_id)
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission(RT_SYSTEM_PERMISSIONS, "manage")] = _admin_override()

    # Mock execute to return empty list after clear
    def execute(*args, **kwargs):
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        return result

    mock_session.execute = AsyncMock(side_effect=execute)

    batch_payload = {"policies": []}

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/user-roles/{role_id}/policies/batch",
                json=batch_payload,
            )

    assert response.status_code == 200
    data = response.json()
    assert data == []


@pytest.mark.asyncio
async def test_batch_save_invalid_module_rejected():
    """PUT /user-roles/{id}/policies/batch rejects invalid resource type module."""
    role_id = str(uuid.uuid4())
    app = create_app()
    mock_session, db_dep = _setup_batch_mock_db(role_id)
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission(RT_SYSTEM_PERMISSIONS, "manage")] = _admin_override()

    batch_payload = {
        "policies": [
            {
                "module": "agent::nonexistent_submodule",
                "effect": "allow",
                "actions": [{"action": "read"}],
                "resources": [],
                "tag_conditions": [],
            }
        ]
    }

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/user-roles/{role_id}/policies/batch",
                json=batch_payload,
            )

    # 422 due to schema validation (model_validator in BatchPolicySaveRequest)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_batch_save_invalid_module_flat_value_rejected():
    """PUT /user-roles/{id}/policies/batch rejects flat (non-namespaced) module values."""
    role_id = str(uuid.uuid4())
    app = create_app()
    mock_session, db_dep = _setup_batch_mock_db(role_id)
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission(RT_SYSTEM_PERMISSIONS, "manage")] = _admin_override()

    batch_payload = {
        "policies": [
            {
                "module": "agent",  # flat value, not namespaced
                "effect": "allow",
                "actions": [{"action": "read"}],
                "resources": [],
                "tag_conditions": [],
            }
        ]
    }

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/user-roles/{role_id}/policies/batch",
                json=batch_payload,
            )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_batch_save_missing_required_fields_rejected():
    """PUT /user-roles/{id}/policies/batch rejects policies with missing required fields."""
    role_id = str(uuid.uuid4())
    app = create_app()
    mock_session, db_dep = _setup_batch_mock_db(role_id)
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission(RT_SYSTEM_PERMISSIONS, "manage")] = _admin_override()

    # Missing 'module' field
    batch_payload = {
        "policies": [
            {
                "effect": "allow",
                "actions": [{"action": "read"}],
                "resources": [],
                "tag_conditions": [],
            }
        ]
    }

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/user-roles/{role_id}/policies/batch",
                json=batch_payload,
            )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_batch_save_empty_actions_rejected():
    """PUT /user-roles/{id}/policies/batch rejects policies with empty actions array."""
    role_id = str(uuid.uuid4())
    app = create_app()
    mock_session, db_dep = _setup_batch_mock_db(role_id)
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission(RT_SYSTEM_PERMISSIONS, "manage")] = _admin_override()

    batch_payload = {
        "policies": [
            {
                "module": "agent::roles",
                "effect": "allow",
                "actions": [],  # empty — must have at least one
                "resources": [],
                "tag_conditions": [],
            }
        ]
    }

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/user-roles/{role_id}/policies/batch",
                json=batch_payload,
            )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_batch_save_authentication_required():
    """PUT /user-roles/{id}/policies/batch returns 401 without valid auth."""
    role_id = str(uuid.uuid4())
    app = create_app()
    mock_session, db_dep = _setup_batch_mock_db(role_id)
    app.dependency_overrides[get_db] = db_dep
    # Do NOT override require_permission — no auth means the endpoint should fail

    batch_payload = {
        "policies": [
            {
                "module": "agent::roles",
                "effect": "allow",
                "actions": [{"action": "read"}],
                "resources": [],
                "tag_conditions": [],
            }
        ]
    }

    # Use non-admin bypass to test auth rejection
    with _bypass_auth(admin=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/user-roles/{role_id}/policies/batch",
                json=batch_payload,
            )

    # Without the require_permission override, the dependency will fail
    # because the middleware sets no roles="admin"
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_batch_save_role_not_found_returns_404():
    """PUT /user-roles/{id}/policies/batch returns 404 when role does not exist."""
    role_id = str(uuid.uuid4())
    app = create_app()
    mock_session, db_dep = _setup_batch_mock_db(role_id)
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission(RT_SYSTEM_PERMISSIONS, "manage")] = _admin_override()

    # Override get to return None (role not found)
    mock_session.get = AsyncMock(return_value=None)

    batch_payload = {
        "policies": [
            {
                "module": "agent::roles",
                "effect": "allow",
                "actions": [{"action": "read"}],
                "resources": [],
                "tag_conditions": [],
            }
        ]
    }

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/user-roles/{role_id}/policies/batch",
                json=batch_payload,
            )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_batch_save_wildcard_module_accepted():
    """PUT /user-roles/{id}/policies/batch accepts valid wildcard module values."""
    role_id = str(uuid.uuid4())
    app = create_app()
    mock_session, db_dep = _setup_batch_mock_db(role_id)
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission(RT_SYSTEM_PERMISSIONS, "manage")] = _admin_override()

    def execute(*args, **kwargs):
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        return result

    mock_session.execute = AsyncMock(side_effect=execute)

    # Test each wildcard pattern
    wildcards = ["agent::*", "integration::*", "system::*", "*::*"]

    for wildcard in wildcards:
        batch_payload = {
            "policies": [
                {
                    "module": wildcard,
                    "effect": "allow",
                    "actions": [{"action": "read"}],
                    "resources": [],
                    "tag_conditions": [],
                }
            ]
        }

        with _bypass_auth():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.put(
                    f"/api/v1/user-roles/{role_id}/policies/batch",
                    json=batch_payload,
                )

        assert response.status_code == 200, f"Wildcard {wildcard} should be accepted, got {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_batch_save_multiple_policies_atomic():
    """PUT /user-roles/{id}/policies/batch saves multiple policies in a single batch."""
    role_id = str(uuid.uuid4())
    app = create_app()
    mock_session, db_dep = _setup_batch_mock_db(role_id)
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission(RT_SYSTEM_PERMISSIONS, "manage")] = _admin_override()

    def execute(*args, **kwargs):
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        return result

    mock_session.execute = AsyncMock(side_effect=execute)

    batch_payload = {
        "policies": [
            {
                "module": "agent::roles",
                "effect": "allow",
                "actions": [{"action": "read"}, {"action": "manage"}],
                "resources": [],
                "tag_conditions": [],
            },
            {
                "module": "integration::mcp_hub",
                "effect": "allow",
                "actions": [{"action": "execute"}],
                "resources": [{"resource_type": "integration::mcp_hub", "resource_id": "mcp-1"}],
                "tag_conditions": [],
            },
            {
                "module": "system::observability",
                "effect": "deny",
                "actions": [{"action": "read"}],
                "resources": [],
                "tag_conditions": [{"tag_key": "env", "tag_value": "prod"}],
            },
        ]
    }

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/user-roles/{role_id}/policies/batch",
                json=batch_payload,
            )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_batch_save_malformed_json_rejected():
    """PUT /user-roles/{id}/policies/batch rejects request with invalid policy structure."""
    role_id = str(uuid.uuid4())
    app = create_app()
    mock_session, db_dep = _setup_batch_mock_db(role_id)
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission(RT_SYSTEM_PERMISSIONS, "manage")] = _admin_override()

    # Pass 'policies' but with an item that has neither module nor actions (missing required)
    # Since module is constrained to min_length=1, an empty string should fail Pydantic validation
    malformed_payload = {
        "policies": [
            {
                "module": "",  # empty module — fails min_length=1 constraint
                "effect": "allow",
                "actions": [{"action": "read"}],
                "resources": [],
                "tag_conditions": [],
            }
        ]
    }

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/user-roles/{role_id}/policies/batch",
                json=malformed_payload,
            )

    # Empty module '""' should fail min_length=1 validation on the PolicyStatementCreate.module field
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_batch_save_permission_denied():
    """PUT /user-roles/{id}/policies/batch returns 403 when user lacks manage permission."""
    role_id = str(uuid.uuid4())
    app = create_app()
    mock_session, db_dep = _setup_batch_mock_db(role_id)
    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[require_permission(RT_SYSTEM_PERMISSIONS, "manage")] = _deny_override()

    batch_payload = {
        "policies": [
            {
                "module": "agent::roles",
                "effect": "allow",
                "actions": [{"action": "read"}],
                "resources": [],
                "tag_conditions": [],
            }
        ]
    }

    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/user-roles/{role_id}/policies/batch",
                json=batch_payload,
            )

    assert response.status_code == 403
