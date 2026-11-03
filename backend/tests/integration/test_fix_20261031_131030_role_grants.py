"""FIX-20261031-131030 (defect 2) — role skill/SOP grants in the management toolset.

The user asked the assistant to create a skill + agent type for a role-based
agent, but the skill was never granted to the agent's ROLE — role-based
agents resolve their runtime tool access from the role's ``AgentRoleSkill`` /
``AgentRoleSOP`` assignments, so the agent could not access the skill.

These tests pin the new capability:

- ``create_agent_role`` accepts ``skill_ids`` / ``sop_ids`` (id or name,
  tenant-scoped) and creates ``AgentRoleSkill`` / ``AgentRoleSOP`` rows;
- ``update_agent_role`` accepts the same fields and ADDS grants additively
  (never silently removes existing ones);
- re-granting an existing pair is idempotent (no-op success);
- an unknown skill/SOP id or name → structured 404 with an actionable
  message and NO partial write;
- permission parity is unchanged — role tools stay on the bare ``agent``
  resource type (same as agent types / identities / model configs);
- the tool schemas served by ``get_management_tool_schema`` expose the new
  fields;
- the knowledge corpus surfaces the grant-to-role workflow.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_service_certificate
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
    from app.api.v1.internal import management_tools

    async def _allow(db, user_sub, resource_type, action, tenant_id):
        return None

    monkeypatch.setattr(management_tools, "_authorize", _allow)


async def _invoke(client: AsyncClient, tool_name: str, args: dict) -> dict:
    response = await client.post(
        "/api/v1/internal/management-tools/invoke_management_tool",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {"tool_name": tool_name, "args": args},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


async def _role_grants(test_engine, role_id):
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    from app.db.models.agents import AgentRoleSkill, AgentRoleSOP

    rid = uuid.UUID(str(role_id))
    async with SessionLocal() as session:
        skill_rows = (
            (
                await session.execute(
                    select(AgentRoleSkill).where(AgentRoleSkill.role_id == rid)
                )
            )
            .scalars()
            .all()
        )
        sop_rows = (
            (
                await session.execute(
                    select(AgentRoleSOP).where(AgentRoleSOP.role_id == rid)
                )
            )
            .scalars()
            .all()
        )
        return skill_rows, sop_rows


# ── FAILING-FIRST: update_agent_role previously ignored skill_ids ────────────


@pytest.mark.asyncio
async def test_update_agent_role_grants_skills(
    authed_client, allow_all, test_engine
) -> None:
    """FAILING-FIRST: update_agent_role with skill_ids previously IGNORED them."""
    skill = await _invoke(
        authed_client, "create_skill", {"name": "fix131030-grant-skill"}
    )
    role = await _invoke(
        authed_client, "create_agent_role", {"name": "fix131030-role"}
    )
    role_id = role["record"]["id"]

    await _invoke(
        authed_client,
        "update_agent_role",
        {"id": role_id, "data": {"skill_ids": [skill["record"]["id"]]}},
    )

    skill_rows, sop_rows = await _role_grants(test_engine, role_id)
    assert {str(b.skill_id) for b in skill_rows} == {skill["record"]["id"]}, (
        "update_agent_role must grant skills to the role (AgentRoleSkill rows)"
    )
    assert sop_rows == []


@pytest.mark.asyncio
async def test_create_agent_role_grants_skills_and_sops(
    authed_client, allow_all, test_engine
) -> None:
    skill = await _invoke(
        authed_client, "create_skill", {"name": "fix131030-create-skill"}
    )
    sop = await _invoke(authed_client, "create_sop", {"name": "fix131030-create-sop"})
    created = await _invoke(
        authed_client,
        "create_agent_role",
        {
            "name": "fix131030-create-role",
            "data": {
                "description": "granted at create time",
                "skill_ids": [skill["record"]["id"]],
                "sop_ids": [sop["record"]["id"]],
            },
        },
    )
    skill_rows, sop_rows = await _role_grants(test_engine, created["record"]["id"])
    assert {str(b.skill_id) for b in skill_rows} == {skill["record"]["id"]}
    assert {str(b.sop_id) for b in sop_rows} == {sop["record"]["id"]}


@pytest.mark.asyncio
async def test_grants_resolve_by_name(authed_client, allow_all, test_engine) -> None:
    await _invoke(authed_client, "create_skill", {"name": "fix131030-named-skill"})
    role = await _invoke(
        authed_client,
        "create_agent_role",
        {"name": "fix131030-named-role", "data": {"skill_ids": ["fix131030-named-skill"]}},
    )
    skill_rows, _ = await _role_grants(test_engine, role["record"]["id"])
    assert len(skill_rows) == 1


# ── Additive merge + idempotent re-grant ─────────────────────────────────────


@pytest.mark.asyncio
async def test_update_agent_role_additive_merge_and_idempotent(
    authed_client, allow_all, test_engine
) -> None:
    s1 = await _invoke(authed_client, "create_skill", {"name": "fix131030-u-s1"})
    s2 = await _invoke(authed_client, "create_skill", {"name": "fix131030-u-s2"})
    role = await _invoke(
        authed_client,
        "create_agent_role",
        {"name": "fix131030-u-role", "data": {"skill_ids": [s1["record"]["id"]]}},
    )
    role_id = role["record"]["id"]

    # Additive: grant s2 alongside s1 — s1 must NOT be removed.
    await _invoke(
        authed_client,
        "update_agent_role",
        {"id": role_id, "data": {"skill_ids": [s2["record"]["id"]]}},
    )
    skill_rows, _ = await _role_grants(test_engine, role_id)
    assert {str(b.skill_id) for b in skill_rows} == {
        s1["record"]["id"],
        s2["record"]["id"],
    }

    # Idempotent: re-granting both succeeds without duplicates.
    await _invoke(
        authed_client,
        "update_agent_role",
        {"id": role_id, "data": {"skill_ids": [s1["record"]["id"], s2["record"]["id"]]}},
    )
    skill_rows, _ = await _role_grants(test_engine, role_id)
    assert len(skill_rows) == 2, "re-granting must not create duplicate rows"


# ── Unknown skill → 404, no partial write ────────────────────────────────────


@pytest.mark.asyncio
async def test_update_agent_role_unknown_skill_is_404_no_partial_write(
    authed_client, allow_all, test_engine
) -> None:
    s1 = await _invoke(authed_client, "create_skill", {"name": "fix131030-x-s1"})
    role = await _invoke(
        authed_client, "create_agent_role", {"name": "fix131030-x-role"}
    )
    role_id = role["record"]["id"]

    response = await authed_client.post(
        "/api/v1/internal/management-tools/invoke_management_tool",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {
                "tool_name": "update_agent_role",
                "args": {
                    "id": role_id,
                    "data": {"skill_ids": [s1["record"]["id"], str(uuid.uuid4())]},
                },
            },
        },
    )
    assert response.status_code == 404
    # Actionable message.
    assert "create_skill" in response.text.lower() or "create the skill" in response.text.lower()

    skill_rows, _ = await _role_grants(test_engine, role_id)
    assert skill_rows == [], "unknown skill must abort the whole grant set (no partial write)"


@pytest.mark.asyncio
async def test_create_agent_role_unknown_sop_name_is_404(authed_client, allow_all) -> None:
    response = await authed_client.post(
        "/api/v1/internal/management-tools/invoke_management_tool",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {
                "tool_name": "create_agent_role",
                "args": {
                    "name": "fix131030-y-role",
                    "data": {"sop_ids": ["no-such-sop-anywhere"]},
                },
            },
        },
    )
    assert response.status_code == 404
    assert "sop" in response.text.lower()


# ── Permission parity unchanged (bare `agent` resource type) ─────────────────


def test_parity_map_roles_and_agent_types_use_bare_agent() -> None:
    from app.services.agents.system_tool_registry import SystemToolRegistry

    parity = SystemToolRegistry.get_parity_map()
    assert parity["create_agent_role"] == ("agent", "create")
    assert parity["update_agent_role"] == ("agent", "update")
    assert parity["create_agent_type"] == ("agent", "create")
    assert parity["create_agent_identity"] == ("agent", "create")
    assert parity["create_model_config"] == ("agent", "create")


@pytest.mark.asyncio
async def test_update_agent_role_denied_without_permission(
    authed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    from app.api.v1.internal import management_tools

    async def _deny(db, user_sub, resource_type, action, tenant_id):
        raise HTTPException(status_code=403, detail="permission denied")

    monkeypatch.setattr(management_tools, "_authorize", _deny)
    response = await authed_client.post(
        "/api/v1/internal/management-tools/invoke_management_tool",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {
                "tool_name": "update_agent_role",
                "args": {
                    "id": str(uuid.uuid4()),
                    "data": {"skill_ids": [str(uuid.uuid4())]},
                },
            },
        },
    )
    assert response.status_code == 403


# ── Served tool schemas expose the new fields ────────────────────────────────


@pytest.mark.asyncio
async def test_get_management_tool_schema_role_includes_grant_fields(authed_client) -> None:
    for tool_name in ("create_agent_role", "update_agent_role"):
        response = await authed_client.post(
            "/api/v1/internal/management-tools/get_management_tool_schema",
            json={
                "session_id": str(uuid.uuid4()),
                "user_sub": "user-1",
                "tool_args": {"tool_name": tool_name},
            },
        )
        assert response.status_code == 200, response.text
        schema = response.json()["result"]["schema"]
        props = schema["function"]["parameters"]["properties"]
        data_props = props.get("data", {}).get("properties", {})
        assert "skill_ids" in data_props, (tool_name, data_props)
        assert "sop_ids" in data_props, (tool_name, data_props)


# ── Knowledge corpus: grant-skill-to-role workflow ───────────────────────────


@pytest.mark.asyncio
async def test_search_knowledge_returns_role_grant_workflow(authed_client) -> None:
    response = await authed_client.post(
        "/api/v1/internal/management-tools/search_assistant_knowledge",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {"query": "assign skill to agent role"},
        },
    )
    assert response.status_code == 200, response.text
    results = response.json()["result"]["results"]
    combined = " ".join(r["rule_text"] for r in results)
    assert "update_agent_role" in combined and "skill_ids" in combined, (
        "knowledge must explain the grant-skill-to-role workflow"
    )
    assert "ALWAYS" in combined.upper() or "granted" in combined.lower()
