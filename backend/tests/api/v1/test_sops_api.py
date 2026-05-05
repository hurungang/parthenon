"""API tests for SOPs endpoints (enhance-mcp-hub-skills-sops change).

Tests cover:
- Create/update SOP with instructions field
- GET /sops/{id} returns instructions
- PUT /sops/{id}/steps uses target_agent_type_id (not delegate_agent_type_id)
- PUT /sops/{id}/steps uses step_config in request and response
- GET /sops/{id}/roles and PUT /sops/{id}/roles
- Default step_type is skill_invocation
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


def _make_sop(sop_id=None, instructions=None):
    sid = sop_id or uuid.uuid4()
    now = datetime.now(timezone.utc)
    m = MagicMock()
    m.id = sid
    m.name = "Incident Response SOP"
    m.description = "Handle incidents"
    m.instructions = instructions
    m.is_active = True
    m.created_at = now
    m.updated_at = now
    m.steps = []
    return m


def _make_sop_step(sop_id, order=1, step_type="skill_invocation",
                   target_agent_type_id=None, step_config=None, skill_id=None):
    now = datetime.now(timezone.utc)
    m = MagicMock()
    m.id = uuid.uuid4()
    m.sop_id = sop_id
    m.order = order
    m.step_type = step_type
    m.skill_id = skill_id
    m.target_agent_type_id = target_agent_type_id
    m.step_config = step_config
    m.name = f"Step {order}"
    m.description = None
    m.created_at = now
    return m


def _db_with_sop(sop, scalar_all=None, step_list=None):
    mock_db = AsyncMock()
    call_count = [0]

    def make_result(val):
        res = MagicMock()
        res.scalar_one_or_none = MagicMock(return_value=val)
        res.scalar_one = MagicMock(return_value=val)
        items = scalar_all or ([val] if val else [])
        res.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=items))
        )
        return res

    mock_db.execute = AsyncMock(return_value=make_result(sop))
    mock_db.get = AsyncMock(return_value=sop)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.delete = AsyncMock()

    async def override():
        yield mock_db

    return mock_db, override


# ── List SOPs ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_sops_returns_200():
    """GET /sops returns 200 with SOP list."""
    sop = _make_sop(instructions="Follow this SOP carefully.")
    mock_db, db_dep = _db_with_sop(sop, scalar_all=[sop])

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/sops")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)


# ── Get SOP ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_sop_returns_instructions():
    """GET /sops/{id} returns instructions field."""
    sop_id = uuid.uuid4()
    sop = _make_sop(sop_id=sop_id, instructions="Escalate to manager after 30 minutes.")
    mock_db, db_dep = _db_with_sop(sop, step_list=[])

    # Step list query returns empty
    step_result = MagicMock()
    step_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    mock_db.execute = AsyncMock(side_effect=[
        # PlatformUser lookup by require_permission — must come first
        MagicMock(
            scalar_one_or_none=MagicMock(return_value=MagicMock()),
            scalar_one=MagicMock(return_value=MagicMock()),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        ),
        MagicMock(
            scalar_one_or_none=MagicMock(return_value=sop),
            scalar_one=MagicMock(return_value=sop),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sop]))),
        ),
        step_result,
    ])

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/sops/{sop_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["instructions"] == "Escalate to manager after 30 minutes."


@pytest.mark.asyncio
async def test_get_sop_instructions_null_when_not_set():
    """GET /sops/{id} returns instructions as null when not provided."""
    sop_id = uuid.uuid4()
    sop = _make_sop(sop_id=sop_id, instructions=None)

    step_result = MagicMock()
    step_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=sop)
    mock_db.execute = AsyncMock(side_effect=[
        # PlatformUser lookup by require_permission — must come first
        MagicMock(
            scalar_one_or_none=MagicMock(return_value=MagicMock()),
            scalar_one=MagicMock(return_value=MagicMock()),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        ),
        MagicMock(
            scalar_one_or_none=MagicMock(return_value=sop),
            scalar_one=MagicMock(return_value=sop),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[sop]))),
        ),
        step_result,
    ])
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()

    async def db_dep():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/sops/{sop_id}")

    assert resp.status_code == 200
    assert resp.json()["instructions"] is None


# ── Create SOP ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_sop_with_instructions_returns_201():
    """POST /sops with instructions field returns 201 with instructions persisted."""
    sop = _make_sop(instructions="Follow step-by-step procedure.")
    mock_db, db_dep = _db_with_sop(sop)
    _now_create = datetime.now(timezone.utc)

    async def _populate_sop(s):
        s.id = uuid.uuid4()
        s.created_at = _now_create
        s.updated_at = _now_create
        s.is_active = True

    mock_db.refresh = AsyncMock(side_effect=_populate_sop)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {
        "name": "Incident Response SOP",
        "description": "Handle incidents",
        "instructions": "Follow step-by-step procedure.",
    }

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/sops", json=payload)

    assert resp.status_code == 201
    body = resp.json()
    assert body["instructions"] == "Follow step-by-step procedure."


@pytest.mark.asyncio
async def test_create_sop_without_instructions_accepted():
    """POST /sops without instructions field is accepted (nullable)."""
    sop = _make_sop(instructions=None)
    mock_db, db_dep = _db_with_sop(sop)
    _now_create2 = datetime.now(timezone.utc)

    async def _populate_sop_null(s):
        s.id = uuid.uuid4()
        s.created_at = _now_create2
        s.updated_at = _now_create2
        s.is_active = True

    mock_db.refresh = AsyncMock(side_effect=_populate_sop_null)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {"name": "SOP No Instructions", "description": "No instructions"}

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/sops", json=payload)

    assert resp.status_code == 201
    assert resp.json()["instructions"] is None


# ── Update SOP ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_sop_instructions_returns_updated_value():
    """PUT /sops/{id} updates instructions field."""
    sop_id = uuid.uuid4()
    sop = _make_sop(sop_id=sop_id, instructions="Updated instructions.")
    mock_db, db_dep = _db_with_sop(sop)
    mock_db.refresh = AsyncMock()

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {"instructions": "Updated instructions."}

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(f"/api/v1/sops/{sop_id}", json=payload)

    assert resp.status_code == 200
    assert resp.json()["instructions"] == "Updated instructions."


# ── SOP Steps with target_agent_type_id and step_config ─────────────────────────


@pytest.mark.asyncio
async def test_replace_sop_steps_with_target_agent_type_id():
    """PUT /sops/{id}/steps uses target_agent_type_id in request and response."""
    sop_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    sop = _make_sop(sop_id=sop_id)
    step = _make_sop_step(
        sop_id=sop_id,
        step_type="agent_delegation",
        target_agent_type_id=agent_type_id,
    )
    step.target_agent_type_id = agent_type_id

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=sop)
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    _now_step1 = datetime.now(timezone.utc)

    async def _populate_step1(s):
        s.id = uuid.uuid4()
        s.created_at = _now_step1

    mock_db.refresh = AsyncMock(side_effect=_populate_step1)

    # Capture added steps
    added_steps: list = []
    original_add = mock_db.add

    def capture_add(obj):
        added_steps.append(obj)

    mock_db.add = MagicMock(side_effect=capture_add)

    async def db_dep():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = [
        {
            "order": 1,
            "step_type": "agent_delegation",
            "target_agent_type_id": str(agent_type_id),
            "step_config": {"delegate_prompt": "Summarise this"},
        }
    ]

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(f"/api/v1/sops/{sop_id}/steps", json=payload)

    # Verify the step was created with target_agent_type_id (not delegate_agent_type_id)
    assert resp.status_code == 200
    sop_step_objects = [s for s in added_steps if hasattr(s, "target_agent_type_id")]
    assert len(sop_step_objects) == 1
    assert sop_step_objects[0].target_agent_type_id == agent_type_id
    assert sop_step_objects[0].step_config == {"delegate_prompt": "Summarise this"}


@pytest.mark.asyncio
async def test_replace_sop_steps_default_type_is_skill_invocation():
    """PUT /sops/{id}/steps: default step_type is skill_invocation when not provided."""
    sop_id = uuid.uuid4()
    sop = _make_sop(sop_id=sop_id)

    added_steps: list = []
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=sop)
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_db.add = MagicMock(side_effect=lambda obj: added_steps.append(obj))
    mock_db.flush = AsyncMock()
    _now_step2 = datetime.now(timezone.utc)

    async def _populate_step2(s):
        s.id = uuid.uuid4()
        s.created_at = _now_step2

    mock_db.refresh = AsyncMock(side_effect=_populate_step2)

    async def db_dep():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    # Send step without step_type — should default to skill_invocation
    payload = [{"order": 1}]

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(f"/api/v1/sops/{sop_id}/steps", json=payload)

    assert resp.status_code == 200
    sop_steps = [s for s in added_steps if hasattr(s, "step_type")]
    assert len(sop_steps) == 1
    from app.db.models.skills import SopStepType
    assert sop_steps[0].step_type == SopStepType.skill_invocation


@pytest.mark.asyncio
async def test_replace_sop_steps_with_step_config():
    """PUT /sops/{id}/steps passes step_config through correctly."""
    sop_id = uuid.uuid4()
    sop = _make_sop(sop_id=sop_id)

    added_steps: list = []
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=sop)
    mock_db.execute = AsyncMock(return_value=MagicMock())
    mock_db.add = MagicMock(side_effect=lambda obj: added_steps.append(obj))
    mock_db.flush = AsyncMock()
    _now_step_config = datetime.now(timezone.utc)

    async def _populate_step_config(s):
        s.id = uuid.uuid4()
        s.created_at = _now_step_config

    mock_db.refresh = AsyncMock(side_effect=_populate_step_config)

    async def db_dep():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    config = {"timeout_seconds": 60, "max_retries": 2}
    payload = [{"order": 1, "step_type": "skill_invocation", "step_config": config}]

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(f"/api/v1/sops/{sop_id}/steps", json=payload)

    assert resp.status_code == 200
    sop_steps = [s for s in added_steps if hasattr(s, "step_config")]
    assert len(sop_steps) == 1
    assert sop_steps[0].step_config == config


# ── SOP Roles ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_sop_roles_returns_list():
    """GET /sops/{id}/roles returns list of role UUIDs."""
    sop_id = uuid.uuid4()
    role_id = uuid.uuid4()
    sop = _make_sop(sop_id=sop_id)

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=sop)

    roles_result = MagicMock()
    roles_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[role_id]))
    )
    mock_db.execute = AsyncMock(return_value=roles_result)

    async def db_dep():
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/sops/{sop_id}/roles")

    assert resp.status_code == 200
    body = resp.json()
    assert str(role_id) in body


@pytest.mark.asyncio
async def test_put_sop_roles_replaces_membership():
    """PUT /sops/{id}/roles atomically replaces role membership."""
    sop_id = uuid.uuid4()
    new_role_id = uuid.uuid4()
    sop = _make_sop(sop_id=sop_id)

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=sop)
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
            resp = await client.put(f"/api/v1/sops/{sop_id}/roles", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert str(new_role_id) in body


@pytest.mark.asyncio
async def test_put_sop_roles_with_empty_list_removes_all():
    """PUT /sops/{id}/roles with role_ids=[] removes all memberships."""
    sop_id = uuid.uuid4()
    sop = _make_sop(sop_id=sop_id)

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=sop)
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
            resp = await client.put(f"/api/v1/sops/{sop_id}/roles", json=payload)

    assert resp.status_code == 200
    assert resp.json() == []
