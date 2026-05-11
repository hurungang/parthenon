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
    ModelConfig,
    ModelProvider,
)
from app.services.agents.identity_service import (
    AgentIdentityConflictError,
    AgentIdentityService,
)
from app.services.agents.model_config_service import (
    ModelConfigConflictError,
    ModelConfigService,
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
        model_id="gpt-4o",
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
        model_id="gpt-4o",
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
        model_id="gpt-4o",
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
        model_id="gpt-4o",
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
        model_id="gpt-4o",
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
        model_id="gpt-4o",
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
        model_id="gpt-4o",
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


# ── ModelConfig schema + CRUD against real DB ──────────────────────────────────


@pytest.mark.asyncio
async def test_model_configs_table_exists(db_session: AsyncSession):
    """model_configs table must exist (migration applied for model config feature)."""
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='model_configs'")
    )
    row = result.fetchone()
    assert row is not None, "model_configs table is missing — migration not applied"


@pytest.mark.asyncio
async def test_model_configs_has_required_columns(db_session: AsyncSession):
    """model_configs must have provider_type, api_base_url, encrypted_api_key, enabled_models columns."""
    result = await db_session.execute(text("PRAGMA table_info(model_configs)"))
    columns = {row[1] for row in result.fetchall()}
    required = {"id", "display_name", "provider_type", "api_base_url", "encrypted_api_key", "enabled_models"}
    missing = required - columns
    assert not missing, f"Missing columns on model_configs: {missing}"


@pytest.mark.asyncio
async def test_agent_types_has_model_id_column(db_session: AsyncSession):
    """agent_types must have model_id column (plain string, no FK to model_configs)."""
    result = await db_session.execute(text("PRAGMA table_info(agent_types)"))
    columns = {row[1] for row in result.fetchall()}
    assert "model_id" in columns, "model_id column missing from agent_types"


@pytest.mark.asyncio
async def test_agent_types_missing_model_config_id_column(db_session: AsyncSession):
    """agent_types must NOT have model_config_id or model_name columns (removed by migration)."""
    result = await db_session.execute(text("PRAGMA table_info(agent_types)"))
    columns = {row[1] for row in result.fetchall()}
    removed = {"model_config_id", "model_name"}
    present = removed & columns
    assert not present, f"Removed model-FK columns still present on agent_types: {present}"


@pytest.mark.asyncio
async def test_create_and_list_model_config(db_session: AsyncSession):
    """Create a ModelConfig and verify it appears in list_model_configs."""
    from unittest.mock import patch, MagicMock

    service = ModelConfigService()
    vault = MagicMock()
    vault.encrypt = MagicMock(return_value="enc:test-key")

    with patch("app.services.agents.model_config_service.get_vault", return_value=vault):
        config = await service.create_model_config(
            display_name=f"IntTestConfig-{uuid.uuid4().hex[:8]}",
            provider_type=ModelProvider.openai,
            api_base_url="https://api.openai.com/v1",
            api_key="sk-testkey",
            enabled_models=[],
            db=db_session,
        )
        await db_session.commit()

    configs = await service.list_model_configs(db_session)
    ids = [c.id for c in configs]
    assert config.id in ids


@pytest.mark.asyncio
async def test_model_config_api_key_stored_encrypted(db_session: AsyncSession):
    """Stored ModelConfig must have encrypted_api_key set, not plaintext."""
    from unittest.mock import patch, MagicMock

    service = ModelConfigService()
    vault = MagicMock()
    vault.encrypt = MagicMock(return_value="enc:stored-key")

    with patch("app.services.agents.model_config_service.get_vault", return_value=vault):
        config = await service.create_model_config(
            display_name=f"EncTest-{uuid.uuid4().hex[:8]}",
            provider_type=ModelProvider.anthropic,
            api_base_url=None,
            api_key="sk-plain",
            enabled_models=[],
            db=db_session,
        )
        await db_session.commit()

    fetched = await service.get_model_config(config.id, db_session)
    # Encrypted key stored — must not be the plaintext value
    assert fetched.encrypted_api_key != "sk-plain"
    # And it must be the value our vault returned
    assert fetched.encrypted_api_key == "enc:stored-key"


@pytest.mark.asyncio
async def test_update_model_config_persists_changes(db_session: AsyncSession):
    """Update a ModelConfig name and verify it persists in the database."""
    from unittest.mock import patch, MagicMock

    service = ModelConfigService()
    vault = MagicMock()
    vault.encrypt = MagicMock(return_value="enc:any")

    with patch("app.services.agents.model_config_service.get_vault", return_value=vault):
        config = await service.create_model_config(
            display_name=f"Original-{uuid.uuid4().hex[:8]}",
            provider_type=ModelProvider.litellm_proxy,
            api_base_url="http://proxy:4000",
            api_key=None,
            enabled_models=[],
            db=db_session,
        )
        await db_session.commit()

        updated = await service.update_model_config(
            config.id,
            display_name="Updated Name",
            provider_type=None,
            api_base_url=None,
            api_key=None,
            enabled_models=None,
            db=db_session,
        )
        await db_session.commit()

    assert updated.display_name == "Updated Name"

    fetched = await service.get_model_config(config.id, db_session)
    assert fetched.display_name == "Updated Name"


@pytest.mark.asyncio
async def test_delete_model_config_raises_409_when_model_id_in_use(
    db_session: AsyncSession,
):
    """Deleting a ModelConfig raises ModelConfigConflictError when an AgentType.model_id
    matches one of its enabled_models entries."""
    from unittest.mock import patch, MagicMock

    service = ModelConfigService()
    vault = MagicMock()
    vault.encrypt = MagicMock(return_value="enc:key")

    with patch("app.services.agents.model_config_service.get_vault", return_value=vault):
        config = await service.create_model_config(
            display_name=f"RefConfig-{uuid.uuid4().hex[:8]}",
            provider_type=ModelProvider.openai,
            api_base_url=None,
            api_key="sk-key",
            enabled_models=["gpt-4o"],
            db=db_session,
        )
        await db_session.flush()

    # Create an AgentType whose model_id is in the config's enabled_models
    agent_type = AgentType(
        name=f"TypeWithModelId-{uuid.uuid4().hex[:8]}",
        model_id="gpt-4o",
        input_type=AgentInputType.none,
        output_type=AgentOutputType.auto,
    )
    db_session.add(agent_type)
    await db_session.flush()
    await db_session.commit()

    with pytest.raises(ModelConfigConflictError):
        await service.delete_model_config(config.id, db_session)


@pytest.mark.asyncio
async def test_session_with_model_id_persists(db_session: AsyncSession):
    """AgentJob session for an AgentType with model_id (plain string) enqueues correctly."""
    from unittest.mock import patch, MagicMock

    mc_service = ModelConfigService()
    vault = MagicMock()
    vault.encrypt = MagicMock(return_value="enc:k")

    with patch("app.services.agents.model_config_service.get_vault", return_value=vault):
        await mc_service.create_model_config(
            display_name=f"SessionConfig-{uuid.uuid4().hex[:8]}",
            provider_type=ModelProvider.openai,
            api_base_url=None,
            api_key="sk-test",
            enabled_models=["gpt-4o"],
            db=db_session,
        )
        await db_session.flush()

    # AgentType references the model by model_id string, no FK
    agent_type = AgentType(
        name=f"ModelBoundAgent-{uuid.uuid4().hex[:8]}",
        model_id="gpt-4o",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.typed,
    )
    db_session.add(agent_type)
    await db_session.flush()

    session_service = AgentSessionService()
    job = await session_service.enqueue(agent_type.id, {"query": "test"}, None, db_session)
    await db_session.commit()

    fetched = await session_service.get_session(job.id, db_session)
    assert fetched is not None
    assert fetched.status == AgentJobStatus.queued


@pytest.mark.asyncio
async def test_enabled_models_persisted_and_updated(db_session: AsyncSession):
    """ModelConfig.enabled_models is persisted on create and updated correctly."""
    from unittest.mock import patch, MagicMock

    service = ModelConfigService()
    vault = MagicMock()
    vault.encrypt = MagicMock(return_value="enc:k")

    with patch("app.services.agents.model_config_service.get_vault", return_value=vault):
        config = await service.create_model_config(
            display_name=f"EnabledModels-{uuid.uuid4().hex[:8]}",
            provider_type=ModelProvider.openai,
            api_base_url=None,
            api_key="sk-test",
            enabled_models=["gpt-4o"],
            db=db_session,
        )
        await db_session.commit()

    fetched = await service.get_model_config(config.id, db_session)
    assert fetched.enabled_models == ["gpt-4o"]

    with patch("app.services.agents.model_config_service.get_vault", return_value=vault):
        await service.update_model_config(
            config.id,
            display_name=None,
            provider_type=None,
            api_base_url=None,
            api_key=None,
            enabled_models=["gpt-4o", "gpt-4-turbo"],
            db=db_session,
        )
        await db_session.commit()

    updated = await service.get_model_config(config.id, db_session)
    assert set(updated.enabled_models) == {"gpt-4o", "gpt-4-turbo"}


@pytest.mark.asyncio
async def test_resolve_model_config_from_real_db(db_session: AsyncSession):
    """ModelBindingLayer.resolve_model_config finds the correct ModelConfig from real DB."""
    from unittest.mock import patch, MagicMock
    from app.services.agents.model_binding import ModelBindingLayer

    service = ModelConfigService()
    vault = MagicMock()
    vault.encrypt = MagicMock(return_value="enc:k")

    with patch("app.services.agents.model_config_service.get_vault", return_value=vault):
        config = await service.create_model_config(
            display_name=f"BindingConfig-{uuid.uuid4().hex[:8]}",
            provider_type=ModelProvider.anthropic,
            api_base_url=None,
            api_key="sk-test",
            enabled_models=["claude-sonnet-4-5"],
            db=db_session,
        )
        await db_session.commit()

    layer = ModelBindingLayer()
    resolved = await layer.resolve_model_config("claude-sonnet-4-5", db_session)
    assert resolved.id == config.id
    assert resolved.provider_type == ModelProvider.anthropic


@pytest.mark.asyncio
async def test_resolve_model_config_raises_from_real_db(db_session: AsyncSession):
    """ModelBindingLayer.resolve_model_config raises ModelBindingError from real DB when not found."""
    from app.services.agents.model_binding import ModelBindingError, ModelBindingLayer

    layer = ModelBindingLayer()
    # No ModelConfig in the test DB has 'nonexistent-model-xyz' in enabled_models
    with pytest.raises(ModelBindingError):
        await layer.resolve_model_config("nonexistent-model-xyz", db_session)


# ── AgentPermissionManager tests (regression for SopStepType.skill bug) ────────


def test_sop_step_type_enum_has_skill_invocation_not_skill():
    """SopStepType must have 'skill_invocation' value and must NOT have 'skill'.

    Regression guard for the bug where SopStepType.skill was used instead of
    SopStepType.skill_invocation in permission_manager.py, causing AttributeError
    when starting an agent session that had SOP steps.
    """
    from app.db.models.skills import SopStepType

    # Correct value must exist
    assert hasattr(SopStepType, "skill_invocation"), (
        "SopStepType.skill_invocation is missing — permission_manager will crash"
    )
    assert SopStepType.skill_invocation.value == "skill_invocation"

    # Incorrect value that caused the bug must NOT exist
    assert not hasattr(SopStepType, "skill"), (
        "SopStepType.skill must not exist; use SopStepType.skill_invocation"
    )


@pytest.mark.asyncio
async def test_permission_manager_resolves_tools_from_direct_skills(
    db_session: AsyncSession,
):
    """calculate_allowed_tools returns tool identifiers for a role with direct skill assignments.

    Tests the direct-skill code path in AgentPermissionManager._resolve_allowed_tools
    (the AgentRoleSkill → Skill → SkillToolBinding → McpTool chain).
    """
    from app.db.models.mcp_hub import McpServer, McpTool
    from app.db.models.skills import Skill, SkillToolBinding
    from app.services.agents.permission_manager import AgentPermissionManager

    suffix = uuid.uuid4().hex[:8]

    # 1. Create MCP server + tool
    server = McpServer(
        name=f"test-server-{suffix}",
        slug=f"test-srv-{suffix}",
        base_url="http://localhost:9999",
    )
    db_session.add(server)
    await db_session.flush()

    tool = McpTool(
        server_id=server.id,
        name=f"test-srv-{suffix}/my_tool_{suffix}",  # namespaced: mcp_slug/tool_name
        original_name=f"my_tool_{suffix}",
        description="Integration test tool",
    )
    db_session.add(tool)
    await db_session.flush()

    # 2. Create a Skill bound to the tool
    skill = Skill(name=f"test-skill-{suffix}", description="Integration test skill")
    db_session.add(skill)
    await db_session.flush()

    binding = SkillToolBinding(skill_id=skill.id, tool_id=tool.id, order=0)
    db_session.add(binding)
    await db_session.flush()

    # 3. Create a role and directly assign the skill
    role_service = AgentRoleService()
    role = await role_service.create_role(
        name=f"DirectSkillRole-{suffix}",
        description=None,
        sop_ids=[],
        skill_ids=[skill.id],
        db=db_session,
    )
    await db_session.commit()

    # 4. Resolve allowed tools — must include the tool in "mcp_slug/tool_name" format
    manager = AgentPermissionManager()
    manager.invalidate(role.id)  # ensure no stale cache
    allowed = await manager.calculate_allowed_tools(role.id, db_session)

    expected_identifier = f"test-srv-{suffix}/my_tool_{suffix}"
    assert expected_identifier in allowed, (
        f"Expected '{expected_identifier}' in allowed tools {allowed}"
    )
    # save_result is always injected
    assert "save_result" in allowed


@pytest.mark.asyncio
async def test_permission_manager_resolves_tools_from_sop_skill_invocation_steps(
    db_session: AsyncSession,
):
    """calculate_allowed_tools returns tool identifiers from SOP skill_invocation steps.

    This test specifically exercises the SOP path in _resolve_allowed_tools and would
    have caught the SopStepType.skill bug: if the filter used SopStepType.skill (which
    does not exist) an AttributeError would be raised, or if it silently evaluated to
    False no tools would be returned.

    Regression test for: permission_manager.py used SopStepType.skill instead of
    SopStepType.skill_invocation, causing agent session startup to fail.
    """
    from app.db.models.mcp_hub import McpServer, McpTool
    from app.db.models.skills import Skill, SkillToolBinding, Sop, SopStep, SopStepType
    from app.services.agents.permission_manager import AgentPermissionManager

    suffix = uuid.uuid4().hex[:8]

    # 1. Create MCP server + tool
    server = McpServer(
        name=f"sop-server-{suffix}",
        slug=f"sop-srv-{suffix}",
        base_url="http://localhost:9998",
    )
    db_session.add(server)
    await db_session.flush()

    tool = McpTool(
        server_id=server.id,
        name=f"sop-srv-{suffix}/sop_tool_{suffix}",  # namespaced: mcp_slug/tool_name
        original_name=f"sop_tool_{suffix}",
        description="SOP integration test tool",
    )
    db_session.add(tool)
    await db_session.flush()

    # 2. Create a Skill bound to the tool
    skill = Skill(name=f"sop-skill-{suffix}", description="SOP skill")
    db_session.add(skill)
    await db_session.flush()

    binding = SkillToolBinding(skill_id=skill.id, tool_id=tool.id, order=0)
    db_session.add(binding)
    await db_session.flush()

    # 3. Create a SOP with one skill_invocation step (uses the correct enum value)
    sop = Sop(name=f"test-sop-{suffix}", description="Integration test SOP")
    db_session.add(sop)
    await db_session.flush()

    step = SopStep(
        sop_id=sop.id,
        order=1,
        step_type=SopStepType.skill_invocation,  # must be this, NOT SopStepType.skill
        skill_id=skill.id,
        name="Invoke test skill",
    )
    db_session.add(step)
    await db_session.flush()

    # 4. Create a role with the SOP assigned (no direct skills)
    role_service = AgentRoleService()
    role = await role_service.create_role(
        name=f"SopRole-{suffix}",
        description=None,
        sop_ids=[sop.id],
        skill_ids=[],
        db=db_session,
    )
    await db_session.commit()

    # 5. Resolve allowed tools via permission_manager — must walk SOP steps
    manager = AgentPermissionManager()
    manager.invalidate(role.id)
    allowed = await manager.calculate_allowed_tools(role.id, db_session)

    expected_identifier = f"sop-srv-{suffix}/sop_tool_{suffix}"
    assert expected_identifier in allowed, (
        f"Expected '{expected_identifier}' in allowed tools {allowed}. "
        "If this is empty, SopStepType.skill_invocation filter may be broken."
    )
    assert "save_result" in allowed


@pytest.mark.asyncio
async def test_permission_manager_agent_delegation_steps_not_included_in_tools(
    db_session: AsyncSession,
):
    """agent_delegation SOP steps must not contribute tool identifiers.

    Only skill_invocation steps contribute tools. This ensures the step_type
    filter in _resolve_allowed_tools is working as intended.
    """
    from app.db.models.skills import Sop, SopStep, SopStepType
    from app.services.agents.permission_manager import AgentPermissionManager

    suffix = uuid.uuid4().hex[:8]

    # SOP with only an agent_delegation step (no skill_id)
    sop = Sop(name=f"delegation-sop-{suffix}", description="Delegation SOP")
    db_session.add(sop)
    await db_session.flush()

    step = SopStep(
        sop_id=sop.id,
        order=1,
        step_type=SopStepType.agent_delegation,
        skill_id=None,
        target_agent_type_id=None,
        name="Delegate to other agent",
    )
    db_session.add(step)
    await db_session.flush()

    role_service = AgentRoleService()
    role = await role_service.create_role(
        name=f"DelegationRole-{suffix}",
        description=None,
        sop_ids=[sop.id],
        skill_ids=[],
        db=db_session,
    )
    await db_session.commit()

    manager = AgentPermissionManager()
    manager.invalidate(role.id)
    allowed = await manager.calculate_allowed_tools(role.id, db_session)

    # Only save_result should be present — no tools from agent_delegation step
    assert allowed == {"save_result"}, (
        f"Expected only save_result for delegation-only role, got: {allowed}"
    )


@pytest.mark.asyncio
async def test_full_agent_session_with_sop_and_permission_resolution(
    db_session: AsyncSession,
):
    """End-to-end: create agent type with SOP, enqueue session, resolve permissions.

    Simulates the complete lifecycle that failed due to the SopStepType.skill bug:
    1. Create all required entities (server, tool, skill, SOP, role, agent type)
    2. Enqueue an agent session
    3. Call calculate_allowed_tools() — this would raise AttributeError with the bug
    4. Verify session exists with expected status
    """
    from app.db.models.mcp_hub import McpServer, McpTool
    from app.db.models.skills import Skill, SkillToolBinding, Sop, SopStep, SopStepType
    from app.services.agents.permission_manager import AgentPermissionManager

    suffix = uuid.uuid4().hex[:8]

    # Infrastructure: MCP server + tool
    server = McpServer(
        name=f"e2e-server-{suffix}",
        slug=f"e2e-srv-{suffix}",
        base_url="http://localhost:9997",
    )
    db_session.add(server)
    await db_session.flush()

    tool = McpTool(
        server_id=server.id,
        name=f"e2e-srv-{suffix}/e2e_tool_{suffix}",  # namespaced: mcp_slug/tool_name
        original_name=f"e2e_tool_{suffix}",
    )
    db_session.add(tool)
    await db_session.flush()

    # Skill + binding
    skill = Skill(name=f"e2e-skill-{suffix}")
    db_session.add(skill)
    await db_session.flush()

    db_session.add(SkillToolBinding(skill_id=skill.id, tool_id=tool.id, order=0))
    await db_session.flush()

    # SOP with skill_invocation step
    sop = Sop(name=f"e2e-sop-{suffix}")
    db_session.add(sop)
    await db_session.flush()

    db_session.add(SopStep(
        sop_id=sop.id,
        order=1,
        step_type=SopStepType.skill_invocation,
        skill_id=skill.id,
    ))
    await db_session.flush()

    # Role with SOP
    role_service = AgentRoleService()
    role = await role_service.create_role(
        name=f"E2ERole-{suffix}",
        description=None,
        sop_ids=[sop.id],
        skill_ids=[],
        db=db_session,
    )
    await db_session.flush()

    # Agent type with the role
    agent_type = AgentType(
        name=f"E2EAgent-{suffix}",
        role_id=role.id,
        model_id="gpt-4o",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
    )
    db_session.add(agent_type)
    await db_session.flush()

    # Enqueue a session
    session_service = AgentSessionService()
    job = await session_service.enqueue(
        agent_type_id=agent_type.id,
        input_data={"task": "run e2e test"},
        user_id=None,
        db=db_session,
    )
    await db_session.commit()

    # Session created successfully
    fetched = await session_service.get_session(job.id, db_session)
    assert fetched is not None
    assert fetched.status == AgentJobStatus.queued

    # Resolve permissions — this is the call that crashed with SopStepType.skill
    manager = AgentPermissionManager()
    manager.invalidate(role.id)
    allowed = await manager.calculate_allowed_tools(role.id, db_session)

    expected_identifier = tool.name
    assert expected_identifier in allowed, (
        f"Permission resolution failed — expected '{expected_identifier}' in {allowed}. "
        "Check that SopStepType.skill_invocation is used (not SopStepType.skill)."
    )


# ── execution_logs table — prompt capture (LangChain deep agent) ──────────────


@pytest.mark.asyncio
async def test_execution_logs_table_exists(db_session: AsyncSession):
    """execution_logs table must exist (migration 8612fc7e10a7 applied)."""
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='execution_logs'")
    )
    row = result.fetchone()
    assert row is not None, (
        "execution_logs table is missing — run: alembic upgrade head"
    )


@pytest.mark.asyncio
async def test_execution_logs_has_required_columns(db_session: AsyncSession):
    """execution_logs must have id, session_id, system_instruction, user_prompt, logged_at."""
    result = await db_session.execute(text("PRAGMA table_info(execution_logs)"))
    columns = {row[1] for row in result.fetchall()}
    required = {"id", "session_id", "system_instruction", "user_prompt", "logged_at"}
    missing = required - columns
    assert not missing, f"Missing columns on execution_logs: {missing}"


@pytest.mark.asyncio
async def test_agent_prompt_log_can_be_inserted(db_session: AsyncSession):
    """AgentPromptLog (table: execution_logs) can be inserted and queried."""
    from app.db.models.agents import AgentJob, AgentJobStatus, AgentInputType, AgentOutputType, AgentType, AgentPromptLog

    # Create minimal AgentType and AgentJob
    agent_type = AgentType(
        name=f"PromptLogType-{uuid.uuid4().hex[:8]}",
        model_id="gpt-4o",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
        system_instruction="You are a test assistant.",
    )
    db_session.add(agent_type)
    await db_session.flush()

    job = AgentJob(
        agent_type_id=agent_type.id,
        input_data={"task": "test"},
        status=AgentJobStatus.running,
    )
    db_session.add(job)
    await db_session.flush()

    # Insert a prompt log entry
    prompt_log = AgentPromptLog(
        session_id=job.id,
        system_instruction="You are a test assistant.",
        user_prompt='{"task": "test"}',
    )
    db_session.add(prompt_log)
    await db_session.flush()
    await db_session.commit()

    # Query back
    from sqlalchemy import select
    result = await db_session.execute(
        select(AgentPromptLog).where(AgentPromptLog.session_id == job.id)
    )
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].system_instruction == "You are a test assistant."
    assert entries[0].user_prompt == '{"task": "test"}'


@pytest.mark.asyncio
async def test_runtime_executor_uses_langchain_loop_no_langgraph(db_session: AsyncSession):
    """AgentRuntimeExecutor runs the LangChain observe-reason-act loop (not LangGraph).

    Verifies:
    1. No langgraph import in runtime_executor.py source
    2. The executor can be instantiated and has the LangChain loop methods
    3. _run_task_loop exists (LangChain loop) and _build_task_graph does NOT exist (LangGraph)
    """
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()

    # Verify LangChain loop methods present
    assert callable(getattr(executor, "_run_task_loop", None)), (
        "_run_task_loop must exist on AgentRuntimeExecutor (LangChain loop)"
    )
    assert callable(getattr(executor, "_observe", None)), (
        "_observe phase method must exist"
    )
    assert callable(getattr(executor, "_reason", None)), (
        "_reason phase method must exist"
    )
    assert callable(getattr(executor, "_act", None)), (
        "_act phase method must exist"
    )

    # Verify LangGraph-specific method is gone
    assert not hasattr(executor, "_build_task_graph"), (
        "_build_task_graph must NOT exist — LangGraph was removed"
    )


@pytest.mark.asyncio
async def test_prompt_log_written_during_session_execution(db_session: AsyncSession):
    """AgentRuntimeExecutor writes an AgentPromptLog before the first LLM call.

    The executor should capture system_instruction and user_prompt in execution_logs
    for every session it processes, even when the LLM is not actually called (stub mode).
    """
    from app.db.models.agents import AgentJob, AgentJobStatus, AgentInputType, AgentOutputType, AgentType, AgentPromptLog
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.session_service import AgentSessionService
    from sqlalchemy import select

    # Create AgentType with system_instruction
    agent_type = AgentType(
        name=f"PromptCaptureAgent-{uuid.uuid4().hex[:8]}",
        model_id="gpt-4o",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
        system_instruction="You are a prompt-capture test assistant.",
    )
    db_session.add(agent_type)
    await db_session.flush()

    # Enqueue and mark running
    session_svc = AgentSessionService()
    job = await session_svc.enqueue(
        agent_type_id=agent_type.id,
        input_data={"query": "capture this"},
        user_id=None,
        db=db_session,
    )
    await db_session.flush()
    job = await session_svc.mark_running(job.id, db_session)
    await db_session.flush()

    # Run executor
    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    # Verify prompt log was written
    result = await db_session.execute(
        select(AgentPromptLog).where(AgentPromptLog.session_id == job.id)
    )
    logs = result.scalars().all()
    assert len(logs) == 1, (
        f"Expected 1 AgentPromptLog entry for session {job.id}, got {len(logs)}"
    )
    assert logs[0].system_instruction == "You are a prompt-capture test assistant."
    assert logs[0].user_prompt is not None

    # Verify session completed after execution
    completed = await session_svc.get_session(job.id, db_session)
    assert completed.status == AgentJobStatus.completed, (
        f"Session should be completed after executor.run(), got: {completed.status}"
    )


@pytest.mark.asyncio
async def test_no_prompt_log_for_queued_session(db_session: AsyncSession):
    """A queued session (not yet executed) has no AgentPromptLog entries."""
    from app.db.models.agents import AgentJob, AgentJobStatus, AgentInputType, AgentOutputType, AgentType, AgentPromptLog
    from app.services.agents.session_service import AgentSessionService
    from sqlalchemy import select

    agent_type = AgentType(
        name=f"QueuedNoLog-{uuid.uuid4().hex[:8]}",
        model_id="gpt-4o",
        input_type=AgentInputType.none,
        output_type=AgentOutputType.auto,
    )
    db_session.add(agent_type)
    await db_session.flush()

    session_svc = AgentSessionService()
    job = await session_svc.enqueue(
        agent_type_id=agent_type.id,
        input_data=None,
        user_id=None,
        db=db_session,
    )
    await db_session.commit()

    # No prompt log should exist for a merely queued session
    result = await db_session.execute(
        select(AgentPromptLog).where(AgentPromptLog.session_id == job.id)
    )
    logs = result.scalars().all()
    assert len(logs) == 0, (
        f"Expected no AgentPromptLog for queued session, got {len(logs)}"
    )
