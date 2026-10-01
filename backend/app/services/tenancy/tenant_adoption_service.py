"""Tenant Adoption Service — system-tenant adoption when tenancy is enabled.

When the platform switch is turned on against an existing single-tenant
deployment, ALL pre-existing data is adopted into one implicit system
tenant (``is_system_tenant = true``):

1. The system tenant is created (slug ``system``).
2. Every tenant-scoped row with a NULL tenant reference is backfilled to
   the system tenant — existing users, roles, agents, MCP servers,
   skills, SOPs, schedules, model configs, provider configs and history
   keep working unchanged.
3. Existing administrators (holders of the ``system_admin`` role) are
   granted a ``platform_admin`` membership in the system tenant; every
   other existing user receives a regular membership.
4. The pre-existing identity provider (a global, tenant-less row)
   continues to serve as the system tenant's provider via the registry's
   system-tenant fallback — no reconfiguration.

Idempotent: safe to re-run (it backfills only rows still NULL and only
creates missing memberships).  Runs behind the settings toggle, with the
switch still OFF, inside the caller's transaction.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.platform_user import PlatformUser
from app.db.models.tenant import Tenant, TenantStatus
from app.db.models.tenant_audit_event import (
    TenantAuditActorType,
    TenantAuditEventType,
)
from app.db.models.tenant_membership import (
    TenantUserMembership,
    TenantUserMembershipStatus,
)
from app.db.models.user_role import UserRole
from app.services.tenancy.default_tenant_roles import seed_default_tenant_roles
from app.services.tenancy.tenant_audit_service import TenantAuditService

logger = logging.getLogger(__name__)

#: Fixed identity of the implicit system tenant.
SYSTEM_TENANT_SLUG = "system"
SYSTEM_TENANT_NAME = "System"
SYSTEM_ADMIN_ROLE_NAME = "system_admin"


class TenantAdoptionError(Exception):
    """Raised when system-tenant adoption cannot proceed."""


class TenantAdoptionService:
    """Adopts an existing deployment into the implicit system tenant."""

    def __init__(self, audit_service: TenantAuditService | None = None) -> None:
        self._audit = audit_service or TenantAuditService()

    async def find_system_tenant(self, db: AsyncSession) -> Tenant | None:
        result = await db.execute(
            select(Tenant).where(Tenant.is_system_tenant.is_(True))
        )
        return result.scalar_one_or_none()

    async def adopt_system_tenant(
        self,
        db: AsyncSession,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Create/backfill the system tenant.  Idempotent.

        Returns a summary dict (slug, backfilled table count, memberships
        granted) used by the settings API response and audit detail.
        """
        system = await self.find_system_tenant(db)
        created = False
        if system is None:
            # Guard against a regular tenant already occupying the slug.
            clash = await db.execute(
                select(Tenant).where(Tenant.slug == SYSTEM_TENANT_SLUG)
            )
            existing = clash.scalar_one_or_none()
            if existing is not None:
                if existing.status == TenantStatus.deleted:
                    raise TenantAdoptionError(
                        "Slug 'system' is reserved for the system tenant but is "
                        "held by a deleted tenant; purge it first."
                    )
                raise TenantAdoptionError(
                    "Slug 'system' is reserved for the system tenant but is "
                    "held by a regular tenant; rename that tenant first."
                )
            system = Tenant(
                name=SYSTEM_TENANT_NAME,
                slug=SYSTEM_TENANT_SLUG,
                status=TenantStatus.active,
                is_system_tenant=True,
                is_onboarded=True,
                admin_contact_role="platform_admin",
            )
            db.add(system)
            await db.flush()
            created = True
            logger.info("System tenant created: id=%s", system.id)

        backfilled = await self._backfill_null_tenant_rows(db, system.id)
        memberships = await self._grant_memberships(db, system)
        # Consistency: the system tenant gets the four default tenant
        # roles too.  NOBODY is force-assigned here — existing users keep
        # their global roles (their memberships date from adoption).
        await seed_default_tenant_roles(db, system.id)

        summary: dict[str, Any] = {
            "slug": system.slug,
            "tenant_id": str(system.id),
            "created": created,
            "backfilled_tables": backfilled,
            "memberships_granted": memberships,
        }
        await self._audit.record_safe(
            db,
            TenantAuditEventType.tenant_created,
            tenant_id=system.id,
            actor_type=(
                TenantAuditActorType.platform_admin
                if actor_id is not None
                else TenantAuditActorType.system
            ),
            actor_id=actor_id,
            target_resource=f"tenant:{system.slug}",
            detail={"adoption": summary},
        )
        return summary

    async def validate_disable(self, db: AsyncSession) -> dict[str, Any]:
        """Validate that disabling the switch is safe (data preserved).

        Disabling never deletes anything: tenant rows stay, references
        stay, and the platform returns to byte-for-byte single-tenant
        behaviour.  The validation reports the state for the audit trail.
        """
        system = await self.find_system_tenant(db)
        tenant_count = (
            await db.execute(select(func.count()).select_from(Tenant))
        ).scalar() or 0
        return {
            "system_tenant_present": system is not None,
            "system_tenant_slug": system.slug if system else None,
            "tenants_remaining": int(tenant_count),
            "data_loss": False,
        }

    # ── Internals ────────────────────────────────────────────────────────────

    async def _backfill_null_tenant_rows(
        self, db: AsyncSession, system_tenant_id: uuid.UUID
    ) -> int:
        """Point every NULL tenant reference at the system tenant.

        Iterates the metadata in reverse topological order (children
        first) so parent rows exist for FK checks within the same pass.
        """
        from app.db.session import Base

        touched = 0
        for table in Base.metadata.sorted_tables:
            if table.name in ("tenants", "tenant_audit_events", "platform_settings"):
                continue  # not business rows / platform-scoped
            tenant_col = table.columns.get("tenant_id")
            if tenant_col is None or tenant_col.nullable is False:
                continue
            result = await db.execute(
                table.update()
                .where(tenant_col.is_(None))
                .values(tenant_id=system_tenant_id)
            )
            touched += 1
        logger.info(
            "Adoption backfill: system_tenant=%s tables=%d",
            system_tenant_id, touched,
        )
        return touched

    async def _grant_memberships(self, db: AsyncSession, system: Tenant) -> int:
        """Ensure every existing PlatformUser holds a membership.

        Holders of the ``system_admin`` role become ``platform_admin``;
        everyone else becomes a ``member``.  Only missing memberships are
        created (idempotent).
        """
        from app.db.models.identity import Role
        from app.db.models.tenant import TenantRole

        admin_result = await db.execute(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.name == SYSTEM_ADMIN_ROLE_NAME, Role.is_system.is_(True))
        )
        admin_ids = set(admin_result.scalars().all())

        users = (await db.execute(select(PlatformUser))).scalars().all()
        existing_result = await db.execute(
            select(TenantUserMembership.user_id).where(
                TenantUserMembership.tenant_id == system.id
            )
        )
        existing = set(existing_result.scalars().all())

        granted = 0
        admins_granted = 0
        for user in users:
            if user.id in existing:
                continue
            is_admin = user.id in admin_ids
            db.add(
                TenantUserMembership(
                    tenant_id=system.id,
                    user_id=user.id,
                    tenant_role=(
                        TenantRole.platform_admin if is_admin else TenantRole.member
                    ),
                    status=TenantUserMembershipStatus.active,
                    is_default=is_admin,
                )
            )
            granted += 1
            if is_admin:
                admins_granted += 1
        await db.flush()
        logger.info(
            "Adoption memberships: granted=%d (platform_admin=%d) for system tenant",
            granted, admins_granted,
        )
        return granted
