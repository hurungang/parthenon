"""Unit tests for the row-level tenant scoping choke point (Phase 3.3 / 9.2).

``app.db.tenant_scoping`` is the SINGLE isolation mechanism: sessions
scoped via ``apply_tenant_scope`` must

- SELECT only the scoped tenant's rows (``with_loader_criteria``)
- UPDATE / DELETE only the scoped tenant's rows (extra where-criterion)
- stamp INSERTs with the session's tenant (before_flush)
- record cross-tenant probe misses (session.get / scalar_one_or_none)
- flush those misses as security-relevant ``cross_tenant_access_denied``
  TenantAuditEvents at request completion
- leave UNSCOPED sessions byte-for-byte untouched (single-tenant mode)

Join/child tables (E-01) inherit scope through their scoped parents.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.resource_types import RT_AGENT_ROLES  # noqa: E402
from app.db.models.identity import Role  # noqa: E402
from app.db.models.policy_action import PolicyAction  # noqa: E402
from app.db.models.policy_resource import PolicyResource  # noqa: E402
from app.db.models.policy_statement import PolicyEffect, PolicyStatement  # noqa: E402
from app.db.models.tenant import Tenant, TenantStatus  # noqa: E402
from app.db.models.tenant_audit_event import (  # noqa: E402
    TenantAuditEvent,
    TenantAuditEventType,
)
from app.db.models.user_role import UserRole  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.db.tenant_scoping import (  # noqa: E402
    apply_tenant_scope,
    flush_scope_miss_audits,
    register_tenant_scope_listener,
    scope_for_session,
)
from app.services.permissions.permission_engine import PermissionEngine  # noqa: E402

TENANT_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory engine per test (no cross-test pollution)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # SQLite renders the Postgres-partial unique index (postgresql_where)
        # as a FULL unique index, which would forbid per-tenant duplicate
        # role names — legal in multi-tenancy.  Drop it for this module;
        # the real per-tenant uniqueness is verified against PostgreSQL in
        # tests/db/test_tenant_schema_migration.py.
        await conn.exec_driver_sql("DROP INDEX IF EXISTS uq_roles_global_name")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_engine(engine):
    """Engine with two tenants' roles committed (fresh ids per module run)."""
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        existing = len((await db.execute(select(Role))).scalars().all())
        if existing == 0:
            db.add_all(
                [
                    Role(name="alpha-role", tenant_id=TENANT_A),
                    Role(name="beta-role", tenant_id=TENANT_B),
                    Role(name="shared-name", tenant_id=TENANT_A),
                    Role(name="shared-name", tenant_id=TENANT_B),
                    Role(name="global-role", tenant_id=None),
                ]
            )
            await db.commit()
    register_tenant_scope_listener()  # idempotent
    return engine


@pytest_asyncio.fixture
async def unscoped_db(seeded_engine):
    SessionLocal = async_sessionmaker(
        bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def scoped_db_a(seeded_engine):
    """Session scoped to tenant A (what get_db does in multi-tenant mode)."""
    SessionLocal = async_sessionmaker(
        bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        apply_tenant_scope(session, TENANT_A)
        yield session
        await session.rollback()


def _role_ids(roles):
    return sorted(r.name for r in roles)


# ── Scope binding ────────────────────────────────────────────────────────────


class TestScopeBinding:
    async def test_scope_recorded_on_session(self, scoped_db_a):
        assert scope_for_session(scoped_db_a) == TENANT_A

    async def test_unscoped_session_has_no_scope(self, unscoped_db):
        assert scope_for_session(unscoped_db) is None


# ── SELECT isolation (CS-13) ─────────────────────────────────────────────────


class TestSelectIsolation:
    async def test_unscoped_session_sees_everything(self, unscoped_db):
        rows = (await unscoped_db.execute(select(Role))).scalars().all()
        assert len(_role_ids(rows)) == 5

    async def test_tenant_less_rows_hidden_in_scoped_sessions(self, scoped_db_a):
        """NULL-tenant rows are excluded by the scope criterion — a scoped
        session never surfaces unattributed (orphan) rows."""
        rows = (await scoped_db_a.execute(select(Role))).scalars().all()
        assert all(r.tenant_id is not None for r in rows)

    async def test_scoped_select_returns_only_own_rows(self, scoped_db_a):
        rows = (await scoped_db_a.execute(select(Role))).scalars().all()
        names = _role_ids(rows)
        assert "beta-role" not in names
        assert "alpha-role" in names
        assert "shared-name" in names
        for row in rows:
            assert row.tenant_id == TENANT_A

    async def test_identical_role_names_no_collision_across_tenants(self, scoped_db_a):
        """CS-21 groundwork: 'shared-name' exists in A and B; a scoped
        list yields exactly the caller's tenant's row."""
        rows = (
            await scoped_db_a.execute(select(Role).where(Role.name == "shared-name"))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].tenant_id == TENANT_A

    async def test_scoped_get_of_foreign_id_is_none_and_audited(
        self, scoped_db_a, seeded_engine
    ):
        """CS-12: direct-addressed foreign id → None + scope miss recorded."""
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as finder:
            foreign = (
                await finder.execute(
                    select(Role).where(Role.tenant_id == TENANT_B, Role.name == "beta-role")
                )
            ).scalar_one()

        row = await scoped_db_a.get(Role, foreign.id)
        assert row is None  # 404-equivalent at the ORM level — no leak

        await flush_scope_miss_audits(scoped_db_a)
        await scoped_db_a.commit()
        async with SessionLocal() as checker:
            events = (
                await checker.execute(
                    select(TenantAuditEvent).where(
                        TenantAuditEvent.tenant_id == TENANT_A,
                        TenantAuditEvent.event_type
                        == TenantAuditEventType.cross_tenant_access_denied,
                    )
                )
            ).scalars().all()
        assert len(events) >= 1
        assert events[-1].is_security_relevant is True


# ── UPDATE / DELETE isolation (CS-12) ────────────────────────────────────────


class TestWriteIsolation:
    async def test_scoped_update_cannot_touch_foreign_rows(self, scoped_db_a, seeded_engine):
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as finder:
            foreign = (
                await finder.execute(
                    select(Role).where(Role.tenant_id == TENANT_B, Role.name == "beta-role")
                )
            ).scalar_one()

        result = await scoped_db_a.execute(
            update(Role).where(Role.id == foreign.id).values(name="hijacked")
        )
        await scoped_db_a.commit()
        assert result.rowcount == 0  # tenant B row untouched

        async with SessionLocal() as checker:
            row_after = (
                await checker.execute(select(Role).where(Role.id == foreign.id))
            ).scalar_one()
            assert row_after.name == "beta-role"

    async def test_scoped_delete_cannot_remove_foreign_rows(self, scoped_db_a, seeded_engine):
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as finder:
            foreign = (
                await finder.execute(
                    select(Role).where(Role.tenant_id == TENANT_B, Role.name == "beta-role")
                )
            ).scalar_one()

        result = await scoped_db_a.execute(delete(Role).where(Role.id == foreign.id))
        await scoped_db_a.commit()
        assert result.rowcount == 0

        async with SessionLocal() as checker:
            still_there = await checker.get(Role, foreign.id)
            assert still_there is not None

    async def test_scoped_update_within_own_tenant_works(self, scoped_db_a, seeded_engine):
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as finder:
            own = (
                await finder.execute(
                    select(Role).where(Role.tenant_id == TENANT_A, Role.name == "alpha-role")
                )
            ).scalar_one()
        result = await scoped_db_a.execute(
            update(Role).where(Role.id == own.id).values(description="renamed-in-a")
        )
        await scoped_db_a.commit()
        assert result.rowcount == 1

    async def test_insert_auto_stamped_with_session_tenant(self, scoped_db_a, seeded_engine):
        """INSERTs cannot leak into another tenant — rows inherit the
        session's tenant automatically."""
        new_role = Role(name="created-via-scoped-session")
        scoped_db_a.add(new_role)
        await scoped_db_a.flush()
        assert new_role.tenant_id == TENANT_A


# ── Join-table inheritance through parents (E-01) ────────────────────────────


class TestJoinTableInheritance:
    async def test_child_rows_reached_through_parent_are_scoped(
        self, seeded_engine, unscoped_db
    ):
        """UserRole carries NO tenant column; scope flows through the
        parent Role.  A tenant-A-scoped query joining the parent must not
        surface tenant B's membership rows."""
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        user_a, user_b = uuid.uuid4(), uuid.uuid4()
        async with SessionLocal() as seeder:
            role_a = (
                await seeder.execute(select(Role).where(Role.name == "alpha-role"))
            ).scalar_one()
            role_b = (
                await seeder.execute(select(Role).where(Role.name == "beta-role"))
            ).scalar_one()
            seeder.add_all(
                [
                    UserRole(user_id=user_a, role_id=role_a.id),
                    UserRole(user_id=user_b, role_id=role_b.id),
                ]
            )
            await seeder.commit()

        # Tenant-B membership pairs (must be unreachable from a scoped session)
        async with SessionLocal() as finder:
            foreign_link_pairs = set(
                (
                    await finder.execute(
                        select(UserRole.user_id, UserRole.role_id).join(
                            Role, Role.id == UserRole.role_id
                        ).where(Role.tenant_id == TENANT_B)
                    )
                ).all()
            )
        assert foreign_link_pairs, "fixture must create tenant-B child rows"

        scoped = SessionLocal()
        apply_tenant_scope(scoped, TENANT_A)
        visible_pairs = set(
            (
                await scoped.execute(
                    select(UserRole.user_id, UserRole.role_id).join(
                        Role, Role.id == UserRole.role_id
                    )
                )
            ).all()
        )
        await scoped.rollback()
        await scoped.close()

        assert visible_pairs.isdisjoint(foreign_link_pairs), (
            "child rows of tenant B parents leaked through a joined parent"
        )


# ── PermissionEngine tenant binding (CS-21) ──────────────────────────────────


class TestPermissionEngineTenantBinding:
    async def test_role_collection_bound_to_tenant(self, seeded_engine, unscoped_db):
        engine = PermissionEngine()
        user = uuid.uuid4()

        async def bind_role(session, role_name, tenant_id):
            role = Role(name=role_name, tenant_id=tenant_id)
            session.add(role)
            await session.flush()
            session.add(UserRole(user_id=user, role_id=role.id))
            await session.flush()
            return role.id

        role_a = await bind_role(unscoped_db, "tenant-a-admin", TENANT_A)
        role_b = await bind_role(unscoped_db, "tenant-b-admin", TENANT_B)
        await unscoped_db.commit()

        effective_a = await engine._get_effective_role_ids(unscoped_db, user, TENANT_A)
        effective_b = await engine._get_effective_role_ids(unscoped_db, user, TENANT_B)

        assert role_a in effective_a and role_b not in effective_a
        assert role_b in effective_b and role_a not in effective_b

    async def test_global_roles_effective_in_every_tenant(self, seeded_engine, unscoped_db):
        engine = PermissionEngine()
        user = uuid.uuid4()
        global_role = Role(name="platform-bridge", tenant_id=None)
        unscoped_db.add(global_role)
        await unscoped_db.flush()
        unscoped_db.add(UserRole(user_id=user, role_id=global_role.id))
        await unscoped_db.commit()

        for tenant in (TENANT_A, TENANT_B):
            effective = await engine._get_effective_role_ids(unscoped_db, user, tenant)
            assert global_role.id in effective

    async def test_foreign_tenant_roles_never_collected(self, seeded_engine, unscoped_db):
        """CS-21: identical role names across tenants never collide — the
        engine only ever collects the request tenant's roles."""
        engine = PermissionEngine()
        user = uuid.uuid4()

        role_b = Role(name="dup-name", tenant_id=TENANT_B)
        unscoped_db.add(role_b)
        await unscoped_db.flush()
        unscoped_db.add(UserRole(user_id=user, role_id=role_b.id))
        await unscoped_db.commit()

        effective_a = await engine._get_effective_role_ids(unscoped_db, user, TENANT_A)
        assert role_b.id not in effective_a
        assert effective_a == []  # no other role exists for the user in A

    async def test_wildcard_policy_never_grants_beyond_own_tenant(
        self, seeded_engine, unscoped_db
    ):
        """CS-21: a ``*::*`` wildcard policy attached to a tenant B role
        grants everything inside tenant B but NEVER authorizes the same
        user against tenant A's context."""
        engine = PermissionEngine()
        user = uuid.uuid4()

        role_b = Role(name="wildcard-b", tenant_id=TENANT_B)
        unscoped_db.add(role_b)
        await unscoped_db.flush()
        unscoped_db.add(UserRole(user_id=user, role_id=role_b.id))
        stmt = PolicyStatement(
            role_id=role_b.id, effect=PolicyEffect.allow, module="*::*"
        )
        unscoped_db.add(stmt)
        await unscoped_db.flush()
        unscoped_db.add(PolicyAction(policy_statement_id=stmt.id, action="*"))
        unscoped_db.add(
            PolicyResource(
                policy_statement_id=stmt.id, resource_type="*", resource_id="*"
            )
        )
        await unscoped_db.commit()

        allowed_in_b = await engine.authorize(
            unscoped_db,
            user_id=user,
            module=RT_AGENT_ROLES,
            action="read",
            resource_id="*",
            resource_tags={},
            tenant_id=TENANT_B,
        )
        assert allowed_in_b.allowed is True

        denied_in_a = await engine.authorize(
            unscoped_db,
            user_id=user,
            module=RT_AGENT_ROLES,
            action="read",
            resource_id="*",
            resource_tags={},
            tenant_id=TENANT_A,
        )
        assert denied_in_a.allowed is False


# ── Tenant lifecycle service (Phase 5.1, CS-07/CS-09) ────────────────────────


class TestTenantLifecycleService:
    @pytest_asyncio.fixture
    async def lifecycle_db(self, seeded_engine):
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as session:
            yield session
            await session.rollback()

    async def test_create_requires_name(self, lifecycle_db):
        from app.services.tenancy.tenant_service import TenantService, TenantServiceError

        service = TenantService()
        with pytest.raises(TenantServiceError, match="name is required"):
            await service.create(lifecycle_db, name="   ", slug="valid-slug")

    async def test_create_validates_slug_shape(self, lifecycle_db):
        from app.services.tenancy.tenant_service import TenantService, TenantServiceError

        service = TenantService()
        with pytest.raises(TenantServiceError, match="Slug"):
            await service.create(lifecycle_db, name="Ok", slug="Bad_Slug!")

    async def test_duplicate_slug_rejected(self, lifecycle_db):
        from app.services.tenancy.tenant_service import TenantService, TenantServiceError

        service = TenantService()
        await service.create(lifecycle_db, name="First", slug="dup-slug")
        with pytest.raises(TenantServiceError, match="already exists"):
            await service.create(lifecycle_db, name="Second", slug="dup-slug")

    async def test_duplicate_name_rejected(self, lifecycle_db):
        from app.services.tenancy.tenant_service import TenantService, TenantServiceError

        service = TenantService()
        await service.create(lifecycle_db, name="Same Name", slug="slug-one")
        with pytest.raises(TenantServiceError, match="already exists"):
            await service.create(lifecycle_db, name="Same Name", slug="slug-two")

    async def test_suspend_resume_round_trip_audited(self, lifecycle_db):
        from app.services.tenancy.tenant_service import TenantService

        service = TenantService()
        tenant = await service.create(lifecycle_db, name="Cycle Co", slug="cycle-co")
        await lifecycle_db.commit()

        suspended = await service.suspend(lifecycle_db, tenant.id)
        assert suspended.status == TenantStatus.suspended
        resumed = await service.resume(lifecycle_db, tenant.id)
        assert resumed.status == TenantStatus.active

        events = (
            await lifecycle_db.execute(
                select(TenantAuditEvent).where(
                    TenantAuditEvent.tenant_id == tenant.id
                )
            )
        ).scalars().all()
        types = {e.event_type for e in events}
        assert TenantAuditEventType.tenant_created in types
        assert TenantAuditEventType.tenant_suspended in types
        assert TenantAuditEventType.tenant_resumed in types

    async def test_delete_requires_explicit_confirmation(self, lifecycle_db):
        from app.services.tenancy.tenant_service import TenantService, TenantServiceError

        service = TenantService()
        tenant = await service.create(lifecycle_db, name="Doomed", slug="doomed")
        await lifecycle_db.commit()
        with pytest.raises(TenantServiceError, match="confirmation"):
            await service.delete(lifecycle_db, tenant.id, confirm_slug="wrong-slug")

    async def test_delete_removes_tenant_and_slug_is_reusable(self, lifecycle_db):
        """CS-09: deletion is TRUE deletion — the slug can be recreated."""
        from app.services.tenancy.tenant_service import TenantService

        service = TenantService()
        tenant = await service.create(
            lifecycle_db, name="Doomed Two", slug="doomed-two"
        )
        # Give the tenant a business row that must be hard-deleted with it.
        lifecycle_db.add(Role(name="doomed-role", tenant_id=tenant.id))
        await lifecycle_db.commit()
        tenant_id = tenant.id

        await service.delete(lifecycle_db, tenant_id, confirm_slug="doomed-two")
        await lifecycle_db.commit()

        assert await service.get(lifecycle_db, tenant_id) is None
        rows = (
            await lifecycle_db.execute(
                select(Role).where(Role.tenant_id == tenant_id)
            )
        ).scalars().all()
        assert rows == []

        recreated = await service.create(
            lifecycle_db, name="Doomed Two Reborn", slug="doomed-two"
        )
        assert recreated.slug == "doomed-two"
        assert recreated.id != tenant_id

    async def test_system_tenant_cannot_be_deleted(self, lifecycle_db):
        from app.services.tenancy.tenant_service import TenantService, TenantServiceError

        service = TenantService()
        system = Tenant(
            name="System", slug="system", status=TenantStatus.active, is_system_tenant=True
        )
        lifecycle_db.add(system)
        await lifecycle_db.flush()
        with pytest.raises(TenantServiceError, match="system tenant cannot be deleted"):
            await service.delete(lifecycle_db, system.id, confirm_slug="system")
