"""Roles and Policy API router."""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.resource_types import RT_PERMISSIONS
from app.db.models.group_role import GroupRole
from app.db.models.identity import Role
from app.db.models.policy_action import PolicyAction
from app.db.models.policy_resource import PolicyResource
from app.db.models.policy_statement import PolicyStatement
from app.db.models.policy_tag_condition import PolicyTagCondition
from app.db.models.user_role import UserRole
from app.db.session import DbSession
from app.schemas.perm_roles import (
    PermRoleCreate,
    PermRoleRead,
    PermRoleUpdate,
    PolicyStatementCreate,
    PolicyStatementRead,
)

RolesRouter = APIRouter(prefix="/user-roles", tags=["Permissions: Roles"])


@RolesRouter.get("", response_model=List[PermRoleRead])
async def list_roles(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(require_permission(RT_PERMISSIONS, "read")),
) -> List[PermRoleRead]:
    """Paginated list of roles with policy and assignment counts. Admin only."""
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Role).order_by(Role.name).offset(offset).limit(page_size)
    )
    roles = list(result.scalars().all())

    enriched: List[PermRoleRead] = []
    for role in roles:
        pc_r = await db.execute(
            select(func.count()).select_from(PolicyStatement).where(PolicyStatement.role_id == role.id)
        )
        uc_r = await db.execute(
            select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)
        )
        gc_r = await db.execute(
            select(func.count()).select_from(GroupRole).where(GroupRole.role_id == role.id)
        )
        read = PermRoleRead.model_validate(role)
        read = read.model_copy(update={
            "policy_count": pc_r.scalar_one(),
            "user_assignment_count": uc_r.scalar_one(),
            "group_assignment_count": gc_r.scalar_one(),
        })
        enriched.append(read)
    return enriched


@RolesRouter.post("", response_model=PermRoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: PermRoleCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PERMISSIONS, "manage")),
) -> Role:
    """Create a new role. Admin only."""
    existing = await db.execute(select(Role).where(Role.name == body.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Role '{body.name}' already exists.")
    role = Role(name=body.name, description=body.description)
    db.add(role)
    await db.flush()
    await db.refresh(role)
    return role


@RolesRouter.get("/{role_id}", response_model=PermRoleRead)
async def get_role(
    role_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PERMISSIONS, "read")),
) -> Role:
    """Get a single role by ID. Admin only."""
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found.")
    return role


@RolesRouter.patch("/{role_id}", response_model=PermRoleRead)
async def update_role(
    role_id: uuid.UUID,
    body: PermRoleUpdate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PERMISSIONS, "manage")),
) -> Role:
    """Update a role's name or description. Admin only. System roles cannot be modified."""
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found.")
    if role.is_system:
        raise HTTPException(status_code=403, detail="System roles cannot be modified.")
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(role, field, value)
    await db.flush()
    await db.refresh(role)
    return role


@RolesRouter.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: uuid.UUID,
    db: DbSession,
    force: bool = Query(default=False),
    _: dict = Depends(require_permission(RT_PERMISSIONS, "manage")),
) -> None:
    """Delete a role. Admin only. System roles cannot be deleted."""
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found.")
    if role.is_system:
        raise HTTPException(status_code=403, detail="System roles cannot be deleted.")

    if not force:
        uc_r = await db.execute(
            select(func.count()).select_from(UserRole).where(UserRole.role_id == role_id)
        )
        gc_r = await db.execute(
            select(func.count()).select_from(GroupRole).where(GroupRole.role_id == role_id)
        )
        if uc_r.scalar_one() > 0 or gc_r.scalar_one() > 0:
            raise HTTPException(
                status_code=409,
                detail="Role has active assignments. Use ?force=true to delete anyway.",
            )

    await db.delete(role)


@RolesRouter.get("/{role_id}/policies", response_model=List[PolicyStatementRead])
async def list_role_policies(
    role_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PERMISSIONS, "read")),
) -> list:
    """List all policy statements for a role with nested actions/resources/conditions. Admin only."""
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found.")
    result = await db.execute(
        select(PolicyStatement)
        .where(PolicyStatement.role_id == role_id)
        .options(
            selectinload(PolicyStatement.actions),
            selectinload(PolicyStatement.resources),
            selectinload(PolicyStatement.tag_conditions),
        )
    )
    return list(result.scalars().all())


@RolesRouter.post(
    "/{role_id}/policies",
    response_model=PolicyStatementRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_policy_statement(
    role_id: uuid.UUID,
    body: PolicyStatementCreate,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PERMISSIONS, "manage")),
) -> PolicyStatement:
    """Create a policy statement for a role. Admin only."""
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found.")

    stmt = PolicyStatement(role_id=role_id, effect=body.effect, module=body.module)
    db.add(stmt)
    await db.flush()

    for action_body in body.actions:
        db.add(PolicyAction(policy_statement_id=stmt.id, action=action_body.action))

    for resource_body in body.resources:
        db.add(PolicyResource(
            policy_statement_id=stmt.id,
            resource_type=resource_body.resource_type,
            resource_id=resource_body.resource_id,
        ))

    for cond_body in body.tag_conditions:
        db.add(PolicyTagCondition(
            policy_statement_id=stmt.id,
            tag_key=cond_body.tag_key,
            tag_value=cond_body.tag_value,
        ))

    await db.flush()

    # Re-query with eager loading for response
    stmt_result = await db.execute(
        select(PolicyStatement)
        .where(PolicyStatement.id == stmt.id)
        .options(
            selectinload(PolicyStatement.actions),
            selectinload(PolicyStatement.resources),
            selectinload(PolicyStatement.tag_conditions),
        )
    )
    return stmt_result.scalar_one()


@RolesRouter.delete(
    "/{role_id}/policies/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_policy_statement(
    role_id: uuid.UUID,
    policy_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PERMISSIONS, "manage")),
) -> None:
    """Delete a policy statement. Admin only."""
    stmt = await db.get(PolicyStatement, policy_id)
    if not stmt or stmt.role_id != role_id:
        raise HTTPException(status_code=404, detail="Policy statement not found.")
    await db.delete(stmt)
