"""Integration tests for AgentRole identity assignment constraints.

Tests:
  - Create a role; assign an identity via agent_role_identities join table
  - Query identities assigned to a role → correct results
  - Remove identity from role → assignment removed
  - Runtime execution validates identity-role membership via join table (not type field)

Uses the shared SQLite in-memory engine from conftest.py (StaticPool).
Note: The conftest uses SQLAlchemy's `Base.metadata.create_all` which covers all declared
models, including the agent_role_identities join table.
"""
from __future__ import annotations

import uuid
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Test: assign identity to role via join table
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_identity_to_role_persists(db_session):
    """assign_identities creates an agent_role_identity record for the identity."""
    from app.services.agents.role_service import AgentRoleService
    from app.db.models.agents import AgentIdentity, AgentIdentityStatus, AgentIdentityType

    service = AgentRoleService()

    # Create a role
    role = await service.create_role(
        name=f"TestRole-{uuid.uuid4().hex[:6]}",
        description="For assignment test",
        sop_ids=[],
        skill_ids=[],
        db=db_session,
    )
    await db_session.commit()

    # Create an identity in the DB
    identity = AgentIdentity(
        name="Test Bot",
        identity_type=AgentIdentityType.realm_user,
        realm_name="ai_agents",
        realm_username=f"bot-{uuid.uuid4().hex[:6]}",
        status=AgentIdentityStatus.active,
    )
    db_session.add(identity)
    await db_session.flush()

    # Assign identity to role
    await service.assign_identities(role.id, [identity.id], db_session)
    await db_session.commit()

    # Verify assignment persisted
    is_assigned = await service.is_identity_assigned(role.id, identity.id, db_session)
    assert is_assigned is True


@pytest.mark.asyncio
async def test_assign_identity_twice_is_idempotent(db_session):
    """Assigning the same identity to the same role twice does not create duplicates."""
    from app.services.agents.role_service import AgentRoleService
    from app.db.models.agents import AgentIdentity, AgentIdentityStatus, AgentIdentityType

    service = AgentRoleService()

    role = await service.create_role(
        name=f"IdempotentRole-{uuid.uuid4().hex[:6]}",
        description=None,
        sop_ids=[],
        skill_ids=[],
        db=db_session,
    )
    await db_session.commit()

    identity = AgentIdentity(
        name="Idempotent Bot",
        identity_type=AgentIdentityType.realm_user,
        realm_name="ai_agents",
        realm_username=f"idem-{uuid.uuid4().hex[:6]}",
        status=AgentIdentityStatus.active,
    )
    db_session.add(identity)
    await db_session.flush()

    # Assign twice
    await service.assign_identities(role.id, [identity.id], db_session)
    await db_session.commit()
    await service.assign_identities(role.id, [identity.id], db_session)
    await db_session.commit()

    # List identities — should appear exactly once
    identities = await service.list_identities(role.id, db_session)
    matching = [i for i in identities if i.id == identity.id]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_remove_identity_from_role(db_session):
    """remove_identity removes the agent_role_identity record."""
    from app.services.agents.role_service import AgentRoleService
    from app.db.models.agents import AgentIdentity, AgentIdentityStatus, AgentIdentityType

    service = AgentRoleService()

    role = await service.create_role(
        name=f"RemoveRole-{uuid.uuid4().hex[:6]}",
        description=None,
        sop_ids=[],
        skill_ids=[],
        db=db_session,
    )
    await db_session.commit()

    identity = AgentIdentity(
        name="Removal Bot",        identity_type=AgentIdentityType.realm_user,        realm_name="ai_agents",
        realm_username=f"rem-{uuid.uuid4().hex[:6]}",
        status=AgentIdentityStatus.active,
    )
    db_session.add(identity)
    await db_session.flush()

    # Assign then remove
    await service.assign_identities(role.id, [identity.id], db_session)
    await db_session.commit()

    await service.remove_identity(role.id, identity.id, db_session)
    await db_session.commit()

    # Should no longer be assigned
    is_assigned = await service.is_identity_assigned(role.id, identity.id, db_session)
    assert is_assigned is False


# ---------------------------------------------------------------------------
# Test: runtime execution rejects when identity not assigned to role
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runtime_rejects_when_identity_not_assigned_to_role():
    """_execute_job raises PermissionDeniedError when identity is not in agent_role_identities.

    This validates the new assignment-based guard (not the old type-based guard).
    """
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.permission_manager import PermissionDeniedError
    from app.db.models.agents import AgentInputType, AgentOutputType

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    role_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()

    job = MagicMock()
    job.id = session_id
    job.agent_type_id = agent_type_id
    job.input_data = {}

    agent_type = MagicMock()
    agent_type.id = agent_type_id
    agent_type.identity_id = identity_id
    agent_type.role_id = role_id
    agent_type.model_id = "gpt-4o"
    agent_type.input_type = AgentInputType.typed
    agent_type.output_type = AgentOutputType.markdown
    agent_type.system_instruction = "test"
    agent_type.output_schema = None

    async def db_get_side_effect(model_class, pk):
        if pk == agent_type_id:
            return agent_type
        return None

    # agent_role_identities query returns None → not assigned
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.get = AsyncMock(side_effect=db_get_side_effect)
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(PermissionDeniedError):
        await executor._execute_job(job, db)


@pytest.mark.asyncio
async def test_runtime_accepts_when_identity_assigned_to_role():
    """_execute_job proceeds when identity IS present in agent_role_identities."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.db.models.agents import AgentInputType, AgentOutputType

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    role_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()

    job = MagicMock()
    job.id = session_id
    job.agent_type_id = agent_type_id
    job.input_data = {"query": "test"}

    agent_type = MagicMock()
    agent_type.id = agent_type_id
    agent_type.identity_id = identity_id
    agent_type.role_id = role_id
    agent_type.model_id = "gpt-4o"
    agent_type.input_type = AgentInputType.typed
    agent_type.output_type = AgentOutputType.markdown
    agent_type.system_instruction = "test"
    agent_type.output_schema = None

    async def db_get_side_effect(model_class, pk):
        if pk == agent_type_id:
            return agent_type
        return None

    # agent_role_identities query returns a row → identity IS assigned
    mock_row = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row

    db = AsyncMock()
    db.get = AsyncMock(side_effect=db_get_side_effect)
    db.execute = AsyncMock(return_value=mock_result)

    executor._run_task_loop = AsyncMock(return_value={"answer": "ok"})
    executor._log_execution_event = AsyncMock()
    executor._log_sops_skills = AsyncMock()
    executor._permission_manager.calculate_allowed_tools = AsyncMock(
        return_value={"save_result"}
    )

    # Should not raise
    result = await executor._execute_job(job, db)
    assert result == {"answer": "ok"}


@pytest.mark.asyncio
async def test_runtime_accepts_empty_allowed_identity_types():
    """_execute_job does not raise when allowed_identity_types is empty (no restriction)."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.db.models.agents import AgentInputType, AgentOutputType

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    role_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()

    job = MagicMock()
    job.id = session_id
    job.agent_type_id = agent_type_id
    job.input_data = {"query": "test"}

    agent_type = MagicMock()
    agent_type.id = agent_type_id
    agent_type.identity_id = identity_id
    agent_type.role_id = role_id
    agent_type.model_id = "gpt-4o"
    agent_type.input_type = AgentInputType.typed
    agent_type.output_type = AgentOutputType.markdown
    agent_type.system_instruction = "test"
    agent_type.output_schema = None

    identity = MagicMock()
    identity.identity_type = MagicMock()
    identity.identity_type.value = "agent_user"

    # Empty allowed_identity_types means no restriction
    role = MagicMock()
    role.allowed_identity_types = []

    async def db_get_side_effect(model_class, pk):
        if pk == agent_type_id:
            return agent_type
        if pk == identity_id:
            return identity
        if pk == role_id:
            return role
        return None

    db = AsyncMock()
    db.get = AsyncMock(side_effect=db_get_side_effect)

    executor._run_task_loop = AsyncMock(return_value={"answer": "ok"})
    executor._log_execution_event = AsyncMock()
    executor._log_sops_skills = AsyncMock()
    executor._permission_manager.calculate_allowed_tools = AsyncMock(
        return_value={"save_result"}
    )

    # Should not raise
    result = await executor._execute_job(job, db)
    assert result == {"answer": "ok"}
