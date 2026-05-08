"""API tests for Skills endpoints (enhance-mcp-hub-skills-sops change).

Tests cover:
- Create/update skill with instructions field
- GET /skills returns tool_ids array and instructions_with_tools
- GET /skills/{id} returns instructions, instructions_with_tools, and tool section assembly
- instructions_with_tools is read-only (ignored if sent in request body)
- GET /skills/{id}/roles returns role IDs
- PUT /skills/{id}/roles atomically replaces role membership
- PUT /skills/{id}/roles with empty list removes all memberships
- SkillSeeder creates save_result and send_notification default skills (idempotent)
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
    # instructions_with_tools must be None/str so Pydantic model_validate succeeds
    m.instructions_with_tools = None
    # Tool bindings — each binding has a proper tool mock with serializable attributes
    bindings = []
    for i, tid in enumerate(tool_ids or []):
        b = MagicMock()
        b.tool_id = tid
        b.order = i
        t = MagicMock()
        t.name = f"tool-{i}"
        t.description = None
        t.input_schema = None  # None → assemble_tool_section omits schema block (no JSON error)
        b.tool = t
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
async def test_list_skills_includes_instructions_with_tools_field():
    """GET /skills response includes instructions_with_tools field for each skill."""
    skill = _make_skill(instructions="Use this skill to summarise documents.")
    mock_db, db_dep = _db_with_skill(skill, scalar_all=[skill])

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/skills")

    assert resp.status_code == 200
    body = resp.json()
    # SkillRead has instructions_with_tools (not instructions — use GET /skills/{id} for that)
    assert "instructions_with_tools" in body[0]


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


# ── instructions_with_tools field ─────────────────────────────────────────────


def _make_binding_with_tool(
    tool_id=None,
    order: int = 0,
    name: str = "search",
    description: str | None = "Searches the web",
    input_schema: dict | None = None,
):
    """Create a properly-mocked SkillToolBinding with an attached McpTool mock."""
    b = MagicMock()
    b.tool_id = tool_id or uuid.uuid4()
    b.order = order
    t = MagicMock()
    t.name = name
    t.description = description
    t.input_schema = input_schema  # None → schema block omitted by assemble_tool_section
    b.tool = t
    return b


@pytest.mark.asyncio
async def test_get_skill_returns_instructions_with_tools_when_has_bindings():
    """GET /skills/{id} instructions_with_tools includes Tool Section when bindings exist."""
    skill_id = uuid.uuid4()
    binding = _make_binding_with_tool(name="internal-tools/search", description="Searches the web")
    skill = _make_skill(skill_id=skill_id, instructions="Use search for all queries.")
    skill.tool_bindings = [binding]

    mock_db, db_dep = _db_with_skill(skill)
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/skills/{skill_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert "instructions_with_tools" in body
    iwt = body["instructions_with_tools"]
    assert iwt is not None
    assert "## Tools" in iwt
    assert "internal-tools/search" in iwt
    assert "Use search for all queries." in iwt


@pytest.mark.asyncio
async def test_get_skill_instructions_with_tools_equals_instructions_when_no_bindings():
    """GET /skills/{id} instructions_with_tools equals instructions when no tool bindings."""
    skill_id = uuid.uuid4()
    skill = _make_skill(skill_id=skill_id, instructions="Static instructions only.")
    skill.tool_bindings = []

    mock_db, db_dep = _db_with_skill(skill)
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/skills/{skill_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["instructions_with_tools"] == "Static instructions only."
    assert "## Tools" not in (body["instructions_with_tools"] or "")


@pytest.mark.asyncio
async def test_get_skill_instructions_with_tools_is_null_when_no_bindings_and_no_instructions():
    """GET /skills/{id} instructions_with_tools is null when skill has no instructions and no tools."""
    skill_id = uuid.uuid4()
    skill = _make_skill(skill_id=skill_id, instructions=None)
    skill.tool_bindings = []

    mock_db, db_dep = _db_with_skill(skill)
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/skills/{skill_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["instructions_with_tools"] is None


@pytest.mark.asyncio
async def test_get_skill_tool_section_includes_tool_description_and_schema():
    """GET /skills/{id} tool section includes the tool's description and JSON schema."""
    skill_id = uuid.uuid4()
    schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    binding = _make_binding_with_tool(
        name="web/search",
        description="Full-text web search",
        input_schema=schema,
    )
    skill = _make_skill(skill_id=skill_id, instructions="Search the web.")
    skill.tool_bindings = [binding]

    mock_db, db_dep = _db_with_skill(skill)
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/skills/{skill_id}")

    assert resp.status_code == 200
    body = resp.json()
    iwt = body["instructions_with_tools"]
    assert "Full-text web search" in iwt
    assert "Input Schema" in iwt
    assert "query" in iwt


@pytest.mark.asyncio
async def test_post_skill_ignores_instructions_with_tools_in_request():
    """POST /skills body with instructions_with_tools is accepted; field is ignored (read-only)."""
    skill = _make_skill(instructions="My instructions.")
    mock_db, db_dep = _db_with_skill(skill)

    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    payload = {
        "name": "Test Skill",
        "instructions": "My instructions.",
        "instructions_with_tools": "INJECTED — should be ignored",
        "tool_ids": [],
    }

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/skills", json=payload)

    assert resp.status_code == 201
    body = resp.json()
    # instructions_with_tools is computed, not stored from request
    assert body.get("instructions_with_tools") != "INJECTED — should be ignored"


@pytest.mark.asyncio
async def test_list_skills_instructions_with_tools_present_for_each_skill():
    """GET /skills list response includes instructions_with_tools for every skill."""
    binding = _make_binding_with_tool(name="tool-a", description="Tool A")
    skill1 = _make_skill(instructions="Skill 1 instructions.")
    skill1.tool_bindings = [binding]
    skill2 = _make_skill(instructions=None)
    skill2.tool_bindings = []

    mock_db, db_dep = _db_with_skill(skill1, scalar_all=[skill1, skill2])
    app = create_app()
    app.dependency_overrides[get_db] = db_dep

    with _bypass_auth(), _mock_permission_allow():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/skills")

    assert resp.status_code == 200
    body = resp.json()
    for item in body:
        assert "instructions_with_tools" in item


# ── Default skills seeding ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_seeder_creates_save_result_skill():
    """SkillSeeder.run() creates save_result skill on a clean database."""
    from app.services.skill_seeder import SkillSeeder
    from app.db.models.skills import Skill

    no_skill_result = MagicMock()
    no_skill_result.scalar_one_or_none = MagicMock(return_value=None)
    no_tool_result = MagicMock()
    no_tool_result.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=[
            no_skill_result,  # save_result: skill existence check
            no_tool_result,   # save_result: tool lookup
            no_skill_result,  # send_notification: skill existence check
            no_tool_result,   # send_notification: tool lookup
        ]
    )
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.rollback = AsyncMock()

    seeder = SkillSeeder()
    summary = await seeder.run(mock_session)

    assert summary["save_result"] == "created"
    added_skills = [
        call.args[0]
        for call in mock_session.add.call_args_list
        if isinstance(call.args[0], Skill)
    ]
    assert any(s.name == "save_result" for s in added_skills)


@pytest.mark.asyncio
async def test_skill_seeder_creates_send_notification_skill():
    """SkillSeeder.run() creates send_notification skill on a clean database."""
    from app.services.skill_seeder import SkillSeeder
    from app.db.models.skills import Skill

    no_skill_result = MagicMock()
    no_skill_result.scalar_one_or_none = MagicMock(return_value=None)
    no_tool_result = MagicMock()
    no_tool_result.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=[
            no_skill_result,
            no_tool_result,
            no_skill_result,
            no_tool_result,
        ]
    )
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.rollback = AsyncMock()

    seeder = SkillSeeder()
    summary = await seeder.run(mock_session)

    assert summary["send_notification"] == "created"
    added_skills = [
        call.args[0]
        for call in mock_session.add.call_args_list
        if isinstance(call.args[0], Skill)
    ]
    assert any(s.name == "send_notification" for s in added_skills)


@pytest.mark.asyncio
async def test_skill_seeder_is_idempotent_when_skills_already_exist():
    """SkillSeeder.run() returns 'exists' for skills already in the database (no duplicates)."""
    from app.services.skill_seeder import SkillSeeder

    existing_save_result = MagicMock()
    existing_save_result.name = "save_result"
    existing_send_notification = MagicMock()
    existing_send_notification.name = "send_notification"

    exists_save = MagicMock()
    exists_save.scalar_one_or_none = MagicMock(return_value=existing_save_result)
    exists_notif = MagicMock()
    exists_notif.scalar_one_or_none = MagicMock(return_value=existing_send_notification)

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[exists_save, exists_notif])
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.rollback = AsyncMock()

    seeder = SkillSeeder()
    summary = await seeder.run(mock_session)

    assert summary["save_result"] == "exists"
    assert summary["send_notification"] == "exists"
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_skill_seeder_returns_both_default_skill_names():
    """SkillSeeder.run() summary contains entries for both save_result and send_notification."""
    from app.services.skill_seeder import SkillSeeder

    no_skill_result = MagicMock()
    no_skill_result.scalar_one_or_none = MagicMock(return_value=None)
    no_tool_result = MagicMock()
    no_tool_result.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=[no_skill_result, no_tool_result, no_skill_result, no_tool_result]
    )
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.rollback = AsyncMock()

    seeder = SkillSeeder()
    summary = await seeder.run(mock_session)

    assert "save_result" in summary
    assert "send_notification" in summary
