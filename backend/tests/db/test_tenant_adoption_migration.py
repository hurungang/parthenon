"""Scenario 6 + 8 — adoption migration ``b8c9d0e1f2a3`` verification.

Runs the REAL Alembic migration chain against a scratch ``parthenon_test``
database (never the development database) and verifies:

- NULL→root adoption guarantee: ``tenant_id`` is NOT NULL on every
  tightened data-plane table (``information_schema``)
- retired NULL-variant partial unique indexes are gone; the composite
  ``uq_mcp_servers_tenant_slug`` exists
- DB-level negative inserts: NULL tenant rejected, duplicate
  ``(tenant, slug)`` rejected, same slug across two tenants accepted
- idempotency: ``upgrade head`` twice is a no-op; ``downgrade`` to the
  previous revision restores the legacy schema and the upgrade replays

The module tears the schema down afterwards (drop + recreate from ORM
metadata) so other test modules are unaffected.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.integration._strict_tenant_utils import (
    TEST_DB_URL,
    ensure_database,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]

#: Tables whose ``tenant_id`` must be NOT NULL after b8c9d0e1f2a3
#: (mirrors the migration's _ADOPT_AND_REQUIRE_TENANT list).
_TENANT_REQUIRED_TABLES = [
    "mcp_servers",
    "mcp_tools",
    "agent_data",
    "agent_outputs",
    "agent_data_types",
    "scheduled_jobs",
    "notification_channels",
    "recipient_groups",
    "skills",
    "sops",
    "agent_types",
    "model_configs",
    "groups",
    "tag_definitions",
    "agent_api_keys",
    "agent_roles",
    "agent_identities",
]

_RETIRED_GLOBAL_INDEXES = [
    "uq_skills_global_name",
    "uq_sops_global_name",
    "uq_agent_data_types_global_name",
    "uq_agent_data_types_global_slug",
    "uq_scheduled_jobs_global_name",
    "uq_notification_channels_global_name",
    "uq_recipient_groups_global_name",
    "uq_recipient_groups_global_slug",
]


def _alembic(*args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = TEST_DB_URL
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
    )


def _drop_schema() -> None:
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    async def _run() -> None:
        engine = create_async_engine(TEST_DB_URL)
        async with engine.begin() as conn:
            await conn.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
            await conn.exec_driver_sql("CREATE SCHEMA public")
        await engine.dispose()

    asyncio.new_event_loop().run_until_complete(_run())


async def _create_orm_schema() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db.session import Base

    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn))
    await engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def migrated_database():
    """A parthenon_test migrated from scratch to head; restored afterwards."""
    ensure_database()
    _drop_schema()
    _alembic("upgrade", "head")
    yield
    # Restore a clean ORM-metadata schema for the other test modules.
    _drop_schema()
    import asyncio

    asyncio.new_event_loop().run_until_complete(_create_orm_schema())


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine

    engine = create_async_engine(TEST_DB_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


async def _two_tenant_ids(db):
    from app.db.models.tenant import Tenant

    suffix = uuid.uuid4().hex[:6]
    tenant_a = Tenant(name=f"mig-a-{suffix}", slug=f"mig-a-{suffix}")
    tenant_b = Tenant(name=f"mig-b-{suffix}", slug=f"mig-b-{suffix}")
    db.add_all([tenant_a, tenant_b])
    await db.commit()
    return tenant_a.id, tenant_b.id


def _mcp_server(tenant_id, name: str, slug: str = "supabase"):
    from app.db.models.mcp_hub import McpServer, McpServerStatus

    return McpServer(
        tenant_id=tenant_id,
        name=name,
        slug=slug,
        base_url="http://x",
        status=McpServerStatus.active,
    )




class TestIdempotencyAndReplay:
    async def test_upgrade_head_twice_is_noop(self, db):
        before = (
            await db.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar()
        _alembic("upgrade", "head")
        after = (
            await db.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar()
        assert before == after

    async def test_downgrade_restores_legacy_schema_and_upgrade_replays(self, db):
        _alembic("downgrade", "a7b9c1d3e5f7")

        # tenant_id is nullable again (legacy schema restored).
        row = (
            await db.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'skills' AND column_name = 'tenant_id'"
                )
            )
        ).first()
        assert row is not None and row[0] == "YES"
        # The NULL-variant partial indexes are back.
        row = (
            await db.execute(
                text("SELECT 1 FROM pg_indexes WHERE indexname = 'uq_skills_global_name'")
            )
        ).first()
        assert row is not None

        # Replay: the upgrade re-applies cleanly (idempotent by design).
        _alembic("upgrade", "head")
        row = (
            await db.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'skills' AND column_name = 'tenant_id'"
                )
            )
        ).first()
        assert row[0] == "NO"
        row = (
            await db.execute(
                text("SELECT 1 FROM pg_indexes WHERE indexname = 'uq_skills_global_name'")
            )
        ).first()
        assert row is None

class TestAdoptionIdempotency:
    async def test_adoption_service_idempotent_on_migrated_db(self, db):
        from app.services.tenancy.root_tenant import ROOT_TENANT_SLUG
        from app.services.tenancy.tenant_adoption_service import TenantAdoptionService

        service = TenantAdoptionService()
        first = await service.adopt_system_tenant(db)
        await db.commit()
        second = await service.adopt_system_tenant(db)
        await db.commit()

        assert second["created"] is False
        assert second["tenant_id"] == first["tenant_id"]
        system = await service.find_system_tenant(db)
        assert system is not None
        assert system.slug == ROOT_TENANT_SLUG

        # Adopted rows: no NULL business rows anywhere it can see.
        for table in ("skills", "recipient_groups", "scheduled_jobs", "agent_data_types"):
            orphans = (
                await db.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id IS NULL")
                )
            ).scalar()
            assert orphans == 0, f"{table} has NULL-tenant rows after adoption"

class TestNotNullTenantColumns:
    @pytest.mark.parametrize("table", _TENANT_REQUIRED_TABLES)
    async def test_tenant_id_is_not_null(self, db, table):
        row = (
            await db.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = 'tenant_id'"
                ),
                {"t": table},
            )
        ).first()
        assert row is not None, f"table {table} has no tenant_id column"
        assert row[0] == "NO", f"{table}.tenant_id is nullable after migration"

class TestIndexRetirementAndSlugScoping:
    async def test_retired_null_variant_indexes_are_gone(self, db):
        for index in _RETIRED_GLOBAL_INDEXES:
            row = (
                await db.execute(
                    text(
                        "SELECT 1 FROM pg_indexes WHERE indexname = :i"
                    ),
                    {"i": index},
                )
            ).first()
            assert row is None, f"NULL-variant index {index} still exists"

    async def test_composite_tenant_slug_unique_present(self, db):
        row = (
            await db.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'uq_mcp_servers_tenant_slug'"
                )
            )
        ).first()
        assert row is not None
        definition = row[0].lower()
        assert "tenant_id" in definition and "slug" in definition
        # No platform-wide unique on slug alone remains (the pkey on id
        # doesn't count).
        platform_unique = (
            await db.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE tablename = 'mcp_servers' AND indexdef ILIKE '%unique%' "
                    "AND indexdef NOT ILIKE '%tenant_id%' "
                    "AND indexname <> 'mcp_servers_pkey'"
                )
            )
        ).fetchall()
        assert platform_unique == []

    async def test_duplicate_tenant_slug_insert_rejected(self, db):
        from sqlalchemy.exc import IntegrityError

        tenant_a, _ = await _two_tenant_ids(db)
        db.add(_mcp_server(tenant_a, "srv1"))
        db.add(_mcp_server(tenant_a, "srv2"))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    async def test_same_slug_across_two_tenants_accepted(self, db):
        tenant_a, tenant_b = await _two_tenant_ids(db)
        db.add_all([_mcp_server(tenant_a, "srv-a"), _mcp_server(tenant_b, "srv-b")])
        await db.commit()

    async def test_null_tenant_insert_rejected(self, db):
        from sqlalchemy.exc import IntegrityError

        from app.db.models.skills import Skill

        db.add(Skill(tenant_id=None, name="legacy-skill", is_active=True))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
