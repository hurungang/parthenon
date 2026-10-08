"""Tenant Adoption Service — root-tenant adoption when tenancy is enabled.

When the platform switch is turned on against an existing single-tenant
deployment, ALL pre-existing data is adopted into one implicit ROOT
tenant (``is_system_tenant = true``, workspace ``root`` — Phase 11 "the
platform is itself a tenant"):

1. The root tenant is created/renamed to its canonical identity
   (name ``Root``, slug ``root``).
2. Every tenant-scoped row with a NULL tenant reference is backfilled to
   the root tenant — existing users, roles, agents, MCP servers,
   skills, SOPs, schedules, model configs, provider configs and history
   keep working unchanged.  This INCLUDES the legacy global (tenant-less)
   business roles: they are re-homed into the root tenant's role space,
   retiring the global role variant (Phase 11 containment).
3. Existing administrators (holders of the ``system_admin`` role) are
   granted a ``platform_admin`` membership in the root tenant; every
   other existing user receives a regular membership.
4. The pre-existing identity provider (a global, tenant-less row)
   continues to serve as the root tenant's provider via the registry's
   root-slot fallback — no reconfiguration.

Idempotent: safe to re-run (it backfills only rows still NULL and only
creates missing memberships).  Runs behind the settings toggle, with the
switch still OFF, inside the caller's transaction.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select, text
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
from app.services.tenancy.root_tenant import (
    ROOT_TENANT_NAME,
    ROOT_TENANT_SLUG,
    ensure_root_tenant,
    invalidate_root_tenant_cache,
    seed_root_platform_admin_role,
)
from app.services.tenancy.tenant_audit_service import TenantAuditService

logger = logging.getLogger(__name__)

#: Fixed identity of the implicit ROOT tenant (Phase 11 rename from the
#: legacy ``system`` identity — resolution is by slug lookup, so runtime
#: references follow the row).
ROOT_ADMIN_ROLE_NAME = "system_admin"


class TenantAdoptionError(Exception):
    """Raised when system-tenant adoption cannot proceed."""


class TenantAdoptionService:
    """Adopts an existing deployment into the implicit ROOT tenant."""

    def __init__(self, audit_service: TenantAuditService | None = None) -> None:
        self._audit = audit_service or TenantAuditService()

    async def find_root_tenant(self, db: AsyncSession) -> Tenant | None:
        result = await db.execute(
            select(Tenant).where(Tenant.is_system_tenant.is_(True))
        )
        return result.scalar_one_or_none()

    # Backwards-compatible alias (pre-Phase-11 name).
    find_system_tenant = find_root_tenant

    async def adopt_system_tenant(
        self,
        db: AsyncSession,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Create/backfill the root tenant.  Idempotent.

        Returns a summary dict (slug, backfilled table count, memberships
        granted) used by the settings API response and audit detail.
        """
        system = await self.find_root_tenant(db)
        created = False
        if system is None:
            system = await ensure_root_tenant(db)
            created = True
            logger.info("Root tenant created: id=%s", system.id)
        else:
            # Normalize the identity in place (legacy 'system' → 'root').
            await ensure_root_tenant(db)
            invalidate_root_tenant_cache()

        backfilled = await self._backfill_null_tenant_rows(db, system.id)
        # Phase 3 alignment: the denormalized McpTool.tenant_id must equal
        # its server's tenant — a legacy tool row predating the column (or
        # re-created NULL by a race) is re-bound to its server's tenant so
        # enabling multi-tenancy can never leave divergent tool namespaces.
        # PostgreSQL-only DDL string; SQLite (unit tests) has no divergent
        # rows because tool rows are stamped by the flush listener.
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            await db.execute(
                text(
                    "UPDATE mcp_tools t SET tenant_id = s.tenant_id "
                    "FROM mcp_servers s "
                    "WHERE t.server_id = s.id AND t.tenant_id IS DISTINCT FROM s.tenant_id"
                )
            )
        memberships = await self._grant_memberships(db, system)
        # Consistency: the root tenant gets the four default tenant roles
        # too.  NOBODY is force-assigned here — existing users keep their
        # (re-homed) root-tenant roles.
        await seed_default_tenant_roles(db, system.id)
        # Phase 11 containment: seed the root Platform Admin role and
        # assign it to root platform_admin membership holders.
        await seed_root_platform_admin_role(db)
        invalidate_root_tenant_cache()

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
        stay, and the platform returns to the root-tenant world (the
        Phase 11 OFF default context) with legacy behaviour driven by the
        root's migrated roles.  The validation reports the state for the
        audit trail.
        """
        system = await self.find_root_tenant(db)
        tenant_count = (
            await db.execute(select(func.count()).select_from(Tenant))
        ).scalar() or 0
        return {
            "root_tenant_present": system is not None,
            "root_tenant_slug": system.slug if system else None,
            "tenants_remaining": int(tenant_count),
            "data_loss": False,
        }

    # ── Internals ────────────────────────────────────────────────────────────

    async def _backfill_null_tenant_rows(
        self, db: AsyncSession, root_tenant_id: uuid.UUID
    ) -> int:
        """Point every NULL tenant reference at the root tenant.

        Iterates the metadata in reverse topological order (children
        first) so parent rows exist for FK checks within the same pass.
        This is the adoption-time re-homing of legacy global roles
        (Phase 11): tenant-less business roles become root-tenant roles.
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
                .values(tenant_id=root_tenant_id)
            )
            touched += 1
        logger.info(
            "Adoption backfill: root_tenant=%s tables=%d",
            root_tenant_id, touched,
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
            .where(Role.name == ROOT_ADMIN_ROLE_NAME, Role.is_system.is_(True))
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
