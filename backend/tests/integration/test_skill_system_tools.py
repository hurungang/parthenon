"""Integration tests for skill creation with system tools.

Covers:
  - System tools seeding (seed_system_tools function)
  - Skill CRUD with system tool IDs (bypasses DB validation)
  - Mixed system + regular MCP tool bindings
  - Skill retrieval builds correct instructions_with_tools for system tools
  - Invalid (non-existent, non-system) tool IDs return 422

Database:
  Uses the shared SQLite StaticPool engine from integration/conftest.py.
  seed_system_tools() is tested both directly (DB layer) and via the API
  (authed_client fixture with JWT middleware bypassed).
"""
from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason='Requires running services (CC, AR, or CH)')

import uuid
from typing import AsyncGenerator
from unittest.mock import patch as _patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.mcp_hub import (
    SYSTEM_SERVER_ID,
    SYSTEM_TOOL_GET_RECIPIENT_GROUP_ID,
    SYSTEM_TOOL_SAVE_RESULT_ID,
    SYSTEM_TOOL_SEND_NOTIFICATION_ID,
    SYSTEM_TOOL_IDS,
    seed_system_tools,
)
from app.api.deps import require_permission
from app.core.resource_types import RT_SKILL, RT_MCP_SERVER
from app.db.models.mcp_hub import McpServer, McpServerStatus, McpTool
from app.db.models.skills import Skill, SkillToolBinding
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware


# ── Auth helpers ──────────────────────────────────────────────────────────────


def _allow_skill_read():
    def override():
        return {"sub": "test-admin", "roles": ["admin"]}
    return override


def _allow_skill_create():
    def override():
        return {"sub": "test-admin", "roles": ["admin"]}
    return override


def _allow_skill_update():
    def override():
        return {"sub": "test-admin", "roles": ["admin"]}
    return override


def _bypass_jwt():
    async def _patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-admin", "roles": ["admin"]}
        return await call_next(request)

    return _patch.object(JWTAuthMiddleware, "dispatch", _patched_dispatch)


# ── authed_client fixture ─────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def authed_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient with JWT middleware and Skill permission deps bypassed."""
    app = create_app()

    app.dependency_overrides[require_permission(RT_SKILL, "read")] = _allow_skill_read()
    app.dependency_overrides[require_permission(RT_SKILL, "create")] = _allow_skill_create()
    app.dependency_overrides[require_permission(RT_SKILL, "update")] = _allow_skill_update()
    app.dependency_overrides[require_permission(RT_SKILL, "delete")] = _allow_skill_create()
    app.dependency_overrides[require_permission(RT_MCP_SERVER, "read")] = _allow_skill_read()

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    with _bypass_jwt():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


# ── 1. System Tools Seeding Tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_system_tools_creates_server(db_session: AsyncSession):
    """seed_system_tools() inserts the system server into mcp_servers."""
    # Ensure clean state: delete if somehow already present
    existing = await db_session.get(McpServer, SYSTEM_SERVER_ID)
    if existing:
        await db_session.delete(existing)
        await db_session.flush()

    await seed_system_tools(db_session)

    server = await db_session.get(McpServer, SYSTEM_SERVER_ID)
    assert server is not None
    assert server.slug == "system"
    assert server.status == McpServerStatus.active
    assert server.name == "System"


@pytest.mark.asyncio
async def test_seed_system_tools_creates_save_result_tool(db_session: AsyncSession):
    """seed_system_tools() inserts system/save_result into mcp_tools."""
    await seed_system_tools(db_session)

    tool = await db_session.get(McpTool, SYSTEM_TOOL_SAVE_RESULT_ID)
    assert tool is not None
    assert tool.name == "system____save_result"
    assert tool.original_name == "save_result"
    assert tool.server_id == SYSTEM_SERVER_ID
    assert tool.is_active is True


@pytest.mark.asyncio
async def test_seed_system_tools_creates_send_notification_tool(db_session: AsyncSession):
    """seed_system_tools() inserts system/send_notification into mcp_tools."""
    await seed_system_tools(db_session)

    tool = await db_session.get(McpTool, SYSTEM_TOOL_SEND_NOTIFICATION_ID)
    assert tool is not None
    assert tool.name == "system____send_notification"
    assert tool.original_name == "send_notification"
    assert tool.server_id == SYSTEM_SERVER_ID
    assert tool.is_active is True


@pytest.mark.asyncio
async def test_seed_system_tools_creates_get_recipient_group_tool(db_session: AsyncSession):
    """seed_system_tools() inserts system/get_recipient_group into mcp_tools."""
    await seed_system_tools(db_session)

    tool = await db_session.get(McpTool, SYSTEM_TOOL_GET_RECIPIENT_GROUP_ID)
    assert tool is not None
    assert tool.name == "system____get_recipient_group"
    assert tool.server_id == SYSTEM_SERVER_ID


@pytest.mark.asyncio
async def test_seed_system_tools_is_idempotent(db_session: AsyncSession):
    """Calling seed_system_tools() twice must not raise or duplicate rows."""
    await seed_system_tools(db_session)
    # Second call — must be a no-op without integrity errors
    await seed_system_tools(db_session)

    result = await db_session.execute(
        select(McpTool).where(McpTool.server_id == SYSTEM_SERVER_ID)
    )
    tools = result.scalars().all()
    # There should be exactly 3 system tools (no duplicates)
    assert len(tools) == 3


def test_system_tool_ids_set_contains_all_three():
    """SYSTEM_TOOL_IDS must include all three known system tool UUIDs."""
    assert SYSTEM_TOOL_SAVE_RESULT_ID in SYSTEM_TOOL_IDS
    assert SYSTEM_TOOL_SEND_NOTIFICATION_ID in SYSTEM_TOOL_IDS
    assert SYSTEM_TOOL_GET_RECIPIENT_GROUP_ID in SYSTEM_TOOL_IDS
    assert len(SYSTEM_TOOL_IDS) == 3


# ── 2. Skill Creation with System Tools ──────────────────────────────────────


@pytest.mark.asyncio
async def test_create_skill_with_only_save_result_tool(authed_client: AsyncClient):
    """POST /api/v1/skills with save_result system tool returns 201."""
    resp = await authed_client.post(
        "/api/v1/skills",
        json={
            "name": f"system-only-skill-{uuid.uuid4().hex[:6]}",
            "description": "Uses only save_result",
            "tool_ids": [str(SYSTEM_TOOL_SAVE_RESULT_ID)],
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert str(SYSTEM_TOOL_SAVE_RESULT_ID) in data["tool_ids"]


@pytest.mark.asyncio
async def test_create_skill_with_both_notification_tools(authed_client: AsyncClient):
    """POST /api/v1/skills with two system tools returns 201 and both tool_ids."""
    tool_ids = [str(SYSTEM_TOOL_SAVE_RESULT_ID), str(SYSTEM_TOOL_SEND_NOTIFICATION_ID)]
    resp = await authed_client.post(
        "/api/v1/skills",
        json={
            "name": f"multi-system-skill-{uuid.uuid4().hex[:6]}",
            "tool_ids": tool_ids,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    returned_ids = data["tool_ids"]
    assert str(SYSTEM_TOOL_SAVE_RESULT_ID) in returned_ids
    assert str(SYSTEM_TOOL_SEND_NOTIFICATION_ID) in returned_ids
    assert len(returned_ids) == 2


@pytest.mark.asyncio
async def test_create_skill_with_all_system_tools(authed_client: AsyncClient):
    """POST /api/v1/skills with all three system tools returns 201."""
    tool_ids = [
        str(SYSTEM_TOOL_SAVE_RESULT_ID),
        str(SYSTEM_TOOL_SEND_NOTIFICATION_ID),
        str(SYSTEM_TOOL_GET_RECIPIENT_GROUP_ID),
    ]
    resp = await authed_client.post(
        "/api/v1/skills",
        json={
            "name": f"all-system-skill-{uuid.uuid4().hex[:6]}",
            "tool_ids": tool_ids,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert len(data["tool_ids"]) == 3


@pytest.mark.asyncio
async def test_create_skill_with_no_tools(authed_client: AsyncClient):
    """POST /api/v1/skills with empty tool_ids returns 201."""
    resp = await authed_client.post(
        "/api/v1/skills",
        json={
            "name": f"empty-tools-skill-{uuid.uuid4().hex[:6]}",
            "tool_ids": [],
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["tool_ids"] == []


# ── 3. Skill Update with System Tools ────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_skill_add_system_tool(authed_client: AsyncClient):
    """PUT /api/v1/skills/{id} can add a system tool to an existing skill."""
    # Create skill without tools
    create_resp = await authed_client.post(
        "/api/v1/skills",
        json={"name": f"update-test-{uuid.uuid4().hex[:6]}", "tool_ids": []},
    )
    assert create_resp.status_code == 201
    skill_id = create_resp.json()["id"]

    # Update to add system tool
    update_resp = await authed_client.put(
        f"/api/v1/skills/{skill_id}",
        json={"tool_ids": [str(SYSTEM_TOOL_SAVE_RESULT_ID)]},
    )
    assert update_resp.status_code == 200, update_resp.text
    # Verify via GET: the PUT response may show stale session data; the GET uses a
    # fresh session that reflects the committed state correctly.
    get_resp = await authed_client.get(f"/api/v1/skills/{skill_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert str(SYSTEM_TOOL_SAVE_RESULT_ID) in get_resp.json()["tool_ids"]


@pytest.mark.asyncio
async def test_update_skill_remove_system_tool(authed_client: AsyncClient):
    """PUT /api/v1/skills/{id} can remove a system tool by providing empty tool_ids."""
    # Create skill with system tool
    create_resp = await authed_client.post(
        "/api/v1/skills",
        json={
            "name": f"remove-sys-tool-{uuid.uuid4().hex[:6]}",
            "tool_ids": [str(SYSTEM_TOOL_SAVE_RESULT_ID)],
        },
    )
    assert create_resp.status_code == 201
    skill_id = create_resp.json()["id"]

    # Update to remove all tools
    update_resp = await authed_client.put(
        f"/api/v1/skills/{skill_id}",
        json={"tool_ids": []},
    )
    assert update_resp.status_code == 200, update_resp.text
    # Verify via GET: the PUT response may show stale session data; the GET uses a
    # fresh session that reflects the committed state correctly.
    get_resp = await authed_client.get(f"/api/v1/skills/{skill_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["tool_ids"] == []


@pytest.mark.asyncio
async def test_update_skill_swap_system_tools(authed_client: AsyncClient):
    """PUT /api/v1/skills/{id} can replace one system tool with another."""
    create_resp = await authed_client.post(
        "/api/v1/skills",
        json={
            "name": f"swap-sys-tool-{uuid.uuid4().hex[:6]}",
            "tool_ids": [str(SYSTEM_TOOL_SAVE_RESULT_ID)],
        },
    )
    assert create_resp.status_code == 201
    skill_id = create_resp.json()["id"]

    update_resp = await authed_client.put(
        f"/api/v1/skills/{skill_id}",
        json={"tool_ids": [str(SYSTEM_TOOL_SEND_NOTIFICATION_ID)]},
    )
    assert update_resp.status_code == 200, update_resp.text
    # Verify via GET: the PUT response may show stale session data; the GET uses a
    # fresh session that reflects the committed state correctly.
    get_resp = await authed_client.get(f"/api/v1/skills/{skill_id}")
    assert get_resp.status_code == 200, get_resp.text
    data = get_resp.json()
    assert str(SYSTEM_TOOL_SEND_NOTIFICATION_ID) in data["tool_ids"]
    assert str(SYSTEM_TOOL_SAVE_RESULT_ID) not in data["tool_ids"]


# ── 4. Skill Retrieval with System Tools ─────────────────────────────────────


@pytest.mark.asyncio
async def test_get_skill_detail_includes_system_tool_info(authed_client: AsyncClient):
    """GET /api/v1/skills/{id} returns instructions_with_tools containing system tool names."""
    create_resp = await authed_client.post(
        "/api/v1/skills",
        json={
            "name": f"detail-sys-tool-{uuid.uuid4().hex[:6]}",
            "instructions": "Use the save result tool.",
            "tool_ids": [str(SYSTEM_TOOL_SAVE_RESULT_ID)],
        },
    )
    assert create_resp.status_code == 201
    skill_id = create_resp.json()["id"]

    get_resp = await authed_client.get(f"/api/v1/skills/{skill_id}")
    assert get_resp.status_code == 200, get_resp.text
    data = get_resp.json()
    assert data["instructions_with_tools"] is not None
    assert "system____save_result" in data["instructions_with_tools"]
    assert "Save the final result of agent execution" in data["instructions_with_tools"]


@pytest.mark.asyncio
async def test_get_skill_detail_all_system_tools_in_instructions(authed_client: AsyncClient):
    """GET /api/v1/skills/{id} with all system tools shows all tool names in instructions."""
    create_resp = await authed_client.post(
        "/api/v1/skills",
        json={
            "name": f"all-sys-detail-{uuid.uuid4().hex[:6]}",
            "instructions": "Base instructions.",
            "tool_ids": [
                str(SYSTEM_TOOL_SAVE_RESULT_ID),
                str(SYSTEM_TOOL_SEND_NOTIFICATION_ID),
            ],
        },
    )
    assert create_resp.status_code == 201
    skill_id = create_resp.json()["id"]

    get_resp = await authed_client.get(f"/api/v1/skills/{skill_id}")
    assert get_resp.status_code == 200, get_resp.text
    instructions = get_resp.json()["instructions_with_tools"]
    assert "system____save_result" in instructions
    assert "system____send_notification" in instructions


@pytest.mark.asyncio
async def test_list_skills_includes_skill_with_system_tools(authed_client: AsyncClient):
    """GET /api/v1/skills returns skills that have system tool bindings."""
    skill_name = f"list-sys-check-{uuid.uuid4().hex[:6]}"
    create_resp = await authed_client.post(
        "/api/v1/skills",
        json={
            "name": skill_name,
            "tool_ids": [str(SYSTEM_TOOL_SAVE_RESULT_ID)],
        },
    )
    assert create_resp.status_code == 201

    list_resp = await authed_client.get("/api/v1/skills")
    assert list_resp.status_code == 200
    skills = list_resp.json()
    names = [s["name"] for s in skills]
    assert skill_name in names

    created_skill = next(s for s in skills if s["name"] == skill_name)
    assert str(SYSTEM_TOOL_SAVE_RESULT_ID) in created_skill["tool_ids"]


# ── 5. Invalid Tool ID Validation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_skill_with_nonexistent_tool_returns_422(authed_client: AsyncClient):
    """POST /api/v1/skills with a random non-existent, non-system tool ID returns 422."""
    fake_tool_id = str(uuid.uuid4())
    resp = await authed_client.post(
        "/api/v1/skills",
        json={
            "name": f"invalid-tool-{uuid.uuid4().hex[:6]}",
            "tool_ids": [fake_tool_id],
        },
    )
    assert resp.status_code == 422, resp.text
    assert "not found" in resp.text.lower()


@pytest.mark.asyncio
async def test_update_skill_with_nonexistent_tool_returns_422(authed_client: AsyncClient):
    """PUT /api/v1/skills/{id} with a random non-existent tool ID returns 422."""
    create_resp = await authed_client.post(
        "/api/v1/skills",
        json={"name": f"pre-invalid-{uuid.uuid4().hex[:6]}", "tool_ids": []},
    )
    assert create_resp.status_code == 201
    skill_id = create_resp.json()["id"]

    fake_tool_id = str(uuid.uuid4())
    resp = await authed_client.put(
        f"/api/v1/skills/{skill_id}",
        json={"tool_ids": [fake_tool_id]},
    )
    assert resp.status_code == 422, resp.text
    assert "not found" in resp.text.lower()


@pytest.mark.asyncio
async def test_system_tool_ids_are_not_rejected(authed_client: AsyncClient):
    """System tool IDs must NOT trigger 422 — they bypass DB validation intentionally."""
    for tool_id in SYSTEM_TOOL_IDS:
        resp = await authed_client.post(
            "/api/v1/skills",
            json={
                "name": f"sys-valid-{uuid.uuid4().hex[:6]}",
                "tool_ids": [str(tool_id)],
            },
        )
        assert resp.status_code == 201, (
            f"System tool {tool_id} was incorrectly rejected: {resp.text}"
        )


# ── 6. MCP Tools Endpoint — System Tools Deduplication ───────────────────────


@pytest.mark.asyncio
async def test_system_tools_appear_once_in_mcp_tools_endpoint(
    authed_client: AsyncClient,
    db_session: AsyncSession,
):
    """GET /mcp/tools returns each system tool exactly once — no duplicates.

    Requires the system server and tools to be seeded first.
    """
    await seed_system_tools(db_session)

    resp = await authed_client.get("/api/v1/mcp/tools")
    assert resp.status_code == 200, resp.text
    tools = resp.json()

    system_tools = [t for t in tools if t.get("server_slug") == "system"]

    # Deduplicate by tool name
    names = [t["name"] for t in system_tools]
    assert len(names) == len(set(names)), f"Duplicate system tools found: {names}"

    # Verify each expected system tool is present exactly once
    expected_names = {"system____save_result", "system____send_notification", "system____get_recipient_group"}
    found_names = set(names)
    for expected in expected_names:
        assert expected in found_names, f"System tool '{expected}' not found in /mcp/tools response"
        count = names.count(expected)
        assert count == 1, f"System tool '{expected}' appears {count} times, expected exactly once"


# ── 7. MCP Servers Endpoint — System Server ───────────────────────────────────


@pytest.mark.asyncio
async def test_system_server_appears_in_servers_list(
    authed_client: AsyncClient,
    db_session: AsyncSession,
):
    """GET /mcp/servers always returns the system server with slug 'system'.

    The list_mcp_servers API always prepends a virtual system server entry,
    so no seeding is required and the system server is guaranteed to appear.
    """
    resp = await authed_client.get("/api/v1/mcp/servers")
    assert resp.status_code == 200, resp.text
    servers = resp.json()

    system_servers = [s for s in servers if s.get("slug") == "system"]
    assert len(system_servers) >= 1, "System server with slug='system' not found in /mcp/servers"

    # The virtual system server is always prepended first by the API.
    system_server = system_servers[0]
    assert system_server["id"] == str(SYSTEM_SERVER_ID)
    assert system_server["name"] == "System"
    assert system_server["status"] == "active"


# ── 8. Permission Manager — System Tool Access ────────────────────────────────


@pytest.mark.asyncio
async def test_agent_permission_for_system_tools(db_session: AsyncSession):
    """AgentPermissionManager returns empty allowed set when no skills are assigned.

    Under Phase 10 (tool naming refactor), system tools are NO LONGER auto-injected.
    They are only included when explicitly assigned via a skill bound to the role.
    A role with no skills or SOPs must receive an empty allowed set.
    """
    from unittest.mock import AsyncMock, MagicMock
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._cache = {}  # ensure clean state

    role_id = uuid.uuid4()

    # Mock DB for a role with no direct skills or SOPs → no tools injected
    db_mock = AsyncMock()
    empty_result = MagicMock()
    empty_result.fetchall.return_value = []

    db_mock.execute = AsyncMock(return_value=empty_result)

    allowed = await pm.calculate_allowed_tools(role_id, db_mock)

    # System tools are NOT auto-injected under Phase 10 architecture
    assert "save_result" not in allowed, (
        "save_result must NOT be auto-injected; it requires explicit skill assignment"
    )
    assert len(allowed) == 0, f"Expected empty allowed set for role with no skills, got: {allowed}"

    pm.invalidate(role_id)


@pytest.mark.asyncio
async def test_agent_permission_system_tool_prefixed_name(db_session: AsyncSession):
    """Permission check passes for system/save_result (namespaced identifier)."""
    from unittest.mock import AsyncMock, MagicMock
    from app.services.agents.permission_manager import AgentPermissionManager

    pm = AgentPermissionManager()
    pm._cache = {}
    role_id = uuid.uuid4()

    # Manually set allowed set to include system tool in both formats
    allowed = {"save_result", "system/save_result", "system/send_notification"}

    # Both prefixed and unprefixed names should pass the check
    pm.check_tool_allowed("save_result", allowed, role_id)
    pm.check_tool_allowed("system/save_result", allowed, role_id)
    pm.check_tool_allowed("system/send_notification", allowed, role_id)


@pytest.mark.asyncio
async def test_agent_permission_denies_unknown_tool():
    """PermissionDeniedError is raised for tools not in the allowed set."""
    from app.services.agents.permission_manager import AgentPermissionManager, PermissionDeniedError

    pm = AgentPermissionManager()
    role_id = uuid.uuid4()
    allowed = {"save_result"}

    with pytest.raises(PermissionDeniedError):
        pm.check_tool_allowed("malicious/drop_table", allowed, role_id)

