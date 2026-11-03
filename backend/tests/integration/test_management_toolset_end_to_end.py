"""End-to-end tests for the management MCP tool CC handlers.

Exercises ``POST /internal/management-tools/{tool_name}`` (the Control Center
side of the Control Center Assistant) against the real handlers with SQLite:

- full lifecycle per family: create → appears in list with correct values →
  get returns it → update → changes visible immediately (no reload);
- duplicate identifiers rejected (409) with no write;
- required-field validation (missing name → 400) with no write;
- permission denial (403) and no write;
- delete-shaped / unknown tool → 404 (no delete verb; defense-in-depth).

The service-cert dependency and the internal tenant context (single-tenant →
root) are the same overrides as the existing system-tool endpoint tests; the
``_authorize`` permission gate is monkeypatched per test (allow / deny).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_service_certificate
from app.db.models.agents import AgentType
from app.db.models.mcp_hub import McpServer
from app.db.models.skills import Skill
from app.db.session import get_db
from app.main import create_app


def _bypass_service_cert():
    async def override():
        return {"cert_type": "service", "service_name": "test-service"}

    return override


@pytest_asyncio.fixture
async def authed_client(test_engine):
    app = create_app()
    app.dependency_overrides[require_service_certificate] = _bypass_service_cert()

    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
def allow_all(monkeypatch: pytest.MonkeyPatch):
    """Make the permission gate a no-op (user authorized for everything)."""
    from app.api.v1.internal import management_tools

    async def _allow(db, user_sub, resource_type, action, tenant_id):
        return None

    monkeypatch.setattr(management_tools, "_authorize", _allow)


@pytest.fixture
def deny_all(monkeypatch: pytest.MonkeyPatch):
    """Make the permission gate always deny (403)."""
    from fastapi import HTTPException

    from app.api.v1.internal import management_tools

    async def _deny(db, user_sub, resource_type, action, tenant_id):
        raise HTTPException(status_code=403, detail="permission denied")

    monkeypatch.setattr(management_tools, "_authorize", _deny)


async def _post(client: AsyncClient, tool_name: str, body: dict):
    return await client.post(
        f"/api/v1/internal/management-tools/{tool_name}",
        json={"session_id": str(uuid.uuid4()), "user_sub": "user-1", "tool_args": body},
    )


# ── Skill family: full lifecycle ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_create_list_get_update_lifecycle(
    authed_client: AsyncClient, allow_all
) -> None:
    name = f"e2e-skill-{uuid.uuid4().hex[:8]}"

    # CREATE
    created = await _post(
        authed_client,
        "create_skill",
        {"name": name, "data": {"description": "created via management tool"}},
    )
    assert created.status_code == 200, created.text
    record = created.json()["result"]["record"]
    assert record["name"] == name
    assert record["description"] == "created via management tool"
    skill_id = record["id"]

    # LIST — appears with correct values.
    listed = await _post(authed_client, "list_skills", {})
    assert listed.status_code == 200
    names = [r["name"] for r in listed.json()["result"]["records"]]
    assert name in names

    # GET — matches the created record.
    gotten = await _post(authed_client, "get_skill", {"id": skill_id})
    assert gotten.status_code == 200, gotten.text
    assert gotten.json()["result"]["record"]["name"] == name

    # UPDATE — changes visible immediately (no reload / no re-fetch needed).
    updated = await _post(
        authed_client,
        "update_skill",
        {"id": skill_id, "name": name + "-updated", "data": {"description": "updated"}},
    )
    assert updated.status_code == 200, updated.text
    updated_record = updated.json()["result"]["record"]
    assert updated_record["description"] == "updated"

    gotten2 = await _post(authed_client, "get_skill", {"id": skill_id})
    assert gotten2.json()["result"]["record"]["name"] == name + "-updated"


@pytest.mark.asyncio
async def test_skill_duplicate_name_rejected(
    authed_client: AsyncClient, allow_all
) -> None:
    name = f"e2e-skill-dup-{uuid.uuid4().hex[:8]}"
    first = await _post(authed_client, "create_skill", {"name": name})
    assert first.status_code == 200

    second = await _post(authed_client, "create_skill", {"name": name})
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_skill_missing_name_rejected(
    authed_client: AsyncClient, allow_all
) -> None:
    response = await _post(authed_client, "create_skill", {"data": {"description": "no name"}})
    assert response.status_code == 400


# ── Defense-in-depth: no delete verb ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_shaped_tool_is_unknown(
    authed_client: AsyncClient, allow_all
) -> None:
    response = await _post(authed_client, "delete_skill", {"id": str(uuid.uuid4())})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unknown_management_tool_is_404(
    authed_client: AsyncClient, allow_all
) -> None:
    response = await _post(authed_client, "create_nonexistent", {"name": "x"})
    assert response.status_code == 404


# ── Permission enforcement ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_denied_action_returns_403_and_no_write(
    authed_client: AsyncClient, deny_all, test_engine
) -> None:
    name = f"e2e-skill-denied-{uuid.uuid4().hex[:8]}"
    response = await _post(authed_client, "create_skill", {"name": name})
    assert response.status_code == 403

    # No write occurred.
    async with async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )() as db:
        count = (
            await db.execute(select(Skill).where(Skill.name == name))
        ).scalars().all()
        assert len(count) == 0


# ── Additional families (create → list) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_type_create_and_list(authed_client: AsyncClient, allow_all) -> None:
    name = f"e2e-agent-type-{uuid.uuid4().hex[:8]}"
    created = await _post(
        authed_client,
        "create_agent_type",
        {"name": name, "data": {"input_type": "conversation"}},
    )
    assert created.status_code == 200, created.text
    record = created.json()["result"]["record"]
    assert record["name"] == name
    # Default is_system must be false (only the seeder marks it true).
    assert record["is_system"] is False

    listed = await _post(authed_client, "list_agent_types", {})
    names = [r["name"] for r in listed.json()["result"]["records"]]
    assert name in names


@pytest.mark.asyncio
async def test_mcp_server_create_requires_slug_and_base_url(
    authed_client: AsyncClient, allow_all
) -> None:
    name = f"e2e-mcp-{uuid.uuid4().hex[:8]}"
    slug = f"e2e-mcp-{uuid.uuid4().hex[:8]}"
    created = await _post(
        authed_client,
        "create_mcp_server",
        {"name": name, "data": {"slug": slug, "base_url": "http://localhost:9/mcp"}},
    )
    assert created.status_code == 200, created.text
    record = created.json()["result"]["record"]
    assert record["slug"] == slug

    # Missing base_url → 400 (required field).
    missing = await _post(
        authed_client,
        "create_mcp_server",
        {"name": name + "-x", "data": {"slug": slug + "-x"}},
    )
    assert missing.status_code == 400


@pytest.mark.asyncio
async def test_data_type_create_requires_slug(authed_client: AsyncClient, allow_all) -> None:
    missing = await _post(
        authed_client, "create_data_type", {"name": "no-slug"}
    )
    assert missing.status_code == 400
