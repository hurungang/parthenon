"""Platform Users API router."""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import require_permission
from app.core.resource_types import RT_USER
from app.db.models.group import Group
from app.db.models.group_role import GroupRole
from app.db.models.identity import Role
from app.db.models.platform_user import PlatformUser
from app.db.models.user_group import UserGroup
from app.db.models.user_role import UserRole
from app.db.session import DbSession
from app.schemas.groups import GroupMembershipRead
from app.schemas.platform_users import (
    AddUserToGroupBody,
    AssignUserRoleBody,
    PlatformUserDetail,
    PlatformUserRead,
)
from app.schemas.perm_roles import PermRoleRead

PlatformUsersRouter = APIRouter(prefix="/platform-users", tags=["Permissions: Platform Users"])


async def _get_user_or_404(db: DbSession, user_id: uuid.UUID) -> PlatformUser:
    user = await db.get(PlatformUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


async def _enrich_user(db: DbSession, user: PlatformUser) -> PlatformUserRead:
    rc_r = await db.execute(
        select(func.count()).select_from(UserRole).where(UserRole.user_id == user.id)
    )
    gc_r = await db.execute(
        select(func.count()).select_from(UserGroup).where(UserGroup.user_id == user.id)
    )
    read = PlatformUserRead.model_validate(user)
    return read.model_copy(update={
        "direct_role_count": rc_r.scalar_one(),
        "group_count": gc_r.scalar_one(),
    })


@PlatformUsersRouter.get("", response_model=List[PlatformUserRead])
async def list_platform_users(
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
    _: dict = Depends(require_permission(RT_USER, "read")),
) -> List[PlatformUserRead]:
    """Paginated list of platform users with role/group counts."""
    offset = (page - 1) * page_size
    result = await db.execute(
        select(PlatformUser)
        .order_by(PlatformUser.display_name)
        .offset(offset)
        .limit(page_size)
    )
    users = list(result.scalars().all())
    return [await _enrich_user(db, u) for u in users]


@PlatformUsersRouter.get("/{user_id}", response_model=PlatformUserDetail)
async def get_platform_user(
    user_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_USER, "read")),
) -> PlatformUserDetail:
    """Get a platform user with full role and group membership detail."""
    user = await _get_user_or_404(db, user_id)

    # Direct roles
    roles_result = await db.execute(
        select(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
        .order_by(Role.name)
    )
    direct_roles = list(roles_result.scalars().all())

    # Group memberships with group names
    groups_result = await db.execute(
        select(UserGroup, Group)
        .join(Group, UserGroup.group_id == Group.id)
        .where(UserGroup.user_id == user_id)
        .order_by(Group.name)
    )
    memberships = [
        GroupMembershipRead(
            group_id=ug.group_id,
            group_name=grp.name,
            joined_at=ug.joined_at,
            join_reason=ug.join_reason,
        )
        for ug, grp in groups_result.all()
    ]

    base = await _enrich_user(db, user)
    role_reads = [PermRoleRead.model_validate(r) for r in direct_roles]
    return PlatformUserDetail(
        **base.model_dump(),
        direct_roles=role_reads,
        group_memberships=memberships,
    )


@PlatformUsersRouter.post(
    "/{user_id}/roles",
    response_model=PermRoleRead,
    status_code=status.HTTP_201_CREATED,
)
async def assign_user_role(
    user_id: uuid.UUID,
    body: AssignUserRoleBody,
    db: DbSession,
    _: dict = Depends(require_permission(RT_USER, "manage")),
) -> Role:
    """Assign a direct role to a platform user."""
    await _get_user_or_404(db, user_id)

    role = await db.get(Role, body.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found.")

    existing = await db.execute(
        select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == body.role_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Role already assigned to this user.")

    db.add(UserRole(user_id=user_id, role_id=body.role_id))
    await db.flush()
    return role


@PlatformUsersRouter.delete(
    "/{user_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_user_role(
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_USER, "manage")),
) -> None:
    """Remove a direct role from a platform user."""
    await _get_user_or_404(db, user_id)
    result = await db.execute(
        select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Role assignment not found.")
    await db.delete(row)


@PlatformUsersRouter.post(
    "/{user_id}/groups",
    response_model=GroupMembershipRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_user_to_group(
    user_id: uuid.UUID,
    body: AddUserToGroupBody,
    db: DbSession,
    _: dict = Depends(require_permission(RT_USER, "manage")),
) -> GroupMembershipRead:
    """Add a platform user to a group directly."""
    await _get_user_or_404(db, user_id)

    group = await db.get(Group, body.group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found.")

    existing = await db.execute(
        select(UserGroup).where(UserGroup.user_id == user_id, UserGroup.group_id == body.group_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="User is already a member of this group.")

    ug = UserGroup(user_id=user_id, group_id=body.group_id, join_reason=body.join_reason)
    db.add(ug)
    await db.flush()

    return GroupMembershipRead(
        group_id=ug.group_id,
        group_name=group.name,
        joined_at=ug.joined_at,
        join_reason=ug.join_reason,
    )


@PlatformUsersRouter.delete(
    "/{user_id}/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_user_from_group(
    user_id: uuid.UUID,
    group_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_USER, "manage")),
) -> None:
    """Remove a platform user from a group."""
    await _get_user_or_404(db, user_id)
    result = await db.execute(
        select(UserGroup).where(UserGroup.user_id == user_id, UserGroup.group_id == group_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Group membership not found.")
    await db.delete(row)

