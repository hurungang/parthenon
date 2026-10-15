"""Shared helpers for strict-tenant-isolation tests.

Provides the ``parthenon_test`` database pattern used by
``tests/integration/test_tenant_adoption.py``: an isolated PostgreSQL
database whose schema is created from the ORM metadata (matching the
applied migrations), plus two-tenant fixture builders.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DB_URL = "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test"


def ensure_database() -> None:
    """Create parthenon_test if it does not exist (via the admin DB)."""
    import asyncpg

    async def _run() -> None:
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
            pass  # a clear connection error surfaces from the tests themselves

    asyncio.new_event_loop().run_until_complete(_run())


def reset_schema() -> None:
    """(Re)create the full ORM schema in parthenon_test.

    Mirrors ``tests/integration/test_tenant_adoption.py``: truncate all
    tables, then ``create_all`` (idempotent — never drop_all, the
    metadata carries an unresolvable FK cycle by design).
    """
    ensure_database()

    async def _create() -> None:
        from app.db.session import Base

        engine = create_async_engine(TEST_DB_URL)
        async with engine.begin() as conn:
            # Drop + recreate the schema so create_all rebuilds tables with
            # the CURRENT metadata shape (truncate alone would leave stale
            # columns from older runs — create_all never alters tables).
            await conn.exec_driver_sql("DROP SCHEMA public CASCADE")
            await conn.exec_driver_sql("CREATE SCHEMA public")
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn))
        await engine.dispose()

    asyncio.new_event_loop().run_until_complete(_create())


def make_module_schema_fixture():
    """Return a module-scoped autouse fixture that resets the schema once."""
    import pytest

    @pytest.fixture(scope="module", autouse=True)
    def _schema():
        reset_schema()
        yield

    return _schema


@pytest_asyncio.fixture
async def db():
    """Plain session on parthenon_test."""
    engine = create_async_engine(TEST_DB_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


async def create_two_tenants(db: AsyncSession):
    """Create two fully independent tenants (A and B) and return them."""
    from app.db.models.tenant import Tenant

    suffix = uuid.uuid4().hex[:6]
    tenant_a = Tenant(name=f"iso-a-{suffix}", slug=f"iso-a-{suffix}")
    tenant_b = Tenant(name=f"iso-b-{suffix}", slug=f"iso-b-{suffix}")
    db.add_all([tenant_a, tenant_b])
    await db.commit()
    await db.refresh(tenant_a)
    await db.refresh(tenant_b)
    return tenant_a, tenant_b


async def create_agent_type(db: AsyncSession, tenant_id, name: str):
    from app.db.models.agents import AgentInputType, AgentOutputType, AgentType

    agent_type = AgentType(
        tenant_id=tenant_id,
        name=name,
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.typed,
    )
    db.add(agent_type)
    await db.commit()
    await db.refresh(agent_type)
    return agent_type


async def create_agent_job(db: AsyncSession, tenant_id, agent_type_id):
    from app.db.models.agents import AgentJob, AgentJobStatus

    job = AgentJob(
        tenant_id=tenant_id,
        agent_type_id=agent_type_id,
        status=AgentJobStatus.completed,
        input_data={"prompt": "x"},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def count_null_tenant_rows(db: AsyncSession, table: str) -> int:
    return (
        await db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id IS NULL"))
    ).scalar()


async def seed_root_tenant(engine) -> None:
    """Provision the root tenant in the given engine's database.

    Needed by test modules that build their own in-memory SQLite engine
    and drive ``/api/v1/internal/*`` endpoints headerless: the fail-closed
    tenant dependency binds the ROOT tenant when multi-tenancy is off.
    """
    from sqlalchemy import select

    from app.db.models.tenant import Tenant

    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        existing = (
            await session.execute(select(Tenant).where(Tenant.is_system_tenant.is_(True)))
        ).scalar_one_or_none()
        if existing is None:
            session.add(Tenant(name="Root", slug="root", is_system_tenant=True))
            await session.commit()
