"""Platform admin tenants API — tenant overview, lifecycle, licensing.

Exposes tenant METADATA only (status, admin contact, aggregate usage
counts, license tier + quota usage) — never tenant business rows.
Guarded by ``platform::tenants``.

- ``GET    /platform/tenants``                — list (filterable by status)
- ``POST   /platform/tenants``                — create
- ``GET    /platform/tenants/{tenant_id}``    — detail (aggregates only)
- ``PATCH  /platform/tenants/{tenant_id}``    — update name/contact
- ``POST   /platform/tenants/{tenant_id}/suspend``
- ``POST   /platform/tenants/{tenant_id}/resume``
- ``DELETE /platform/tenants/{tenant_id}``    — requires ``confirm_slug``
- ``PUT    /platform/tenants/{tenant_id}/license``    — assign/change (Phase 10)
- ``DELETE /platform/tenants/{tenant_id}/license``    — remove → free tier (Phase 10)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import require_permission
from app.core.resource_types import RT_PLATFORM_TENANTS
from app.db.session import DbSession
from app.db.models.tenant import Tenant, TenantRole, TenantStatus
from app.db.models.tenant_license import LicenseTier
from app.schemas.tenant_quota import TenantUsageRead
from app.services.tenancy.tenant_service import (
    TenantService,
    TenantServiceError,
)

logger = logging.getLogger(__name__)

PlatformTenantsRouter = APIRouter(prefix="/platform/tenants", tags=["Platform: Tenants"])

_SERVICE = TenantService()


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=3, max_length=63)
    admin_contact_name: Optional[str] = Field(default=None, max_length=200)
    admin_contact_email: Optional[str] = Field(default=None, max_length=320)
    admin_contact_role: TenantRole = TenantRole.tenant_admin


class TenantUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    admin_contact_name: Optional[str] = Field(default=None, max_length=200)
    admin_contact_email: Optional[str] = Field(default=None, max_length=320)


class TenantLicenseWrite(BaseModel):
    """License assign/change input — tier plus explicit positive limits."""

    tier: LicenseTier
    max_users: int = Field(..., ge=1, le=1_000_000)
    max_agent_types: int = Field(..., ge=1, le=1_000_000)
    monthly_agent_executions: int = Field(..., ge=1, le=1_000_000_000)


class TenantLicenseRead(BaseModel):
    tier: str
    max_users: int
    max_agent_types: int
    monthly_agent_executions: int
    assigned_at: Optional[datetime] = None


class TenantRead(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    is_system_tenant: bool
    is_onboarded: bool
    admin_contact_name: Optional[str] = None
    admin_contact_email: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Phase 10: license tier + effective limits (free defaults when unlicensed)
    license: Optional[TenantLicenseRead] = None
    usage: Optional[TenantUsageRead] = None


class TenantDetailRead(TenantRead):
    user_count: int = 0
    agent_count: int = 0
    role_count: int = 0


class TenantListResponse(BaseModel):
    items: list[TenantRead]
    total: int


# ── Helpers ──────────────────────────────────────────────────────────────────


def _actor_id(request: Request) -> Optional[uuid.UUID]:
    value = getattr(request.state, "platform_user_id", None)
    try:
        return uuid.UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


async def _license_read(db: DbSession, tenant_id: uuid.UUID) -> Optional[TenantLicenseRead]:
    from app.services.tenancy.licensing_service import get_tenant_licensing_service

    license_row = await get_tenant_licensing_service().get_active_license(db, tenant_id)
    if license_row is None:
        return None
    return TenantLicenseRead(
        tier=license_row.tier.value,
        max_users=license_row.max_users,
        max_agent_types=license_row.max_agent_types,
        monthly_agent_executions=license_row.monthly_agent_executions,
        assigned_at=license_row.assigned_at,
    )


async def _usage_read(db: DbSession, tenant_id: uuid.UUID) -> TenantUsageRead:
    from app.services.tenancy.quota_service import get_tenant_quota_service

    return TenantUsageRead(
        **await get_tenant_quota_service().get_usage(db, tenant_id)
    )


async def _to_read(db: DbSession, tenant: Tenant) -> TenantRead:
    return TenantRead(
        id=str(tenant.id),
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status.value if hasattr(tenant.status, "value") else str(tenant.status),
        is_system_tenant=bool(tenant.is_system_tenant),
        is_onboarded=bool(tenant.is_onboarded),
        admin_contact_name=tenant.admin_contact_name,
        admin_contact_email=tenant.admin_contact_email,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        license=await _license_read(db, tenant.id),
        usage=await _usage_read(db, tenant.id),
    )


async def _load(db: DbSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = await _SERVICE.get(db, tenant_id)
    if tenant is None or tenant.status == TenantStatus.deleted:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


# ── Endpoints ────────────────────────────────────────────────────────────────


@PlatformTenantsRouter.get("", response_model=TenantListResponse)
async def list_tenants(
    db: DbSession,
    status: Optional[TenantStatus] = Query(default=None),
    _: dict = Depends(require_permission(RT_PLATFORM_TENANTS, "read")),
) -> TenantListResponse:
    """List tenants (metadata + lifecycle status + license/usage only)."""
    tenants = await _SERVICE.list_tenants(db, status=status)
    # Deleted tenants are excluded from the listing.
    items = [
        await _to_read(db, t)
        for t in tenants
        if t.status != TenantStatus.deleted
    ]
    return TenantListResponse(items=items, total=len(items))


@PlatformTenantsRouter.post("", response_model=TenantRead, status_code=201)
async def create_tenant(
    body: TenantCreate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_TENANTS, "create")),
) -> TenantRead:
    """Create a tenant workspace."""
    try:
        tenant = await _SERVICE.create(
            db,
            name=body.name,
            slug=body.slug,
            admin_contact_name=body.admin_contact_name,
            admin_contact_email=body.admin_contact_email,
            admin_contact_role=body.admin_contact_role,
            actor_id=_actor_id(request),
        )
        await db.commit()
        await db.refresh(tenant)
        return await _to_read(db, tenant)
    except TenantServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@PlatformTenantsRouter.get("/{tenant_id}", response_model=TenantDetailRead)
async def get_tenant(
    tenant_id: uuid.UUID,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_TENANTS, "read")),
) -> TenantDetailRead:
    """Tenant detail with aggregate usage counts (no business rows)."""
    from app.db.models.agents import AgentType
    from app.db.models.identity import Role
    from app.db.models.tenant_membership import (
        TenantUserMembership,
        TenantUserMembershipStatus,
    )

    tenant = await _load(db, tenant_id)
    from sqlalchemy import func as sa_func

    user_count = int(
        (
            await db.execute(
                select(sa_func.count())
                .select_from(TenantUserMembership)
                .where(
                    TenantUserMembership.tenant_id == tenant_id,
                    TenantUserMembership.status == TenantUserMembershipStatus.active,
                )
            )
        ).scalar()
        or 0
    )
    agent_count = int(
        (
            await db.execute(
                select(sa_func.count())
                .select_from(AgentType)
                .where(AgentType.tenant_id == tenant_id)
            )
        ).scalar()
        or 0
    )
    role_count = int(
        (
            await db.execute(
                select(sa_func.count())
                .select_from(Role)
                .where(Role.tenant_id == tenant_id)
            )
        ).scalar()
        or 0
    )
    detail = TenantDetailRead(
        **(await _to_read(db, tenant)).model_dump(),
        user_count=user_count,
        agent_count=agent_count,
        role_count=role_count,
    )
    return detail


@PlatformTenantsRouter.patch("/{tenant_id}", response_model=TenantRead)
async def update_tenant(
    tenant_id: uuid.UUID,
    body: TenantUpdate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_TENANTS, "update")),
) -> TenantRead:
    """Update tenant name / admin contact."""
    try:
        tenant = await _SERVICE.update(
            db,
            tenant_id,
            name=body.name,
            admin_contact_name=body.admin_contact_name,
            admin_contact_email=body.admin_contact_email,
            actor_id=_actor_id(request),
        )
        await db.commit()
        await db.refresh(tenant)  # server onupdate values expire on flush
        return await _to_read(db, tenant)
    except TenantServiceError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 409
        raise HTTPException(status_code=status, detail=message)


@PlatformTenantsRouter.post("/{tenant_id}/suspend", response_model=TenantRead)
async def suspend_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_TENANTS, "manage")),
) -> TenantRead:
    """Suspend a tenant: blocks sign-in and resolution immediately."""
    try:
        tenant = await _SERVICE.suspend(db, tenant_id, actor_id=_actor_id(request))
        await db.commit()
        await db.refresh(tenant)  # server onupdate values expire on flush
        return await _to_read(db, tenant)
    except TenantServiceError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 409
        raise HTTPException(status_code=status, detail=message)


@PlatformTenantsRouter.post("/{tenant_id}/resume", response_model=TenantRead)
async def resume_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_TENANTS, "manage")),
) -> TenantRead:
    """Resume a suspended tenant."""
    try:
        tenant = await _SERVICE.resume(db, tenant_id, actor_id=_actor_id(request))
        await db.commit()
        await db.refresh(tenant)  # server onupdate values expire on flush
        return await _to_read(db, tenant)
    except TenantServiceError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 409
        raise HTTPException(status_code=status, detail=message)


# ── Licensing (Phase 10) ─────────────────────────────────────────────────────


@PlatformTenantsRouter.put("/{tenant_id}/license", response_model=TenantLicenseRead)
async def assign_tenant_license(
    tenant_id: uuid.UUID,
    body: TenantLicenseWrite,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_TENANTS, "manage")),
) -> TenantLicenseRead:
    """Assign or change the tenant license (supersedes the previous active)."""
    from app.services.tenancy.licensing_service import (
        TenantLicenseError,
        get_tenant_licensing_service,
    )

    await _load(db, tenant_id)
    try:
        license_row = await get_tenant_licensing_service().assign_license(
            db,
            tenant_id,
            tier=body.tier,
            max_users=body.max_users,
            max_agent_types=body.max_agent_types,
            monthly_agent_executions=body.monthly_agent_executions,
            actor_id=_actor_id(request),
        )
        await db.commit()
        await db.refresh(license_row)
        return TenantLicenseRead(
            tier=license_row.tier.value,
            max_users=license_row.max_users,
            max_agent_types=license_row.max_agent_types,
            monthly_agent_executions=license_row.monthly_agent_executions,
            assigned_at=license_row.assigned_at,
        )
    except TenantLicenseError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@PlatformTenantsRouter.delete("/{tenant_id}/license", status_code=204)
async def remove_tenant_license(
    tenant_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_TENANTS, "manage")),
) -> None:
    """Remove the active license — the tenant falls back to the free tier."""
    from app.services.tenancy.licensing_service import (
        TenantLicenseError,
        get_tenant_licensing_service,
    )

    await _load(db, tenant_id)
    try:
        await get_tenant_licensing_service().remove_license(
            db, tenant_id, actor_id=_actor_id(request)
        )
        await db.commit()
    except TenantLicenseError as exc:
        message = str(exc)
        if "no active license" in message.lower():
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=409, detail=message)


@PlatformTenantsRouter.delete("/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    db: DbSession,
    confirm_slug: str = Query(..., description="Type the tenant slug to confirm"),
    _: dict = Depends(require_permission(RT_PLATFORM_TENANTS, "delete")),
) -> None:
    """Delete a tenant and ALL of its data (irreversible; slug reusable)."""
    try:
        await _SERVICE.delete(
            db, tenant_id, confirm_slug=confirm_slug, actor_id=_actor_id(request)
        )
        await db.commit()
    except TenantServiceError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message)
        if "confirmation" in message.lower():
            raise HTTPException(status_code=400, detail=message)
        raise HTTPException(status_code=409, detail=message)
