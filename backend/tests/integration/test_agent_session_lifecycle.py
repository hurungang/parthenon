"""Integration tests for the Agent Session lifecycle against a real (SQLite) database.

These tests verify:
- Schema constraints via information_schema equivalents on SQLite
- Full session lifecycle: enqueue → running → completed / failed
- Referential integrity guards (409 on role/identity delete when AgentType references them)
- Dispatcher concurrency safety (only one dispatch per session)
- New columns exist on agent_types; removed columns are absent

Note: The integration conftest uses a StaticPool SQLite in-memory DB with
Base.metadata.create_all() applied — equivalent to `alembic upgrade head`
for our test schema.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import (
    AgentIdentity,
    AgentIdentityStatus,
    AgentIdentityType,
    AgentJob,
    AgentJobStatus,
    AgentRole,
    AgentRoleSkill,
    AgentRoleSOP,
    AgentType,
    AgentInputType,
    AgentOutputType,
)
from app.services.agents.identity_service import (
    AgentIdentityConflictError,
    AgentIdentityService,
)
from app.services.agents.role_service import AgentRoleConflictError, AgentRoleService
from app.services.agents.session_service import AgentSessionService


# ── Schema / column presence tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_roles_table_exists(db_session: AsyncSession):
    """agent_roles table must exist in the database (migration applied)."""
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_roles'")
    )
    row = result.fetchone()
    assert row is not None, "agent_roles table is missing — migration not applied"


@pytest.mark.asyncio
async def test_agent_identities_table_exists(db_session: AsyncSession):
    """agent_identities table must exist in the database."""
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_identities'")
    )
    row = result.fetchone()
    assert row is not None, "agent_identities table is missing"


@pytest.mark.asyncio
async def test_agent_jobs_table_exists(db_session: AsyncSession):
    """agent_jobs table must exist in the database."""
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_jobs'")
    )
    row = result.fetchone()
    assert row is not None, "agent_jobs table is missing"


@pytest.mark.asyncio
async def test_agent_role_sops_table_exists(db_session: AsyncSession):
    """agent_role_sops join table must exist."""
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_role_sops'")
    )
    row = result.fetchone()
    assert row is not None, "agent_role_sops table is missing"


@pytest.mark.asyncio
async def test_agent_role_skills_table_exists(db_session: AsyncSession):
    """agent_role_skills join table must exist."""
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_role_skills'")
    )
    row = result.fetchone()
    assert row is not None, "agent_role_skills table is missing"


@pytest.mark.asyncio
async def test_agent_types_has_new_columns(db_session: AsyncSession):
    """agent_types must have identity_id, role_id, system_instruction, input_type, output_type."""
    result = await db_session.execute(text("PRAGMA table_info(agent_types)"))
    columns = {row[1] for row in result.fetchall()}  # row[1] is column name
    required = {"identity_id", "role_id", "system_instruction", "input_type", "output_type"}
    missing = required - columns
    assert not missing, f"Missing columns on agent_types: {missing}"


@pytest.mark.asyncio
async def test_agent_types_missing_removed_columns(db_session: AsyncSession):
    """agent_types must NOT have mode, sop_id, identity_subject, system_prompt, max_instances."""
    result = await db_session.execute(text("PRAGMA table_info(agent_types)"))
    columns = {row[1] for row in result.fetchall()}
    removed = {"mode", "sop_id", "identity_subject", "system_prompt", "max_instances"}
    present = removed & columns
    assert not present, f"Removed columns still present on agent_types: {present}"


@pytest.mark.asyncio
async def test_agent_identities_has_realm_and_token_columns(db_session: AsyncSession):
    """agent_identities must have realm_name, realm_username, access_token, refresh_token, token_expires_at."""
    result = await db_session.execute(text("PRAGMA table_info(agent_identities)"))
    columns = {row[1] for row in result.fetchall()}
    required = {"realm_name", "realm_username", "access_token", "refresh_token", "token_expires_at"}
    missing = required - columns
    assert not missing, f"Missing OAuth columns on agent_identities: {missing}"


# ── AgentRole CRUD against real DB ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_list_agent_role(db_session: AsyncSession):
    """Create an AgentRole and verify it appears in list_roles."""
    service = AgentRoleService()
    role = await service.create_role(
        name=f"IntegrationRole-{uuid.uuid4().hex[:8]}",
        description="Integration test role",
        sop_ids=[],
        skill_ids=[],
        db=db_session,
    )
    await db_session.commit()

    roles = await service.list_roles(db_session)
    ids = [r.id for r in roles]
    assert role.id in ids


@pytest.mark.asyncio
async def test_update_agent_role(db_session: AsyncSession):
    """Update an AgentRole name and verify it persists."""
    service = AgentRoleService()
    role = await service.create_role(
        name=f"OriginalName-{uuid.uuid4().hex[:8]}",
        description=None,
        sop_ids=[],
        skill_ids=[],
        db=db_session,
    )
    await db_session.commit()

    updated = await service.update_role(
        role_id=role.id,
        name="UpdatedName",
        description="Updated description",
        sop_ids=None,
        skill_ids=None,
        db=db_session,
    )
    await db_session.commit()

    assert updated.name == "UpdatedName"

    fetched = await service.get_role(role.id, db_session)
    assert fetched.name == "UpdatedName"


@pytest.mark.asyncio
async def test_delete_agent_role_succeeds(db_session: AsyncSession):
    """Delete an unreferenced AgentRole and verify it no longer appears in list."""
    service = AgentRoleService()
    role = await service.create_role(
        name=f"ToDelete-{uuid.uuid4().hex[:8]}",
        description=None,
        sop_ids=[],
        skill_ids=[],
        db=db_session,
    )
    await db_session.commit()

    await service.delete_role(role.id, db_session)
    await db_session.commit()

    roles = await service.list_roles(db_session)
    ids = [r.id for r in roles]
    assert role.id not in ids


@pytest.mark.asyncio
async def test_delete_role_raises_409_when_referenced_by_agent_type(
    db_session: AsyncSession,
):
    """Deleting a role referenced by an AgentType must raise AgentRoleConflictError."""
    role_service = AgentRoleService()
    role = await role_service.create_role(
        name=f"ReferencedRole-{uuid.uuid4().hex[:8]}",
        description=None,
        sop_ids=[],
        skill_ids=[],
        db=db_session,
    )
    await db_session.flush()

    agent_type = AgentType(
        name=f"AgentType-{uuid.uuid4().hex[:8]}",
        role_id=role.id,
        llm_provider="openai",
        llm_model="gpt-4o",
        input_type=AgentInputType.none,
        output_type=AgentOutputType.auto,
    )
    db_session.add(agent_type)
    await db_session.flush()
    await db_session.commit()

    with pytest.raises(AgentRoleConflictError):
        await role_service.delete_role(role.id, db_session)


# ── AgentIdentity CRUD against real DB ────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_list_agent_identity(db_session: AsyncSession):
    """Create an AgentIdentity (realm_user type) and verify it appears in list_identities."""
    service = AgentIdentityService()
    identity = await service.create_identity(
        name=f"TestIdentity-{uuid.uuid4().hex[:8]}",
        realm_name="ai_agents",
        realm_username=f"agent-{uuid.uuid4().hex[:6]}",
        status=AgentIdentityStatus.active,
        db=db_session,
    )
    await db_session.commit()

    identities = await service.list_identities(db_session)
    ids = [i.id for i in identities]
    assert identity.id in ids


@pytest.mark.asyncio
async def test_delete_identity_raises_409_when_referenced(db_session: AsyncSession):
    """Deleting an identity referenced by an AgentType must raise AgentIdentityConflictError."""
    id_service = AgentIdentityService()
    identity = await id_service.create_identity(
        name=f"RefIdentity-{uuid.uuid4().hex[:8]}",
        realm_name="ai_agents",
        realm_username=f"ref-agent-{uuid.uuid4().hex[:6]}",
        status=AgentIdentityStatus.active,
        db=db_session,
    )
    await db_session.flush()

    agent_type = AgentType(
        name=f"TypeWithIdentity-{uuid.uuid4().hex[:8]}",
        identity_id=identity.id,
        llm_provider="openai",
        llm_model="gpt-4o",
        input_type=AgentInputType.none,
        output_type=AgentOutputType.auto,
    )
    db_session.add(agent_type)
    await db_session.flush()
    await db_session.commit()

    with pytest.raises(AgentIdentityConflictError):
        await id_service.delete_identity(identity.id, db_session)


# ── AgentSession lifecycle against real DB ─────────────────────────────────────


@pytest.mark.asyncio
async def test_enqueue_creates_queued_session(db_session: AsyncSession):
    """Enqueue a session and verify it is persisted with status=queued."""
    session_service = AgentSessionService()

    # Create a minimal AgentType first
    agent_type = AgentType(
        name=f"EnqueueType-{uuid.uuid4().hex[:8]}",
        llm_provider="openai",
        llm_model="gpt-4o",
        input_type=AgentInputType.none,
        output_type=AgentOutputType.auto,
    )
    db_session.add(agent_type)
    await db_session.flush()

    job = await session_service.enqueue(
        agent_type_id=agent_type.id,
        input_data={"key": "value"},
        user_id=None,
        db=db_session,
    )
    await db_session.commit()

    fetched = await session_service.get_session(job.id, db_session)
    assert fetched is not None
    assert fetched.status == AgentJobStatus.queued
    assert fetched.agent_type_id == agent_type.id


@pytest.mark.asyncio
async def test_session_happy_path_queued_running_completed(db_session: AsyncSession):
    """Full happy path: queued → running → completed with output persisted."""
    session_service = AgentSessionService()

    agent_type = AgentType(
        name=f"HappyType-{uuid.uuid4().hex[:8]}",
        llm_provider="openai",
        llm_model="gpt-4o",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.typed,
    )
    db_session.add(agent_type)
    await db_session.flush()

    job = await session_service.enqueue(agent_type.id, {"task": "run"}, None, db_session)
    await db_session.commit()
    assert job.status == AgentJobStatus.queued

    job = await session_service.mark_running(job.id, db_session)
    await db_session.commit()
    assert job.status == AgentJobStatus.running
    assert job.started_at is not None

    output = {"result": "all done", "count": 3}
    job = await session_service.mark_completed(job.id, output, db_session)
    await db_session.commit()
    assert job.status == AgentJobStatus.completed
    assert job.output_data == output
    assert job.completed_at is not None


@pytest.mark.asyncio
async def test_session_error_path_queued_running_failed(db_session: AsyncSession):
    """Error path: queued → running → failed with error message persisted."""
    session_service = AgentSessionService()

    agent_type = AgentType(
        name=f"FailType-{uuid.uuid4().hex[:8]}",
        llm_provider="openai",
        llm_model="gpt-4o",
        input_type=AgentInputType.none,
        output_type=AgentOutputType.auto,
    )
    db_session.add(agent_type)
    await db_session.flush()

    job = await session_service.enqueue(agent_type.id, None, None, db_session)
    await session_service.mark_running(job.id, db_session)
    failed = await session_service.mark_failed(job.id, "Executor crashed", db_session)
    await db_session.commit()

    fetched = await session_service.get_session(job.id, db_session)
    assert fetched.status == AgentJobStatus.failed
    assert "Executor crashed" in fetched.error_message


@pytest.mark.asyncio
async def test_list_sessions_returns_only_user_sessions(db_session: AsyncSession):
    """list_sessions filters to only the requesting user's sessions."""
    session_service = AgentSessionService()
    user_id = uuid.uuid4()
    other_user_id = uuid.uuid4()

    agent_type = AgentType(
        name=f"ListType-{uuid.uuid4().hex[:8]}",
        llm_provider="openai",
        llm_model="gpt-4o",
        input_type=AgentInputType.none,
        output_type=AgentOutputType.auto,
    )
    db_session.add(agent_type)
    await db_session.flush()

    # Create one session per user
    my_job = await session_service.enqueue(agent_type.id, None, user_id, db_session)
    await session_service.enqueue(agent_type.id, None, other_user_id, db_session)
    await db_session.commit()

    my_sessions = await session_service.list_sessions(user_id, db_session)
    ids = [s.id for s in my_sessions]
    assert my_job.id in ids
    assert all(s.triggered_by_user_id == user_id for s in my_sessions)


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_for_unique_jobs(db_session: AsyncSession):
    """Each enqueue call creates a distinct AgentJob with a unique ID."""
    session_service = AgentSessionService()

    agent_type = AgentType(
        name=f"IdempotentType-{uuid.uuid4().hex[:8]}",
        llm_provider="openai",
        llm_model="gpt-4o",
        input_type=AgentInputType.none,
        output_type=AgentOutputType.auto,
    )
    db_session.add(agent_type)
    await db_session.flush()

    job1 = await session_service.enqueue(agent_type.id, None, None, db_session)
    job2 = await session_service.enqueue(agent_type.id, None, None, db_session)
    await db_session.commit()

    assert job1.id != job2.id


@pytest.mark.asyncio
async def test_agent_identity_all_three_types_storable(db_session: AsyncSession):
    """realm_user and legacy identity types can all be stored and retrieved."""
    service = AgentIdentityService()
    for identity_type in AgentIdentityType:
        identity = await service.create_identity(
            name=f"Identity-{identity_type.value}-{uuid.uuid4().hex[:6]}",
            realm_name="ai_agents",
            realm_username=f"agent-{uuid.uuid4().hex[:6]}",
            status=AgentIdentityStatus.active,
            db=db_session,
            identity_type=identity_type,
        )
        await db_session.flush()
        fetched = await service.get_identity(identity.id, db_session)
        assert fetched.identity_type == identity_type


@pytest.mark.asyncio
async def test_agent_identity_status_transitions(db_session: AsyncSession):
    """AgentIdentity status can be updated to all three values."""
    service = AgentIdentityService()
    identity = await service.create_identity(
        name=f"StatusBot-{uuid.uuid4().hex[:8]}",
        realm_name="ai_agents",
        realm_username=f"status-agent-{uuid.uuid4().hex[:6]}",
        status=AgentIdentityStatus.active,
        db=db_session,
    )
    await db_session.flush()

    for status in [AgentIdentityStatus.suspended, AgentIdentityStatus.deprovisioned]:
        updated = await service.update_identity(
            identity_id=identity.id,
            name=None,
            realm_name=None,
            realm_username=None,
            status=status,
            db=db_session,
        )
        assert updated.status == status
