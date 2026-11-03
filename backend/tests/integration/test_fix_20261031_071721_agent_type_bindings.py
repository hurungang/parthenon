"""FIX-20261031-071721 (defect 2, backend) — agent type skill/SOP bindings
through the management toolset.

The user asked the assistant to create an agent; it created the skill and the
agent type but could NOT associate the skill to the agent type, because
``create_agent_type`` / ``update_agent_type`` in the management toolset had no
skill/SOP binding support.  These tests pin the new capability:

- ``create_agent_type`` accepts ``skill_ids`` / ``sop_ids`` (id or name,
  tenant-scoped) and creates ``AgentTypeSkillBinding`` /
  ``AgentTypeSopBinding`` rows;
- ``update_agent_type`` accepts the same fields and ADDS bindings additively
  (never silently removes existing ones);
- re-binding an existing pair is idempotent (no-op success);
- an unknown skill/SOP id or name → structured 404 with a clear message and
  NO partial write;
- permission parity is unchanged — ``create_agent_type`` requires
  ``agent:create`` and ``update_agent_type`` requires ``agent:update``;
- the tool schemas served by ``get_management_tool_schema`` expose the new
  fields;
- the knowledge corpus contains the associate-skill-with-agent-type workflow.
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


async def _bindings_for_session(test_engine, skill_cls, sop_cls, agent_type_id):
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    at_id = uuid.UUID(str(agent_type_id))
    async with SessionLocal() as session:
        skill_rows = (
            (
                await session.execute(
                    select(skill_cls).where(skill_cls.agent_type_id == at_id)
                )
            )
            .scalars()
            .all()
        )
        sop_rows = (
            (
                await session.execute(
                    select(sop_cls).where(sop_cls.agent_type_id == at_id)
                )
            )
            .scalars()
            .all()
        )
        return skill_rows, sop_rows


# ── Create path: bindings are created from skill_ids / sop_ids ───────────────


@pytest.mark.asyncio
async def test_create_agent_type_creates_skill_bindings(
    authed_client, allow_all, test_engine
) -> None:
    """FAILING-FIRST: create_agent_type with skill_ids previously IGNORED
    them — the test asserts binding rows exist."""
    from app.db.models.agents import AgentTypeSkillBinding, AgentTypeSopBinding

    skill = await _invoke(
        authed_client,
        "create_skill",
        {"name": "fix071721-skill", "data": {"description": "d"}},
    )
    sop = await _invoke(
        authed_client,
        "create_sop",
        {"name": "fix071721-sop", "data": {"description": "d"}},
    )

    created = await _invoke(
        authed_client,
        "create_agent_type",
        {
            "name": "fix071721-agent",
            "data": {
                "description": "bound at create time",
                "skill_ids": [skill["record"]["id"]],
                "sop_ids": [sop["record"]["id"]],
            },
        },
    )
    agent_type_id = created["record"]["id"]

    skill_rows, sop_rows = await _bindings_for_session(
        test_engine, AgentTypeSkillBinding, AgentTypeSopBinding, agent_type_id
    )
    assert {str(b.skill_id) for b in skill_rows} == {skill["record"]["id"]}
    assert {str(b.sop_id) for b in sop_rows} == {sop["record"]["id"]}
    # order conventions: bindings start at 0/1-style small ordered integers
    assert [b.order for b in sorted(skill_rows, key=lambda b: b.order)] == [0]
    assert [b.order for b in sorted(sop_rows, key=lambda b: b.order)] == [0]


@pytest.mark.asyncio
async def test_create_agent_type_resolves_skills_by_name(
    authed_client, allow_all, test_engine
) -> None:
    """Name-resolution parity with the rest of the toolset (tenant-scoped)."""
    from app.db.models.agents import AgentTypeSkillBinding

    await _invoke(authed_client, "create_skill", {"name": "fix071721-named-skill"})
    created = await _invoke(
        authed_client,
        "create_agent_type",
        {
            "name": "fix071721-agent-by-name",
            "data": {"skill_ids": ["fix071721-named-skill"]},
        },
    )
    skill_rows, _ = await _bindings_for_session(
        test_engine, AgentTypeSkillBinding, AgentTypeSkillBinding, created["record"]["id"]
    )
    assert len(skill_rows) == 1


# ── Update path: additive merge, idempotent re-binding ───────────────────────


@pytest.mark.asyncio
async def test_update_agent_type_adds_bindings_additively_and_idempotent(
    authed_client, allow_all, test_engine
) -> None:
    """Binding an already-bound skill again = no-op success; new skills are
    ADDED and existing bindings are NEVER removed."""
    from app.db.models.agents import AgentTypeSkillBinding

    s1 = await _invoke(authed_client, "create_skill", {"name": "fix071721-u-s1"})
    s2 = await _invoke(authed_client, "create_skill", {"name": "fix071721-u-s2"})
    agent = await _invoke(
        authed_client,
        "create_agent_type",
        {
            "name": "fix071721-u-agent",
            "data": {"skill_ids": [s1["record"]["id"]]},
        },
    )
    agent_id = agent["record"]["id"]

    # Additive: bind s2 alongside s1.
    await _invoke(
        authed_client,
        "update_agent_type",
        {"id": agent_id, "data": {"skill_ids": [s2["record"]["id"]]}},
    )
    rows, _ = await _bindings_for_session(
        test_engine, AgentTypeSkillBinding, AgentTypeSkillBinding, agent_id
    )
    assert {str(b.skill_id) for b in rows} == {s1["record"]["id"], s2["record"]["id"]}

    # Idempotent: re-binding s1 (mixed with s2) succeeds without duplicates.
    await _invoke(
        authed_client,
        "update_agent_type",
        {"id": agent_id, "data": {"skill_ids": [s1["record"]["id"], s2["record"]["id"]]}},
    )
    rows, _ = await _bindings_for_session(
        test_engine, AgentTypeSkillBinding, AgentTypeSkillBinding, agent_id
    )
    assert len(rows) == 2, "re-binding must not create duplicate rows"
    assert {str(b.skill_id) for b in rows} == {s1["record"]["id"], s2["record"]["id"]}


# ── Validation: unknown skill/SOP → 404, no partial write ────────────────────


@pytest.mark.asyncio
async def test_update_agent_type_unknown_skill_id_is_404_no_partial_write(
    authed_client, allow_all, test_engine
) -> None:
    from app.db.models.agents import AgentTypeSkillBinding

    s1 = await _invoke(authed_client, "create_skill", {"name": "fix071721-x-s1"})
    agent = await _invoke(
        authed_client, "create_agent_type", {"name": "fix071721-x-agent"}
    )
    agent_id = agent["record"]["id"]

    response = await authed_client.post(
        "/api/v1/internal/management-tools/invoke_management_tool",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {
                "tool_name": "update_agent_type",
                "args": {
                    "id": agent_id,
                    "data": {
                        "skill_ids": [s1["record"]["id"], str(uuid.uuid4())],
                    },
                },
            },
        },
    )
    assert response.status_code == 404
    assert "skill" in response.text.lower()

    rows, _ = await _bindings_for_session(
        test_engine, AgentTypeSkillBinding, AgentTypeSkillBinding, agent_id
    )
    assert rows == [], "unknown skill must abort the whole binding set (no partial write)"


@pytest.mark.asyncio
async def test_update_agent_type_unknown_sop_name_is_404(authed_client, allow_all) -> None:
    agent = await _invoke(
        authed_client, "create_agent_type", {"name": "fix071721-y-agent"}
    )
    response = await authed_client.post(
        "/api/v1/internal/management-tools/invoke_management_tool",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {
                "tool_name": "update_agent_type",
                "args": {
                    "id": agent["record"]["id"],
                    "data": {"sop_ids": ["no-such-sop-anywhere"]},
                },
            },
        },
    )
    assert response.status_code == 404
    assert "sop" in response.text.lower()


# ── Permission parity unchanged ──────────────────────────────────────────────


def test_parity_map_unchanged_for_agent_type_tools() -> None:
    from app.services.agents.system_tool_registry import SystemToolRegistry

    parity = SystemToolRegistry.get_parity_map()
    # Exact pairs: the parity map must stay on the bare `agent` resource type.
    assert parity["create_agent_type"] == ("agent", "create")
    assert parity["update_agent_type"] == ("agent", "update")


@pytest.mark.asyncio
async def test_create_agent_type_denied_without_permission(
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
                "tool_name": "create_agent_type",
                "args": {"name": "nope", "data": {"skill_ids": [str(uuid.uuid4())]}},
            },
        },
    )
    assert response.status_code == 403


# ── Served tool schemas expose the new fields ────────────────────────────────


@pytest.mark.asyncio
async def test_get_management_tool_schema_includes_binding_fields(authed_client) -> None:
    for tool_name in ("create_agent_type", "update_agent_type"):
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
        assert "additive" in schema["function"]["description"].lower() or (
            "associat" in schema["function"]["description"].lower()
        ), tool_name


# ── Knowledge corpus: associate-skill-with-agent-type workflow ───────────────


@pytest.mark.asyncio
async def test_search_knowledge_returns_association_workflow(authed_client) -> None:
    response = await authed_client.post(
        "/api/v1/internal/management-tools/search_assistant_knowledge",
        json={
            "session_id": str(uuid.uuid4()),
            "user_sub": "user-1",
            "tool_args": {"query": "associate skill with agent type"},
        },
    )
    assert response.status_code == 200, response.text
    results = response.json()["result"]["results"]
    combined = " ".join(r["rule_text"] for r in results)
    assert "skill_ids" in combined, (
        "knowledge must explain the skill_ids/sop_ids association workflow"
    )
    assert "create_agent_type" in combined or "update_agent_type" in combined
