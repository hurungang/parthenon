"""Tenant Provisioning Service — guided onboarding and self-service orgs.

- ``provision_tenant``: creates a tenant in the pending-onboarded state
  with its first admin (a ``tenant_admin`` membership).
- ``complete_onboarding``: flips ``is_onboarded`` once sign-in is
  connected and users are invited (idempotent, audited).
- ``create_organization_self_service``: a new user self-creates an
  organization and becomes its first ``tenant_admin``.  Exposed through
  a public, rate-limited endpoint that returns no data beyond the new
  organization's public identity.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.platform_user import PlatformUser
from app.db.models.tenant import Tenant, TenantRole, TenantStatus
from app.db.models.tenant_audit_event import (
    TenantAuditActorType,
    TenantAuditEventType,
)
from app.db.models.tenant_membership import (
    TenantUserMembership,
    TenantUserMembershipStatus,
)
from app.services.tenancy.default_tenant_roles import assign_tenant_system_admin_role
from app.services.tenancy.tenant_service import (
    TenantService,
    TenantServiceError,
    validate_slug,
)

logger = logging.getLogger(__name__)


class TenantProvisioningError(Exception):
    """Raised when tenant provisioning fails validation."""


class TenantProvisioningService:
    """Creates tenants with their first admin; completes onboarding."""

    def __init__(
        self,
        tenant_service: TenantService | None = None,
        audit_service=None,
    ) -> None:
        self._tenants = tenant_service or TenantService(audit_service=audit_service)

    async def provision_tenant(
        self,
        db: AsyncSession,
        *,
        name: str,
        slug: str,
        admin_user_id: uuid.UUID,
        admin_contact_name: str | None = None,
        admin_contact_email: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant:
        """Create a pending-onboarding tenant with *admin_user_id* as first admin."""
        tenant = await self._tenants.create(
            db,
            name=name,
            slug=slug,
            admin_contact_name=admin_contact_name,
            admin_contact_email=admin_contact_email,
            admin_contact_role=TenantRole.tenant_admin,
            is_onboarded=False,
            actor_id=actor_id,
        )
        user = await db.get(PlatformUser, admin_user_id)
        if user is None:
            raise TenantProvisioningError("First admin user not found.")
        db.add(
            TenantUserMembership(
                tenant_id=tenant.id,
                user_id=admin_user_id,
                tenant_role=TenantRole.tenant_admin,
                status=TenantUserMembershipStatus.active,
                is_default=True,
                # Phase 10: platform-created tenants make their primary
                # admin contact the tenant ROOT (owner membership) —
                # grants all tenant permissions; immutable.
                is_root=True,
            )
        )
        await db.flush()
        # The root (owner) holds the tenant's system-admin role so the
        # seeded tenant RBAC covers them too (idempotent; the default
        # roles themselves were seeded by TenantService.create above).
        await assign_tenant_system_admin_role(db, tenant.id, admin_user_id)
        logger.info(
            "Tenant provisioned: slug=%s first_admin=user:%s", tenant.slug, admin_user_id
        )
        return tenant

    async def complete_onboarding(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant:
        """Flip ``is_onboarded`` (idempotent; audited)."""
        tenant = await db.get(Tenant, tenant_id)
        if tenant is None:
            raise TenantProvisioningError("Tenant not found.")
        if not tenant.is_onboarded:
            tenant.is_onboarded = True
            await db.flush()
            await self._tenants._audit.record_safe(  # noqa: SLF001
                db,
                TenantAuditEventType.tenant_updated,
                tenant_id=tenant.id,
                actor_type=(
                    TenantAuditActorType.tenant_admin
                    if actor_id is not None
                    else TenantAuditActorType.system
                ),
                actor_id=actor_id,
                target_resource=f"tenant:{tenant.slug}",
                detail={"onboarding_completed": True},
            )
            logger.info("Tenant onboarding completed: slug=%s", tenant.slug)
        return tenant

    async def create_organization_self_service(
        self,
        db: AsyncSession,
        *,
        name: str,
        slug: str,
        creator_user_id: uuid.UUID,
    ) -> Tenant:
        """Self-service organization creation (public path).

        The creator becomes the organization's first ``tenant_admin``.
        Returns only public identity data to the caller.
        """
        creator = await db.get(PlatformUser, creator_user_id)
        if creator is None:
            raise TenantProvisioningError("Creator account not found.")
        tenant = await self.provision_tenant(
            db,
            name=name,
            slug=slug,
            admin_user_id=creator_user_id,
            admin_contact_name=creator.display_name,
            admin_contact_email=creator.email,
            actor_id=creator_user_id,
        )
        return tenant
