"""Identity API routers: Role, Permission, Identity CRUD."""
import uuid
import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, delete

from app.db.session import DbSession
from app.db.models.identity import Identity, Permission, Role, RolePermission
from app.schemas.identity import (
    IdentityCreate,
    IdentityRead,
    PermissionCreate,
    PermissionRead,
    RoleCreate,
    RolePermissionAssign,
    RoleRead,
    RoleUpdate,
)

logger = logging.getLogger(__name__)

# ── Permission Router ──────────────────────────────────────────────────────────
PermissionRouter = APIRouter(prefix="/permissions", tags=["Permissions"])


@PermissionRouter.get("", response_model=list[PermissionRead])
async def list_permissions(db: DbSession) -> list[Permission]:
    result = await db.execute(select(Permission).order_by(Permission.name))
    return list(result.scalars().all())


@PermissionRouter.post("", response_model=PermissionRead, status_code=status.HTTP_201_CREATED)
async def create_permission(body: PermissionCreate, db: DbSession) -> Permission:
    perm = Permission(**body.model_dump())
    db.add(perm)
    await db.flush()
    await db.refresh(perm)
    return perm


@PermissionRouter.get("/{permission_id}", response_model=PermissionRead)
async def get_permission(permission_id: uuid.UUID, db: DbSession) -> Permission:
    perm = await db.get(Permission, permission_id)
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    return perm


@PermissionRouter.delete("/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_permission(permission_id: uuid.UUID, db: DbSession) -> None:
    perm = await db.get(Permission, permission_id)
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    await db.delete(perm)


# ── Role Router ────────────────────────────────────────────────────────────────
RoleRouter = APIRouter(prefix="/roles", tags=["Roles"])


@RoleRouter.get("", response_model=list[RoleRead])
async def list_roles(db: DbSession) -> list[Role]:
    result = await db.execute(select(Role).order_by(Role.name))
    return list(result.scalars().all())


@RoleRouter.post("", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(body: RoleCreate, db: DbSession) -> Role:
    role = Role(**body.model_dump())
    db.add(role)
    await db.flush()
    await db.refresh(role)
    return role


@RoleRouter.get("/{role_id}", response_model=RoleRead)
async def get_role(role_id: uuid.UUID, db: DbSession) -> Role:
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


@RoleRouter.put("/{role_id}", response_model=RoleRead)
async def update_role(role_id: uuid.UUID, body: RoleUpdate, db: DbSession) -> Role:
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(role, field, value)
    await db.flush()
    await db.refresh(role)
    return role


@RoleRouter.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: uuid.UUID, db: DbSession) -> None:
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    await db.delete(role)


@RoleRouter.post(
    "/{role_id}/permissions",
    response_model=PermissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def assign_permission_to_role(
    role_id: uuid.UUID, body: RolePermissionAssign, db: DbSession
) -> Permission:
    role = await db.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    perm = await db.get(Permission, body.permission_id)
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")

    # Check if already assigned
    existing = await db.execute(
        select(RolePermission).where(
            RolePermission.role_id == role_id,
            RolePermission.permission_id == body.permission_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Permission already assigned to role")

    rp = RolePermission(role_id=role_id, permission_id=body.permission_id)
    db.add(rp)
    await db.flush()
    return perm


@RoleRouter.delete(
    "/{role_id}/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_permission_from_role(
    role_id: uuid.UUID, permission_id: uuid.UUID, db: DbSession
) -> None:
    result = await db.execute(
        select(RolePermission).where(
            RolePermission.role_id == role_id,
            RolePermission.permission_id == permission_id,
        )
    )
    rp = result.scalar_one_or_none()
    if not rp:
        raise HTTPException(status_code=404, detail="Role-Permission assignment not found")
    await db.delete(rp)


# ── Identity Router ────────────────────────────────────────────────────────────
IdentityRouter = APIRouter(prefix="/identities", tags=["Identities"])


@IdentityRouter.get("", response_model=list[IdentityRead])
async def list_identities(db: DbSession) -> list[Identity]:
    result = await db.execute(select(Identity).order_by(Identity.created_at.desc()))
    return list(result.scalars().all())


@IdentityRouter.post("", response_model=IdentityRead, status_code=status.HTTP_201_CREATED)
async def create_identity(body: IdentityCreate, db: DbSession) -> Identity:
    if body.role_id:
        role = await db.get(Role, body.role_id)
        if not role:
            raise HTTPException(status_code=422, detail="Role not found")

    identity = Identity(**body.model_dump())
    db.add(identity)
    await db.flush()
    await db.refresh(identity)
    return identity


@IdentityRouter.get("/{identity_id}", response_model=IdentityRead)
async def get_identity(identity_id: uuid.UUID, db: DbSession) -> Identity:
    identity = await db.get(Identity, identity_id)
    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found")
    return identity
