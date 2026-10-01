"""Tenant self-service API — the caller's tenant settings, onboarding,
members, and invitations, plus public invitation acceptance.

Routes are tenant-scoped by the request's resolved tenant context: a
tenant admin can only ever see and manage their own tenant's members and
invitations.  Guarded by ``tenant::settings`` / ``tenant::members``.

- ``GET   /tenant/settings``                     — own tenant metadata
- ``PATCH /tenant/settings``                     — update name/contact
- ``GET   /tenant/onboarding``                   — onboarding state
- ``POST  /tenant/onboarding/complete``          — finish onboarding
- ``GET   /tenant/members``                      — list memberships
- ``PATCH /tenant/members/{membership_id}``      — role/suspend/remove
- ``POST  /tenant/invitations``                  — create single-use invite
- ``POST  /tenant/invitations/{invitation_id}/revoke``
- ``POST  /invitations/accept``                  — PUBLIC token acceptance
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.resource_types import RT_TENANT_MEMBERS, RT_TENANT_SETTINGS
from app.db.models.platform_user import PlatformUser
from app.db.models.tenant import Tenant, TenantRole
from app.db.models.tenant_invitation import (
    TenantInvitation,
    TenantInvitationStatus,
)
from app.db.models.tenant_membership import (
    TenantUserMembership,
    TenantUserMembershipStatus,
)
from app.db.session import DbSession
from app.schemas.tenant_quota import TenantUsageRead
from app.services.tenancy.tenant_provisioning_service import (
    TenantProvisioningService,
)

logger = logging.getLogger(__name__)

TenantRouter = APIRouter(prefix="/tenant", tags=["Tenant"])
InvitationAcceptRouter = APIRouter(prefix="/invitations", tags=["Tenant: Invitations"])

_PROVISIONING = TenantProvisioningService()

#: How long an invitation stays valid when no explicit expiry is given.
DEFAULT_INVITATION_EXPIRY_DAYS = 7

_MANAGER_ROLES = {TenantRole.tenant_admin, TenantRole.platform_admin}


# ── Dependencies ─────────────────────────────────────────────────────────────


async def require_tenant_membership(
    request: Request, db: DbSession
) -> TenantUserMembership:
    """Resolve the caller's ACTIVE membership in the request's tenant.

    Fail-closed: without a resolved tenant context or without an active
    membership in THAT tenant, the request is rejected.  The tenant
    context is established by TenantResolutionMiddleware (multi-tenancy
    on); the caller's sub comes from the validated JWT.

    Identity-plane note (FIX-20260929-221449): the PlatformUser-by-sub
    lookup is IDENTITY resolution — tenant-scope-exempt — so an
    authenticated user always RESOLVES; the membership check alone
    decides access.  Without an active membership the caller gets the
    clean flat ``no_access_to_workspace`` 403 (a permission denial,
    never a re-authentication prompt).
    """
    from app.api.deps import NoWorkspaceAccessError
    from app.core.tenant_context import require_tenant_context
    from app.db.tenant_scoping import execute_unscoped

    context = require_tenant_context(request)
    claims = getattr(request.state, "identity", {}) or {}
    sub = claims.get("sub", "")
    if not sub:
        raise NoWorkspaceAccessError(tenant_slug=context.slug)
    user = (
        await execute_unscoped(
            db, select(PlatformUser).where(PlatformUser.sub == sub)
        )
    ).scalar_one_or_none()
    if user is None:
        raise NoWorkspaceAccessError(tenant_slug=context.slug)
    membership = (
        await db.execute(
            select(TenantUserMembership).where(
                TenantUserMembership.tenant_id == context.tenant_id,
                TenantUserMembership.user_id == user.id,
                TenantUserMembership.status == TenantUserMembershipStatus.active,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise NoWorkspaceAccessError(tenant_slug=context.slug)
    return membership


async def require_tenant_manager(
    request: Request,
    db: DbSession,
) -> TenantUserMembership:
    """Membership with management rights (tenant_admin / platform_admin)."""
    membership = await require_tenant_membership(request, db)
    role = membership.tenant_role
    if role not in _MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Tenant admin access required")
    return membership


def _actor_id(membership: TenantUserMembership) -> uuid.UUID:
    return membership.id


# ── Schemas ──────────────────────────────────────────────────────────────────


class TenantSettingsRead(BaseModel):
    tenant_id: str
    slug: str
    name: str
    admin_contact_name: Optional[str] = None
    admin_contact_email: Optional[str] = None
    is_onboarded: bool
    your_role: str
    # True when the caller holds the immutable root (owner) membership
    is_root: bool = False


class TenantSettingsUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    admin_contact_name: Optional[str] = Field(default=None, max_length=200)
    admin_contact_email: Optional[str] = Field(default=None, max_length=320)


class OnboardingStatusRead(BaseModel):
    tenant_id: str
    is_onboarded: bool


class MemberRead(BaseModel):
    membership_id: str
    user_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    tenant_role: str
    status: str
    is_default: bool
    # Root (owner) membership — immutable; UI disables mutating actions
    is_root: bool = False


class MemberListResponse(BaseModel):
    items: list[MemberRead]


class MemberUpdate(BaseModel):
    tenant_role: Optional[TenantRole] = None
    status: Optional[TenantUserMembershipStatus] = None


class InvitationCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    tenant_role: TenantRole = TenantRole.member
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InvitationRead(BaseModel):
    invitation_id: str
    email: str
    tenant_role: str
    status: str
    expires_at: Optional[datetime] = None
    # Shown ONCE at creation — never stored in plaintext, never listed.
    accept_token: Optional[str] = None


class InvitationAccept(BaseModel):
    token: str = Field(..., min_length=16, max_length=128)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _load_tenant(request: Request, db: DbSession) -> Tenant:
    from app.core.tenant_context import require_tenant_context

    context = require_tenant_context(request)
    tenant = await db.get(Tenant, context.tenant_id)
    if tenant is None or tenant.status.value != "active":
        raise HTTPException(status_code=403, detail="Tenant is not active")
    return tenant


# ── Settings ─────────────────────────────────────────────────────────────────


@TenantRouter.get("/settings", response_model=TenantSettingsRead)
async def get_tenant_settings(
    request: Request,
    db: DbSession,
    membership: TenantUserMembership = Depends(require_tenant_membership),
    _: dict = Depends(require_permission(RT_TENANT_SETTINGS, "read")),
) -> TenantSettingsRead:
    """The caller's own tenant metadata (never another tenant's)."""
    tenant = await _load_tenant(request, db)
    return TenantSettingsRead(
        tenant_id=str(tenant.id),
        slug=tenant.slug,
        name=tenant.name,
        admin_contact_name=tenant.admin_contact_name,
        admin_contact_email=tenant.admin_contact_email,
        is_onboarded=bool(tenant.is_onboarded),
        your_role=membership.tenant_role.value,
        is_root=bool(membership.is_root),
    )


@TenantRouter.patch("/settings", response_model=TenantSettingsRead)
async def update_tenant_settings(
    body: TenantSettingsUpdate,
    request: Request,
    db: DbSession,
    membership: TenantUserMembership = Depends(require_tenant_manager),
    _: dict = Depends(require_permission(RT_TENANT_SETTINGS, "manage")),
) -> TenantSettingsRead:
    """Update the caller's own tenant name (alias) / admin contact.

    The alias (``Tenant.name``) may be changed ONLY by the tenant root
    (owner membership); other tenant admins receive a clear rejection.
    The slug (unique address) is immutable — it is not part of the
    request schema and no endpoint accepts it.  Alias changes are
    audited as ``tenant_updated``.
    """
    tenant = await _load_tenant(request, db)
    alias_changed = False
    if body.name is not None and body.name.strip() != tenant.name:
        # Root-only alias editing (Phase 10)
        if not membership.is_root:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Only the organization owner (root) can rename the "
                    "organization"
                ),
            )
        clean = body.name.strip()
        if not clean:
            raise HTTPException(status_code=422, detail="Name cannot be empty")
        # Alias uniqueness is enforced platform-wide (tenants.name is
        # unique): a conflicting rename must fail with a CLEAR error, not
        # an IntegrityError 500 (E-19) — and a failed rename must never
        # touch the immutable slug.
        name_conflict = (
            await db.execute(
                select(Tenant).where(
                    Tenant.name == clean, Tenant.id != tenant.id
                )
            )
        ).scalar_one_or_none()
        if name_conflict is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A tenant named '{clean}' already exists.",
            )
        tenant.name = clean
        alias_changed = True
    if body.admin_contact_name is not None:
        tenant.admin_contact_name = body.admin_contact_name.strip() or None
    if body.admin_contact_email is not None:
        tenant.admin_contact_email = body.admin_contact_email.strip() or None
    if alias_changed:
        from app.db.models.tenant_audit_event import (
            TenantAuditActorType,
            TenantAuditEventType,
        )
        from app.services.tenancy.tenant_audit_service import TenantAuditService

        await TenantAuditService().record_safe(
            db,
            TenantAuditEventType.tenant_updated,
            tenant_id=tenant.id,
            actor_type=(
                TenantAuditActorType.tenant_admin
                if membership.tenant_role == TenantRole.tenant_admin
                else TenantAuditActorType.platform_admin
            ),
            actor_id=membership.id,
            target_resource=f"tenant:{tenant.slug}",
            detail={"alias": tenant.name},
        )
    await db.commit()
    await db.refresh(tenant)
    return TenantSettingsRead(
        tenant_id=str(tenant.id),
        slug=tenant.slug,
        name=tenant.name,
        admin_contact_name=tenant.admin_contact_name,
        admin_contact_email=tenant.admin_contact_email,
        is_onboarded=bool(tenant.is_onboarded),
        your_role=membership.tenant_role.value,
        is_root=bool(membership.is_root),
    )


# ── License & usage (Phase 10) ───────────────────────────────────────────────


@TenantRouter.get("/usage", response_model=TenantUsageRead)
async def get_tenant_usage(
    request: Request,
    db: DbSession,
    _membership: TenantUserMembership = Depends(require_tenant_membership),
    _: dict = Depends(require_permission(RT_TENANT_SETTINGS, "read")),
) -> TenantUsageRead:
    """The caller's tenant tier, effective limits and current usage.

    Returns the free-tier defaults when the tenant is unlicensed; license
    changes are reflected on the next read.  No cross-tenant data — the
    tenant comes from the request's resolved context.  Inert/absent with
    the switch off (the router requires a resolved tenant context).
    """
    from app.core.tenant_context import require_tenant_context
    from app.services.tenancy.quota_service import get_tenant_quota_service

    context = require_tenant_context(request)
    usage = await get_tenant_quota_service().get_usage(db, context.tenant_id)
    return TenantUsageRead(**usage)


# ── Onboarding ───────────────────────────────────────────────────────────────


@TenantRouter.get("/onboarding", response_model=OnboardingStatusRead)
async def get_onboarding_status(
    request: Request,
    db: DbSession,
    _membership: TenantUserMembership = Depends(require_tenant_membership),
    _: dict = Depends(require_permission(RT_TENANT_SETTINGS, "read")),
) -> OnboardingStatusRead:
    tenant = await _load_tenant(request, db)
    return OnboardingStatusRead(
        tenant_id=str(tenant.id), is_onboarded=bool(tenant.is_onboarded)
    )


@TenantRouter.post("/onboarding/complete", response_model=OnboardingStatusRead)
async def complete_onboarding(
    request: Request,
    db: DbSession,
    membership: TenantUserMembership = Depends(require_tenant_manager),
    _: dict = Depends(require_permission(RT_TENANT_SETTINGS, "manage")),
) -> OnboardingStatusRead:
    tenant = await _load_tenant(request, db)
    tenant = await _PROVISIONING.complete_onboarding(
        db, tenant.id, actor_id=_actor_id(membership)
    )
    await db.commit()
    return OnboardingStatusRead(
        tenant_id=str(tenant.id), is_onboarded=bool(tenant.is_onboarded)
    )


# ── Members ──────────────────────────────────────────────────────────────────


@TenantRouter.get("/members", response_model=MemberListResponse)
async def list_members(
    request: Request,
    db: DbSession,
    _membership: TenantUserMembership = Depends(require_tenant_membership),
    _: dict = Depends(require_permission(RT_TENANT_MEMBERS, "read")),
) -> MemberListResponse:
    """List the caller's tenant's members (joined with platform user info)."""
    from app.core.tenant_context import require_tenant_context

    context = require_tenant_context(request)
    rows = (
        await db.execute(
            select(TenantUserMembership, PlatformUser)
            .join(PlatformUser, PlatformUser.id == TenantUserMembership.user_id)
            .where(TenantUserMembership.tenant_id == context.tenant_id)
            .order_by(TenantUserMembership.created_at.asc())
        )
    ).all()
    return MemberListResponse(
        items=[
            MemberRead(
                membership_id=str(m.id),
                user_id=str(u.id),
                display_name=u.display_name,
                email=u.email,
                tenant_role=m.tenant_role.value,
                status=m.status.value,
                is_default=bool(m.is_default),
                is_root=bool(m.is_root),
            )
            for m, u in rows
        ]
    )


@TenantRouter.patch("/members/{membership_id}", response_model=MemberRead)
async def update_member(
    membership_id: uuid.UUID,
    body: MemberUpdate,
    request: Request,
    db: DbSession,
    manager: TenantUserMembership = Depends(require_tenant_manager),
    _: dict = Depends(require_permission(RT_TENANT_MEMBERS, "manage")),
) -> MemberRead:
    """Change a member's tenant role, suspend, or remove them."""
    from app.api.deps import guard_non_root_membership
    from app.core.tenant_context import require_tenant_context

    context = require_tenant_context(request)
    member = await db.get(TenantUserMembership, membership_id)
    if member is None or member.tenant_id != context.tenant_id:
        # Cross-tenant / unknown membership: identical not-found (no leak)
        raise HTTPException(status_code=404, detail="Member not found")
    # Root protection: the owner membership is immutable for EVERY actor
    if body.tenant_role is not None or body.status is not None:
        await guard_non_root_membership(
            db, member, request=request,
            action="role_change" if body.tenant_role is not None else "status_change",
        )
    if body.tenant_role is not None:
        if member.tenant_role == TenantRole.platform_admin:
            raise HTTPException(
                status_code=403, detail="Platform-admin memberships cannot be changed here"
            )
        member.tenant_role = body.tenant_role
    if body.status is not None:
        if member.tenant_role == TenantRole.platform_admin:
            raise HTTPException(
                status_code=403, detail="Platform-admin memberships cannot be changed here"
            )
        member.status = body.status
    await db.commit()
    await db.refresh(member)
    user = await db.get(PlatformUser, member.user_id)
    return MemberRead(
        membership_id=str(member.id),
        user_id=str(member.user_id),
        display_name=user.display_name if user else None,
        email=user.email if user else None,
        tenant_role=member.tenant_role.value,
        status=member.status.value,
        is_default=bool(member.is_default),
        is_root=bool(member.is_root),
    )


# ── Invitations ──────────────────────────────────────────────────────────────


@TenantRouter.post("/invitations", response_model=InvitationRead, status_code=201)
async def create_invitation(
    body: InvitationCreate,
    request: Request,
    db: DbSession,
    manager: TenantUserMembership = Depends(require_tenant_manager),
    _: dict = Depends(require_permission(RT_TENANT_MEMBERS, "create")),
) -> InvitationRead:
    """Create a single-use invitation; the accept token is shown once.

    Consults the USERS quota before any write (Phase 10): an exhausted
    quota returns the structured tier/limit/usage/upgrade payload (403)
    and no invitation is created.
    """
    from app.core.tenant_context import get_tenant_context, require_tenant_context

    if body.tenant_role == TenantRole.platform_admin:
        raise HTTPException(
            status_code=422, detail="Invitations cannot grant the platform-admin role"
        )
    context = require_tenant_context(request)
    # Quota gate: users (inert when the tenancy switch is off)
    from app.services.tenancy.quota_service import get_tenant_quota_service

    tenant_context = get_tenant_context(request)
    if tenant_context.is_set:
        await get_tenant_quota_service().ensure_users(db, tenant_context.tenant_id)
    raw_token = secrets.token_urlsafe(32)
    invitation = TenantInvitation(
        tenant_id=context.tenant_id,
        invited_by_id=manager.id,
        email=body.email.strip().lower(),
        token_hash=_hash_token(raw_token),
        tenant_role=body.tenant_role,
        status=TenantInvitationStatus.pending,
        is_single_use=True,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=body.expires_in_days or DEFAULT_INVITATION_EXPIRY_DAYS),
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)
    return InvitationRead(
        invitation_id=str(invitation.id),
        email=invitation.email,
        tenant_role=invitation.tenant_role.value,
        status=invitation.status.value,
        expires_at=invitation.expires_at,
        accept_token=raw_token,
    )


@TenantRouter.get("/invitations", response_model=list[InvitationRead])
async def list_invitations(
    request: Request,
    db: DbSession,
    _manager: TenantUserMembership = Depends(require_tenant_manager),
    _: dict = Depends(require_permission(RT_TENANT_MEMBERS, "read")),
) -> list[InvitationRead]:
    """List the tenant's invitations (no tokens — hashes are not exposed)."""
    from app.core.tenant_context import require_tenant_context

    context = require_tenant_context(request)
    rows = (
        await db.execute(
            select(TenantInvitation)
            .where(TenantInvitation.tenant_id == context.tenant_id)
            .order_by(TenantInvitation.created_at.desc())
        )
    ).scalars().all()
    return [
        InvitationRead(
            invitation_id=str(i.id),
            email=i.email,
            tenant_role=i.tenant_role.value,
            status=i.status.value,
            expires_at=i.expires_at,
            accept_token=None,
        )
        for i in rows
    ]


@TenantRouter.post("/invitations/{invitation_id}/revoke", response_model=InvitationRead)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _manager: TenantUserMembership = Depends(require_tenant_manager),
    _: dict = Depends(require_permission(RT_TENANT_MEMBERS, "manage")),
) -> InvitationRead:
    """Revoke a pending invitation (token becomes unusable)."""
    from app.core.tenant_context import require_tenant_context

    context = require_tenant_context(request)
    invitation = await db.get(TenantInvitation, invitation_id)
    if invitation is None or invitation.tenant_id != context.tenant_id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.status != TenantInvitationStatus.pending:
        raise HTTPException(status_code=409, detail="Invitation is not pending")
    invitation.status = TenantInvitationStatus.revoked
    invitation.token_hash = None
    await db.commit()
    await db.refresh(invitation)
    return InvitationRead(
        invitation_id=str(invitation.id),
        email=invitation.email,
        tenant_role=invitation.tenant_role.value,
        status=invitation.status.value,
        expires_at=invitation.expires_at,
        accept_token=None,
    )


# ── Public acceptance ────────────────────────────────────────────────────────


@InvitationAcceptRouter.post("/accept", response_model=TenantSettingsRead)
async def accept_invitation(
    body: InvitationAccept,
    request: Request,
    db: DbSession,
) -> TenantSettingsRead:
    """PUBLIC (JWT-authenticated) invitation acceptance by token.

    Looks up the invitation by token hash, validates status/expiry,
    creates (or reactivates) the caller's membership with the invited
    role, and consumes the single-use token.  Other tenants' invitations
    are unreachable (lookup is by token only).
    """
    claims = getattr(request.state, "identity", {}) or {}
    sub = claims.get("sub", "")
    if not sub:
        raise HTTPException(status_code=401, detail="Sign in to accept invitations")
    # Identity-plane lookup (FIX-20260929-221449): the caller resolves by
    # sub regardless of any tenant scope — invitation acceptance happens
    # outside a resolved tenant context by design.
    from app.db.tenant_scoping import execute_unscoped

    user = (
        await execute_unscoped(
            db, select(PlatformUser).where(PlatformUser.sub == sub)
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=403, detail="User account not provisioned yet")

    invitation = (
        await db.execute(
            select(TenantInvitation).where(
                TenantInvitation.token_hash == _hash_token(body.token)
            )
        )
    ).scalar_one_or_none()
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found or invalid")
    if invitation.status != TenantInvitationStatus.pending:
        raise HTTPException(status_code=409, detail="Invitation is no longer pending")
    # Normalise naive datetimes (SQLite loses tzinfo) before comparing —
    # mirrors the guard in api_key_service.is_key_expired.
    expires_at = invitation.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at is not None and expires_at < datetime.now(timezone.utc):
        invitation.status = TenantInvitationStatus.expired
        await db.commit()
        raise HTTPException(status_code=410, detail="Invitation has expired")

    tenant = await db.get(Tenant, invitation.tenant_id)
    if tenant is None or tenant.status.value != "active":
        raise HTTPException(status_code=409, detail="Tenant is not active")

    # Quota gate (Phase 10): the member-creating acceptance path consults
    # the users quota before creating/reactivating a membership.  The
    # gate targets the INVITATION's tenant — the public accept flow has
    # no resolved tenant context (a fresh invitee carries no tenant
    # headers), so conditioning on the context would skip the gate
    # entirely.  Inert when the tenancy switch is off.
    from app.core.tenant_context import get_tenant_context as _get_ctx
    from app.services.tenancy.quota_service import get_tenant_quota_service

    ctx = _get_ctx(request)
    if ctx.is_set and ctx.tenant_id != invitation.tenant_id:
        raise HTTPException(status_code=404, detail="Invitation not found or invalid")
    await get_tenant_quota_service().ensure_users(db, invitation.tenant_id)

    membership = (
        await db.execute(
            select(TenantUserMembership).where(
                TenantUserMembership.tenant_id == invitation.tenant_id,
                TenantUserMembership.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        membership = TenantUserMembership(
            tenant_id=invitation.tenant_id,
            user_id=user.id,
            tenant_role=invitation.tenant_role,
            status=TenantUserMembershipStatus.active,
            is_default=False,
        )
        db.add(membership)
    else:
        if membership.status == TenantUserMembershipStatus.active:
            raise HTTPException(status_code=409, detail="Already a member of this organization")
        # Root protection (defensive): a root membership can never be
        # demoted/suspended/removed by any path, so this branch should be
        # unreachable for roots — reject rather than silently mutate.
        from app.api.deps import guard_non_root_membership

        await guard_non_root_membership(db, membership, request=request, action="reactivate")
        membership.status = TenantUserMembershipStatus.active
        membership.tenant_role = invitation.tenant_role
    invitation.status = TenantInvitationStatus.accepted
    invitation.token_hash = None  # single use
    await db.commit()
    await db.refresh(membership)

    return TenantSettingsRead(
        tenant_id=str(tenant.id),
        slug=tenant.slug,
        name=tenant.name,
        admin_contact_name=tenant.admin_contact_name,
        admin_contact_email=tenant.admin_contact_email,
        is_onboarded=bool(tenant.is_onboarded),
        your_role=membership.tenant_role.value,
        is_root=bool(membership.is_root),
    )
