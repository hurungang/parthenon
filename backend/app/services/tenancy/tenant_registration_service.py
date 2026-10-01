"""Tenant Registration Service — account-first self-serve signup.

Creates, in ONE database transaction:

1. the ``PlatformUser`` (email + bcrypt password credential,
   platform-issued ``sub`` — deliberately outside the per-tenant OIDC
   registry);
2. the ``Tenant`` (name = alias, unique slug — the immutable address);
3. the owner's ROOT ``TenantUserMembership`` (``is_root = true``).

Validation happens BEFORE anything is written: duplicate email, invalid
fields, slug conflicts and the one-tenant-per-user rule (an existing
root membership) all reject with zero partial data.  The flow reuses
``TenantProvisioningService.provision_tenant`` (the 5.6 extension
point), which now stamps the first admin membership as the root — this
service SUPERSEDES the authenticated ``register-organization`` path.

Switch-gated (rejected when ``multi_tenancy_enabled = false``) and
basically throttled (simple in-process per-IP sliding window; the
public endpoints additionally sit behind the global slowapi limiter).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.platform_user import PlatformUser
from app.db.models.tenant import Tenant
from app.db.models.tenant_audit_event import (
    TenantAuditActorType,
    TenantAuditEventType,
)
from app.db.models.tenant_membership import (
    TenantUserMembership,
    TenantUserMembershipStatus,
)
from app.services.tenancy.platform_account_auth_service import (
    hash_password,
    is_valid_email,
    new_platform_sub,
    normalize_email,
    validate_password_rules,
)
from app.services.tenancy.platform_settings_service import (
    get_platform_settings_service,
)
from app.services.tenancy.tenant_audit_service import TenantAuditService
from app.services.tenancy.tenant_provisioning_service import (
    TenantProvisioningError,
    TenantProvisioningService,
)
from app.services.tenancy.tenant_service import TenantServiceError, validate_slug

logger = logging.getLogger(__name__)


class TenantRegistrationError(Exception):
    """Raised when self-serve registration fails validation.

    ``status_code`` suggests the HTTP mapping (409 conflicts, 403 gate,
    422 field validation).
    """

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class RegistrationResult:
    """The freshly created account + tenant + root membership."""

    user: PlatformUser
    tenant: Tenant
    membership: TenantUserMembership


# ── Basic in-process throttling (per-IP sliding window) ──────────────────────

_MAX_REGISTRATIONS_PER_WINDOW = 5
_WINDOW_SECONDS = 3600.0  # 1 hour
_attempts: dict[str, list[float]] = {}


def _throttle_check(ip: str) -> bool:
    """True when the IP may attempt registration now (records the attempt)."""
    now = time.monotonic()
    recent = [t for t in _attempts.get(ip, []) if now - t < _WINDOW_SECONDS]
    if len(recent) >= _MAX_REGISTRATIONS_PER_WINDOW:
        _attempts[ip] = recent
        return False
    recent.append(now)
    _attempts[ip] = recent
    return True


class TenantRegistrationService:
    """Atomic account-first self-serve tenant + owner registration."""

    def __init__(
        self,
        provisioning_service: TenantProvisioningService | None = None,
        audit_service: TenantAuditService | None = None,
    ) -> None:
        self._provisioning = provisioning_service or TenantProvisioningService()
        self._audit = audit_service or TenantAuditService()

    async def register(
        self,
        db: AsyncSession,
        *,
        email: str,
        password: str,
        organization_name: str,
        slug: str,
        actor_ip: str | None = None,
    ) -> RegistrationResult:
        """Create account + tenant + root membership in ONE transaction.

        All validation precedes any write; any failure leaves zero
        partial data (the caller owns commit/rollback of the single
        transaction).  Writes the ``self_serve_registration`` audit
        event on success.
        """
        # ── Switch gate (reject BEFORE anything else) ────────────────────
        if not await get_platform_settings_service().is_multi_tenancy_enabled(db):
            raise TenantRegistrationError(
                "Self-serve registration is not available on this platform",
                status_code=403,
            )

        # ── Field validation (no writes yet) ─────────────────────────────
        normalized_email = normalize_email(email)
        if not is_valid_email(normalized_email):
            raise TenantRegistrationError("A valid email address is required")
        password_problem = validate_password_rules(password)
        if password_problem:
            raise TenantRegistrationError(password_problem)
        clean_name = (organization_name or "").strip()
        if not clean_name:
            raise TenantRegistrationError("Organization name is required")
        if len(clean_name) > 200:
            raise TenantRegistrationError(
                "Organization name must be at most 200 characters"
            )
        normalized_slug = validate_slug(slug)

        # ── Uniqueness / one-tenant-per-user checks (still no writes) ────
        # The ONE-TENANT-PER-USER check runs FIRST: an existing account
        # that already ROOTS a tenant must receive the dedicated "one
        # organization" message (PRD), not the generic duplicate-email
        # error.  Plain existing accounts (no root membership) fall
        # through to the duplicate-email rejection below.
        existing_owner = (
            await db.execute(
                select(TenantUserMembership.id)
                .where(
                    TenantUserMembership.user_id == select(PlatformUser.id).where(
                        PlatformUser.email == normalized_email
                    ).scalar_subquery(),
                    TenantUserMembership.is_root.is_(True),
                    TenantUserMembership.status == TenantUserMembershipStatus.active,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing_owner is not None:
            raise TenantRegistrationError(
                "Each user can own only one organization", status_code=409,
            )

        existing_email = (
            await db.execute(
                select(PlatformUser).where(PlatformUser.email == normalized_email)
            )
        ).scalar_one_or_none()
        if existing_email is not None:
            # Generic-ish but actionable for the signer-upper's OWN input;
            # no account data is exposed beyond the conflict itself.
            raise TenantRegistrationError(
                "An account with this email already exists", status_code=409,
            )

        existing_slug = (
            await db.execute(select(Tenant).where(Tenant.slug == normalized_slug))
        ).scalar_one_or_none()
        if existing_slug is not None:
            raise TenantRegistrationError(
                f"The address '{normalized_slug}' is already taken",
                status_code=409,
            )

        # ── Writes (single transaction; caller commits) ──────────────────
        user = PlatformUser(
            sub=new_platform_sub(),
            email=normalized_email,
            display_name=normalized_email.split("@", 1)[0],
            password_credential=hash_password(password),
        )
        db.add(user)
        await db.flush()  # assigns user.id

        try:
            tenant = await self._provisioning.provision_tenant(
                db,
                name=clean_name,
                slug=normalized_slug,
                admin_user_id=user.id,
                admin_contact_name=user.display_name,
                admin_contact_email=user.email,
                # Audit attribution: registration is a self-service (not
                # platform-admin) action.
                actor_id=None,
            )
        except TenantServiceError as exc:
            # Slug raced between validation and creation — clean abort.
            raise TenantRegistrationError(str(exc), status_code=409) from exc

        membership = (
            await db.execute(
                select(TenantUserMembership).where(
                    TenantUserMembership.tenant_id == tenant.id,
                    TenantUserMembership.user_id == user.id,
                )
            )
        ).scalar_one()

        await self._audit.record_safe(
            db,
            TenantAuditEventType.self_serve_registration,
            tenant_id=tenant.id,
            actor_type=TenantAuditActorType.tenant_admin,
            actor_id=user.id,
            actor_ip=actor_ip,
            target_resource=f"tenant:{tenant.slug}",
            detail={
                "email": normalized_email,
                "slug": tenant.slug,
                "name": tenant.name,
            },
        )

        logger.info(
            "Self-serve registration: tenant=%s owner=user:%s",
            tenant.slug, user.id,
        )
        return RegistrationResult(user=user, tenant=tenant, membership=membership)


_service: TenantRegistrationService | None = None


def get_tenant_registration_service() -> TenantRegistrationService:
    """Return the module-level TenantRegistrationService singleton."""
    global _service
    if _service is None:
        _service = TenantRegistrationService()
    return _service
