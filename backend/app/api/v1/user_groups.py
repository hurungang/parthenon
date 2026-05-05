"""Groups API router."""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select

from app.api.deps import get_current_claims, require_permission
from app.core.resource_types import RT_GROUP
from app.db.models.group import Group
from app.db.models.group_role import GroupRole
from app.db.models.identity import Role
from app.db.models.platform_user import PlatformUser
from app.db.models.user_group import UserGroup
from app.db.session import DbSession
from app.schemas.groups import (
    AddGroupMemberBody,
    AssignGroupRoleBody,
    GroupCreate,
    GroupMemberRead,
    GroupRead,
    GroupUpdate,
)
from app.schemas.perm_roles import PermRoleRead
from app.services.permissions.permission_engine import PermissionEngine

GroupsRouter = APIRouter(prefix="/user-groups", tags=["Permissions: Groups"])


async def _has_permission(db: DbSession, platform_user_id: uuid.UUID, module: str, action: str) -> bool:
    """Check if user has permission for the given module and action."""
    engine = PermissionEngine()
    result = await engine.authorize(
        db=db,
        user_id=platform_user_id,
        module=module,
        action=action,
        resource_id="*",
        resource_tags={},
    )
    return result.allowed


async def _get_group_or_404(db: DbSession, group_id: uuid.UUID) -> Group:
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found.")
    return group


async def _enrich_group(db: DbSession, group: Group) -> GroupRead:
    """Add owner_display_name, member_count, and role_count to a GroupRead."""
    owner_name: str | None = None
    if group.owner_id:
        owner = await db.get(PlatformUser, group.owner_id)
        if owner:
            owner_name = owner.display_name

    mc_r = await db.execute(
        select(func.count()).select_from(UserGroup).where(UserGroup.group_id == group.id)
    )
    rc_r = await db.execute(
        select(func.count()).select_from(GroupRole).where(GroupRole.group_id == group.id)
    )
    read = GroupRead.model_validate(group)
    return read.model_copy(update={
        "owner_display_name": owner_name,
        "member_count": mc_r.scalar_one(),
        "role_count": rc_r.scalar_one(),
    })


@GroupsRouter.get("", response_model=List[GroupRead])
async def list_groups(
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
) -> List[GroupRead]:
    """List all groups. Any authenticated user."""
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Group).order_by(Group.name).offset(offset).limit(page_size)
    )
    groups = list(result.scalars().all())
    return [await _enrich_group(db, g) for g in groups]


@GroupsRouter.post("", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_GROUP, "manage")),
) -> GroupRead:
    """Create a new group. Admin only."""
    existing = await db.execute(select(Group).where(Group.name == body.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Group '{body.name}' already exists.")

    group = Group(
        name=body.name,
        description=body.description,
        owner_id=body.owner_id,
        idp_claim_value=body.idp_claim_value,
    )
    db.add(group)
    await db.flush()

    for role_id in body.role_ids:
        role = await db.get(Role, role_id)
        if not role:
            raise HTTPException(status_code=422, detail=f"Role {role_id} not found.")
        db.add(GroupRole(group_id=group.id, role_id=role_id))

    await db.flush()
    await db.refresh(group)
    return await _enrich_group(db, group)


@GroupsRouter.get("/{group_id}", response_model=GroupRead)
async def get_group(group_id: uuid.UUID, db: DbSession) -> GroupRead:
    """Get a group by ID. Any authenticated user."""
    group = await _get_group_or_404(db, group_id)
    return await _enrich_group(db, group)


@GroupsRouter.patch("/{group_id}", response_model=GroupRead)
async def update_group(
    group_id: uuid.UUID,
    body: GroupUpdate,
    request: Request,
    db: DbSession,
) -> GroupRead:
    """Update a group. Users with permission to manage permissions or group owner only."""
    group = await _get_group_or_404(db, group_id)

    platform_user_id: uuid.UUID | None = getattr(request.state, "platform_user_id", None)
    
    # Check if user has permissions to manage permissions
    has_manage_permission = False
    if platform_user_id:
        has_manage_permission = await _has_permission(db, platform_user_id, RT_GROUP, "manage")

    if not has_manage_permission:
        if platform_user_id is None or group.owner_id != platform_user_id:
            raise HTTPException(status_code=403, detail="Not authorized to update this group.")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(group, field, value)

    await db.flush()
    await db.refresh(group)
    return await _enrich_group(db, group)


@GroupsRouter.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_GROUP, "manage")),
) -> None:
    """Delete a group. Admin only."""
    group = await _get_group_or_404(db, group_id)
    await db.delete(group)


@GroupsRouter.get("/{group_id}/members", response_model=List[GroupMemberRead])
async def list_group_members(
    group_id: uuid.UUID,
    request: Request,
    db: DbSession,
) -> List[GroupMemberRead]:
    """List group members. Users with permission to manage permissions or group owner."""
    group = await _get_group_or_404(db, group_id)
    platform_user_id: uuid.UUID | None = getattr(request.state, "platform_user_id", None)
    
    # Check if user has permissions to manage permissions
    has_manage_permission = False
    if platform_user_id:
        has_manage_permission = await _has_permission(db, platform_user_id, RT_GROUP, "manage")

    if not has_manage_permission and (platform_user_id is None or group.owner_id != platform_user_id):
        raise HTTPException(status_code=403, detail="Not authorized.")

    result = await db.execute(
        select(UserGroup, PlatformUser)
        .join(PlatformUser, UserGroup.user_id == PlatformUser.id)
        .where(UserGroup.group_id == group_id)
        .order_by(UserGroup.joined_at.desc())
    )
    rows = result.all()
    return [
        GroupMemberRead(
            user_id=ug.user_id,
            group_id=ug.group_id,
            display_name=user.display_name,
            email=user.email,
            joined_at=ug.joined_at,
            join_reason=ug.join_reason,
        )
        for ug, user in rows
    ]


@GroupsRouter.post(
    "/{group_id}/members",
    response_model=GroupMemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_group_member(
    group_id: uuid.UUID,
    body: AddGroupMemberBody,
    db: DbSession,
    _: dict = Depends(require_permission(RT_GROUP, "manage")),
) -> GroupMemberRead:
    """Directly add a member to a group. Admin only."""
    await _get_group_or_404(db, group_id)

    user = await db.get(PlatformUser, body.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    existing = await db.execute(
        select(UserGroup).where(UserGroup.user_id == body.user_id, UserGroup.group_id == group_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="User is already a member of this group.")

    ug = UserGroup(user_id=body.user_id, group_id=group_id, join_reason=body.join_reason)
    db.add(ug)
    await db.flush()

    return GroupMemberRead(
        user_id=ug.user_id,
        group_id=ug.group_id,
        display_name=user.display_name,
        email=user.email,
        joined_at=ug.joined_at,
        join_reason=ug.join_reason,
    )


@GroupsRouter.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_group_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_GROUP, "manage")),
) -> None:
    """Remove a member from a group. Admin only."""
    await _get_group_or_404(db, group_id)
    ug = await db.execute(
        select(UserGroup).where(UserGroup.user_id == user_id, UserGroup.group_id == group_id)
    )
    row = ug.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Membership not found.")
    await db.delete(row)


@GroupsRouter.get("/{group_id}/roles", response_model=List[PermRoleRead])
async def list_group_roles(
    group_id: uuid.UUID,
    request: Request,
    db: DbSession,
) -> List[PermRoleRead]:
    """List roles assigned to a group. Users with permission to manage permissions or group owner."""
    group = await _get_group_or_404(db, group_id)
    platform_user_id: uuid.UUID | None = getattr(request.state, "platform_user_id", None)
    
    # Check if user has permissions to manage permissions
    has_manage_permission = False
    if platform_user_id:
        has_manage_permission = await _has_permission(db, platform_user_id, RT_GROUP, "manage")

    if not has_manage_permission and (platform_user_id is None or group.owner_id != platform_user_id):
        raise HTTPException(status_code=403, detail="Not authorized.")

    result = await db.execute(
        select(Role)
        .join(GroupRole, GroupRole.role_id == Role.id)
        .where(GroupRole.group_id == group_id)
        .order_by(Role.name)
    )
    return list(result.scalars().all())


@GroupsRouter.post(
    "/{group_id}/roles",
    response_model=PermRoleRead,
    status_code=status.HTTP_201_CREATED,
)
async def assign_group_role(
    group_id: uuid.UUID,
    body: AssignGroupRoleBody,
    db: DbSession,
    _: dict = Depends(require_permission(RT_GROUP, "manage")),
) -> Role:
    """Assign a role to a group. Admin only. Returns 409 if already assigned."""
    await _get_group_or_404(db, group_id)

    role = await db.get(Role, body.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found.")

    existing = await db.execute(
        select(GroupRole).where(GroupRole.group_id == group_id, GroupRole.role_id == body.role_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Role is already assigned to this group.")

    db.add(GroupRole(group_id=group_id, role_id=body.role_id))
    await db.flush()
    return role


@GroupsRouter.delete("/{group_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_group_role(
    group_id: uuid.UUID,
    role_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_GROUP, "manage")),
) -> None:
    """Remove a role from a group. Admin only."""
    await _get_group_or_404(db, group_id)
    result = await db.execute(
        select(GroupRole).where(GroupRole.group_id == group_id, GroupRole.role_id == role_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Role assignment not found.")
    await db.delete(row)

