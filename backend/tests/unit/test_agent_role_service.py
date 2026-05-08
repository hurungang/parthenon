"""Unit tests for AgentRoleService CRUD operations and permission cache integration."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.agents.role_service import (
    AgentRoleService,
    AgentRoleNotFoundError,
    AgentRoleConflictError,
)
from app.db.models.agents import AgentRole, AgentRoleIdentity, AgentRoleSOP, AgentRoleSkill


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


# ── Identity Assignment ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_identities_adds_new_records():
    """assign_identities inserts AgentRoleIdentity records for each identity_id."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    identity_id_1 = uuid.uuid4()
    identity_id_2 = uuid.uuid4()
    role = _make_role(role_id=role_id)

    # get_role returns the role
    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = role

    # No existing assignment for either identity
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None

    added = []

    def capture_add(obj):
        added.append(obj)

    db = _mock_db()
    db.add = capture_add
    db.execute = AsyncMock(side_effect=[get_result, empty_result, empty_result])

    await service.assign_identities(role_id, [identity_id_1, identity_id_2], db)

    assigned = [a for a in added if isinstance(a, AgentRoleIdentity)]
    assert len(assigned) == 2
    assigned_ids = {a.identity_id for a in assigned}
    assert identity_id_1 in assigned_ids
    assert identity_id_2 in assigned_ids


@pytest.mark.asyncio
async def test_assign_identities_skips_duplicates():
    """assign_identities does not insert duplicate AgentRoleIdentity records."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    role = _make_role(role_id=role_id)

    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = role

    # Existing assignment already present
    existing_row = MagicMock(spec=AgentRoleIdentity)
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing_row

    added = []
    db = _mock_db()
    db.add = lambda obj: added.append(obj)
    db.execute = AsyncMock(side_effect=[get_result, existing_result])

    await service.assign_identities(role_id, [identity_id], db)

    # Nothing new should have been added
    assert len([a for a in added if isinstance(a, AgentRoleIdentity)]) == 0


@pytest.mark.asyncio
async def test_assign_identities_raises_not_found_for_missing_role():
    """assign_identities raises AgentRoleNotFoundError when role does not exist."""
    service = AgentRoleService()

    not_found_result = MagicMock()
    not_found_result.scalar_one_or_none.return_value = None

    db = _mock_db()
    db.execute = AsyncMock(return_value=not_found_result)

    with pytest.raises(AgentRoleNotFoundError):
        await service.assign_identities(uuid.uuid4(), [uuid.uuid4()], db)


@pytest.mark.asyncio
async def test_remove_identity_deletes_assignment_record():
    """remove_identity deletes the AgentRoleIdentity row when it exists."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    role = _make_role(role_id=role_id)

    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = role

    assignment_row = MagicMock(spec=AgentRoleIdentity)
    assignment_result = MagicMock()
    assignment_result.scalar_one_or_none.return_value = assignment_row

    db = _mock_db()
    db.execute = AsyncMock(side_effect=[get_result, assignment_result])

    await service.remove_identity(role_id, identity_id, db)

    db.delete.assert_called_once_with(assignment_row)


@pytest.mark.asyncio
async def test_remove_identity_no_op_when_not_assigned():
    """remove_identity does nothing when the identity is not assigned to the role."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    role = _make_role(role_id=role_id)

    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = role

    # No assignment row found
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None

    db = _mock_db()
    db.execute = AsyncMock(side_effect=[get_result, empty_result])

    # Should not raise
    await service.remove_identity(role_id, identity_id, db)

    db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_list_identities_returns_assigned_identities():
    """list_identities returns AgentIdentity records joined via agent_role_identities."""
    from app.db.models.agents import AgentIdentity

    service = AgentRoleService()
    role_id = uuid.uuid4()
    role = _make_role(role_id=role_id)

    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = role

    identity_a = MagicMock(spec=AgentIdentity)
    identity_a.name = "Bot A"
    identity_b = MagicMock(spec=AgentIdentity)
    identity_b.name = "Bot B"

    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = [identity_a, identity_b]

    db = _mock_db()
    db.execute = AsyncMock(side_effect=[get_result, list_result])

    identities = await service.list_identities(role_id, db)

    assert len(identities) == 2
    names = [i.name for i in identities]
    assert "Bot A" in names
    assert "Bot B" in names


@pytest.mark.asyncio
async def test_is_identity_assigned_returns_true_when_present():
    """is_identity_assigned returns True when the join record exists."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    identity_id = uuid.uuid4()

    assignment_result = MagicMock()
    assignment_result.scalar_one_or_none.return_value = MagicMock(spec=AgentRoleIdentity)

    db = _mock_db()
    db.execute = AsyncMock(return_value=assignment_result)

    result = await service.is_identity_assigned(role_id, identity_id, db)

    assert result is True


@pytest.mark.asyncio
async def test_is_identity_assigned_returns_false_when_absent():
    """is_identity_assigned returns False when no join record exists."""
    service = AgentRoleService()
    role_id = uuid.uuid4()
    identity_id = uuid.uuid4()

    no_assignment = MagicMock()
    no_assignment.scalar_one_or_none.return_value = None

    db = _mock_db()
    db.execute = AsyncMock(return_value=no_assignment)

    result = await service.is_identity_assigned(role_id, identity_id, db)

    assert result is False
