"""Unit tests for AssistantSeeder — idempotent, per-tenant provisioning.

The Control Center Assistant is a seeded ``AgentType`` (``is_system=True``,
conversational) plus a management skill binding its management tools, and it
is tenant-bound: every tenant gets its own rows.  Running the seeder more
than once must be a no-op for rows already present (no duplicate agent type /
skill / bindings), while still enforcing the system flag, conversational
input type and active status.  The seeder never binds a model — per-tenant
model selection happens through the assistant-model API endpoints.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.models.agents import AgentInputType, AgentType
from app.db.models.skills import Skill
from app.db.models.tenant import Tenant
from app.services.agents.assistant_seeder import (
    ASSISTANT_AGENT_TYPE_NAME,
    MANAGEMENT_SKILL_NAME,
    AssistantSeeder,
)


async def _create_tenant(session, slug: str) -> Tenant:
    tenant = Tenant(
        id=uuid.uuid4(),
        slug=slug,
        name=slug.title(),
        status="active",
    )
    session.add(tenant)
    await session.flush()
    return tenant


@pytest.mark.asyncio
async def test_seeder_is_idempotent(db_session) -> None:
    seeder = AssistantSeeder()

    first = await seeder.run(db_session)
    await db_session.commit()

    second = await seeder.run(db_session)
    await db_session.commit()

    # Summary is per-tenant.
    assert set(first.keys()) == {"tenants", "per_tenant"}
    assert set(second.keys()) == {"tenants", "per_tenant"}
    for summary in (first, second):
        for tenant_summary in summary["per_tenant"].values():
            assert set(tenant_summary.keys()) == {"skill", "agent_type"}

    # Exactly one assistant agent type and one management skill per tenant.
    agent_types = (
        await db_session.execute(
            select(AgentType).where(AgentType.name == ASSISTANT_AGENT_TYPE_NAME)
        )
    ).scalars().all()
    skills = (
        await db_session.execute(
            select(Skill).where(Skill.name == MANAGEMENT_SKILL_NAME)
        )
    ).scalars().all()
    tenant_ids = (await db_session.execute(select(Tenant))).scalars().all()
    assert len(agent_types) == len({a.tenant_id for a in agent_types}) == len(tenant_ids)
    assert len(skills) == len({s.tenant_id for s in skills}) == len(tenant_ids)


@pytest.mark.asyncio
async def test_seeder_marks_assistant_as_system_conversational(db_session) -> None:
    seeder = AssistantSeeder()
    await seeder.run(db_session)
    await db_session.commit()

    agent_type = (
        await db_session.execute(
            select(AgentType).where(AgentType.name == ASSISTANT_AGENT_TYPE_NAME)
        )
    ).scalar_one()

    assert agent_type.is_system is True
    assert agent_type.input_type == AgentInputType.conversation
    assert agent_type.is_active is True


@pytest.mark.asyncio
async def test_seeder_does_not_bind_a_model(db_session) -> None:
    """Model binding is per-tenant API configuration, never a seeder concern."""
    seeder = AssistantSeeder()
    await seeder.run(db_session)
    await db_session.commit()

    agent_types = (
        await db_session.execute(
            select(AgentType).where(AgentType.name == ASSISTANT_AGENT_TYPE_NAME)
        )
    ).scalars().all()
    assert agent_types
    for agent_type in agent_types:
        assert agent_type.model_id is None


@pytest.mark.asyncio
async def test_seeder_upgrades_existing_non_system_agent_type(db_session) -> None:
    """An existing assistant row that lost its system flag is repaired in place."""
    seeder = AssistantSeeder()
    await seeder.run(db_session)
    await db_session.commit()

    agent_type = (
        await db_session.execute(
            select(AgentType).where(AgentType.name == ASSISTANT_AGENT_TYPE_NAME)
        )
    ).scalar_one()
    agent_type.is_system = False
    agent_type.is_active = False
    await db_session.commit()

    await seeder.run(db_session)
    await db_session.commit()

    reloaded = (
        await db_session.execute(
            select(AgentType).where(AgentType.id == agent_type.id)
        )
    ).scalar_one()
    assert reloaded.is_system is True
    assert reloaded.is_active is True
    assert reloaded.input_type == AgentInputType.conversation


@pytest.mark.asyncio
async def test_seeder_sets_workflow_iteration_budget(db_session) -> None:
    """FIX-20261101-111439: seeded assistant gets the raised iteration budget."""
    from app.services.agents.assistant_seeder import ASSISTANT_GUARDRAIL_MAX_ITERATIONS

    seeder = AssistantSeeder()
    await seeder.run(db_session)
    await db_session.commit()

    agent_types = (
        await db_session.execute(
            select(AgentType).where(AgentType.name == ASSISTANT_AGENT_TYPE_NAME)
        )
    ).scalars().all()
    assert agent_types
    for agent_type in agent_types:
        assert agent_type.guardrail_max_iterations == ASSISTANT_GUARDRAIL_MAX_ITERATIONS
        # Budget must exceed the 11-step workflow exhaustion observed at 10.
        assert agent_type.guardrail_max_iterations >= 24


@pytest.mark.asyncio
async def test_seeder_refreshes_stale_iteration_budget(db_session) -> None:
    """FIX-20261101-111439: existing seeded rows (default 10) are upgraded."""
    from app.services.agents.assistant_seeder import ASSISTANT_GUARDRAIL_MAX_ITERATIONS

    seeder = AssistantSeeder()
    await seeder.run(db_session)
    await db_session.commit()

    agent_type = (
        await db_session.execute(
            select(AgentType).where(AgentType.name == ASSISTANT_AGENT_TYPE_NAME)
        )
    ).scalar_one()
    agent_type.guardrail_max_iterations = 10
    await db_session.commit()

    await seeder.run(db_session)
    await db_session.commit()

    reloaded = (
        await db_session.execute(
            select(AgentType).where(AgentType.id == agent_type.id)
        )
    ).scalar_one()
    assert reloaded.guardrail_max_iterations == ASSISTANT_GUARDRAIL_MAX_ITERATIONS


@pytest.mark.asyncio
async def test_management_skill_is_system(db_session) -> None:
    seeder = AssistantSeeder()
    await seeder.run(db_session)
    await db_session.commit()

    skill = (
        await db_session.execute(
            select(Skill).where(Skill.name == MANAGEMENT_SKILL_NAME)
        )
    ).scalar_one()
    assert skill.is_system is True
    assert skill.is_active is True


@pytest.mark.asyncio
async def test_seeder_provisions_every_tenant(db_session) -> None:
    """Each tenant gets its own assistant agent type + management skill."""
    tenant_a = await _create_tenant(db_session, "tenant-a")
    tenant_b = await _create_tenant(db_session, "tenant-b")
    await db_session.flush()

    seeder = AssistantSeeder()
    summary = await seeder.run(db_session)
    await db_session.commit()

    assert tenant_a.id in [uuid.UUID(k) for k in summary["per_tenant"]]
    assert tenant_b.id in [uuid.UUID(k) for k in summary["per_tenant"]]

    agent_types = (
        await db_session.execute(
            select(AgentType).where(AgentType.name == ASSISTANT_AGENT_TYPE_NAME)
        )
    ).scalars().all()
    by_tenant = {a.tenant_id: a for a in agent_types}
    assert set(by_tenant) >= {tenant_a.id, tenant_b.id}
    for tenant_id in (tenant_a.id, tenant_b.id):
        assert by_tenant[tenant_id].is_system is True
        assert by_tenant[tenant_id].model_id is None

    skills = (
        await db_session.execute(
            select(Skill).where(Skill.name == MANAGEMENT_SKILL_NAME)
        )
    ).scalars().all()
    assert {s.tenant_id for s in skills} >= {tenant_a.id, tenant_b.id}


@pytest.mark.asyncio
async def test_seeder_refreshes_stale_instruction_and_digest(db_session) -> None:
    """FIX-20261102-100704: existing seeded rows converge to the current
    (generic) instruction + skill digest on the next seeder run."""
    from app.services.agents.assistant_seeder import (
        ASSISTANT_SYSTEM_INSTRUCTION,
        MANAGEMENT_SKILL_INSTRUCTIONS,
    )

    seeder = AssistantSeeder()
    await seeder.run(db_session)
    await db_session.commit()

    agent_types = (
        await db_session.execute(
            select(AgentType).where(AgentType.name == ASSISTANT_AGENT_TYPE_NAME)
        )
    ).scalars().all()
    skills = (
        await db_session.execute(
            select(Skill).where(Skill.name == MANAGEMENT_SKILL_NAME)
        )
    ).scalars().all()
    assert agent_types and skills

    for row in agent_types:
        row.system_instruction = "stale pre-generic instruction"
    for row in skills:
        row.instructions = "stale composition chain: create skill first"
    await db_session.commit()

    await seeder.run(db_session)
    await db_session.commit()

    refreshed_agents = (
        await db_session.execute(
            select(AgentType).where(AgentType.name == ASSISTANT_AGENT_TYPE_NAME)
        )
    ).scalars().all()
    refreshed_skills = (
        await db_session.execute(
            select(Skill).where(Skill.name == MANAGEMENT_SKILL_NAME)
        )
    ).scalars().all()
    for row in refreshed_agents:
        assert row.system_instruction == ASSISTANT_SYSTEM_INSTRUCTION
        assert "completeness principle" in row.system_instruction.lower()
    for row in refreshed_skills:
        assert row.instructions == MANAGEMENT_SKILL_INSTRUCTIONS
        assert "principles" in row.instructions.lower()


@pytest.mark.asyncio
async def test_seeder_one_tenant_failure_does_not_abort_the_rest(
    db_session, monkeypatch
) -> None:
    """A failing tenant is skipped; the other tenants are still provisioned."""
    tenant_a = await _create_tenant(db_session, "tenant-ok")
    tenant_b = await _create_tenant(db_session, "tenant-boom")
    await db_session.flush()

    seeder = AssistantSeeder()
    original = seeder._seed_tenant

    async def flaky(session, tenant_id):
        if tenant_id == tenant_b.id:
            raise RuntimeError("boom")
        return await original(session, tenant_id)

    monkeypatch.setattr(seeder, "_seed_tenant", flaky)
    summary = await seeder.run(db_session)
    await db_session.commit()

    assert summary["per_tenant"][str(tenant_b.id)] == "failed"
    assert summary["per_tenant"][str(tenant_a.id)]["agent_type"] in {"created", "exists"}

    assistant_rows = (
        await db_session.execute(
            select(AgentType).where(AgentType.name == ASSISTANT_AGENT_TYPE_NAME)
        )
    ).scalars().all()
    assisted = {a.tenant_id for a in assistant_rows}
    assert tenant_a.id in assisted
    assert tenant_b.id not in assisted
