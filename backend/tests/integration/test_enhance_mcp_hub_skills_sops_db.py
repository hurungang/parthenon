"""Integration tests for enhance-mcp-hub-skills-sops database schema changes.

Verifies that the schema is correct after the migration:
- McpSession.identity_binding and credential_config columns exist and accept JSON
- Sop.instructions column exists and is nullable
- SopStep.target_agent_type_id and step_config columns exist and are nullable
- SopStepType enum rename: skill_invocation is valid; legacy 'skill' is absent
- Nullable fields accept None values without error
- Full round-trip CRUD for new/renamed columns

Uses SQLite in-memory database with Base.metadata.create_all() — equivalent
to alembic upgrade head in that all model-defined columns are created.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.mcp_hub import McpServer, McpSession, McpSessionAuthType, McpTool
from app.db.models.skills import Skill, Sop, SopStep, SopStepType


# ── Schema / column presence ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mcp_session_table_has_identity_binding_column(db_session: AsyncSession):
    """mcp_sessions.identity_binding column must exist (migration applied)."""
    result = await db_session.execute(text("PRAGMA table_info(mcp_sessions)"))
    columns = {row[1] for row in result.fetchall()}
    assert "identity_binding" in columns, (
        "identity_binding column missing from mcp_sessions — migration not applied"
    )


@pytest.mark.asyncio
async def test_mcp_session_table_has_credential_config_column(db_session: AsyncSession):
    """mcp_sessions.credential_config column must exist (migration applied)."""
    result = await db_session.execute(text("PRAGMA table_info(mcp_sessions)"))
    columns = {row[1] for row in result.fetchall()}
    assert "credential_config" in columns, (
        "credential_config column missing from mcp_sessions — migration not applied"
    )


@pytest.mark.asyncio
async def test_sop_table_has_instructions_column(db_session: AsyncSession):
    """sops.instructions column must exist (migration applied)."""
    result = await db_session.execute(text("PRAGMA table_info(sops)"))
    columns = {row[1] for row in result.fetchall()}
    assert "instructions" in columns, (
        "instructions column missing from sops — migration not applied"
    )


@pytest.mark.asyncio
async def test_sop_step_table_has_target_agent_type_id_column(db_session: AsyncSession):
    """sop_steps.target_agent_type_id column must exist (renamed from delegate_agent_type_id)."""
    result = await db_session.execute(text("PRAGMA table_info(sop_steps)"))
    columns = {row[1] for row in result.fetchall()}
    assert "target_agent_type_id" in columns, (
        "target_agent_type_id column missing from sop_steps — rename migration not applied"
    )


@pytest.mark.asyncio
async def test_sop_step_table_has_step_config_column(db_session: AsyncSession):
    """sop_steps.step_config column must exist (migration applied)."""
    result = await db_session.execute(text("PRAGMA table_info(sop_steps)"))
    columns = {row[1] for row in result.fetchall()}
    assert "step_config" in columns, (
        "step_config column missing from sop_steps — migration not applied"
    )


@pytest.mark.asyncio
async def test_sop_step_table_does_not_have_delegate_agent_type_id(db_session: AsyncSession):
    """sop_steps must NOT have the old delegate_agent_type_id column."""
    result = await db_session.execute(text("PRAGMA table_info(sop_steps)"))
    columns = {row[1] for row in result.fetchall()}
    assert "delegate_agent_type_id" not in columns, (
        "delegate_agent_type_id still present in sop_steps — rename migration not applied"
    )


# ── SopStepType enum ──────────────────────────────────────────────────────────


def test_sop_step_type_enum_has_skill_invocation():
    """SopStepType.skill_invocation must be a valid enum member."""
    assert SopStepType.skill_invocation.value == "skill_invocation"


def test_sop_step_type_enum_has_agent_delegation():
    """SopStepType.agent_delegation must be a valid enum member."""
    assert SopStepType.agent_delegation.value == "agent_delegation"


def test_sop_step_type_enum_does_not_have_legacy_skill_value():
    """SopStepType must NOT have a 'skill' member — it was renamed to skill_invocation."""
    values = {m.value for m in SopStepType}
    assert "skill" not in values, (
        "Legacy enum value 'skill' still present in SopStepType — rename migration not applied"
    )


# ── McpSession with new fields ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mcp_session_create_with_identity_binding(db_session: AsyncSession):
    """Create McpSession with identity_binding JSON and verify round-trip."""
    server = McpServer(
        name="Test Server",
        slug="test-server-schema",
        base_url="http://mcp.test",
    )
    db_session.add(server)
    await db_session.flush()

    binding: dict[str, Any] = {"agent_id": "agt-001", "realm": "parthenon"}
    session = McpSession(
        server_id=server.id,
        name="Test Session",
        auth_type=McpSessionAuthType.api_key,
        identity_binding=binding,
    )
    db_session.add(session)
    await db_session.flush()
    await db_session.refresh(session)

    assert session.identity_binding == binding
    assert session.identity_binding["agent_id"] == "agt-001"


@pytest.mark.asyncio
async def test_mcp_session_create_with_credential_config(db_session: AsyncSession):
    """Create McpSession with credential_config JSON and verify round-trip."""
    server = McpServer(
        name="Test Server CC",
        slug="test-server-cc",
        base_url="http://mcp.test.cc",
    )
    db_session.add(server)
    await db_session.flush()

    config: dict[str, Any] = {"required_keys": ["api_key"], "description": "API Key auth"}
    session = McpSession(
        server_id=server.id,
        name="CC Session",
        auth_type=McpSessionAuthType.api_key,
        credential_config=config,
    )
    db_session.add(session)
    await db_session.flush()
    await db_session.refresh(session)

    assert session.credential_config == config
    assert session.credential_config["required_keys"] == ["api_key"]


@pytest.mark.asyncio
async def test_mcp_session_create_without_new_fields(db_session: AsyncSession):
    """Create McpSession without identity_binding/credential_config — both nullable."""
    server = McpServer(
        name="Test Server Null",
        slug="test-server-null",
        base_url="http://mcp.test.null",
    )
    db_session.add(server)
    await db_session.flush()

    session = McpSession(
        server_id=server.id,
        name="Null Session",
        auth_type=McpSessionAuthType.none,
    )
    db_session.add(session)
    await db_session.flush()
    await db_session.refresh(session)

    assert session.identity_binding is None
    assert session.credential_config is None


# ── Sop with instructions ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sop_create_with_instructions(db_session: AsyncSession):
    """Create Sop with instructions field and verify persistence."""
    sop = Sop(
        name="Test SOP Instructions",
        description="Test description",
        instructions="Use this SOP to handle incident escalation.",
    )
    db_session.add(sop)
    await db_session.flush()
    await db_session.refresh(sop)

    assert sop.instructions == "Use this SOP to handle incident escalation."


@pytest.mark.asyncio
async def test_sop_create_without_instructions_is_nullable(db_session: AsyncSession):
    """Create Sop without instructions — column is nullable, should return None."""
    sop = Sop(name="SOP No Instructions", description="no instructions")
    db_session.add(sop)
    await db_session.flush()
    await db_session.refresh(sop)

    assert sop.instructions is None


# ── SopStep with target_agent_type_id and step_config ─────────────────────────


@pytest.mark.asyncio
async def test_sop_step_create_with_skill_invocation_type(db_session: AsyncSession):
    """Create SopStep with step_type=skill_invocation — valid enum value."""
    sop = Sop(name="SOP Step Test")
    db_session.add(sop)
    await db_session.flush()

    step = SopStep(
        sop_id=sop.id,
        order=1,
        step_type=SopStepType.skill_invocation,
        name="First Step",
    )
    db_session.add(step)
    await db_session.flush()
    await db_session.refresh(step)

    assert step.step_type == SopStepType.skill_invocation


@pytest.mark.asyncio
async def test_sop_step_create_with_target_agent_type_id(db_session: AsyncSession):
    """Create SopStep with target_agent_type_id (agent_delegation step)."""
    sop = Sop(name="SOP Delegation Test")
    db_session.add(sop)
    await db_session.flush()

    agent_type_id = uuid.uuid4()
    step = SopStep(
        sop_id=sop.id,
        order=1,
        step_type=SopStepType.agent_delegation,
        target_agent_type_id=agent_type_id,
    )
    db_session.add(step)
    await db_session.flush()
    await db_session.refresh(step)

    assert step.target_agent_type_id == agent_type_id


@pytest.mark.asyncio
async def test_sop_step_create_without_target_agent_type_id_is_nullable(db_session: AsyncSession):
    """Create SopStep without target_agent_type_id — column is nullable."""
    sop = Sop(name="SOP Nullable Target")
    db_session.add(sop)
    await db_session.flush()

    step = SopStep(
        sop_id=sop.id,
        order=1,
        step_type=SopStepType.skill_invocation,
    )
    db_session.add(step)
    await db_session.flush()
    await db_session.refresh(step)

    assert step.target_agent_type_id is None


@pytest.mark.asyncio
async def test_sop_step_create_with_step_config(db_session: AsyncSession):
    """Create SopStep with step_config JSON and verify round-trip."""
    sop = Sop(name="SOP Config Test")
    db_session.add(sop)
    await db_session.flush()

    config: dict[str, Any] = {"timeout_seconds": 30, "retry_count": 3}
    step = SopStep(
        sop_id=sop.id,
        order=1,
        step_type=SopStepType.skill_invocation,
        step_config=config,
    )
    db_session.add(step)
    await db_session.flush()
    await db_session.refresh(step)

    assert step.step_config == config
    assert step.step_config["timeout_seconds"] == 30


@pytest.mark.asyncio
async def test_sop_step_create_without_step_config_is_nullable(db_session: AsyncSession):
    """Create SopStep without step_config — column is nullable."""
    sop = Sop(name="SOP Null Config")
    db_session.add(sop)
    await db_session.flush()

    step = SopStep(sop_id=sop.id, order=1, step_type=SopStepType.skill_invocation)
    db_session.add(step)
    await db_session.flush()
    await db_session.refresh(step)

    assert step.step_config is None


# ── Credential security: encrypted_credentials not leaked ─────────────────────


@pytest.mark.asyncio
async def test_mcp_session_encrypted_credentials_not_in_public_attributes(db_session: AsyncSession):
    """McpSession stores encrypted_credentials internally; schema does not expose it."""
    server = McpServer(
        name="Cred Server",
        slug="cred-server-sec",
        base_url="http://mcp.cred",
    )
    db_session.add(server)
    await db_session.flush()

    session = McpSession(
        server_id=server.id,
        name="Cred Session",
        auth_type=McpSessionAuthType.api_key,
        encrypted_credentials="ENCRYPTED:abc123",
    )
    db_session.add(session)
    await db_session.flush()
    await db_session.refresh(session)

    # The encrypted_credentials field exists on the model for internal use
    # but must not be present in McpSessionRead schema
    from app.schemas.mcp_hub import McpSessionRead
    read = McpSessionRead.model_validate(session)
    read_dict = read.model_dump()
    assert "encrypted_credentials" not in read_dict, (
        "encrypted_credentials must never appear in McpSessionRead response"
    )


# ── Skill instructions field ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_create_with_instructions(db_session: AsyncSession):
    """Create Skill with instructions field and verify persistence."""
    skill = Skill(
        name="Test Skill Instructions",
        description="A test skill",
        instructions="Call the tool with the user query as the first argument.",
    )
    db_session.add(skill)
    await db_session.flush()
    await db_session.refresh(skill)

    assert skill.instructions == "Call the tool with the user query as the first argument."


@pytest.mark.asyncio
async def test_skill_create_without_instructions_is_nullable(db_session: AsyncSession):
    """Create Skill without instructions — column is nullable."""
    skill = Skill(name="Skill No Instructions")
    db_session.add(skill)
    await db_session.flush()
    await db_session.refresh(skill)

    assert skill.instructions is None


# ── Default Skills Seeding ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_seeder_creates_save_result_in_db(db_session: AsyncSession):
    """SkillSeeder creates save_result skill in the database when it does not exist."""
    from app.services.skill_seeder import SkillSeeder
    from sqlalchemy import select

    seeder = SkillSeeder()
    summary = await seeder.run(db_session)

    assert summary["save_result"] == "created"

    result = await db_session.execute(select(Skill).where(Skill.name == "save_result"))
    skill = result.scalar_one_or_none()
    assert skill is not None
    assert skill.name == "save_result"
    assert skill.description is not None
    assert skill.instructions is not None
    assert skill.is_active is True


@pytest.mark.asyncio
async def test_skill_seeder_creates_send_notification_in_db(db_session: AsyncSession):
    """SkillSeeder creates send_notification skill in the database when it does not exist."""
    from app.services.skill_seeder import SkillSeeder
    from sqlalchemy import select

    seeder = SkillSeeder()
    summary = await seeder.run(db_session)

    assert summary["send_notification"] == "created"

    result = await db_session.execute(select(Skill).where(Skill.name == "send_notification"))
    skill = result.scalar_one_or_none()
    assert skill is not None
    assert skill.name == "send_notification"
    assert skill.description is not None
    assert skill.instructions is not None
    assert skill.is_active is True


@pytest.mark.asyncio
async def test_skill_seeder_both_default_skills_queryable_after_seed(db_session: AsyncSession):
    """After seeding, both save_result and send_notification are queryable by name."""
    from app.services.skill_seeder import SkillSeeder
    from sqlalchemy import select

    seeder = SkillSeeder()
    await seeder.run(db_session)

    result = await db_session.execute(
        select(Skill).where(Skill.name.in_(["save_result", "send_notification"]))
    )
    skills = list(result.scalars().all())
    names = {s.name for s in skills}
    assert "save_result" in names
    assert "send_notification" in names


@pytest.mark.asyncio
async def test_skill_seeder_is_idempotent_in_db(db_session: AsyncSession):
    """Running SkillSeeder twice does not create duplicate default skills."""
    from app.services.skill_seeder import SkillSeeder
    from sqlalchemy import select, func

    seeder = SkillSeeder()

    # First seed — creates both skills
    summary1 = await seeder.run(db_session)
    assert summary1["save_result"] == "created"
    assert summary1["send_notification"] == "created"

    # Second seed — both already exist
    summary2 = await seeder.run(db_session)
    assert summary2["save_result"] == "exists"
    assert summary2["send_notification"] == "exists"

    # Count must still be exactly 1 each
    count_result = await db_session.execute(
        select(func.count()).select_from(Skill).where(Skill.name == "save_result")
    )
    assert count_result.scalar_one() == 1

    count_result2 = await db_session.execute(
        select(func.count()).select_from(Skill).where(Skill.name == "send_notification")
    )
    assert count_result2.scalar_one() == 1


@pytest.mark.asyncio
async def test_skill_seeder_default_skill_is_mutable(db_session: AsyncSession):
    """A user can update a default skill's instructions after seeding."""
    from app.services.skill_seeder import SkillSeeder
    from sqlalchemy import select

    seeder = SkillSeeder()
    await seeder.run(db_session)

    result = await db_session.execute(select(Skill).where(Skill.name == "save_result"))
    skill = result.scalar_one()
    original_instructions = skill.instructions

    skill.instructions = "Updated custom instructions for save_result."
    await db_session.flush()
    await db_session.refresh(skill)

    assert skill.instructions == "Updated custom instructions for save_result."
    assert skill.instructions != original_instructions

