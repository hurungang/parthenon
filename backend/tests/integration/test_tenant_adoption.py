"""System-tenant adoption tests against a real PostgreSQL database
(Phase 5.3 / 9.5, CS-03/CS-05/CS-06).

Uses the dedicated ``parthenon_test`` database (schema created from the
ORM metadata, matching the applied migrations) so adoption can run and
clean up after itself without touching the development database:

- enabling adoption creates the implicit system tenant
- EVERY business row with a NULL tenant reference is backfilled to the
  system tenant — including rows inserted between migration and backfill
  (orphan handling, CS-06)
- the existing administrator gains platform-admin membership; regular
  users get member memberships
- adoption is idempotent (re-running changes nothing, CS-05)
- disable validation reports no data loss; the enable→disable→enable
  cycle is repeatable (CS-03)
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.session import Base  # noqa: E402
from app.services.tenancy.root_tenant import (  # noqa: E402
    ROOT_TENANT_SLUG,
)
from app.services.tenancy.tenant_adoption_service import (  # noqa: E402
    TenantAdoptionService,
)


@pytest.fixture(scope="module")
def test_db_url():
    """Isolated parthenon_test database (never the development one)."""
    return "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test"


def _ensure_database() -> None:
    """Create parthenon_test if it does not exist (via the admin DB)."""
    import asyncpg

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_ensure_database_async())
    finally:
        loop.close()


async def _ensure_database_async() -> None:
    import asyncpg

    try:
        conn = await asyncpg.connect(
            host="localhost", port=5432, user="parthenon",
            password="parthenon", database="postgres",
        )
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = 'parthenon_test'"
            )
            if not exists:
                await conn.execute("CREATE DATABASE parthenon_test OWNER parthenon")
        finally:
            await conn.close()
    except Exception:
        pass  # tests fail with a clear connection error if postgres is down


def _reset_schema() -> None:
    """(Re)create the full ORM schema in parthenon_test.

    Runs synchronously at module import so the async fixtures see a ready
    database.  Matches the applied migrations via Base.metadata.  Data
    written by OTHER tests into parthenon_test (e.g. middleware audit
    events) is truncated first so the drop/recreate is order-independent.
    """
    _ensure_database()

    async def _create():
        engine = create_async_engine(TEST_DB_URL_HOLDER["url"])
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                """
                DO $$ DECLARE r RECORD; BEGIN
                  FOR r IN (SELECT tablename FROM pg_tables
                            WHERE schemaname = 'public') LOOP
                    EXECUTE 'TRUNCATE TABLE public.' ||
                            quote_ident(r.tablename) || ' CASCADE';
                  END LOOP;
                END $$;
                """
            )
            # create_all is idempotent; do NOT drop_all (metadata carries an
            # unresolvable FK cycle: agent_jobs/agent_outputs/
            # termination_requests — drop sorting fails by design).
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn))
        await engine.dispose()

    asyncio.new_event_loop().run_until_complete(_create())


TEST_DB_URL_HOLDER = {"url": "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test"}


@pytest.fixture(scope="module", autouse=True)
def _schema():
    """One schema reset for the module; per-test cleanup inside tests."""
    _reset_schema()
    yield


@pytest_asyncio.fixture
async def db(test_db_url):
    engine = create_async_engine(test_db_url)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def clean_db(db):
    """Session on a table-clean database (business tables emptied)."""
    from app.db.models.agents import AgentType
    from app.db.models.identity import Role
    from app.db.models.platform_user import PlatformUser
    from app.db.models.tenant import Tenant
    from app.db.models.tenant_membership import TenantUserMembership
    from app.db.models.user_role import UserRole

    await db.execute(TenantUserMembership.__table__.delete())
    await db.execute(UserRole.__table__.delete())
    await db.execute(Role.__table__.delete())
    await db.execute(AgentType.__table__.delete())
    await db.execute(PlatformUser.__table__.delete())
    await db.execute(Tenant.__table__.delete())
    await db.commit()
    yield db


def _business_tables():
    """All tables carrying a nullable tenant_id (the adoption targets)."""
    tables = []
    for table in Base.metadata.sorted_tables:
        col = table.columns.get("tenant_id")
        if col is not None and table.name not in (
            "tenants", "tenant_audit_events", "platform_settings"
        ):
            tables.append(table)
    return tables


class TestSystemTenantAdoption:
    async def test_adopt_creates_system_tenant(self, clean_db):
        service = TenantAdoptionService()
        summary = await service.adopt_system_tenant(clean_db)
        await clean_db.commit()

        assert summary["created"] is True
        assert summary["slug"] == ROOT_TENANT_SLUG
        system = await service.find_system_tenant(clean_db)
        assert system is not None
        assert system.is_system_tenant is True
        assert system.slug == "root"

    async def test_backfill_claims_every_null_row(self, clean_db):
        """CS-05: every existing business row is claimed by the system
        tenant — including rows with NULL tenants (CS-06 orphans)."""
        service = TenantAdoptionService()

        # Seed pre-existing data with NULL tenant references.
        from app.db.models.agents import AgentType, ModelConfig
        from app.db.models.identity import Role
        from app.db.models.mcp_hub import McpServer
        from app.db.models.platform_user import PlatformUser

        suffix = uuid.uuid4().hex[:6]
        admin = PlatformUser(
            sub=f"adopt-admin-{suffix}", email=f"aa-{suffix}@t.dev", display_name="Admin"
        )
        plain = PlatformUser(
            sub=f"adopt-user-{suffix}", email=f"au-{suffix}@t.dev", display_name="User"
        )
        clean_db.add_all([admin, plain])
        await clean_db.flush()

        # The legacy administrator holds the system_admin role.
        from app.db.models.user_role import UserRole

        legacy_role = Role(name="system_admin", is_system=True, tenant_id=None)
        clean_db.add(legacy_role)
        await clean_db.flush()
        clean_db.add(UserRole(user_id=admin.id, role_id=legacy_role.id))

        clean_db.add_all(
            [
                AgentType(name=f"adopt-at-{suffix}", tenant_id=None),
                McpServer(
                    name=f"adopt-srv-{suffix}",
                    slug=f"adopt-srv-{suffix}",
                    base_url="http://x",
                    tenant_id=None,
                ),
                ModelConfig(
                    display_name=f"adopt-model-{suffix}",
                    provider_type="openai",
                    tenant_id=None,
                ),
            ]
        )
        await clean_db.commit()

        summary = await service.adopt_system_tenant(clean_db)
        await clean_db.commit()

        system_id = uuid.UUID(summary["tenant_id"])
        # NO orphaned rows remain in ANY business table.
        for table in _business_tables():
            col = table.columns.get("tenant_id")
            orphans = (
                await clean_db.execute(
                    text(f"SELECT COUNT(*) FROM {table.name} WHERE {col.name} IS NULL")
                )
            ).scalar()
            assert orphans == 0, f"{table.name} has {orphans} unclaimed NULL rows"

        # The seeded rows now carry the system tenant.
        for model, name_filter in (
            (AgentType, f"adopt-at-{suffix}"),
            (ModelConfig, f"adopt-model-{suffix}"),
        ):
            row = (
                await clean_db.execute(
                    text(
                        f"SELECT tenant_id FROM {model.__tablename__} "
                        f"WHERE {'name' if model is AgentType else 'display_name'} = :n"
                    ),
                    {"n": name_filter},
                )
            ).first()
            assert row is not None and str(row[0]) == str(system_id)

    async def test_admin_gains_platform_admin_membership(self, clean_db):
        """The existing administrator becomes platform admin; others member."""
        from app.db.models.identity import Role
        from app.db.models.platform_user import PlatformUser
        from app.db.models.tenant import TenantRole
        from app.db.models.tenant_membership import TenantUserMembershipStatus
        from app.db.models.user_role import UserRole

        service = TenantAdoptionService()
        suffix = uuid.uuid4().hex[:6]
        admin = PlatformUser(
            sub=f"adm2-{suffix}", email=f"a2-{suffix}@t.dev", display_name="A2"
        )
        member = PlatformUser(
            sub=f"mem2-{suffix}", email=f"m2-{suffix}@t.dev", display_name="M2"
        )
        clean_db.add_all([admin, member])
        await clean_db.flush()
        role = Role(name="system_admin", is_system=True, tenant_id=None)
        clean_db.add(role)
        await clean_db.flush()
        clean_db.add_all(
            [
                UserRole(user_id=admin.id, role_id=role.id),
                UserRole(user_id=member.id, role_id=role.id),  # also admin-typed
            ]
        )
        clean_db.add(
            PlatformUser(sub=f"plain-{suffix}", email=f"p-{suffix}@t.dev", display_name="P")
        )
        await clean_db.commit()

        await service.adopt_system_tenant(clean_db)
        await clean_db.commit()

        memberships = (
            await clean_db.execute(text("SELECT * FROM tenant_user_memberships"))
        ).fetchall()
        roles = {
            str(m.tenant_role): 0 for m in ()
        }
        admin_role_count = 0
        member_role_count = 0
        for m in memberships:
            if str(m.tenant_role) == TenantRole.platform_admin:
                admin_role_count += 1
            elif str(m.tenant_role) == TenantRole.member:
                member_role_count += 1
        assert admin_role_count >= 2  # both system_admin holders promoted
        assert member_role_count >= 1  # the plain user gets member

    async def test_adoption_is_idempotent(self, clean_db):
        """CS-05: re-running adoption changes nothing."""
        service = TenantAdoptionService()
        first = await service.adopt_system_tenant(clean_db)
        await clean_db.commit()
        second = await service.adopt_system_tenant(clean_db)
        await clean_db.commit()

        assert first["created"] is True
        assert second["created"] is False
        assert second["tenant_id"] == first["tenant_id"]

        counts = (
            await clean_db.execute(
                text(
                    "SELECT tenant_role, COUNT(*) FROM tenant_user_memberships "
                    "GROUP BY tenant_role"
                )
            )
        ).all()
        # No duplicated memberships: totals stay stable across re-runs.
        before = {r[0]: r[1] for r in counts}
        await service.adopt_system_tenant(clean_db)
        await clean_db.commit()
        after = (
            await clean_db.execute(
                text(
                    "SELECT tenant_role, COUNT(*) FROM tenant_user_memberships "
                    "GROUP BY tenant_role"
                )
            )
        ).all()
        assert {r[0]: r[1] for r in after} == before

    async def test_disable_reports_no_data_loss(self, clean_db):
        """CS-03: disable is validated as loss-free."""
        service = TenantAdoptionService()
        await service.adopt_system_tenant(clean_db)
        await clean_db.commit()

        report = await service.validate_disable(clean_db)
        assert report["data_loss"] is False
        assert report["root_tenant_present"] is True
        assert report["root_tenant_slug"] == "root"
        assert report["tenants_remaining"] >= 1

    async def test_enable_disable_enable_cycle_repeatable(self, clean_db):
        """CS-03: the enable→disable→enable cycle is repeatable and stable."""
        service = TenantAdoptionService()
        first = await service.adopt_system_tenant(clean_db)
        await clean_db.commit()
        await service.validate_disable(clean_db)
        again = await service.adopt_system_tenant(clean_db)
        await clean_db.commit()

        assert again["created"] is False
        assert again["tenant_id"] == first["tenant_id"]

    async def test_reserved_system_slug_guarded(self, clean_db):
        """A regular tenant occupying 'root' blocks adoption loudly."""
        from app.db.models.tenant import Tenant

        service = TenantAdoptionService()
        clean_db.add(
            Tenant(name="Squatter", slug="root", is_system_tenant=False)
        )
        await clean_db.commit()

        with pytest.raises(Exception, match="reserved"):
            await service.adopt_system_tenant(clean_db)
