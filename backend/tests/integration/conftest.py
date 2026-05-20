"""Integration-test conftest.

Provides a StaticPool-based engine so ``db_session`` and ``async_client``
fixtures share the **same** SQLite in-memory connection.  Without this,
SQLAlchemy's default QueuePool creates separate connections, each with their
own in-memory database, so deletes in ``db_session`` are invisible to the
``async_client``'s requests.

SQLite + UUID compatibility notes
----------------------------------
The production models use ``sqlalchemy.dialects.postgresql.UUID(as_uuid=True)``.
In SQLite, SQLAlchemy generates the DDL column type as ``UUID`` (not ``CHAR(32)``),
which gives the column NUMERIC affinity (SQLite's affinity rules: unrecognised type
names → NUMERIC).  NUMERIC affinity means SQLite coerces strings that look like
decimal integers to INTEGER storage — so the hex value
``'00000000000000000000000000000001'`` is stored as the integer ``1``.

Two patches are applied at module-import time (before any test runs):

1. ``use_insertmanyvalues=False`` on the engine — avoids the SQLAlchemy
   insertmanyvalues batch path that uses the SQLite rowid (int) as a sentinel
   and passes it to the UUID type's result processor (Python 3.13 regression).

2. ``_PG_UUID.result_processor`` monkey-patch — makes the UUID result processor
   tolerate integer values returned by SQLite for NUMERIC-affinity UUID columns
   by converting them via ``uuid.UUID(int=value)``.  The round-trip is lossless:
   ``uuid.UUID(int=1)`` == ``uuid.UUID('00000000-0000-0000-0000-000000000001')``.
"""
from __future__ import annotations

import uuid as _uuid_module
from typing import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import UUID as _PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.main import create_app

_INTEGRATION_URL = "sqlite+aiosqlite:///:memory:"

# ── Patch 2: UUID result-processor tolerates integers from SQLite ─────────────

_orig_pg_uuid_result_processor = _PG_UUID.result_processor


def _sqlite_tolerant_uuid_result_processor(self, dialect, coltype):  # type: ignore[override]
    """Wrap the default result processor to accept int values from SQLite.

    SQLite stores UUID hex strings with NUMERIC affinity as integers when the
    hex string is a well-formed decimal literal (e.g. '00000000...0001' → 1).
    ``uuid.UUID(int=value)`` correctly reconstructs the original UUID.
    """
    orig_proc = _orig_pg_uuid_result_processor(self, dialect, coltype)
    if dialect.name != "sqlite" or orig_proc is None:
        return orig_proc

    def proc(value: object) -> "_uuid_module.UUID | None":
        if value is None:
            return None
        if isinstance(value, int):
            return _uuid_module.UUID(int=value)
        return orig_proc(value)  # type: ignore[arg-type]

    return proc


_PG_UUID.result_processor = _sqlite_tolerant_uuid_result_processor  # type: ignore[method-assign]


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Session-scoped StaticPool engine — single shared in-memory connection."""
    engine = create_async_engine(
        _INTEGRATION_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        # Disable insertmanyvalues to avoid SQLite+UUID+Python 3.13 incompatibility:
        # SQLAlchemy's insertmanyvalues batch optimization uses rowid (int) as a sentinel
        # which it then passes to the UUID type processor — uuid.UUID(int_value) fails
        # in Python 3.13 because the first positional arg is 'hex' (expects str).
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
    """Function-scoped DB session bound to the shared StaticPool engine."""
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


@pytest_asyncio.fixture
async def async_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client whose DB sessions share the StaticPool engine."""
    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
