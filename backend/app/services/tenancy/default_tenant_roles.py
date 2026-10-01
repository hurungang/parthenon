"""Default tenant-scoped roles — presets, idempotent seeding, startup sweep.

Every tenant is created with four built-in roles so its members can use
the business features (agents, MCP hub, ...) out of the box:

- ``Tenant System Admin`` — every tenant-relevant permission (agent::*,
  integration::*, system::*, tenant::*) with the full allowed action set
  from the resource-type manifest.  NEVER ``platform::*`` — that stays
  the platform-admin domain.  Assigned automatically to the tenant ROOT
  (owner) membership.
- ``Agent Manager`` — full manage over the agent domain plus the reads
  needed to configure agents (MCP hub visibility, permission inspection).
- ``Agent Executor`` — what is needed to RUN agents: launch/control
  executions, respond to human interventions, read runs and results.
- ``Agent Viewer`` — read-only visibility across the agent, integration
  and system modules.

Presets are expressed as data (resource_type → action set) and are
validated against the manifest (``backend/app/core/resource_types.py``)
at seed time — an unknown resource type or out-of-manifest action fails
loudly instead of silently granting nothing.

Permission storage mirrors the canonical role seeding path
(``app.services.permissions.bootstrap_service``): each preset action set
becomes one ``PolicyStatement`` per resource type (``effect=allow``,
``module=<resource_type>``) with one ``PolicyAction`` per action and one
wildcard ``PolicyResource``.  Rows carry the tenant id explicitly because
seeding runs on unscoped sessions (public registration, startup sweep)
and the tenant scoping choke point filters policy rows by ``tenant_id``
in tenant-bound request sessions.
"""
from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.resource_types import (
    MODULE_GROUPS,
    ResourceTypeManifest,
    RT_AGENT,
    RT_AGENT_DATA,
    RT_AGENT_DATA_TYPES,
    RT_AGENT_HUMAN_INTERVENTION,
    RT_AGENT_IDENTITIES,
    RT_AGENT_MANAGEMENT,
    RT_AGENT_MODEL_CONFIGS,
    RT_AGENT_OUTPUTS,
    RT_AGENT_ROLES,
    RT_AGENT_RUNTIME_CONTROL,
    RT_AGENT_SCHEDULES,
    RT_AGENT_SKILLS,
    RT_AGENT_SOPS,
    RT_AGENT_TRAILS,
    RT_API_KEYS,
    RT_INTEGRATION_MCP_HUB,
    RT_INTEGRATION_NOTIFICATIONS,
    RT_SYSTEM_CONFIG,
    RT_SYSTEM_OBSERVABILITY,
    RT_SYSTEM_PERMISSIONS,
)
from app.db.models.identity import Role
from app.db.models.policy_action import PolicyAction
from app.db.models.policy_resource import PolicyResource
from app.db.models.policy_statement import PolicyEffect, PolicyStatement
from app.db.models.tenant import Tenant, TenantRole, TenantStatus
from app.db.models.tenant_membership import (
    TenantUserMembership,
    TenantUserMembershipStatus,
)
from app.db.models.user_role import UserRole

logger = logging.getLogger(__name__)

# ── Stable identifiers (DB-facing role names; per-tenant unique) ─────────────

TENANT_SYSTEM_ADMIN_KEY: Final[str] = "tenant_system_admin"
AGENT_MANAGER_KEY: Final[str] = "agent_manager"
AGENT_EXECUTOR_KEY: Final[str] = "agent_executor"
AGENT_VIEWER_KEY: Final[str] = "agent_viewer"

TENANT_SYSTEM_ADMIN_ROLE_NAME: Final[str] = "Tenant System Admin"
AGENT_MANAGER_ROLE_NAME: Final[str] = "Agent Manager"
AGENT_EXECUTOR_ROLE_NAME: Final[str] = "Agent Executor"
AGENT_VIEWER_ROLE_NAME: Final[str] = "Agent Viewer"

#: Module groups a TENANT role may span — everything except the platform
#: admin console (``platform::*``), which remains platform-admin-only.
_TENANT_MODULE_GROUP_NAMES: Final[tuple[str, ...]] = (
    "agent",
    "integration",
    "system",
    "tenant",
)


# ── Presets (data; validated against the manifest at seed time) ──────────────


@dataclass(frozen=True)
class DefaultTenantRolePreset:
    """One default tenant role: stable key, display name, permission set."""

    key: str
    role_name: str
    description: str
    #: resource_type → allowed actions (all must exist in the manifest)
    permissions: dict[str, frozenset[str]]


def _full_tenant_permissions() -> dict[str, frozenset[str]]:
    """Every tenant-relevant resource type with its FULL manifest actions.

    Derived directly from the manifest so newly registered tenant-relevant
    resource types are automatically covered for the system-admin preset.
    The bare ``agent`` type (not a MODULE_GROUPS member) is added
    explicitly — it gates the agent-type CRUD / session surfaces in
    ``agents.py`` and must be granted to the tenant admin too.
    """
    permissions = {
        resource_type: frozenset(ResourceTypeManifest[resource_type]["actions"])
        for group in _TENANT_MODULE_GROUP_NAMES
        for resource_type in MODULE_GROUPS[group]
    }
    permissions[RT_AGENT] = frozenset(ResourceTypeManifest[RT_AGENT]["actions"])
    return permissions


TENANT_SYSTEM_ADMIN_PRESET: Final[DefaultTenantRolePreset] = DefaultTenantRolePreset(
    key=TENANT_SYSTEM_ADMIN_KEY,
    role_name=TENANT_SYSTEM_ADMIN_ROLE_NAME,
    description=(
        "Full access to every tenant-managed module (agents, integrations, "
        "system and tenant workspace). Held by the tenant owner."
    ),
    permissions=_full_tenant_permissions(),
)

AGENT_MANAGER_PRESET: Final[DefaultTenantRolePreset] = DefaultTenantRolePreset(
    key=AGENT_MANAGER_KEY,
    role_name=AGENT_MANAGER_ROLE_NAME,
    description=(
        "Create and manage agents, identities, skills, SOPs, schedules and "
        "related agent data; browse the MCP hub to wire tools into agents."
    ),
    permissions={
        # Bare "agent" gates the agent-type CRUD / session surfaces in
        # agents.py — a manager needs its full action set.
        RT_AGENT: frozenset({"create", "read", "update", "delete", "execute"}),
        RT_API_KEYS: frozenset({"read", "manage"}),
        RT_AGENT_ROLES: frozenset({"read", "manage"}),
        RT_AGENT_IDENTITIES: frozenset({"read", "manage"}),
        RT_AGENT_MANAGEMENT: frozenset({"create", "read", "update", "delete", "execute"}),
        RT_AGENT_RUNTIME_CONTROL: frozenset({"read", "execute"}),
        RT_AGENT_SKILLS: frozenset({"create", "read", "update", "delete", "execute"}),
        RT_AGENT_SOPS: frozenset({"read", "manage"}),
        RT_AGENT_MODEL_CONFIGS: frozenset({"read", "manage"}),
        RT_AGENT_SCHEDULES: frozenset({"create", "read", "update", "delete"}),
        RT_AGENT_TRAILS: frozenset({"create", "read", "update", "delete"}),
        RT_AGENT_HUMAN_INTERVENTION: frozenset({"view", "respond"}),
        RT_AGENT_DATA_TYPES: frozenset({"create", "read", "update", "delete", "manage"}),
        RT_AGENT_DATA: frozenset({"read"}),
        RT_AGENT_OUTPUTS: frozenset({"read"}),
        # Reads needed to configure agents (MCP tool visibility) and to
        # inspect the permission setup the agents rely on.
        RT_INTEGRATION_MCP_HUB: frozenset({"read"}),
        RT_SYSTEM_PERMISSIONS: frozenset({"read"}),
    },
)

AGENT_EXECUTOR_PRESET: Final[DefaultTenantRolePreset] = DefaultTenantRolePreset(
    key=AGENT_EXECUTOR_KEY,
    role_name=AGENT_EXECUTOR_ROLE_NAME,
    description=(
        "Launch and control agent executions, respond to human "
        "interventions and inspect run trails and results."
    ),
    permissions={
        # Bare "agent" gates the session launch/control surfaces — an
        # executor needs read + execute there.
        RT_AGENT: frozenset({"read", "execute"}),
        RT_AGENT_MANAGEMENT: frozenset({"read", "execute"}),
        RT_AGENT_RUNTIME_CONTROL: frozenset({"read", "execute"}),
        RT_AGENT_SKILLS: frozenset({"read", "execute"}),
        RT_AGENT_SOPS: frozenset({"read"}),
        RT_AGENT_TRAILS: frozenset({"read"}),
        RT_AGENT_HUMAN_INTERVENTION: frozenset({"view", "respond"}),
        RT_AGENT_DATA: frozenset({"read"}),
        RT_AGENT_OUTPUTS: frozenset({"read"}),
        RT_INTEGRATION_MCP_HUB: frozenset({"read"}),
    },
)

AGENT_VIEWER_PRESET: Final[DefaultTenantRolePreset] = DefaultTenantRolePreset(
    key=AGENT_VIEWER_KEY,
    role_name=AGENT_VIEWER_ROLE_NAME,
    description=(
        "Read-only visibility across the agent, integration and system "
        "modules."
    ),
    permissions={
        RT_AGENT: frozenset({"read"}),
        RT_API_KEYS: frozenset({"read"}),
        RT_AGENT_ROLES: frozenset({"read"}),
        RT_AGENT_IDENTITIES: frozenset({"read"}),
        RT_AGENT_MANAGEMENT: frozenset({"read"}),
        RT_AGENT_RUNTIME_CONTROL: frozenset({"read"}),
        RT_AGENT_SKILLS: frozenset({"read"}),
        RT_AGENT_SOPS: frozenset({"read"}),
        RT_AGENT_MODEL_CONFIGS: frozenset({"read"}),
        RT_AGENT_SCHEDULES: frozenset({"read"}),
        RT_AGENT_TRAILS: frozenset({"read"}),
        # human_intervention exposes view/respond only — no plain read.
        RT_AGENT_HUMAN_INTERVENTION: frozenset({"view"}),
        RT_AGENT_DATA_TYPES: frozenset({"read"}),
        RT_AGENT_DATA: frozenset({"read"}),
        RT_AGENT_OUTPUTS: frozenset({"read"}),
        RT_INTEGRATION_MCP_HUB: frozenset({"read"}),
        RT_INTEGRATION_NOTIFICATIONS: frozenset({"read"}),
        RT_SYSTEM_OBSERVABILITY: frozenset({"read"}),
        RT_SYSTEM_PERMISSIONS: frozenset({"read"}),
        RT_SYSTEM_CONFIG: frozenset({"read"}),
    },
)

#: All presets, system admin first (insertion order is the seed order).
DEFAULT_TENANT_ROLE_PRESETS: Final[dict[str, DefaultTenantRolePreset]] = {
    TENANT_SYSTEM_ADMIN_PRESET.key: TENANT_SYSTEM_ADMIN_PRESET,
    AGENT_MANAGER_PRESET.key: AGENT_MANAGER_PRESET,
    AGENT_EXECUTOR_PRESET.key: AGENT_EXECUTOR_PRESET,
    AGENT_VIEWER_PRESET.key: AGENT_VIEWER_PRESET,
}


class DefaultTenantRole(str, enum.Enum):
    """The four seeded preset roles, addressable by their stable keys.

    Used by ``IdentityProviderConfig.default_tenant_role`` (JIT default
    role on first OIDC sign-in, FIX-20260930-075014).  Values are the
    EXACT preset keys — the DB-facing identifiers of the seeded roles.
    """

    tenant_system_admin = TENANT_SYSTEM_ADMIN_KEY
    agent_manager = AGENT_MANAGER_KEY
    agent_executor = AGENT_EXECUTOR_KEY
    agent_viewer = AGENT_VIEWER_KEY


def _role_key(value: "str | DefaultTenantRole") -> str | None:
    """Normalize a default-role value (str or enum) to a preset key."""
    key = value.value if isinstance(value, DefaultTenantRole) else str(value)
    return key if key in DEFAULT_TENANT_ROLE_PRESETS else None


async def jit_membership_with_default_role(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role_key: "str | DefaultTenantRole",
) -> bool:
    """JIT admission (FIX-20260930-075014): create an ACTIVE member
    membership for *user_id* in *tenant_id* and assign the tenant's preset
    role for *role_key* — idempotent.

    Returns True when a NEW membership was created (first sign-in);
    False when the user already holds an ACTIVE membership in the tenant
    (second sign-in → nothing happens).

    The PlatformUser row itself is provisioned by the existing
    identity-plane upsert (``UserCacheService.upsert_user``) before this
    runs.  Seeding joins the caller's transaction (commits are left to
    the caller, as in :func:`seed_default_tenant_roles`).
    """
    key = _role_key(role_key)
    if key is None:
        logger.warning(
            "JIT default role: unknown role key %r — skipping (no membership)",
            role_key,
        )
        return False
    preset = DEFAULT_TENANT_ROLE_PRESETS[key]

    existing = (
        await db.execute(
            select(TenantUserMembership).where(
                TenantUserMembership.tenant_id == tenant_id,
                TenantUserMembership.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status == TenantUserMembershipStatus.active:
            return False  # second sign-in — idempotent no-op
        logger.warning(
            "JIT default role: user=%s holds an INACTIVE membership in "
            "tenant=%s — not auto-reactivating",
            user_id, tenant_id,
        )
        return False

    db.add(
        TenantUserMembership(
            tenant_id=tenant_id,
            user_id=user_id,
            tenant_role=TenantRole.member,
            status=TenantUserMembershipStatus.active,
            is_root=False,
        )
    )
    await db.flush()

    role = (
        await db.execute(
            select(Role).where(
                Role.tenant_id == tenant_id, Role.name == preset.role_name
            )
        )
    ).scalar_one_or_none()
    if role is None:
        roles = await seed_default_tenant_roles(db, tenant_id)
        role = roles[key]
    await _ensure_user_role(db, user_id, role)
    logger.info(
        "JIT admission: user=%s admitted to tenant=%s with preset role '%s'",
        user_id, tenant_id, preset.role_name,
    )
    return True


def validate_presets_against_manifest() -> None:
    """Raise ``ValueError`` when a preset leaves the manifest.

    Guards against drift: a resource type removed/renamed in the manifest
    or an action that is not in the type's allowed set must fail loudly
    (a unit test asserts this stays green).
    """
    for preset in DEFAULT_TENANT_ROLE_PRESETS.values():
        for resource_type, actions in preset.permissions.items():
            manifest_entry = ResourceTypeManifest.get(resource_type)
            if manifest_entry is None:
                raise ValueError(
                    f"Default tenant role preset '{preset.key}' references "
                    f"unknown resource type '{resource_type}' — update the "
                    "preset to match the resource-type manifest."
                )
            unknown = set(actions) - set(manifest_entry["actions"])
            if unknown:
                raise ValueError(
                    f"Default tenant role preset '{preset.key}' uses actions "
                    f"{sorted(unknown)} that the manifest does not allow for "
                    f"'{resource_type}'."
                )


# ── Seeding (idempotent; caller owns the transaction/commit) ─────────────────


async def seed_default_tenant_roles(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    root_user_id: uuid.UUID | None = None,
) -> dict[str, Role]:
    """Idempotently create the four default tenant-scoped roles.

    Creates any missing ``Role`` row (``tenant_id`` scoped, ``is_system``,
    per-tenant unique name) plus its policy statements/actions/resources,
    following the storage layout of the permission engine.  When
    *root_user_id* is given, that user is also assigned the tenant's
    system-admin role (``UserRole``) when missing.

    Safe to call repeatedly (creation paths + startup sweep); commits are
    left to the caller so the seeding joins the caller's transaction.
    """
    validate_presets_against_manifest()
    roles: dict[str, Role] = {}
    for preset in DEFAULT_TENANT_ROLE_PRESETS.values():
        roles[preset.key] = await _ensure_preset_role(db, tenant_id, preset)
    if root_user_id is not None:
        await _ensure_user_role(db, root_user_id, roles[TENANT_SYSTEM_ADMIN_KEY])
    return roles


async def assign_tenant_system_admin_role(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """Assign the tenant's system-admin role to *user_id* (idempotent).

    Returns True when a new ``UserRole`` assignment was created.  Seeds
    the default roles first if the tenant has none yet.
    """
    role = (
        await db.execute(
            select(Role).where(
                Role.tenant_id == tenant_id,
                Role.name == TENANT_SYSTEM_ADMIN_ROLE_NAME,
            )
        )
    ).scalar_one_or_none()
    if role is None:
        roles = await seed_default_tenant_roles(db, tenant_id)
        role = roles[TENANT_SYSTEM_ADMIN_KEY]
    return await _ensure_user_role(db, user_id, role)


async def sweep_missing_tenant_default_roles(db: AsyncSession) -> dict[str, int]:
    """Startup sweep: backfill default roles + root assignments platform-wide.

    For every ACTIVE tenant: seed any missing default role, and assign the
    tenant's system-admin role to every active root (owner) membership
    holder that lacks it.  Idempotent and cheap — the scan is a constant
    number of indexed queries; writes happen only for tenants that are
    actually missing something.  This retro-fixes tenants created before
    default seeding existed.
    """
    validate_presets_against_manifest()
    summary: dict[str, int] = {
        "tenants_scanned": 0,
        "tenants_seeded": 0,
        "roles_created": 0,
        "roots_assigned": 0,
    }
    tenants = (
        (await db.execute(select(Tenant).where(Tenant.status == TenantStatus.active)))
        .scalars()
        .all()
    )
    summary["tenants_scanned"] = len(tenants)
    if not tenants:
        return summary

    tenant_ids = [tenant.id for tenant in tenants]
    default_names = {preset.role_name for preset in DEFAULT_TENANT_ROLE_PRESETS.values()}

    # One indexed query: all default-named roles across active tenants.
    roles_by_tenant: dict[uuid.UUID, dict[str, Role]] = {}
    for role in (
        (
            await db.execute(
                select(Role).where(
                    Role.tenant_id.in_(tenant_ids),
                    Role.name.in_(default_names),
                )
            )
        )
        .scalars()
        .all()
    ):
        roles_by_tenant.setdefault(role.tenant_id, {})[role.name] = role

    # One indexed query: active root memberships across those tenants.
    roots_by_tenant: dict[uuid.UUID, list[uuid.UUID]] = {}
    for membership in (
        (
            await db.execute(
                select(TenantUserMembership).where(
                    TenantUserMembership.tenant_id.in_(tenant_ids),
                    TenantUserMembership.is_root.is_(True),
                    TenantUserMembership.status == TenantUserMembershipStatus.active,
                )
            )
        )
        .scalars()
        .all()
    ):
        roots_by_tenant.setdefault(membership.tenant_id, []).append(membership.user_id)

    for tenant in tenants:
        by_name = roles_by_tenant.get(tenant.id, {})
        missing = [
            preset
            for preset in DEFAULT_TENANT_ROLE_PRESETS.values()
            if preset.role_name not in by_name
        ]
        for preset in missing:
            by_name[preset.role_name] = await _ensure_preset_role(db, tenant.id, preset)
        if missing:
            summary["roles_created"] += len(missing)
            summary["tenants_seeded"] += 1

        admin_role = by_name.get(TENANT_SYSTEM_ADMIN_ROLE_NAME)
        if admin_role is None:  # defensive — the loop above just created it
            continue
        for user_id in roots_by_tenant.get(tenant.id, []):
            if await _ensure_user_role(db, user_id, admin_role):
                summary["roots_assigned"] += 1

    if summary["roles_created"] or summary["roots_assigned"]:
        logger.info("Default tenant roles sweep applied: %s", summary)
    return summary


# ── Internals ────────────────────────────────────────────────────────────────


async def _ensure_preset_role(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    preset: DefaultTenantRolePreset,
) -> Role:
    """Create the preset's role + policy set when missing (idempotent)."""
    role = (
        await db.execute(
            select(Role).where(Role.tenant_id == tenant_id, Role.name == preset.role_name)
        )
    ).scalar_one_or_none()
    if role is None:
        role = Role(
            tenant_id=tenant_id,
            name=preset.role_name,
            description=preset.description,
            is_system=True,
            is_active=True,
        )
        db.add(role)
        await db.flush()
        logger.info(
            "Created default tenant role '%s' for tenant=%s", preset.role_name, tenant_id
        )

    # Policy storage mirrors BootstrapService: one allow statement per
    # resource type with one action row per action and a wildcard
    # resource.  tenant_id is stamped explicitly: seeding may run on an
    # unscoped session, and the scoping choke point filters policy rows
    # by tenant_id inside tenant-bound request sessions.
    for resource_type, actions in sorted(preset.permissions.items()):
        existing = (
            await db.execute(
                select(PolicyStatement.id).where(
                    PolicyStatement.role_id == role.id,
                    PolicyStatement.module == resource_type,
                    PolicyStatement.effect == PolicyEffect.allow,
                )
            )
        ).first()
        if existing is not None:
            continue
        statement = PolicyStatement(
            tenant_id=tenant_id,
            role_id=role.id,
            effect=PolicyEffect.allow,
            module=resource_type,
        )
        db.add(statement)
        await db.flush()
        for action in sorted(actions):
            db.add(
                PolicyAction(
                    tenant_id=tenant_id,
                    policy_statement_id=statement.id,
                    action=action,
                )
            )
        db.add(
            PolicyResource(
                tenant_id=tenant_id,
                policy_statement_id=statement.id,
                resource_type=resource_type,
                resource_id="*",
            )
        )
    await db.flush()
    return role


async def _ensure_user_role(db: AsyncSession, user_id: uuid.UUID, role: Role) -> bool:
    """Assign *role* to *user_id* when missing. True when newly assigned."""
    existing = (
        await db.execute(
            select(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id == role.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    db.add(UserRole(user_id=user_id, role_id=role.id))
    await db.flush()
    logger.info(
        "Assigned role '%s' (tenant=%s) to user=%s",
        role.name, role.tenant_id, user_id,
    )
    return True
