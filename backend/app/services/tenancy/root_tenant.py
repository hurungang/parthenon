"""Root tenant helpers — the platform is itself a tenant (Phase 11).

The **root tenant** (workspace ``root``) is the single tenant carrying
``is_system_tenant = true`` (the historical column name is retained —
its blast radius exceeded the rename threshold; see tech-spec.md. It is
the alias of the design's ``is_root_tenant`` flag). It:

- hosts platform staff as ordinary members holding platform roles;
- adopts pre-existing data when multi-tenancy is enabled;
- is the DEFAULT tenant context when the tenancy switch is OFF (the
  one-tenant world) — legacy behaviour is driven by the legacy global
  roles re-homed into its role space.

This module is the single source of truth for the root tenant identity
(slug/name constants) and offers idempotent helpers:

- :func:`get_root_tenant` / :func:`get_root_tenant_id` — lookups
  (short-TTL cached; resolution by slug lookup means runtime references
  follow the row).
- :func:`ensure_root_tenant` — create the root tenant when missing.
- :func:`rehome_global_roles` — move tenant-less business roles (and
  their policy linkage) into the root tenant.
- :func:`seed_root_platform_admin_role` — seed the root-scoped
  ``Platform Admin`` role (``platform::*`` grants) and assign it to
  root ``platform_admin`` membership holders.

All helpers are idempotent and transaction-agnostic (caller commits).
"""
from __future__ import annotations

import logging
import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenant import Tenant, TenantStatus

logger = logging.getLogger(__name__)

#: Fixed identity of the root tenant (workspace ``root``).
ROOT_TENANT_SLUG = "root"
ROOT_TENANT_NAME = "Root"

#: The root tenant's platform role: carries the ``platform::*`` grants.
#: With permission containment, ``platform::*`` checks evaluate the
#: SESSION tenant's roles — so platform staff must hold this ROOT-scoped
#: role (membership alone no longer unlocks the platform console).
PLATFORM_ADMIN_ROLE_NAME = "Platform Admin"

#: Role names owned by the default-tenant-roles seeder — never re-homed
#: back to NULL on downgrade of the Phase 11 migration.
DEFAULT_TENANT_ROLE_NAMES = (
    "Tenant System Admin",
    "Agent Manager",
    "Agent Executor",
    "Agent Viewer",
)

# Short-TTL cache for the root tenant id (resolution by slug lookup means
# runtime references follow the row; a stale id across a TTL window is
# benign — the row is never deleted).
_root_tenant_id_cache: tuple[uuid.UUID | None, float] | None = None
_ROOT_TENANT_CACHE_TTL = 30.0

# Short-TTL cache for the root tenant's immutable TenantContext (used by
# the resolution middleware as the tenancy-OFF default context).
_root_context_cache: tuple[Any | None, float] | None = None


def invalidate_root_tenant_cache() -> None:
    """Drop the cached root tenant id/context (call after adoption/migration)."""
    global _root_tenant_id_cache, _root_context_cache
    _root_tenant_id_cache = None
    _root_context_cache = None


async def get_root_tenant_context(db: AsyncSession) -> Any | None:
    """The root tenant's immutable TenantContext (short-TTL cached), or None.

    Used by the tenant-resolution middleware as the DEFAULT context when
    the tenancy switch is OFF (the one-tenant world).  Returns None when
    the root tenant has not been created/adopted yet — callers fall back
    to context-less legacy behaviour (fail-safe).
    """
    from app.core.tenant_context import TenantContext

    global _root_context_cache
    now = time.monotonic()
    if _root_context_cache is not None:
        cached, cached_at = _root_context_cache
        if now - cached_at < _ROOT_TENANT_CACHE_TTL:
            return cached
    tenant = await get_root_tenant(db)
    context = (
        TenantContext(
            tenant_id=tenant.id,
            slug=tenant.slug,
            name=tenant.name,
            is_system_tenant=True,
        )
        if tenant is not None
        else None
    )
    _root_context_cache = (context, now)
    return context


async def get_root_tenant(db: AsyncSession) -> Tenant | None:
    """The tenant with ``is_system_tenant = true``, or None."""
    result = await db.execute(select(Tenant).where(Tenant.is_system_tenant.is_(True)))
    return result.scalar_one_or_none()


async def get_root_tenant_id(db: AsyncSession) -> uuid.UUID | None:
    """The root tenant's id (short-TTL cached), or None when not adopted yet."""
    global _root_tenant_id_cache
    now = time.monotonic()
    if _root_tenant_id_cache is not None:
        cached_id, cached_at = _root_tenant_id_cache
        if now - cached_at < _ROOT_TENANT_CACHE_TTL:
            return cached_id
    tenant = await get_root_tenant(db)
    _root_tenant_id_cache = (tenant.id if tenant else None, now)
    return tenant.id if tenant else None


async def ensure_root_tenant(db: AsyncSession) -> Tenant:
    """Create the root tenant when missing (idempotent).

    Guarantees exactly one root tenant with the canonical workspace
    identity (name ``Root`` / slug ``root``).  When a root tenant exists
    under legacy identity (name ``System`` / slug ``system``, pre-Phase
    11), it is renamed in place — resolution is by slug lookup so runtime
    references follow the row.
    """
    root = await get_root_tenant(db)
    if root is not None:
        if root.slug != ROOT_TENANT_SLUG or root.name != ROOT_TENANT_NAME:
            clash = (
                await db.execute(
                    select(Tenant).where(
                        Tenant.slug == ROOT_TENANT_SLUG,
                        Tenant.id != root.id,
                    )
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise RuntimeError(
                    f"Slug '{ROOT_TENANT_SLUG}' is reserved for the root tenant "
                    f"but is held by tenant '{clash.name}' (id={clash.id})."
                )
            root.name = ROOT_TENANT_NAME
            root.slug = ROOT_TENANT_SLUG
            await db.flush()
            invalidate_root_tenant_cache()
            logger.info(
                "Root tenant renamed in place: id=%s slug=%s", root.id, root.slug
            )
        return root

    clash = (
        await db.execute(select(Tenant).where(Tenant.slug == ROOT_TENANT_SLUG))
    ).scalar_one_or_none()
    if clash is not None:
        raise RuntimeError(
            f"Slug '{ROOT_TENANT_SLUG}' is reserved for the root tenant but is "
            f"held by tenant '{clash.name}' (id={clash.id}); rename it first."
        )
    root = Tenant(
        name=ROOT_TENANT_NAME,
        slug=ROOT_TENANT_SLUG,
        status=TenantStatus.active,
        is_system_tenant=True,
        is_onboarded=True,
        admin_contact_role="platform_admin",
    )
    db.add(root)
    await db.flush()
    invalidate_root_tenant_cache()
    logger.info("Root tenant created: id=%s slug=%s", root.id, root.slug)
    return root


async def rehome_global_roles(db: AsyncSession) -> int:
    """Re-home tenant-less business roles into the root tenant.

    Every ``Role`` row with ``tenant_id IS NULL`` becomes a root-tenant
    role; its ``PolicyStatement`` rows move with it (statements are
    linked by ``role_id`` FK — ``PolicyAction``/``PolicyResource``/
    ``PolicyTagCondition`` ride the statement).  The statements' own
    ``tenant_id`` is stamped to root for consistency.  The global
    ``Permission`` catalogue is NOT tenant-scoped and is untouched.

    After this runs, no business role rows with NULL ``tenant_id``
    remain.  Idempotent (only NULL rows move).  Caller commits.
    """
    from app.db.models.policy_statement import PolicyStatement
    from app.db.models.identity import Role

    root = await ensure_root_tenant(db)
    roles = (
        await db.execute(select(Role).where(Role.tenant_id.is_(None)))
    ).scalars().all()
    if not roles:
        return 0
    role_ids = [role.id for role in roles]
    for role in roles:
        role.tenant_id = root.id
    await db.execute(
        PolicyStatement.__table__.update()
        .where(PolicyStatement.role_id.in_(role_ids))
        .values(tenant_id=root.id)
    )
    logger.info(
        "Re-homed %d global role(s) into the root tenant (id=%s)",
        len(roles), root.id,
    )
    return len(roles)


async def seed_root_platform_admin_role(db: AsyncSession) -> None:
    """Seed the root-scoped ``Platform Admin`` role (idempotent).

    One ``platform::*`` wildcard policy statement (allow, action ``*``,
    wildcard resource) in the BootstrapService storage layout the
    permission engine consumes, assigned via ``UserRole`` to every user
    holding an ACTIVE ``platform_admin`` membership in the root tenant
    who lacks the role.  Caller commits.
    """
    from app.db.models.identity import Role, RoleType
    from app.db.models.policy_action import PolicyAction
    from app.db.models.policy_resource import PolicyResource
    from app.db.models.policy_statement import PolicyEffect, PolicyStatement
    from app.db.models.tenant_membership import (
        TenantUserMembership,
        TenantUserMembershipStatus,
    )
    from app.db.models.user_role import UserRole

    root = await ensure_root_tenant(db)
    role = (
        await db.execute(
            select(Role).where(
                Role.name == PLATFORM_ADMIN_ROLE_NAME,
                Role.tenant_id == root.id,
                Role.is_system.is_(True),
            )
        )
    ).scalar_one_or_none()
    if role is None:
        role = Role(
            name=PLATFORM_ADMIN_ROLE_NAME,
            description=(
                "Platform administration (root tenant) — platform modules "
                "only; grants nothing inside any customer tenant."
            ),
            role_type=RoleType.user,
            is_system=True,
            is_active=True,
            tenant_id=root.id,
        )
        db.add(role)
        await db.flush()
        logger.info("Root Platform Admin role created: id=%s", role.id)

    stmt = (
        await db.execute(
            select(PolicyStatement).where(
                PolicyStatement.role_id == role.id,
                PolicyStatement.module == "platform::*",
                PolicyStatement.effect == PolicyEffect.allow,
            )
        )
    ).scalar_one_or_none()
    if stmt is None:
        stmt = PolicyStatement(
            role_id=role.id,
            tenant_id=root.id,
            effect=PolicyEffect.allow,
            module="platform::*",
        )
        db.add(stmt)
        await db.flush()
        db.add(PolicyAction(policy_statement_id=stmt.id, action="*", tenant_id=root.id))
        db.add(
            PolicyResource(
                policy_statement_id=stmt.id,
                resource_type="*",
                resource_id="*",
                tenant_id=root.id,
            )
        )
        await db.flush()

    members = (
        await db.execute(
            select(TenantUserMembership.user_id).where(
                TenantUserMembership.tenant_id == root.id,
                TenantUserMembership.status == TenantUserMembershipStatus.active,
                TenantUserMembership.tenant_role == "platform_admin",
            )
        )
    ).scalars().all()
    if not members:
        return
    existing = (
        await db.execute(
            select(UserRole.user_id).where(
                UserRole.user_id.in_(members), UserRole.role_id == role.id
            )
        )
    ).scalars().all()
    missing = set(members) - set(existing)
    for user_id in missing:
        db.add(UserRole(user_id=user_id, role_id=role.id))
    if missing:
        await db.flush()
        logger.info(
            "Platform Admin role assigned to %d root platform_admin member(s)",
            len(missing),
        )
