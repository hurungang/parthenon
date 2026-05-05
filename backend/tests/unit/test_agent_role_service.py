"""Unit tests for AgentRoleService CRUD operations and permission cache integration."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.agents.role_service import (
    AgentRoleService,
    AgentRoleNotFoundError,
    AgentRoleConflictError,
)
from app.db.models.agents import AgentRole, AgentRoleSOP, AgentRoleSkill


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_role(
    role_id: uuid.UUID | None = None,
    name: str = "Test Role",
    sop_ids: list[uuid.UUID] | None = None,
    skill_ids: list[uuid.UUID] | None = None,
) -> AgentRole:
    role = MagicMock(spec=AgentRole)
    role.id = role_id or uuid.uuid4()
    role.name = name
    role.description = "A test role"
    sop_ids = sop_ids or []
    skill_ids = skill_ids or []
    role.sop_assignments = [
        MagicMock(spec=AgentRoleSOP, sop_id=sid) for sid in sop_ids
    ]
    role.skill_assignments = [
        MagicMock(spec=AgentRoleSkill, skill_id=skid) for skid in skill_ids
    ]
    return role


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


# ── Create ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_role_with_no_assignments():
    """create_role with empty sop_ids/skill_ids succeeds and returns a role."""
    service = AgentRoleService()

    role = _make_role()
    db = _mock_db()

    # Simulate db.flush setting the ID on the new role
    async def flush_side_effect():
        pass

    db.flush.side_effect = flush_side_effect

    # Mock _set_assignments to avoid DB queries
    service._set_assignments = AsyncMock()

    # db.refresh should populate sop/skill assignments on the role
    async def refresh_side_effect(obj, attrs):
        obj.sop_assignments = []
        obj.skill_assignments = []

    db.refresh.side_effect = refresh_side_effect

    with patch("app.services.agents.role_service.AgentRole", return_value=role):
        result = await service.create_role("EmptyRole", None, [], [], db)

    assert result.id == role.id
    service._set_assignments.assert_called_once()


@pytest.mark.asyncio
async def test_create_role_with_sop_and_skill_assignments():
    """create_role calls _set_assignments with provided SOP and Skill IDs."""
    service = AgentRoleService()
    service._set_assignments = AsyncMock()

    sop_id = uuid.uuid4()
    skill_id = uuid.uuid4()
    role = _make_role(sop_ids=[sop_id], skill_ids=[skill_id])
    db = _mock_db()

    async def refresh_side_effect(obj, attrs):
        obj.sop_assignments = [MagicMock(sop_id=sop_id)]
        obj.skill_assignments = [MagicMock(skill_id=skill_id)]

    db.refresh.side_effect = refresh_side_effect

    with patch("app.services.agents.role_service.AgentRole", return_value=role):
        await service.create_role("FullRole", "desc", [sop_id], [skill_id], db)

    service._set_assignments.assert_called_once_with(role.id, [sop_id], [skill_id], db)


# ── List ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_roles_returns_ordered_list():
    """list_roles executes a SELECT with selectinload and returns all roles."""
    service = AgentRoleService()
    role_a = _make_role(name="Alpha")
    role_b = _make_role(name="Beta")

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [role_a, role_b]

    db = _mock_db()
    db.execute = AsyncMock(return_value=mock_result)

    result = await service.list_roles(db)

    assert len(result) == 2
    assert result[0].name == "Alpha"
    assert result[1].name == "Beta"


# ── Get by ID ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_role_returns_role_when_found():
    """get_role returns the role when it exists."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    role = _make_role(role_id=role_id)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = role

    db = _mock_db()
    db.execute = AsyncMock(return_value=mock_result)

    result = await service.get_role(role_id, db)
    assert result.id == role_id


@pytest.mark.asyncio
async def test_get_role_raises_not_found():
    """get_role raises AgentRoleNotFoundError when no row is found."""
    service = AgentRoleService()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    db = _mock_db()
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(AgentRoleNotFoundError):
        await service.get_role(uuid.uuid4(), db)


# ── Update ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_role_name_only():
    """update_role changes the name and does not touch assignments when not provided."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    role = _make_role(role_id=role_id, name="OldName")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = role

    db = _mock_db()
    db.execute = AsyncMock(return_value=mock_result)

    service._set_assignments = AsyncMock()

    async def refresh_side_effect(obj, attrs):
        pass

    db.refresh.side_effect = refresh_side_effect

    result = await service.update_role(role_id, "NewName", None, None, None, db)

    assert result.name == "NewName"
    # _set_assignments should NOT be called when sop_ids and skill_ids are both None
    service._set_assignments.assert_not_called()


@pytest.mark.asyncio
async def test_update_role_replaces_sop_assignments():
    """update_role calls _set_assignments when sop_ids are explicitly provided (replace, not append)."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    old_sop = uuid.uuid4()
    new_sop = uuid.uuid4()
    role = _make_role(role_id=role_id, sop_ids=[old_sop])

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = role

    db = _mock_db()
    db.execute = AsyncMock(return_value=mock_result)
    service._set_assignments = AsyncMock()

    async def refresh_side_effect(obj, attrs):
        pass

    db.refresh.side_effect = refresh_side_effect

    await service.update_role(role_id, None, None, [new_sop], [], db)

    service._set_assignments.assert_called_once_with(role_id, [new_sop], [], db)


@pytest.mark.asyncio
async def test_update_role_invalidates_permission_cache():
    """update_role calls permission_manager.invalidate if injected."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    role = _make_role(role_id=role_id)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = role

    db = _mock_db()
    db.execute = AsyncMock(return_value=mock_result)
    service._set_assignments = AsyncMock()

    mock_pm = MagicMock()
    service._permission_manager = mock_pm

    async def refresh_side_effect(obj, attrs):
        pass

    db.refresh.side_effect = refresh_side_effect

    await service.update_role(role_id, "NewName", None, None, None, db)

    mock_pm.invalidate.assert_called_once_with(role_id)


# ── Delete ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_role_succeeds_when_not_referenced():
    """delete_role succeeds when no AgentType references the role."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    role = _make_role(role_id=role_id)

    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = role

    ref_result = MagicMock()
    ref_result.scalar_one_or_none.return_value = None  # no referencing AgentType

    db = _mock_db()
    db.execute = AsyncMock(side_effect=[get_result, ref_result])
    db.delete = AsyncMock()

    await service.delete_role(role_id, db)

    db.delete.assert_called_once_with(role)


@pytest.mark.asyncio
async def test_delete_role_raises_conflict_when_referenced():
    """delete_role raises AgentRoleConflictError (409) when an AgentType references it."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    role = _make_role(role_id=role_id)

    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = role

    ref_result = MagicMock()
    ref_result.scalar_one_or_none.return_value = uuid.uuid4()  # a referencing AgentType ID

    db = _mock_db()
    db.execute = AsyncMock(side_effect=[get_result, ref_result])

    with pytest.raises(AgentRoleConflictError):
        await service.delete_role(role_id, db)


@pytest.mark.asyncio
async def test_delete_role_invalidates_permission_cache():
    """delete_role invalidates the permission cache entry for the role."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    role = _make_role(role_id=role_id)

    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = role

    ref_result = MagicMock()
    ref_result.scalar_one_or_none.return_value = None

    db = _mock_db()
    db.execute = AsyncMock(side_effect=[get_result, ref_result])
    db.delete = AsyncMock()

    mock_pm = MagicMock()
    service._permission_manager = mock_pm

    await service.delete_role(role_id, db)

    mock_pm.invalidate.assert_called_once_with(role_id)


# ── _set_assignments ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_assignments_deletes_existing_and_inserts_new():
    """_set_assignments replaces all existing SOP/Skill join records atomically."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    new_sop = uuid.uuid4()
    new_skill = uuid.uuid4()

    old_sop_row = MagicMock(spec=AgentRoleSOP)
    old_skill_row = MagicMock(spec=AgentRoleSkill)

    sop_exec_result = MagicMock()
    sop_exec_result.scalars.return_value.all.return_value = [old_sop_row]

    skill_exec_result = MagicMock()
    skill_exec_result.scalars.return_value.all.return_value = [old_skill_row]

    db = _mock_db()
    db.execute = AsyncMock(side_effect=[sop_exec_result, skill_exec_result])
    db.delete = AsyncMock()
    added = []
    db.add = MagicMock(side_effect=lambda obj: added.append(obj))

    await service._set_assignments(role_id, [new_sop], [new_skill], db)

    db.delete.assert_any_call(old_sop_row)
    db.delete.assert_any_call(old_skill_row)
    assert len(added) == 2
    assert any(isinstance(obj, AgentRoleSOP) for obj in added)
    assert any(isinstance(obj, AgentRoleSkill) for obj in added)
