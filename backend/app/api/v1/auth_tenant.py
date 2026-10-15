"""Tenant auth router — tenant discovery, memberships for sign-in,
self-serve registration and platform-password sign-in.

Authentication-adjacent endpoints for multi-tenant sign-in:

- ``GET  /auth/tenant`` — PUBLIC tenant discovery by host/query: minimal
  branding info (name, slug, status, sign-in readiness).  Never exposes
  business data.  Inert when the tenancy switch is off (the response
  carries the switch state with no tenant).
- ``GET  /auth/tenant-memberships`` — authenticated: the caller's active
  tenant memberships (id, slug, name, role, default flag) powering the
  sign-in organization picker.
- ``POST /auth/register`` — PUBLIC account-first self-serve registration
  (Phase 10): email + password + organization name/address; atomically
  creates the platform account, the tenant and the root membership and
  returns an authenticated session landing in guided onboarding.
  Switch-gated + throttled.  SUPERSEDES ``register-organization``.
- ``POST /auth/login-password`` — PUBLIC sign-in for platform-issued
  accounts: issues a tenant-bound platform JWT validated by the existing
  tenant-claim machinery (outside the per-tenant OIDC registry).
  Generic failures — no user enumeration.

The discovery/registration/sign-in paths are bypassed by
TenantResolutionMiddleware and listed as public in the JWT middleware
allowlist.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select

from app.db.models.platform_user import PlatformUser
from app.db.models.tenant import Tenant, TenantStatus
from app.db.models.tenant_membership import (
    TenantUserMembership,
    TenantUserMembershipStatus,
)
from app.db.session import DbSession
from app.services.tenancy.platform_settings_service import (
    get_platform_settings_service,
)
from app.services.tenancy.tenant_resolution_service import extract_slug_candidate

logger = logging.getLogger(__name__)

TenantAuthRouter = APIRouter(prefix="/auth", tags=["Auth: Tenant"])

#: Public-path limiter (per-IP).  The app-level handler turns
#: RateLimitExceeded into a 429 response.
_limiter = Limiter(key_func=get_remote_address)


# ── Schemas ──────────────────────────────────────────────────────────────────


class PublicTenantInfo(BaseModel):
    """Minimal public branding info for a resolved tenant.

    Deliberately tiny: identity at sign-in only — never business data.
    """

    slug: str
    name: str
    status: str
    sign_in_ready: bool


class TenantDiscoveryResponse(BaseModel):
    multi_tenancy_enabled: bool
    tenant: Optional[PublicTenantInfo] = None


class TenantMembershipRead(BaseModel):
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    tenant_role: str
    is_default: bool


class TenantMembershipsResponse(BaseModel):
    multi_tenancy_enabled: bool
    items: list[TenantMembershipRead]


# ── Endpoints ────────────────────────────────────────────────────────────────


async def _resolve_sign_in_ready(db, tenant: Tenant) -> bool:
    """Whether the tenant has an enabled user-scope identity provider.

    Uses the per-tenant OIDC registry — ONLY the tenant's own slot (the
    shared NULL-tenant slot is retired).  Never loads provider secrets.
    """
    from app.main import _get_registry

    registry = _get_registry()
    if not registry.initialized:
        return False
    # Tenancy OFF: the ONLY lookup is the explicit DEFAULT (root)
    # provider — a tenant-addressed lookup is not valid with the switch
    # off (the root workspace is THE default tenant).
    if not registry.multi_tenancy_enabled:
        return registry.get_default_provider("user") is not None
    return registry.has_user_provider(
        tenant_id=tenant.id,
        is_system_tenant=bool(tenant.is_system_tenant),
    )


@TenantAuthRouter.get("/tenant", response_model=TenantDiscoveryResponse)
async def discover_tenant(
    request: Request,
    db: DbSession,
    slug: Optional[str] = Query(default=None, description="Explicit tenant slug"),
) -> TenantDiscoveryResponse:
    """PUBLIC tenant discovery by host (or ``?slug=``) for the login page.

    Returns only sign-in-relevant branding: name, slug, lifecycle status,
    and whether sign-in is configured.  Suspended/deleted tenants are
    reported with their status so the UI can block sign-in.  With the
    tenancy switch off the response carries no tenant at all.
    """
    settings_service = get_platform_settings_service()
    multi_tenancy_enabled = await settings_service.is_multi_tenancy_enabled(db)
    if not multi_tenancy_enabled:
        return TenantDiscoveryResponse(multi_tenancy_enabled=False, tenant=None)

    # Candidate slug: explicit query param wins, then X-Tenant header,
    # then the Host subdomain.
    candidate: Optional[str] = (slug or "").strip().lower() or None
    if candidate is None:
        extracted = extract_slug_candidate(request)
        candidate = extracted.slug if extracted else None

    if candidate is None:
        # Base-domain / dev-host requests: no tenant address — the login
        # page falls back to the platform (single-tenant-style) surface.
        return TenantDiscoveryResponse(multi_tenancy_enabled=True, tenant=None)

    result = await db.execute(select(Tenant).where(Tenant.slug == candidate))
    tenant = result.scalar_one_or_none()
    if tenant is None or tenant.status == TenantStatus.deleted:
        # Unknown slugs are indistinguishable from deleted ones (no leak)
        return TenantDiscoveryResponse(multi_tenancy_enabled=True, tenant=None)

    if tenant.status == TenantStatus.suspended:
        return TenantDiscoveryResponse(
            multi_tenancy_enabled=True,
            tenant=PublicTenantInfo(
                slug=tenant.slug,
                name=tenant.name,
                status=TenantStatus.suspended.value,
                sign_in_ready=False,
            ),
        )

    return TenantDiscoveryResponse(
        multi_tenancy_enabled=True,
        tenant=PublicTenantInfo(
            slug=tenant.slug,
            name=tenant.name,
            status=TenantStatus.active.value,
            sign_in_ready=await _resolve_sign_in_ready(db, tenant),
        ),
    )


@TenantAuthRouter.get("/tenant-memberships", response_model=TenantMembershipsResponse)
async def list_my_tenant_memberships(
    request: Request,
    db: DbSession,
) -> TenantMembershipsResponse:
    """List the authenticated caller's active tenant memberships.

    Powers the sign-in organization picker: only the caller's own
    memberships are visible, default tenant first.  Returns an empty
    list when the tenancy switch is off.
    """
    settings_service = get_platform_settings_service()
    multi_tenancy_enabled = await settings_service.is_multi_tenancy_enabled(db)
    if not multi_tenancy_enabled:
        return TenantMembershipsResponse(multi_tenancy_enabled=False, items=[])

    claims = getattr(request.state, "identity", {}) or {}
    sub = claims.get("sub", "")
    if not sub:
        return TenantMembershipsResponse(multi_tenancy_enabled=True, items=[])

    # Identity-plane lookup (FIX-20260929-221449): the caller resolves by
    # sub regardless of any session tenant scope — the org picker must
    # see the platform-level user record.
    from app.db.tenant_scoping import execute_unscoped

    user_result = await execute_unscoped(
        db, select(PlatformUser).where(PlatformUser.sub == sub)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        return TenantMembershipsResponse(multi_tenancy_enabled=True, items=[])

    result = await db.execute(
        select(TenantUserMembership, Tenant)
        .join(Tenant, Tenant.id == TenantUserMembership.tenant_id)
        .where(
            TenantUserMembership.user_id == user.id,
            TenantUserMembership.status == TenantUserMembershipStatus.active,
            Tenant.status == TenantStatus.active,
        )
        .order_by(
            TenantUserMembership.is_default.desc(),
            Tenant.name.asc(),
        )
    )
    items = [
        TenantMembershipRead(
            tenant_id=str(membership.tenant_id),
            tenant_slug=tenant.slug,
            tenant_name=tenant.name,
            tenant_role=membership.tenant_role.value,
            is_default=bool(membership.is_default),
        )
        for membership, tenant in result.all()
    ]
    return TenantMembershipsResponse(multi_tenancy_enabled=True, items=items)


# ── Self-serve registration & platform-password sign-in (Phase 10) ──────────


class RegisterAccountRequest(BaseModel):
    """Account-first self-serve registration input."""

    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)
    organization_name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=3, max_length=63, description="Desired tenant address")


class RegisterAccountResponse(BaseModel):
    """The new tenant identity + an authenticated root session."""

    tenant_id: str
    name: str
    slug: str
    your_role: str
    is_root: bool
    access_token: str
    token_type: str = "bearer"


class LoginPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)


class LoginPasswordResponse(BaseModel):
    """Tenant-bound session for a platform-issued account."""

    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    your_role: str


@TenantAuthRouter.post("/register", response_model=RegisterAccountResponse)
@_limiter.limit("10/hour")
async def register_account(
    body: RegisterAccountRequest,
    request: Request,
    db: DbSession,
) -> RegisterAccountResponse:
    """PUBLIC account-first self-serve registration (multi-tenancy on only).

    Atomically creates the platform account (email + hashed password,
    platform-issued ``sub``), the tenant (name + unique slug) and the
    owner's ROOT membership in ONE transaction; returns the new tenant
    identity plus an authenticated session that lands the root user in
    guided onboarding.  Duplicate emails, one-tenant-per-user, slug
    conflicts and invalid fields are rejected BEFORE anything is
    written.  Replaces the authenticated ``register-organization``
    endpoint (removed).
    """
    from app.services.tenancy.platform_account_auth_service import (
        create_platform_account_token,
    )
    from app.services.tenancy.tenant_registration_service import (
        TenantRegistrationError,
        TenantRegistrationService,
        _throttle_check,
    )

    client_ip = request.client.host if request.client else "unknown"
    if not _throttle_check(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many registration attempts — please try again later",
        )

    service = TenantRegistrationService()
    try:
        result = await service.register(
            db,
            email=body.email,
            password=body.password,
            organization_name=body.organization_name,
            slug=body.slug,
            actor_ip=client_ip,
        )
        await db.commit()
    except TenantRegistrationError as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception:
        await db.rollback()
        logger.exception("Self-serve registration failed")
        raise HTTPException(
            status_code=500, detail="Registration failed — please try again"
        )

    await db.refresh(result.tenant)
    token = create_platform_account_token(
        user=result.user,
        tenant=result.tenant,
        tenant_role=result.membership.tenant_role.value,
    )
    return RegisterAccountResponse(
        tenant_id=str(result.tenant.id),
        name=result.tenant.name,
        slug=result.tenant.slug,
        your_role=result.membership.tenant_role.value,
        is_root=True,
        access_token=token,
    )


@TenantAuthRouter.post("/login-password", response_model=LoginPasswordResponse)
@_limiter.limit("30/minute")
async def login_password(
    body: LoginPasswordRequest,
    request: Request,
    db: DbSession,
) -> LoginPasswordResponse:
    """PUBLIC sign-in for platform-issued (self-serve) accounts.

    Authenticates email + password against the stored bcrypt credential
    and issues a tenant-bound platform JWT (the ``tenant`` claim satisfies
    the existing tenant-claim middleware check).  Failures are generic —
    no user enumeration.
    """
    from app.api.deps import NoWorkspaceAccessError
    from app.services.tenancy.platform_account_auth_service import (
        PlatformAccountAuthError,
        authenticate_platform_account,
        create_platform_account_token,
    )
    from app.services.tenancy.platform_settings_service import (
        get_platform_settings_service,
    )

    account = await authenticate_platform_account(
        db, email=body.email, password=body.password
    )
    if account is None:
        raise HTTPException(
            status_code=401, detail="Invalid email or password"
        )
    user, tenant, role = account

    # ── LOGIN ADMISSION (tenancy OFF): the root workspace is THE default
    # tenant and users cannot switch — signing in to any non-root tenant
    # is rejected even though the credentials are valid (Rule A).  The
    # structured no_access_to_workspace 403 is a permission denial, never
    # an auth failure — and no token is issued.
    multi_tenancy_enabled = await get_platform_settings_service(
    ).is_multi_tenancy_enabled(db)
    if not multi_tenancy_enabled and not bool(tenant.is_system_tenant):
        logger.warning(
            "login-password rejected under tenancy OFF: account belongs "
            "to non-root tenant slug=%s — the root workspace is the only "
            "tenant when multi-tenancy is disabled",
            tenant.slug,
        )
        raise NoWorkspaceAccessError(tenant_slug=tenant.slug)
    token = create_platform_account_token(user=user, tenant=tenant, tenant_role=role)
    return LoginPasswordResponse(
        access_token=token,
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        tenant_name=tenant.name,
        your_role=role,
    )
