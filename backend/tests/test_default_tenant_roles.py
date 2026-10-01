"""Default tenant role presets, seeding and root blanket-grant tests.

Covers the delivered-behavior fix for self-serve tenants whose ROOT user
could not reach business features:

- presets stay consistent with the resource-type manifest (system admin
  spans every tenant-relevant type with FULL actions, never platform::*);
- ``seed_default_tenant_roles`` is idempotent and stores permissions the
  same way the permission engine reads them (PolicyStatement /
  PolicyAction / PolicyResource, tenant-stamped);
- the seeding is wired into tenant creation (``TenantService.create``),
  provisioning (root assignment) and system-tenant adoption;
- the startup sweep backfills existing tenants + root assignments;
- ``_membership_grants`` grants the ROOT membership every module except
  ``platform::*`` while non-root roles keep the legacy dict behaviour.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.api.deps import _membership_grants  # noqa: E402
from app.core.resource_types import (  # noqa: E402
    MODULE_GROUPS,
    ResourceTypeManifest,
)
from app.db.models.identity import Role  # noqa: E402
from app.db.models.platform_user import PlatformUser  # noqa: E402
from app.db.models.policy_action import PolicyAction  # noqa: E402
from app.db.models.policy_resource import PolicyResource  # noqa: E402
from app.db.models.policy_statement import PolicyEffect, PolicyStatement  # noqa: E402
from app.db.models.tenant import Tenant, TenantStatus  # noqa: E402
from app.db.models.tenant_membership import (  # noqa: E402
    TenantUserMembership,
    TenantUserMembershipStatus,
)
from app.db.models.user_role import UserRole  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.services.permissions.permission_engine import PermissionEngine  # noqa: E402
from app.services.tenancy.default_tenant_roles import (  # noqa: E402
    AGENT_MANAGER_PRESET,
    AGENT_EXECUTOR_PRESET,
    AGENT_VIEWER_PRESET,
    DEFAULT_TENANT_ROLE_PRESETS,
    TENANT_SYSTEM_ADMIN_PRESET,
    assign_tenant_system_admin_role,
    seed_default_tenant_roles,
    sweep_missing_tenant_default_roles,
    validate_presets_against_manifest,
)
from app.services.tenancy.tenant_adoption_service import TenantAdoptionService  # noqa: E402
from app.services.tenancy.tenant_provisioning_service import (  # noqa: E402
    TenantProvisioningService,
)
from app.services.tenancy.tenant_service import TenantService  # noqa: E402

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory engine per test (no cross-test pollution)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(engine):
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session


async def _mk_user(db: AsyncSession, tag: str) -> PlatformUser:
    suffix = uuid.uuid4().hex[:8]
    user = PlatformUser(
        sub=f"{tag}-{suffix}",
        email=f"{tag}-{suffix}@t.dev",
        display_name=tag,
    )
    db.add(user)
    await db.flush()
    return user


async def _mk_tenant(db: AsyncSession, slug: str) -> Tenant:
    tenant = Tenant(name=f"Org {slug}", slug=slug, status=TenantStatus.active)
    db.add(tenant)
    await db.flush()
    return tenant


async def _mk_membership(
    db: AsyncSession,
    tenant: Tenant,
    user: PlatformUser,
    *,
    tenant_role: str,
    is_root: bool = False,
) -> TenantUserMembership:
    from app.db.models.tenant import TenantRole

    membership = TenantUserMembership(
        tenant_id=tenant.id,
        user_id=user.id,
        tenant_role=tenant_role,
        status=TenantUserMembershipStatus.active,
        is_root=is_root,
    )
    db.add(membership)
    await db.flush()
    return membership


# ── Preset ↔ manifest consistency ────────────────────────────────────────────


class TestPresetManifestConsistency:
    def test_validate_passes(self):
        validate_presets_against_manifest()

    @pytest.mark.parametrize(
        "preset",
        list(DEFAULT_TENANT_ROLE_PRESETS.values()),
        ids=lambda p: p.key,
    )
    def test_preset_types_and_actions_exist_in_manifest(self, preset):
        for resource_type, actions in preset.permissions.items():
            assert resource_type in ResourceTypeManifest, resource_type
            unknown = set(actions) - set(ResourceTypeManifest[resource_type]["actions"])
            assert not unknown, f"{preset.key}/{resource_type}: unknown {unknown}"

    @pytest.mark.parametrize(
        "preset",
        list(DEFAULT_TENANT_ROLE_PRESETS.values()),
        ids=lambda p: p.key,
    )
    def test_no_platform_types_in_any_preset(self, preset):
        assert not any(rt.startswith("platform::") for rt in preset.permissions)

    def test_system_admin_covers_every_tenant_relevant_type_with_full_actions(self):
        expected = {
            rt
            for group in ("agent", "integration", "system", "tenant")
            for rt in MODULE_GROUPS[group]
        }
        # The bare "agent" type (agent-type CRUD / session gates in
        # agents.py) is granted explicitly on top of the module groups.
        expected.add("agent")
        assert set(TENANT_SYSTEM_ADMIN_PRESET.permissions) == expected
        for resource_type, actions in TENANT_SYSTEM_ADMIN_PRESET.permissions.items():
            assert actions == frozenset(ResourceTypeManifest[resource_type]["actions"])

    def test_agent_manager_covers_full_agent_domain(self):
        agent_types = set(MODULE_GROUPS["agent"])
        covered = {
            rt
            for rt, actions in AGENT_MANAGER_PRESET.permissions.items()
            if rt.startswith("agent")
        }
        assert agent_types <= covered
        # Reads needed to configure agents.
        assert AGENT_MANAGER_PRESET.permissions["integration::mcp_hub"] >= {"read"}
        assert AGENT_MANAGER_PRESET.permissions["system::permissions"] >= {"read"}

    def test_agent_executor_grants_run_actions(self):
        perms = AGENT_EXECUTOR_PRESET.permissions
        assert "execute" in perms["agent"]  # session launch/terminate gates
        assert "execute" in perms["agent::management"]
        assert "execute" in perms["agent::runtime_control"]
        assert perms["agent::human_intervention"] == frozenset({"view", "respond"})
        assert perms["agent::outputs"] == frozenset({"read"})

    def test_agent_viewer_is_read_only(self):
        for resource_type, actions in AGENT_VIEWER_PRESET.permissions.items():
            allowed = set(ResourceTypeManifest[resource_type]["actions"])
            assert actions <= allowed
            assert actions <= {"read", "view"}, (resource_type, actions)


# ── Seeding service ──────────────────────────────────────────────────────────


class TestSeedDefaultTenantRoles:
    async def test_seeds_four_tenant_scoped_system_roles(self, db):
        await seed_default_tenant_roles(db, TENANT_A)
        roles = (
            (await db.execute(select(Role).where(Role.tenant_id == TENANT_A)))
            .scalars()
            .all()
        )
        assert {r.name for r in roles} == {
            TENANT_SYSTEM_ADMIN_PRESET.role_name,
            AGENT_MANAGER_PRESET.role_name,
            AGENT_EXECUTOR_PRESET.role_name,
            AGENT_VIEWER_PRESET.role_name,
        }
        assert all(r.is_system is True for r in roles)
        assert all(r.tenant_id == TENANT_A for r in roles)

    async def test_policy_storage_matches_engine_layout(self, db):
        """Statements/actions/resources mirror BootstrapService, tenant-stamped."""
        await seed_default_tenant_roles(db, TENANT_A)
        admin_role = (
            await db.execute(
                select(Role).where(
                    Role.tenant_id == TENANT_A,
                    Role.name == TENANT_SYSTEM_ADMIN_PRESET.role_name,
                )
            )
        ).scalar_one()

        for resource_type, actions in TENANT_SYSTEM_ADMIN_PRESET.permissions.items():
            stmt = (
                await db.execute(
                    select(PolicyStatement).where(
                        PolicyStatement.role_id == admin_role.id,
                        PolicyStatement.module == resource_type,
                        PolicyStatement.effect == PolicyEffect.allow,
                    )
                )
            ).scalar_one()
            assert stmt.tenant_id == TENANT_A
            stmt_actions = {
                a.action
                for a in (
                    await db.execute(
                        select(PolicyAction).where(
                            PolicyAction.policy_statement_id == stmt.id
                        )
                    )
                )
                .scalars()
                .all()
            }
            assert stmt_actions == set(actions)
            resource = (
                await db.execute(
                    select(PolicyResource).where(
                        PolicyResource.policy_statement_id == stmt.id
                    )
                )
            ).scalar_one()
            assert resource.resource_type == resource_type
            assert resource.resource_id == "*"
            assert resource.tenant_id == TENANT_A

    async def test_idempotent_no_duplicates(self, db):
        await seed_default_tenant_roles(db, TENANT_A)
        await seed_default_tenant_roles(db, TENANT_A)
        roles = (
            (await db.execute(select(Role).where(Role.tenant_id == TENANT_A)))
            .scalars()
            .all()
        )
        assert len(roles) == 4
        stmts = (
            (
                await db.execute(
                    select(PolicyStatement).where(
                        PolicyStatement.role_id.in_([r.id for r in roles])
                    )
                )
            )
            .scalars()
            .all()
        )
        expected = sum(len(p.permissions) for p in DEFAULT_TENANT_ROLE_PRESETS.values())
        assert len(stmts) == expected

    async def test_same_named_roles_allowed_across_tenants(self, db):
        """uq_roles_global_name must stay partial: per-tenant duplicates are legal."""
        await seed_default_tenant_roles(db, TENANT_A)
        await seed_default_tenant_roles(db, TENANT_B)
        names_a = {
            r.name
            for r in (
                (await db.execute(select(Role).where(Role.tenant_id == TENANT_A)))
                .scalars()
                .all()
            )
        }
        names_b = {
            r.name
            for r in (
                (await db.execute(select(Role).where(Role.tenant_id == TENANT_B)))
                .scalars()
                .all()
            )
        }
        assert names_a == names_b
        assert len(names_a) == 4

    async def test_root_user_receives_system_admin_role_once(self, db):
        user = await _mk_user(db, "owner")
        roles = await seed_default_tenant_roles(db, TENANT_A, root_user_id=user.id)
        await seed_default_tenant_roles(db, TENANT_A, root_user_id=user.id)
        assignments = (
            (
                await db.execute(
                    select(UserRole).where(
                        UserRole.user_id == user.id,
                        UserRole.role_id == roles["tenant_system_admin"].id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(assignments) == 1

    async def test_seeded_role_authorizes_via_permission_engine(self, db):
        """The engine collects the tenant role and its tenant-stamped policies."""
        user = await _mk_user(db, "member")
        roles = await seed_default_tenant_roles(db, TENANT_A, root_user_id=user.id)

        engine = PermissionEngine()
        result = await engine.authorize(
            db,
            user.id,
            "agent::management",
            "create",
            "*",
            {},
            tenant_id=TENANT_A,
        )
        assert result.allowed, result.reason
        # The viewer role alone would not allow a create.
        result = await engine.authorize(
            db,
            user.id,
            "platform::tenants",
            "read",
            "*",
            {},
            tenant_id=TENANT_A,
        )
        assert not result.allowed  # platform stays out of tenant presets

        # The system-admin role covers every tenant-relevant module.
        for module, action in (
            ("agent", "create"),
            ("integration::mcp_hub", "manage"),
            ("system::system_config", "manage"),
            ("tenant::members", "manage"),
        ):
            assert (
                await engine.authorize(db, user.id, module, action, "*", {}, tenant_id=TENANT_A)
            ).allowed, module

        assert roles  # returned mapping usable by callers

    async def test_unknown_preset_action_fails_loudly(self, db, monkeypatch):
        import app.services.tenancy.default_tenant_roles as dtr_module

        broken_preset = AGENT_MANAGER_PRESET.__class__(
            key=AGENT_MANAGER_PRESET.key,
            role_name=AGENT_MANAGER_PRESET.role_name,
            description=AGENT_MANAGER_PRESET.description,
            permissions={**AGENT_MANAGER_PRESET.permissions, "agent::roles": frozenset({"fly"})},
        )
        monkeypatch.setattr(
            dtr_module,
            "DEFAULT_TENANT_ROLE_PRESETS",
            {broken_preset.key: broken_preset},
        )
        with pytest.raises(ValueError, match="fly"):
            await seed_default_tenant_roles(db, TENANT_A)
        # Nothing was written before the validation fired.
        roles = (
            (await db.execute(select(Role).where(Role.tenant_id == TENANT_A)))
            .scalars()
            .all()
        )
        assert roles == []


# ── Creation-path wiring ─────────────────────────────────────────────────────


class TestCreationPathWiring:
    async def test_tenant_service_create_seeds_default_roles(self, db):
        tenant = await TenantService().create(db, name="Wired Co", slug="wired-co")
        roles = (
            (await db.execute(select(Role).where(Role.tenant_id == tenant.id)))
            .scalars()
            .all()
        )
        assert {r.name for r in roles} == {
            p.role_name for p in DEFAULT_TENANT_ROLE_PRESETS.values()
        }

    async def test_provisioning_assigns_system_admin_to_root(self, db):
        admin = await _mk_user(db, "root-admin")
        tenant = await TenantProvisioningService().provision_tenant(
            db,
            name="Provisioned",
            slug=f"provisioned-{uuid.uuid4().hex[:6]}",
            admin_user_id=admin.id,
        )
        membership = (
            await db.execute(
                select(TenantUserMembership).where(
                    TenantUserMembership.tenant_id == tenant.id,
                    TenantUserMembership.is_root.is_(True),
                )
            )
        ).scalar_one()
        assert membership.user_id == admin.id

        admin_role = (
            await db.execute(
                select(Role).where(
                    Role.tenant_id == tenant.id,
                    Role.name == TENANT_SYSTEM_ADMIN_PRESET.role_name,
                )
            )
        ).scalar_one()
        assignment = (
            await db.execute(
                select(UserRole).where(
                    UserRole.user_id == admin.id,
                    UserRole.role_id == admin_role.id,
                )
            )
        ).scalar_one_or_none()
        assert assignment is not None

    async def test_assign_helper_idempotent_and_seeding(self, db):
        user = await _mk_user(db, "owner2")
        tenant = await _mk_tenant(db, f"assign-{uuid.uuid4().hex[:6]}")
        assert await assign_tenant_system_admin_role(db, tenant.id, user.id) is True
        assert await assign_tenant_system_admin_role(db, tenant.id, user.id) is False
        roles = (
            (await db.execute(select(Role).where(Role.tenant_id == tenant.id)))
            .scalars()
            .all()
        )
        assert len(roles) == 4  # seeded lazily by the helper

    async def test_adoption_seeds_roles_without_forcing_assignment(self, db):
        """System-tenant adoption seeds the 4 roles; nobody is force-assigned."""
        suffix = uuid.uuid4().hex[:6]
        db.add(
            PlatformUser(
                sub=f"adopt-{suffix}",
                email=f"adopt-{suffix}@t.dev",
                display_name="Adopted",
            )
        )
        await db.flush()
        service = TenantAdoptionService()
        summary = await service.adopt_system_tenant(db)
        system_id = uuid.UUID(summary["tenant_id"])

        roles = (
            (await db.execute(select(Role).where(Role.tenant_id == system_id)))
            .scalars()
            .all()
        )
        assert {r.name for r in roles} == {
            p.role_name for p in DEFAULT_TENANT_ROLE_PRESETS.values()
        }
        # NO default-role assignment was forced onto existing users.
        assignments = (
            (
                await db.execute(
                    select(UserRole).where(UserRole.role_id.in_([r.id for r in roles]))
                )
            )
            .scalars()
            .all()
        )
        assert assignments == []


# ── Startup sweep ────────────────────────────────────────────────────────────


class TestStartupSweep:
    async def test_sweep_backfills_missing_roles_and_root_assignment(self, db):
        """Retro-fix for tenants created before default seeding existed."""
        owner = await _mk_user(db, "legacy-owner")
        tenant = await _mk_tenant(db, f"legacy-{uuid.uuid4().hex[:6]}")
        await _mk_membership(db, tenant, owner, tenant_role="tenant_admin", is_root=True)

        summary = await sweep_missing_tenant_default_roles(db)
        assert summary["tenants_scanned"] >= 1
        assert summary["tenants_seeded"] >= 1
        assert summary["roles_created"] >= 4
        assert summary["roots_assigned"] >= 1

        admin_role = (
            await db.execute(
                select(Role).where(
                    Role.tenant_id == tenant.id,
                    Role.name == TENANT_SYSTEM_ADMIN_PRESET.role_name,
                )
            )
        ).scalar_one()
        assignment = (
            await db.execute(
                select(UserRole).where(
                    UserRole.user_id == owner.id,
                    UserRole.role_id == admin_role.id,
                )
            )
        ).scalar_one_or_none()
        assert assignment is not None

    async def test_sweep_is_idempotent(self, db):
        owner = await _mk_user(db, "sweep-owner")
        tenant = await _mk_tenant(db, f"sweep-{uuid.uuid4().hex[:6]}")
        await _mk_membership(db, tenant, owner, tenant_role="tenant_admin", is_root=True)

        first = await sweep_missing_tenant_default_roles(db)
        roles_after_first = len(
            (
                await db.execute(select(Role).where(Role.tenant_id == tenant.id))
            )
            .scalars()
            .all()
        )
        second = await sweep_missing_tenant_default_roles(db)
        assert second["roles_created"] == 0
        assert second["roots_assigned"] == 0

        roles_after_second = len(
            (
                await db.execute(select(Role).where(Role.tenant_id == tenant.id))
            )
            .scalars()
            .all()
        )
        assert roles_after_first == roles_after_second == 4
        assert first["roles_created"] >= 4

    async def test_sweep_tolerates_reassigned_root_without_roles(self, db):
        """A tenant whose root ALREADY holds the role (e.g. via provisioning)
        is not double-assigned, and a root membership is still honoured."""
        owner = await _mk_user(db, "already-root")
        tenant = await _mk_tenant(db, f"already-{uuid.uuid4().hex[:6]}")
        await _mk_membership(db, tenant, owner, tenant_role="tenant_admin", is_root=True)
        await assign_tenant_system_admin_role(db, tenant.id, owner.id)

        summary = await sweep_missing_tenant_default_roles(db)
        assert summary["roots_assigned"] == 0

        assignments = (
            (
                await db.execute(
                    select(UserRole).where(
                        UserRole.user_id == owner.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(assignments) == 1


# ── Root blanket grant in _membership_grants ─────────────────────────────────


class TestRootBlanketGrant:
    async def test_root_granted_all_modules_except_platform(self, db):
        root = await _mk_user(db, "blanket-root")
        tenant = await _mk_tenant(db, f"blanket-{uuid.uuid4().hex[:6]}")
        await _mk_membership(db, tenant, root, tenant_role="tenant_admin", is_root=True)

        # Business modules missing from the legacy dict are granted.
        for module, action in (
            ("agent::management", "create"),
            ("agent", "execute"),
            ("integration::mcp_hub", "read"),
            ("system::permissions", "manage"),
            ("tenant::settings", "manage"),
            ("agent::human_intervention", "respond"),
        ):
            assert await _membership_grants(
                db, root.id, tenant.id, module, action
            ), f"root must be granted {module}:{action}"

    async def test_root_denied_platform_group(self, db):
        root = await _mk_user(db, "platform-root")
        tenant = await _mk_tenant(db, f"plat-{uuid.uuid4().hex[:6]}")
        await _mk_membership(db, tenant, root, tenant_role="tenant_admin", is_root=True)

        for module, action in (
            ("platform::tenants", "read"),
            ("platform::settings", "manage"),
            ("platform::audit", "read"),
        ):
            assert not await _membership_grants(
                db, root.id, tenant.id, module, action
            ), f"platform::{module} must stay platform-admin-only"

    async def test_non_root_roles_keep_legacy_dict_behaviour(self, db):
        tenant = await _mk_tenant(db, f"nonroot-{uuid.uuid4().hex[:6]}")
        admin = await _mk_user(db, "tenant-admin")
        member = await _mk_user(db, "tenant-member")
        await _mk_membership(db, tenant, admin, tenant_role="tenant_admin")
        await _mk_membership(db, tenant, member, tenant_role="member")

        # Delegated admin: legacy tenant self-service grants hold …
        assert await _membership_grants(db, admin.id, tenant.id, "tenant::members", "manage")
        assert await _membership_grants(db, admin.id, tenant.id, "tenant::settings", "manage")
        # … but business modules are NOT granted via the dict (roles carry them).
        assert not await _membership_grants(db, admin.id, tenant.id, "agent::management", "create")

        # Plain member: settings read only.
        assert await _membership_grants(db, member.id, tenant.id, "tenant::settings", "read")
        assert not await _membership_grants(db, member.id, tenant.id, "tenant::members", "manage")
        assert not await _membership_grants(db, member.id, tenant.id, "system::config", "manage")

    async def test_no_membership_denied_everywhere(self, db):
        outsider = await _mk_user(db, "outsider")
        tenant = await _mk_tenant(db, f"outside-{uuid.uuid4().hex[:6]}")
        assert not await _membership_grants(
            db, outsider.id, tenant.id, "tenant::settings", "read"
        )
        assert not await _membership_grants(
            db, outsider.id, tenant.id, "agent::management", "read"
        )

    async def test_none_tenant_denied(self, db):
        user = await _mk_user(db, "notenant")
        assert not await _membership_grants(db, user.id, None, "tenant::settings", "read")
