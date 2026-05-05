"""API tests for Skills endpoints (enhance-mcp-hub-skills-sops change).

Tests cover:
- Create/update skill with instructions field
- GET /skills returns tool_ids array
- GET /skills/{id} returns instructions with persisted value
- GET /skills/{id}/roles returns role IDs
- PUT /skills/{id}/roles atomically replaces role membership
- PUT /skills/{id}/roles with empty list removes all memberships
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from httpx import ASGITransport, AsyncClient

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


def _make_skill(skill_id=None, instructions=None, tool_ids=None):
    sid = skill_id or uuid.uuid4()
    now = datetime.now(timezone.utc)
    m = MagicMock()
    m.id = sid
    m.name = "Summarise Text"
    m.description = "Summarises long documents"
    m.instructions = instructions
    m.is_active = True
    m.created_at = now
    m.updated_at = now
    # Tool bindings
    bindings = []
    for i, tid in enumerate(tool_ids or []):
        b = MagicMock()
        b.tool_id = tid
        b.order = i
        bindings.append(b)
    m.tool_bindings = bindings
    return m


def _db_with_skill(skill, scalar_all=None):
    mock_db = AsyncMock()

    def make_result(val):
        res = MagicMock()
        res.scalar_one_or_none = MagicMock(return_value=val)
        res.scalar_one = MagicMock(return_value=val)
        res.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=scalar_all or [val] if val else []))
        )
        return res

    mock_db.execute = AsyncMock(return_value=make_result(skill))
    mock_db.get = AsyncMock(return_value=skill)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.delete = AsyncMock()

    async def override():
        yield mock_db

    return mock_db, override


# ── List Skills ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_skills_returns_tool_ids_array():
    """GET /skills returns each skill with tool_ids array."""
    tool_id = uuid.uuid4()
    skill = _make_skill(tool_ids=[tool_id])
    mock_db, db_dep = _db_with_skill(skill, scalar_all=[skill])

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/skills")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert "tool_ids" in body[0]
    assert str(tool_id) in body[0]["tool_ids"]


@pytest.mark.asyncio
async def test_list_skills_includes_instructions_field():
    """GET /skills response includes instructions field."""
    skill = _make_skill(instructions="Use this skill to summarise documents.")
    mock_db, db_dep = _db_with_skill(skill, scalar_all=[skill])

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/skills")

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["instructions"] == "Use this skill to summarise documents."


# ── Get Skill ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_skill_returns_instructions():
    """GET /skills/{id} response includes instructions with persisted value."""
    skill_id = uuid.uuid4()
    skill = _make_skill(skill_id=skill_id, instructions="Agent should call this tool first.")
    mock_db, db_dep = _db_with_skill(skill)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/skills/{skill_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["instructions"] == "Agent should call this tool first."


@pytest.mark.asyncio
async def test_get_skill_instructions_null_when_not_set():
    """GET /skills/{id} instructions is null when not provided."""
    skill_id = uuid.uuid4()
    skill = _make_skill(skill_id=skill_id, instructions=None)
    mock_db, db_dep = _db_with_skill(skill)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/skills/{skill_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["instructions"] is None


# ── Create Skill ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_skill_with_instructions_returns_201():
    """POST /skills with instructions field persists and returns it."""
    skill = _make_skill(instructions="Always prefix the query with the system prompt.")
    mock_db, db_dep = _db_with_skill(skill)
    mock_db.get = AsyncMock(return_value=MagicMock())  # tool exists

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {
        "name": "Summarise Text",
        "description": "Summarises documents",
        "instructions": "Always prefix the query with the system prompt.",
        "tool_ids": [],
    }

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/skills", json=payload)

    assert resp.status_code == 201
    body = resp.json()
    assert body["instructions"] == "Always prefix the query with the system prompt."


@pytest.mark.asyncio
async def test_create_skill_without_instructions_accepted():
    """POST /skills without instructions is accepted (nullable field)."""
    skill = _make_skill(instructions=None)
    mock_db, db_dep = _db_with_skill(skill)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {"name": "No Instruction Skill", "tool_ids": []}

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/skills", json=payload)

    assert resp.status_code == 201
    body = resp.json()
    assert body["instructions"] is None


# ── Update Skill ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_skill_instructions_returns_updated_value():
    """PUT /skills/{id} updates instructions and returns new value."""
    skill_id = uuid.uuid4()
    skill = _make_skill(skill_id=skill_id, instructions="Updated instructions here.")
    mock_db, db_dep = _db_with_skill(skill)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {"instructions": "Updated instructions here."}

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(f"/api/v1/skills/{skill_id}", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["instructions"] == "Updated instructions here."


# ── Skill Roles ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_skill_roles_returns_list_of_role_ids():
    """GET /skills/{id}/roles returns list of role UUIDs."""
    skill_id = uuid.uuid4()
    role_id_1 = uuid.uuid4()
    role_id_2 = uuid.uuid4()

    skill = _make_skill(skill_id=skill_id)
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=skill)

    roles_result = MagicMock()
    roles_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[role_id_1, role_id_2]))
    )
    mock_db.execute = AsyncMock(return_value=roles_result)

    async def db_dep():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/skills/{skill_id}/roles")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert str(role_id_1) in body
    assert str(role_id_2) in body


@pytest.mark.asyncio
async def test_put_skill_roles_replaces_membership():
    """PUT /skills/{id}/roles atomically replaces role membership."""
    skill_id = uuid.uuid4()
    new_role_id = uuid.uuid4()

    skill = _make_skill(skill_id=skill_id)
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=skill)
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    async def db_dep():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {"role_ids": [str(new_role_id)]}

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(f"/api/v1/skills/{skill_id}/roles", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert str(new_role_id) in body


@pytest.mark.asyncio
async def test_put_skill_roles_with_empty_list_removes_all():
    """PUT /skills/{id}/roles with role_ids=[] removes all role memberships."""
    skill_id = uuid.uuid4()
    skill = _make_skill(skill_id=skill_id)
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=skill)
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    async def db_dep():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {"role_ids": []}

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(f"/api/v1/skills/{skill_id}/roles", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body == []
