"""Phase 11 containment — platform::* permission semantics.

SUPERSEDES the FIX-20260930-235927 membership-gate semantics.  Desired
semantics (permission containment, Phase 11):

- NO global (tenant-less) roles exist: every business role belongs to
  exactly one tenant (legacy globals were re-homed into the ROOT tenant
  by migration ``b8e4f2a6c9d1``).
- ``PermissionEngine._get_effective_role_ids`` collects roles ONLY from
  the session's resolved tenant — the global-role collection is removed.
- ``platform::*`` checks simply evaluate the session tenant's roles:
  the ROOT tenant's role space contains the ``platform::`` grants (the
  seeded root ``Platform Admin`` role); customer tenants structurally
  cannot hold them.  The former platform-membership gate
  (``_system_tenant_platform_admin``) is REMOVED.
- The super-admin bypass is unchanged.

CHANGED ASSERTIONS vs FIX-235927 (each called out inline):

- T1: denial reason changed — a legacy wildcard admin in a customer
  tenant session is denied by ROLE CONTAINMENT (their role lives in the
  root tenant, not the session tenant), not by the membership gate.
- T2: RETIRED — "global roles remain effective in tenant contexts" no
  longer holds by design; the legacy wildcard is effective in the ROOT
  workspace only.
- T3: platform admin access now requires the ROOT ``Platform Admin``
  ROLE (``platform::*`` policy); the ``platform_admin`` membership alone
  grants nothing (memberships never granted ``platform::*`` — 10.21).
- T4: tenancy-OFF pin retained under root-world semantics (the legacy
  wildcard is evaluated in the root tenant).
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.models.identity import Role, RoleType  # noqa: E402
from app.db.models.platform_user import PlatformUser  # noqa: E402
from app.db.models.policy_action import PolicyAction  # noqa: E402
from app.db.models.policy_resource import PolicyResource  # noqa: E402
from app.db.models.policy_statement import PolicyEffect, PolicyStatement  # noqa: E402
from app.db.models.tenant import Tenant, TenantRole  # noqa: E402
from app.db.models.tenant_membership import TenantUserMembership  # noqa: E402
from app.db.models.user_role import UserRole  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.services.tenancy.root_tenant import PLATFORM_ADMIN_ROLE_NAME  # noqa: E402

TAG = uuid.uuid4().hex[:8]

TENANT_ROOT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
TENANT_X_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000002")

SUB_LEGACY = f"legacy-admin-{TAG}"       # root-scoped system_admin wildcard, member of X
SUB_PLAT_ADMIN = f"plat-admin-{TAG}"     # platform_admin membership + Platform Admin role in ROOT

PLATFORM_MODULE = "platform::tenants"


@pytest.fixture(autouse=True)
def _fresh_settings_singleton():
    """Isolate the process-wide PlatformSettingsService cache per test."""
    import app.services.tenancy.platform_settings_service as settings_module

    settings_module._service = None
    yield
    settings_module._service = None


async def _set_tenancy(db: AsyncSession, enabled: bool) -> None:
    from app.services.tenancy.platform_settings_service import (
        get_platform_settings_service,
    )

    await get_platform_settings_service().set_setting(
        db, "multi_tenancy_enabled", enabled
    )
    await db.commit()


async def _wildcard_role(db: AsyncSession, tenant_id, name: str, module: str = "*::*") -> Role:
    """A system wildcard role in *tenant_id*'s role space."""
    role = Role(
        name=name,
        role_type=RoleType.user,
        is_system=True,
        tenant_id=tenant_id,
    )
    db.add(role)
    await db.flush()
    stmt = PolicyStatement(
        role_id=role.id,
        tenant_id=tenant_id,
        effect=PolicyEffect.allow,
        module=module,
    )
    db.add(stmt)
    await db.flush()
    db.add(PolicyAction(policy_statement_id=stmt.id, action="*"))
    db.add(
        PolicyResource(
            policy_statement_id=stmt.id,
            resource_type="*",
            resource_id="*",
        )
    )
    return role


@pytest_asyncio.fixture
async def engine():
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
    """Unscoped session seeded with the containment world:

    - ROOT tenant (is_system_tenant) + regular tenant X
    - LEGACY admin: ROOT-scoped ``system_admin`` ``*::*`` wildcard role
      (the migrated pre-tenancy global), active (non-root) membership in
      tenant X only
    - PLATFORM admin: active ``platform_admin`` membership in the ROOT
      tenant PLUS the seeded root ``Platform Admin`` role (the
      ``platform::*`` policy holder)
    """
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        root = Tenant(name="Root", slug=f"root-{TAG}", is_system_tenant=True)
        root.id = TENANT_ROOT_ID
        tenant_x = Tenant(name="Tenant X", slug=f"tenant-x-{TAG}")
        tenant_x.id = TENANT_X_ID
        db.add_all([root, tenant_x])
        await db.flush()

        legacy = PlatformUser(
            sub=SUB_LEGACY,
            email=f"legacy-{TAG}@example.test",
            display_name="Legacy Admin",
        )
        plat_admin = PlatformUser(
            sub=SUB_PLAT_ADMIN,
            email=f"plat-admin-{TAG}@example.test",
            display_name="Platform Admin",
        )
        db.add_all([legacy, plat_admin])
        await db.flush()

        # CHANGED (Phase 11): the legacy global wildcard was RE-HOMED into
        # the root tenant — tenant-less roles no longer exist.
        role = await _wildcard_role(db, TENANT_ROOT_ID, "system_admin")
        db.add(UserRole(user_id=legacy.id, role_id=role.id))

        plat_role = await _wildcard_role(
            db, TENANT_ROOT_ID, PLATFORM_ADMIN_ROLE_NAME, module="platform::*"
        )
        db.add(UserRole(user_id=plat_admin.id, role_id=plat_role.id))

        db.add_all(
            [
                # legacy admin: regular member of tenant X (their workspace)
                # AND of the root tenant (adopted users hold a root
                # membership; their wildcard role lives in root's space)
                TenantUserMembership(
                    tenant_id=TENANT_X_ID,
                    user_id=legacy.id,
                    tenant_role="member",
                    status="active",
                ),
                TenantUserMembership(
                    tenant_id=TENANT_ROOT_ID,
                    user_id=legacy.id,
                    tenant_role="member",
                    status="active",
                ),
                # platform admin: platform_admin membership in the ROOT tenant
                TenantUserMembership(
                    tenant_id=TENANT_ROOT_ID,
                    user_id=plat_admin.id,
                    tenant_role=TenantRole.platform_admin,
                    status="active",
                ),
            ]
        )
        await db.commit()
        yield db
        await db.rollback()


async def _authorize(db, sub, module, action, *, tenant_id=None, is_super_admin=False):
    from app.api.deps import authorize_identity

    claims = {"sub": sub}
    return await authorize_identity(
        db,
        claims,
        module,
        action,
        is_super_admin=is_super_admin,
        tenant_id=tenant_id,
    )


async def _user_id(db: AsyncSession, sub: str) -> uuid.UUID:
    from sqlalchemy import select

    result = await db.execute(select(PlatformUser).where(PlatformUser.sub == sub))
    return result.scalar_one().id


class TestPlatformContainmentTenancyOn:
    async def test_t1_legacy_wildcard_denied_on_platform_module_in_customer_tenant(self, db):
        """T1 — a legacy wildcard admin (root-scoped ``system_admin``)
        holding ONLY a membership in customer tenant X must NOT pass a
        ``platform::*`` check from an X session.

        CHANGED ASSERTION vs FIX-235927: the denial now comes from ROLE
        CONTAINMENT (the engine collects only tenant-X roles; the
        wildcard lives in the root tenant) — the former
        ``_system_tenant_platform_admin`` membership gate is REMOVED."""
        await _set_tenancy(db, True)
        with pytest.raises(HTTPException) as excinfo:
            await _authorize(db, SUB_LEGACY, PLATFORM_MODULE, "read", tenant_id=TENANT_X_ID)
        assert excinfo.value.status_code == 403, (
            "CONTAINMENT (Phase 11): a customer-tenant session can never "
            "evaluate the root tenant's platform:: grants"
        )

    async def test_t2_legacy_wildcard_effective_in_root_workspace(self, db):
        """T2 — RETIRED + REPLACED: the FIX-235927 pin "global roles
        remain effective in tenant contexts" no longer holds by design.
        The legacy wildcard IS still effective in the ROOT workspace
        (root role space) for non-platform modules."""
        await _set_tenancy(db, True)
        claims = await _authorize(
            db, SUB_LEGACY, "agent::management", "read", tenant_id=TENANT_ROOT_ID
        )
        assert claims["sub"] == SUB_LEGACY

    async def test_t2b_legacy_wildcard_not_effective_in_customer_tenant(self, db):
        """T2b (new) — the same legacy user in a tenant-X session has NO
        effective roles (their wildcard lives in root): denied."""
        await _set_tenancy(db, True)
        with pytest.raises(HTTPException):
            await _authorize(
                db, SUB_LEGACY, "agent::management", "read", tenant_id=TENANT_X_ID
            )

    async def test_t3_platform_admin_role_in_root_allowed(self, db):
        """T3 — CHANGED: platform access comes from the seeded ROOT
        ``Platform Admin`` ROLE (``platform::*`` policy in the root role
        space), evaluated in the root context.  The membership alone
        grants nothing (memberships never granted ``platform::*``)."""
        await _set_tenancy(db, True)
        claims = await _authorize(db, SUB_PLAT_ADMIN, PLATFORM_MODULE, "read")
        assert claims["sub"] == SUB_PLAT_ADMIN

    async def test_t3b_membership_without_role_not_sufficient(self, db):
        """T3b — an ACTIVE platform_admin membership in the ROOT tenant
        WITHOUT any root role carrying ``platform::`` grants does not
        unlock platform::* (memberships never granted ``platform::*``)."""
        await _set_tenancy(db, True)
        roleless = PlatformUser(
            sub=f"roleless-{TAG}",
            email=f"roleless-{TAG}@example.test",
            display_name="Roleless Admin",
        )
        db.add(roleless)
        await db.flush()
        db.add(
            TenantUserMembership(
                tenant_id=TENANT_ROOT_ID,
                user_id=roleless.id,
                tenant_role=TenantRole.platform_admin,
                status="active",
            )
        )
        await db.commit()
        with pytest.raises(HTTPException) as excinfo:
            await _authorize(db, f"roleless-{TAG}", PLATFORM_MODULE, "read", tenant_id=TENANT_ROOT_ID)
        assert excinfo.value.status_code == 403

    async def test_t3c_customer_tenant_platform_wildcard_cannot_cross(self, db):
        """T3c (new, containment) — a customer tenant CANNOT carry
        ``platform::`` grants: a tenant-X role with a ``platform::*``
        wildcard policy is never collected outside X, and inside X it
        still cannot satisfy a platform check evaluated for the root
        console (the session tenant is X, whose role space is not the
        root's)."""
        await _set_tenancy(db, True)
        rogue = await _wildcard_role(db, TENANT_X_ID, f"rogue-{TAG}", module="platform::*")
        x_admin = PlatformUser(
            sub=f"rogue-admin-{TAG}",
            email=f"rogue-{TAG}@example.test",
            display_name="Rogue Admin",
        )
        db.add(x_admin)
        await db.flush()
        db.add(UserRole(user_id=x_admin.id, role_id=rogue.id))
        db.add(
            TenantUserMembership(
                tenant_id=TENANT_ROOT_ID,
                user_id=x_admin.id,
                tenant_role="member",
                status="active",
            )
        )
        await db.commit()
        with pytest.raises(HTTPException):
            await _authorize(db, f"rogue-admin-{TAG}", PLATFORM_MODULE, "read")


class TestPlatformContainmentRegressionPins:
    async def test_t4_tenancy_off_root_world_wildcard_allowed(self, db):
        """T4 (regression pin) — multi-tenancy OFF: the deployment is the
        ROOT tenant's workspace; the legacy wildcard (root role space)
        keeps granting everything.  CHANGED vs FIX-235927: evaluated via
        the root tenant id (the OFF default context), not a None tenant."""
        await _set_tenancy(db, False)
        claims = await _authorize(
            db, SUB_LEGACY, PLATFORM_MODULE, "read", tenant_id=TENANT_ROOT_ID
        )
        assert claims["sub"] == SUB_LEGACY

    async def test_t5_super_admin_allowed(self, db):
        """T5 (regression pin) — the super-admin bypass is untouched."""
        await _set_tenancy(db, True)
        claims = await _authorize(
            db, "whatever", PLATFORM_MODULE, "read", is_super_admin=True
        )
        assert claims == {"sub": "whatever"}
