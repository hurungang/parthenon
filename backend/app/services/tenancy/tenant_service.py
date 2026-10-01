"""Tenant Service — tenant lifecycle: create, suspend, resume, delete.

All lifecycle actions write ``TenantAuditEvent`` records and invalidate
the tenant resolution cache so changes take effect immediately
(suspend/delete block sign-in and API resolution right away).

Deletion is fail-safe by contract:
1. The tenant is soft-deleted first (``status=deleted``) — resolution
   fails immediately and atomically.
2. Hard deletion then removes every tenant-scoped row.  Direct-scoped
   tables (those carrying ``tenant_id``) are deleted in reverse
   topological order (children before parents); join/child tables that
   inherit scope via parents are removed by the parent rows' ``ON DELETE
   CASCADE`` FKs.  The slug becomes reusable afterwards.
3. Hard deletion requires an explicit confirmation (the tenant slug).
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenant import Tenant, TenantRole, TenantStatus
from app.db.models.tenant_audit_event import (
    TenantAuditActorType,
    TenantAuditEventType,
)
from app.services.tenancy.default_tenant_roles import seed_default_tenant_roles
from app.services.tenancy.tenant_audit_service import TenantAuditService
from app.services.tenancy.tenant_resolution_service import (
    get_tenant_resolution_service,
)

logger = logging.getLogger(__name__)

#: Tenant slug rules: DNS-label-safe (lowercase letters, digits, hyphens),
#: 3-63 chars, no leading/trailing hyphen.
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")


class TenantServiceError(Exception):
    """Raised when a tenant lifecycle operation fails validation."""


def validate_slug(slug: str) -> str:
    """Normalize and validate a tenant slug (the tenant address)."""
    normalized = slug.strip().lower()
    if not _SLUG_RE.match(normalized):
        raise TenantServiceError(
            "Slug must be 3-63 characters: lowercase letters, digits and "
            "hyphens, starting and ending with a letter or digit."
        )
    return normalized


class TenantService:
    """Tenant lifecycle management for the platform admin."""

    def __init__(self, audit_service: TenantAuditService | None = None) -> None:
        self._audit = audit_service or TenantAuditService()

    # ── Queries ──────────────────────────────────────────────────────────────

    async def get(self, db: AsyncSession, tenant_id: uuid.UUID) -> Optional[Tenant]:
        return await db.get(Tenant, tenant_id)

    async def get_by_slug(self, db: AsyncSession, slug: str) -> Optional[Tenant]:
        result = await db.execute(
            select(Tenant).where(Tenant.slug == slug.strip().lower())
        )
        return result.scalar_one_or_none()

    async def list_tenants(
        self,
        db: AsyncSession,
        *,
        status: TenantStatus | None = None,
    ) -> list[Tenant]:
        query = select(Tenant).order_by(Tenant.created_at.asc())
        if status is not None:
            query = query.where(Tenant.status == status)
        result = await db.execute(query)
        return list(result.scalars().all())

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def create(
        self,
        db: AsyncSession,
        *,
        name: str,
        slug: str,
        admin_contact_name: str | None = None,
        admin_contact_email: str | None = None,
        admin_contact_role: TenantRole = TenantRole.tenant_admin,
        is_onboarded: bool = False,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant:
        """Create a tenant workspace (name + unique slug + admin contact).

        Duplicates (name or slug) are rejected with clear errors.  The
        tenant starts ``active``; onboarding completion flips
        ``is_onboarded`` separately.
        """
        clean_name = (name or "").strip()
        if not clean_name:
            raise TenantServiceError("Tenant name is required.")
        if len(clean_name) > 200:
            raise TenantServiceError("Tenant name must be at most 200 characters.")
        normalized_slug = validate_slug(slug)

        existing_slug = await self.get_by_slug(db, normalized_slug)
        if existing_slug is not None:
            raise TenantServiceError(
                f"A tenant with slug '{normalized_slug}' already exists."
            )
        existing_name = await db.execute(
            select(Tenant).where(Tenant.name == clean_name)
        )
        if existing_name.scalar_one_or_none() is not None:
            raise TenantServiceError(
                f"A tenant named '{clean_name}' already exists."
            )

        tenant = Tenant(
            name=clean_name,
            slug=normalized_slug,
            status=TenantStatus.active,
            admin_contact_role=admin_contact_role,
            is_system_tenant=False,
            is_onboarded=is_onboarded,
            admin_contact_name=admin_contact_name,
            admin_contact_email=admin_contact_email,
        )
        db.add(tenant)
        await db.flush()

        await self._audit.record_safe(
            db,
            TenantAuditEventType.tenant_created,
            tenant_id=tenant.id,
            actor_type=(
                TenantAuditActorType.platform_admin
                if actor_id is not None
                else TenantAuditActorType.system
            ),
            actor_id=actor_id,
            target_resource=f"tenant:{tenant.slug}",
            detail={"name": clean_name, "slug": normalized_slug},
        )

        # Seed the four default tenant-scoped roles (Tenant System Admin,
        # Agent Manager, Agent Executor, Agent Viewer) so tenant members
        # can reach the business features out of the box.  Idempotent and
        # in-transaction: EVERY creation path (self-serve registration,
        # platform console, self-service orgs) funnels through here; the
        # root assignment happens in TenantProvisioningService once the
        # root membership exists.
        await seed_default_tenant_roles(db, tenant.id)

        logger.info("Tenant created: slug=%s id=%s", tenant.slug, tenant.id)
        return tenant

    async def suspend(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant:
        """Suspend a tenant: blocks sign-in and resolution immediately."""
        tenant = await self._require(db, tenant_id)
        if tenant.status == TenantStatus.suspended:
            raise TenantServiceError("Tenant is already suspended.")
        if tenant.status == TenantStatus.deleted:
            raise TenantServiceError("Tenant is deleted.")

        tenant.status = TenantStatus.suspended
        await db.flush()
        await self._invalidate_resolution(tenant.slug)
        await self._audit.record_safe(
            db,
            TenantAuditEventType.tenant_suspended,
            tenant_id=tenant.id,
            actor_type=(
                TenantAuditActorType.platform_admin
                if actor_id is not None
                else TenantAuditActorType.system
            ),
            actor_id=actor_id,
            target_resource=f"tenant:{tenant.slug}",
        )
        logger.info("Tenant suspended: slug=%s", tenant.slug)
        return tenant

    async def resume(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant:
        """Resume a suspended tenant."""
        tenant = await self._require(db, tenant_id)
        if tenant.status == TenantStatus.active:
            raise TenantServiceError("Tenant is already active.")
        if tenant.status == TenantStatus.deleted:
            raise TenantServiceError("Tenant is deleted.")

        tenant.status = TenantStatus.active
        await db.flush()
        await self._invalidate_resolution(tenant.slug)
        await self._audit.record_safe(
            db,
            TenantAuditEventType.tenant_resumed,
            tenant_id=tenant.id,
            actor_type=(
                TenantAuditActorType.platform_admin
                if actor_id is not None
                else TenantAuditActorType.system
            ),
            actor_id=actor_id,
            target_resource=f"tenant:{tenant.slug}",
        )
        logger.info("Tenant resumed: slug=%s", tenant.slug)
        return tenant

    async def update(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        name: str | None = None,
        admin_contact_name: str | None = None,
        admin_contact_email: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> Tenant:
        """Update tenant metadata (name, admin contact)."""
        tenant = await self._require(db, tenant_id)
        if tenant.status == TenantStatus.deleted:
            raise TenantServiceError("Tenant is deleted.")
        if name is not None:
            clean_name = name.strip()
            if not clean_name:
                raise TenantServiceError("Tenant name cannot be empty.")
            if clean_name != tenant.name:
                clash = await db.execute(
                    select(Tenant).where(Tenant.name == clean_name)
                )
                if clash.scalar_one_or_none() is not None:
                    raise TenantServiceError(
                        f"A tenant named '{clean_name}' already exists."
                    )
                tenant.name = clean_name
        if admin_contact_name is not None:
            tenant.admin_contact_name = admin_contact_name.strip() or None
        if admin_contact_email is not None:
            tenant.admin_contact_email = admin_contact_email.strip() or None
        await db.flush()
        await self._audit.record_safe(
            db,
            TenantAuditEventType.tenant_updated,
            tenant_id=tenant.id,
            actor_type=(
                TenantAuditActorType.platform_admin
                if actor_id is not None
                else TenantAuditActorType.system
            ),
            actor_id=actor_id,
            target_resource=f"tenant:{tenant.slug}",
        )
        return tenant

    async def delete(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        confirm_slug: str,
        actor_id: uuid.UUID | None = None,
    ) -> None:
        """Delete a tenant and ALL of its data (irreversible).

        Requires explicit confirmation: ``confirm_slug`` must equal the
        tenant's slug.  The tenant is soft-deleted first (immediate
        fail-closed resolution), then every tenant-scoped row is removed
        in reverse topological order so FK cascades clean up join/child
        tables.  The slug becomes reusable afterwards.
        """
        tenant = await self._require(db, tenant_id)
        if (confirm_slug or "").strip().lower() != tenant.slug:
            raise TenantServiceError(
                "Deletion confirmation failed: type the tenant address "
                f"'{tenant.slug}' to confirm."
            )
        if tenant.is_system_tenant:
            raise TenantServiceError("The system tenant cannot be deleted.")

        slug = tenant.slug
        tenant.status = TenantStatus.deleted
        await db.flush()
        # Fail-closed immediately: resolution cache drop blocks new traffic.
        await self._invalidate_resolution(slug)
        await self._audit.record_safe(
            db,
            TenantAuditEventType.tenant_deleted,
            tenant_id=None,  # the tenant row itself disappears below
            actor_type=(
                TenantAuditActorType.platform_admin
                if actor_id is not None
                else TenantAuditActorType.system
            ),
            actor_id=actor_id,
            target_resource=f"tenant:{slug}",
            detail={"deleted_tenant_id": str(tenant_id)},
        )

        await self._hard_delete_data(db, tenant_id)
        await db.delete(tenant)
        await db.flush()
        logger.info("Tenant deleted: slug=%s id=%s", slug, tenant_id)

    # ── Internals ────────────────────────────────────────────────────────────

    async def _require(self, db: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
        tenant = await db.get(Tenant, tenant_id)
        if tenant is None:
            raise TenantServiceError("Tenant not found.")
        return tenant

    async def _invalidate_resolution(self, slug: str) -> None:
        try:
            await get_tenant_resolution_service().invalidate(slug)
        except Exception:
            logger.exception("Failed to invalidate resolution cache for %s", slug)

    async def _hard_delete_data(
        self, db: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """Delete every tenant-scoped row (children before parents).

        ``Base.metadata.sorted_tables`` is dependency-ordered (referenced
        tables first), so iterating in reverse deletes children first and
        the parents' ``ON DELETE CASCADE`` FKs clean up join/child tables
        that inherit tenant scope via their parents.
        """
        from app.db.session import Base

        # Audit events survive tenant deletion (platform-level lifecycle
        # history; the tenant_id FK is ON DELETE SET NULL).
        PRESERVED_TABLES = {"tenants", "tenant_audit_events"}

        # Candidate deletes; executed children-first.  Tables in FK cycles
        # (unresolvable for topological sorting) may fail on the first
        # pass — failed tables are retried until no progress is made, so
        # mutually-dependent rows are removed once their counterparts are
        # gone.
        pending: list = []
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in PRESERVED_TABLES:
                continue
            tenant_col = table.columns.get("tenant_id")
            if tenant_col is not None:
                pending.append(table)

        deleted_tables = 0
        while pending:
            remaining: list = []
            for table in pending:
                try:
                    await db.execute(
                        table.delete().where(table.c.tenant_id == tenant_id)
                    )
                    deleted_tables += 1
                except Exception:
                    remaining.append(table)
            if len(remaining) == len(pending):
                # No progress — genuine FK obstruction; surface it.
                names = [t.name for t in remaining]
                raise RuntimeError(
                    f"Tenant data deletion blocked by FK constraints on: {names}"
                )
            pending = remaining
        logger.info(
            "Tenant data hard-deleted: tenant_id=%s tables=%d",
            tenant_id, deleted_tables,
        )
