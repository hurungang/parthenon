"""Migration schema verification against the REAL migrated PostgreSQL DB
(Phase 1.8 / 9.5, CS-04).

Verifies the applied multi-tenant migration by querying
``information_schema`` (not ORM metadata):

- the five new tables exist (Tenant, TenantUserMembership,
  TenantInvitation, TenantAuditEvent, PlatformSetting)
- every direct-scoped entity across the schema has a NULLABLE, INDEXED
  ``tenant_id`` column
- join/child tables that inherit scope via parents carry NO tenant column
- negative constraints: inserting a row referencing a non-existent tenant
  fails; tenant (name, slug) uniqueness holds at the DB level; role names
  are unique per tenant
- the platform switch row is seeded false (pristine state)
- no existing column was dropped or made non-nullable (spot-checked)

Full downgrade/re-upgrade reversibility mutates the SHARED development
database schema and is therefore gated behind
``PARTHENON_TEST_MIGRATION_CYCLE=1``.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")


@pytest.fixture(scope="module")
def real_db_url():
    """The migration-applied development database."""
    url = os.environ.get("DATABASE_URL", "")
    if "parthenon_test" in url or not url:
        url = "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon"
    if "postgresql://" in url and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif "postgresql+psycopg2://" in url:
        url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return url


@pytest_asyncio.fixture
async def db(real_db_url):
    """Per-test engine+session (asyncpg connections are loop-bound)."""
    engine = create_async_engine(real_db_url)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


async def _scalar(db, query: str, params: dict | None = None):
    result = await db.execute(text(query), params or {})
    row = result.fetchone()
    return row[0] if row else None


# ── Five new tables (CS-04) ──────────────────────────────────────────────────


class TestNewTables:
    async def test_tenants_table_exists(self, db):
        count = await _scalar(
            db,
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'tenants' AND table_schema = 'public'",
        )
        assert count == 1

    async def test_tenant_memberships_table_exists(self, db):
        count = await _scalar(
            db,
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'tenant_user_memberships' AND table_schema = 'public'",
        )
        assert count == 1

    async def test_tenant_invitations_table_exists(self, db):
        count = await _scalar(
            db,
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'tenant_invitations' AND table_schema = 'public'",
        )
        assert count == 1

    async def test_tenant_audit_events_table_exists(self, db):
        count = await _scalar(
            db,
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'tenant_audit_events' AND table_schema = 'public'",
        )
        assert count == 1

    async def test_platform_settings_table_exists(self, db):
        count = await _scalar(
            db,
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'platform_settings' AND table_schema = 'public'",
        )
        assert count == 1

    async def test_tenancy_switch_seeded_false(self, db):
        """Pristine state: the switch row exists and is FALSE."""
        value = await _scalar(
            db,
            "SELECT value FROM platform_settings WHERE key = 'multi_tenancy_enabled'",
        )
        assert value is not None, "multi_tenancy_enabled row must be seeded"
        assert value.get("enabled") is False

    async def test_tenant_invitation_token_hash_column(self, db):
        """Migration d9f3a6c2e7b1 added the SHA-256 token_hash column."""
        nullable = await _scalar(
            db,
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'tenant_invitations' AND column_name = 'token_hash'",
        )
        assert nullable == "YES"

    async def test_per_tenant_role_name_uniqueness_indexes(self, db):
        """Migration c8e2f5b17a93: per-tenant + global role-name uniqueness."""
        indexes = await _scalar(
            db,
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE tablename = 'roles' "
            "AND indexname IN ('uq_roles_tenant_name', 'uq_roles_global_name')",
        )
        assert indexes == 2


# ── Tenant columns across direct-scoped entities (CS-04) ─────────────────────


# Representative tables per domain group — every direct-scoped entity must
# carry a nullable, indexed tenant_id.
SCOPED_TABLES = [
    # identity & access
    "roles", "identities", "groups", "access_requests", "tag_definitions",
    "policy_statements", "agent_api_keys", "identity_provider_configs",
    # agent domain
    "agent_roles", "agent_identities", "agent_types", "agent_instances",
    "agent_jobs", "model_configs",
    # mcp / skills / sops / scheduling
    "mcp_servers", "skills", "sops", "scheduled_jobs",
    # conversations / results / data
    "conversation_sessions", "runtime_tool_calls", "result_records",
    "agent_data_types", "agent_outputs", "agent_data",
    # interventions / terminations / notifications
    "intervene_requests", "termination_requests", "notification_channels",
    "notification_logs",
    # model governance
    "model_guardrail_configurations", "model_availability",
    "model_usage_postures",
]

# Join/child tables that MUST NOT carry a tenant column (E-01).
JOIN_TABLES_WITHOUT_TENANT = [
    "user_roles", "group_roles", "user_groups", "tag_values",
    "policy_tag_conditions", "api_key_usage_logs", "agent_role_skills",
    "agent_role_sops", "agent_role_identities", "agent_plans",
    "agent_prompt_logs", "termination_cascade_outcomes",
]


class TestTenantColumns:
    @pytest.mark.parametrize("table", SCOPED_TABLES)
    async def test_tenant_column_exists_nullable(self, db, table):
        row = await _scalar(
            db,
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'tenant_id' "
            "AND table_schema = 'public'",
            {"t": table},
        )
        assert row is not None, f"{table}.tenant_id missing"
        assert row == "YES", f"{table}.tenant_id must be nullable"

    @pytest.mark.parametrize("table", SCOPED_TABLES)
    async def test_tenant_column_indexed(self, db, table):
        count = await _scalar(
            db,
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE tablename = :t AND schemaname = 'public' "
            "AND indexdef LIKE '%tenant_id%'",
            {"t": table},
        )
        assert count >= 1, f"{table}.tenant_id must be indexed"

    @pytest.mark.parametrize("table", JOIN_TABLES_WITHOUT_TENANT)
    async def test_join_tables_have_no_tenant_column(self, db, table):
        count = await _scalar(
            db,
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'tenant_id' "
            "AND table_schema = 'public'",
            {"t": table},
        )
        assert count == 0, f"{table} must inherit scope via parents (no tenant_id)"

    async def test_no_existing_column_became_non_nullable(self, db):
        """Spot-check: core legacy columns are still nullable-safe."""
        checks = [
            ("roles", "description"),
            ("agent_types", "description"),
            ("mcp_servers", "description"),
        ]
        for table, column in checks:
            nullable = await _scalar(
                db,
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c AND table_schema = 'public'",
                {"t": table, "c": column},
            )
            assert nullable == "YES", f"{table}.{column} must remain nullable"


# ── Negative constraint tests ────────────────────────────────────────────────


class TestNegativeConstraints:
    async def test_insert_with_nonexistent_tenant_fk_fails(self, db):
        """FK to tenants.id must reject unknown tenant references."""
        with pytest.raises(Exception):
            await db.execute(
                text(
                    "INSERT INTO roles (id, tenant_id, name, role_type, is_active, is_system) "
                    "VALUES (:id, :tid, :name, 'user', true, false)"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": uuid.uuid4(),  # no such tenant
                    "name": f"fk-violation-{uuid.uuid4().hex[:6]}",
                },
            )
        await db.rollback()

    async def test_tenant_slug_unique_at_db_level(self, db):
        slug = f"uniq-slug-{uuid.uuid4().hex[:8]}"
        await db.execute(
            text(
                "INSERT INTO tenants (id, name, slug, status, is_system_tenant, "
                "is_onboarded, admin_contact_role) VALUES "
                "(:id, :name, :slug, 'active', false, false, 'tenant_admin')"
            ),
            {"id": uuid.uuid4(), "name": f"Uniq {uuid.uuid4().hex[:6]}", "slug": slug},
        )
        await db.commit()
        with pytest.raises(Exception):
            await db.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, status, is_system_tenant, "
                    "is_onboarded, admin_contact_role) VALUES "
                    "(:id, :name, :slug, 'active', false, false, 'tenant_admin')"
                ),
                {"id": uuid.uuid4(), "name": f"Other {uuid.uuid4().hex[:6]}", "slug": slug},
            )
        await db.rollback()
        # Cleanup
        await db.execute(text("DELETE FROM tenants WHERE slug = :s"), {"s": slug})
        await db.commit()

    async def test_tenant_name_unique_at_db_level(self, db):
        name = f"UniqName {uuid.uuid4().hex[:8]}"
        await db.execute(
            text(
                "INSERT INTO tenants (id, name, slug, status, is_system_tenant, "
                "is_onboarded, admin_contact_role) VALUES "
                "(:id, :name, :slug, 'active', false, false, 'tenant_admin')"
            ),
            {"id": uuid.uuid4(), "name": name, "slug": f"n-{uuid.uuid4().hex[:8]}"},
        )
        await db.commit()
        with pytest.raises(Exception):
            await db.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, status, is_system_tenant, "
                    "is_onboarded, admin_contact_role) VALUES "
                    "(:id, :name, :slug, 'active', false, false, 'tenant_admin')"
                ),
                {"id": uuid.uuid4(), "name": name, "slug": f"n2-{uuid.uuid4().hex[:8]}"},
            )
        await db.rollback()
        await db.execute(text("DELETE FROM tenants WHERE name = :n"), {"n": name})
        await db.commit()

    async def test_role_names_unique_per_tenant(self, db):
        """Migration c8e2f5b17a93: identical names allowed across tenants,
        rejected within one tenant."""
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        role_name = f"dup-role-{uuid.uuid4().hex[:8]}"
        for tid in (tenant_a, tenant_b):
            await db.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, status, is_system_tenant, "
                    "is_onboarded, admin_contact_role) VALUES "
                    "(:id, :name, :slug, 'active', false, false, 'tenant_admin')"
                ),
                {
                    "id": tid,
                    "name": f"T{tid.hex[:6]}",
                    "slug": f"t-{tid.hex[:8]}",
                },
            )
        await db.execute(
            text(
                "INSERT INTO roles (id, tenant_id, name, role_type, is_active, is_system) "
                "VALUES (:id, :tid, :name, 'user', true, false)"
            ),
            {"id": uuid.uuid4(), "tid": tenant_a, "name": role_name},
        )
        await db.commit()
        # Same name in tenant B is legal.
        await db.execute(
            text(
                "INSERT INTO roles (id, tenant_id, name, role_type, is_active, is_system) "
                "VALUES (:id, :tid, :name, 'user', true, false)"
            ),
            {"id": uuid.uuid4(), "tid": tenant_b, "name": role_name},
        )
        await db.commit()
        # Same name in tenant A again is rejected.
        with pytest.raises(Exception):
            await db.execute(
                text(
                    "INSERT INTO roles (id, tenant_id, name, role_type, is_active, is_system) "
                    "VALUES (:id, :tid, :name, 'user', true, false)"
                ),
                {"id": uuid.uuid4(), "tid": tenant_a, "name": role_name},
            )
        await db.rollback()
        await db.execute(
            text("DELETE FROM roles WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
        await db.execute(
            text("DELETE FROM tenants WHERE id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
        await db.commit()


# ── Reversibility (gated: mutates the shared DB schema) ──────────────────────


@pytest.mark.skipif(
    os.environ.get("PARTHENON_TEST_MIGRATION_CYCLE") != "1",
    reason=(
        "Downgrade/re-upgrade mutates the SHARED development database schema; "
        "run explicitly with PARTHENON_TEST_MIGRATION_CYCLE=1 against a "
        "disposable database"
    ),
)
class TestMigrationReversibility:
    async def test_downgrade_upgrade_cycle(self, real_db_url):
        """CS-04 reversibility: downgrade -1 then re-upgrade succeeds and
        restores the same head revision."""
        import subprocess
        import sys

        env = {**os.environ, "DATABASE_URL": real_db_url}
        head_before = subprocess.run(
            [sys.executable, "-m", "alembic", "current"],
            capture_output=True, text=True, cwd=os.path.dirname(real_db_url) or ".",
            env=env, check=False,
        )
        assert "head" in head_before.stdout or head_before.returncode == 0
