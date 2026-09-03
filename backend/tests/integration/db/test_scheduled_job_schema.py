"""Integration tests: ``scheduled_jobs.scheduled_by_user_id`` schema verification.

The agent-runtime-monitor change adds a nullable ``scheduled_by_user_id`` UUID
column (FK → ``identities.id``, ``ondelete=SET NULL``) to ``ScheduledJob`` to
anchor trigger provenance for schedule-triggered agents.

These tests verify the column is present, nullable, a UUID, carries the FK to
``identities``, and that a schedule persists both with and without the value
(existing/legacy rows retain ``NULL``).

Uses a module-scoped StaticPool in-memory SQLite mirroring
``test_runtime_topology_api.py`` (the schema is defined by the SQLAlchemy
declarative model, so ``Base.metadata.create_all`` produces the new column).
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.models.identity import Identity  # noqa: E402
from app.db.models.scheduling import JobTargetType, ScheduledJob  # noqa: E402
from app.db.session import Base  # noqa: E402
from sqlalchemy.dialects.postgresql import UUID as _PG_UUID  # noqa: E402

_INTEGRATION_URL = "sqlite+aiosqlite:///:memory:"
_orig_pg_uuid_result_processor = _PG_UUID.result_processor


def _sqlite_tolerant_uuid_result_processor(self, dialect, coltype):
    orig_proc = _orig_pg_uuid_result_processor(self, dialect, coltype)
    if dialect.name != "sqlite" or orig_proc is None:
        return orig_proc

    def proc(value: object) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, int):
            return uuid.UUID(int=value)
        return orig_proc(value)

    return proc


_PG_UUID.result_processor = _sqlite_tolerant_uuid_result_processor


@pytest_asyncio.fixture(scope="module")
async def test_engine():
    engine = create_async_engine(
        _INTEGRATION_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        use_insertmanyvalues=False,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with SessionLocal() as session:
        yield session
        await session.rollback()


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scheduled_by_user_id_column_exists(test_engine):
    """The ``scheduled_by_user_id`` column exists on ``scheduled_jobs``."""
    async with test_engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {
                col["name"] for col in inspect(sync_conn).get_columns("scheduled_jobs")
            }
        )
    assert "scheduled_by_user_id" in columns


@pytest.mark.asyncio
async def test_scheduled_by_user_id_is_nullable(test_engine):
    """The column is nullable (legacy rows can retain ``NULL``)."""
    async with test_engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: {
                col["name"]: col["nullable"]
                for col in inspect(sync_conn).get_columns("scheduled_jobs")
            }
        )
    assert columns["scheduled_by_user_id"] is True


@pytest.mark.asyncio
async def test_scheduled_by_user_id_is_uuid():
    """The ORM-declared column type is a UUID (PostgreSQL ``UUID`` type)."""
    col = ScheduledJob.__table__.c.scheduled_by_user_id
    assert col.type.__class__.__name__ == "UUID"
    assert getattr(col.type, "as_uuid", False) is True


@pytest.mark.asyncio
async def test_scheduled_by_user_id_fk_to_identities(test_engine):
    """The column carries a foreign key to ``identities.id``."""
    async with test_engine.connect() as conn:
        fks = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_foreign_keys("scheduled_jobs")
        )
    target_fks = [
        fk
        for fk in fks
        if fk.get("constrained_columns") == ["scheduled_by_user_id"]
    ]
    assert target_fks, "no FK constraint on scheduled_by_user_id"
    assert target_fks[0]["referred_table"] == "identities"
    assert target_fks[0]["referred_columns"] == ["id"]


@pytest.mark.asyncio
async def test_schedule_persists_with_scheduled_by_user_id(db_session):
    """A schedule created with a scheduled-by user persists and round-trips."""
    ident = Identity(
        id=uuid.uuid4(),
        subject=f"sched-by-user-{uuid.uuid4().hex}",
        display_name="Schedule Owner",
    )
    db_session.add(ident)
    await db_session.flush()

    target_id = uuid.uuid4()
    job = ScheduledJob(
        id=uuid.uuid4(),
        name=f"sched-{uuid.uuid4().hex}",
        cron_expression="0 9 * * *",
        target_type=JobTargetType.agent,
        target_id=target_id,
        scheduled_by_user_id=ident.id,
    )
    db_session.add(job)
    await db_session.commit()

    from sqlalchemy import select

    result = await db_session.execute(select(ScheduledJob).where(ScheduledJob.id == job.id))
    loaded = result.scalar_one()
    assert loaded.scheduled_by_user_id == ident.id


@pytest.mark.asyncio
async def test_schedule_persists_with_null_scheduled_by_user_id(db_session):
    """A legacy schedule without a scheduled-by user persists with ``NULL``
    (no backfill errors, no data loss)."""
    job = ScheduledJob(
        id=uuid.uuid4(),
        name=f"sched-legacy-{uuid.uuid4().hex}",
        cron_expression="0 9 * * *",
        target_type=JobTargetType.agent,
        target_id=uuid.uuid4(),
        scheduled_by_user_id=None,
    )
    db_session.add(job)
    await db_session.commit()

    from sqlalchemy import select

    result = await db_session.execute(select(ScheduledJob).where(ScheduledJob.id == job.id))
    loaded = result.scalar_one()
    assert loaded.scheduled_by_user_id is None
