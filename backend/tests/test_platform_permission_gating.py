"""FIX-20260930-235927 — platform::* gating when multi-tenancy is ON.

Desired semantics (multi-tenancy ON):

- ``platform::*`` permission checks are satisfied ONLY by
  (a) the super-admin bypass, or
  (b) an ACTIVE ``platform_admin`` membership in the SYSTEM tenant.
- Legacy GLOBAL tenant-less roles (pre-tenancy ``system_admin`` with a
  ``*::*`` wildcard policy) must NEVER satisfy ``platform::*`` — the
  PermissionEngine collects global roles for every module, which is why
  adopted Keycloak admins saw the whole platform console.
- Everything else (agent::*, integration::*, system::*, tenant::*)
  keeps current behavior: global roles remain effective in tenant
  contexts (the legacy user keeps working in their workspace).
- Multi-tenancy OFF: byte-for-byte unchanged (system_admin wildcard
  still grants everything; there is no platform concept).
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

TAG = uuid.uuid4().hex[:8]

TENANT_SYSTEM_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
TENANT_X_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000002")

SUB_LEGACY = f"legacy-admin-{TAG}"       # global system_admin wildcard, member of X
SUB_PLAT_ADMIN = f"plat-admin-{TAG}"     # platform_admin membership in the SYSTEM tenant

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


async def _global_wildcard_role(db: AsyncSession) -> Role:
    """The pre-tenancy global system_admin role: tenant-less, system,
    with the ``*::*`` allow-everything policy."""
    role = Role(
        name="system_admin",
        role_type=RoleType.user,
        is_system=True,
        tenant_id=None,  # GLOBAL — collected in every tenant context
    )
    db.add(role)
    await db.flush()
    stmt = PolicyStatement(
        role_id=role.id,
        effect=PolicyEffect.allow,
        module="*::*",
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
    """Unscoped session seeded with the fix's world:

    - system tenant + regular tenant X
    - LEGACY admin: global system_admin ``*::*`` wildcard role, active
      (non-root) membership in tenant X, NO platform_admin membership
    - PLATFORM admin: active ``platform_admin`` membership in the
      SYSTEM tenant, no RBAC roles at all
    """
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        system = Tenant(name="System", slug=f"system-{TAG}", is_system_tenant=True)
        system.id = TENANT_SYSTEM_ID
        tenant_x = Tenant(name="Tenant X", slug=f"tenant-x-{TAG}")
        tenant_x.id = TENANT_X_ID
        db.add_all([system, tenant_x])
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

        role = await _global_wildcard_role(db)
        db.add(UserRole(user_id=legacy.id, role_id=role.id))
        db.add_all(
            [
                # legacy admin: regular member of tenant X (their workspace)
                TenantUserMembership(
                    tenant_id=TENANT_X_ID,
                    user_id=legacy.id,
                    tenant_role="member",
                    status="active",
                ),
                # platform admin: platform_admin membership in the SYSTEM tenant
                TenantUserMembership(
                    tenant_id=TENANT_SYSTEM_ID,
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


class TestPlatformGatingTenancyOn:
    async def test_t1_legacy_global_wildcard_denied_on_platform_module(self, db):
        """T1 — a pre-tenancy IdP admin holding ONLY the global
        system_admin ``*::*`` wildcard must NOT pass a ``platform::*``
        check when multi-tenancy is ON (today: allowed — the defect)."""
        await _set_tenancy(db, True)
        with pytest.raises(HTTPException) as excinfo:
            await _authorize(db, SUB_LEGACY, PLATFORM_MODULE, "read")
        assert excinfo.value.status_code == 403, (
            "PLATFORM GATING (FIX-20260930-235927 / T1): the legacy global "
            "system_admin wildcard must NEVER satisfy platform::* when "
            "multi-tenancy is ON"
        )

    async def test_t2_legacy_global_wildcard_still_works_in_tenant_module(self, db):
        """T2 — the SAME legacy user keeps full access to tenant-scoped
        modules: the global wildcard remains effective for agent::* in
        their tenant (existing pinned behavior)."""
        await _set_tenancy(db, True)
        claims = await _authorize(
            db, SUB_LEGACY, "agent::management", "read", tenant_id=TENANT_X_ID
        )
        assert claims["sub"] == SUB_LEGACY

    async def test_t3_system_tenant_platform_admin_membership_allowed(self, db):
        """T3 — an ACTIVE platform_admin membership in the SYSTEM tenant
        satisfies platform::* (the only membership-based path)."""
        await _set_tenancy(db, True)
        claims = await _authorize(db, SUB_PLAT_ADMIN, PLATFORM_MODULE, "read")
        assert claims["sub"] == SUB_PLAT_ADMIN

    async def test_t3b_non_platform_admin_membership_not_sufficient(self, db):
        """T3b — a regular (member) membership in the SYSTEM tenant does
        not unlock platform::*."""
        await _set_tenancy(db, True)
        # reuse the legacy user's X membership as a member role elsewhere —
        # here: grant the legacy user a plain membership in the SYSTEM tenant
        db.add(
            TenantUserMembership(
                tenant_id=TENANT_SYSTEM_ID,
                user_id=(await _user_id(db, SUB_LEGACY)),
                tenant_role="member",
                status="active",
            )
        )
        await db.commit()
        with pytest.raises(HTTPException) as excinfo:
            await _authorize(db, SUB_LEGACY, PLATFORM_MODULE, "read")
        assert excinfo.value.status_code == 403


async def _user_id(db: AsyncSession, sub: str) -> uuid.UUID:
    from sqlalchemy import select

    result = await db.execute(select(PlatformUser).where(PlatformUser.sub == sub))
    return result.scalar_one().id


class TestPlatformGatingRegressionPins:
    async def test_t4_tenancy_off_system_admin_wildcard_allowed(self, db):
        """T4 (regression pin) — multi-tenancy OFF: the legacy
        system_admin wildcard keeps granting everything (no platform
        concept; byte-for-byte legacy behaviour)."""
        await _set_tenancy(db, False)
        claims = await _authorize(db, SUB_LEGACY, PLATFORM_MODULE, "read")
        assert claims["sub"] == SUB_LEGACY

    async def test_t5_super_admin_allowed(self, db):
        """T5 (regression pin) — the super-admin bypass is untouched."""
        await _set_tenancy(db, True)
        claims = await _authorize(
            db, "whatever", PLATFORM_MODULE, "read", is_super_admin=True
        )
        assert claims == {"sub": "whatever"}
