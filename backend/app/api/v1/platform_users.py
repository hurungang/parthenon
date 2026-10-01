"""Platform Users API router."""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import require_permission
from app.core.resource_types import RT_SYSTEM_PERMISSIONS
from app.db.models.group import Group
from app.db.models.group_role import GroupRole
from app.db.models.identity import Identity, Role
from app.db.models.platform_user import PlatformUser
from app.db.models.tenant_membership import (
    TenantUserMembership,
    TenantUserMembershipStatus,
)
from app.db.models.user_group import UserGroup
from app.db.models.user_role import UserRole
from app.db.session import AsyncSessionLocal, DbSession
from app.db.tenant_scoping import filter_platform_users_to_tenant, scope_for_session
from app.schemas.groups import GroupMembershipRead
from app.schemas.platform_users import (
    AddUserToGroupBody,
    AssignUserRoleBody,
    PlatformUserDetail,
    PlatformUserRead,
)
from app.schemas.perm_roles import PermRoleRead

import logging
logger = logging.getLogger(__name__)

PlatformUsersRouter = APIRouter(prefix="/platform-users", tags=["Permissions: Platform Users"])


async def _get_user_or_404(db: DbSession, user_id: uuid.UUID) -> PlatformUser:
    """Resolve a platform user or raise 404 (FIX-20260928-121317).

    Membership-guarded in a tenant context: the session's tenant scope
    (multi-tenancy on) restricts resolution to users with an ACTIVE
    membership in the requesting tenant — foreign user ids behave as
    not-found on EVERY sub-resource (read AND the mutating guards).
    Unscoped sessions (single-tenant mode, platform-admin surface,
    super admin) keep full access — byte-for-byte legacy behaviour.
    """
    tenant_id = scope_for_session(db)
    if tenant_id is not None:
        stmt = filter_platform_users_to_tenant(
            select(PlatformUser).where(PlatformUser.id == user_id), tenant_id
        )
        user = (await db.execute(stmt)).scalar_one_or_none()
    else:
        user = await db.get(PlatformUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


async def _enrich_user(db: DbSession, user: PlatformUser) -> PlatformUserRead:
    """Role/group counts for a user, tenant-scoped in tenant context.

    FIX-20260928-121317 Finding #4: UserRole/UserGroup are parent-scoped
    join tables — without joining the tenant-scoped Role/Group parents
    the counts were the union across ALL tenants of a multi-tenant user.
    Joining the parents puts a tenant-scoped entity into the statement so
    the do_orm_execute choke point constrains the count to the request's
    tenant (no-op join on unscoped sessions — FK-guaranteed parents).
    """
    tenant_id = scope_for_session(db)
    rc_stmt = select(func.count()).select_from(UserRole).where(UserRole.user_id == user.id)
    gc_stmt = select(func.count()).select_from(UserGroup).where(UserGroup.user_id == user.id)
    if tenant_id is not None:
        rc_stmt = rc_stmt.join(Role, Role.id == UserRole.role_id)
        gc_stmt = gc_stmt.join(Group, Group.id == UserGroup.group_id)
    rc_r = await db.execute(rc_stmt)
    gc_r = await db.execute(gc_stmt)
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
    _: dict = Depends(require_permission(RT_SYSTEM_PERMISSIONS, "read")),
) -> List[PlatformUserRead]:
    """Paginated list of platform users with role/group counts.

    Tenant context: ONLY users with an ACTIVE membership in the
    requesting tenant are listed (membership-join strategy applied
    before pagination).
    """
    offset = (page - 1) * page_size
    stmt = select(PlatformUser).order_by(PlatformUser.display_name)
    tenant_id = scope_for_session(db)
    if tenant_id is not None:
        stmt = filter_platform_users_to_tenant(stmt, tenant_id)
    result = await db.execute(stmt.offset(offset).limit(page_size))
    users = list(result.scalars().all())
    return [await _enrich_user(db, u) for u in users]


@PlatformUsersRouter.get("/{user_id}", response_model=PlatformUserDetail)
async def get_platform_user(
    user_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_SYSTEM_PERMISSIONS, "read")),
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
    _: dict = Depends(require_permission(RT_SYSTEM_PERMISSIONS, "manage")),
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
    _: dict = Depends(require_permission(RT_SYSTEM_PERMISSIONS, "manage")),
) -> None:
    """Remove a direct role from a platform user."""
    await _get_user_or_404(db, user_id)
    # Join the tenant-scoped Role parent so the choke point scopes the
    # lookup: an in-tenant user's assignment to a FOREIGN role cannot be
    # resolved (404) in tenant context; unscoped sessions are unchanged.
    result = await db.execute(
        select(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id, UserRole.role_id == role_id)
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
    _: dict = Depends(require_permission(RT_SYSTEM_PERMISSIONS, "manage")),
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
    _: dict = Depends(require_permission(RT_SYSTEM_PERMISSIONS, "manage")),
) -> None:
    """Remove a platform user from a group."""
    await _get_user_or_404(db, user_id)
    # Join the tenant-scoped Group parent so the choke point scopes the
    # lookup (same pattern as the role-removal guard above).
    result = await db.execute(
        select(UserGroup)
        .join(Group, Group.id == UserGroup.group_id)
        .where(UserGroup.user_id == user_id, UserGroup.group_id == group_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Group membership not found.")
    await db.delete(row)


@PlatformUsersRouter.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_platform_user(
    user_id: uuid.UUID,
    db: DbSession,
    force: bool = Query(default=False),
    _: dict = Depends(require_permission(RT_SYSTEM_PERMISSIONS, "delete")),
) -> None:
    """Delete a platform user and all associated records.

    Cascades to user_roles, user_groups, access_requests, and access_request_batches.
    Also removes the corresponding Identity record if it exists.

    Requires ``force=true`` query parameter as a safety measure.

    Tenant context: non-members 404 (membership guard) and users who are
    ALSO active members of another tenant are refused (409) — the global
    PlatformUser deletion would cascade-remove their other tenants'
    memberships, a cross-tenant write.  Tenant-scoped member removal is
    the tenant membership endpoint's job.  Unscoped sessions
    (single-tenant mode / platform admin / super admin) keep full access.
    """
    user = await _get_user_or_404(db, user_id)

    if not force:
        raise HTTPException(
            status_code=400,
            detail="Use ?force=true to confirm user deletion.",
        )

    tenant_id = scope_for_session(db)
    if tenant_id is not None:
        # Cross-tenant cascade guard: TenantUserMembership is tenant-scoped,
        # so this count cannot run on the scoped session (the choke point
        # would AND tenant_id == ours into the predicate).  Use a short-lived
        # UNSCOPED session for the platform-level integrity check only.
        async with AsyncSessionLocal() as probe:
            others = await probe.execute(
                select(func.count())
                .select_from(TenantUserMembership)
                .where(
                    TenantUserMembership.user_id == user_id,
                    TenantUserMembership.tenant_id != tenant_id,
                    TenantUserMembership.status == TenantUserMembershipStatus.active,
                )
            )
            if (others.scalar_one() or 0) > 0:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "User is an active member of other organizations and "
                        "cannot be deleted from this organization's context. "
                        "Remove the membership instead."
                    ),
                )

    sub = user.sub

    await db.delete(user)
    await db.flush()

    # Identity-plane lookup (FIX-20260929-221449): the canonical Identity
    # row of the user being deleted may carry another tenant's stamp than
    # the requesting workspace — resolution is tenant-scope-exempt so the
    # cascade cleanup is complete.
    from app.db.tenant_scoping import execute_unscoped

    identity_result = await execute_unscoped(
        db, select(Identity).where(Identity.subject == sub)
    )
    identity = identity_result.scalar_one_or_none()
    if identity:
        await db.delete(identity)
        await db.flush()

    logger.info(
        "Deleted PlatformUser id=%s sub=%s email=%s",
        user_id, sub, user.email,
    )

