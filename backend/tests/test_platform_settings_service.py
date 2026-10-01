"""Unit tests for the platform settings service (Phase 1.9 / 9.1).

Covers:

- ``multi_tenancy_enabled`` defaults to FALSE on any database without
  the row (and even when the table is unreadable)
- seeding is idempotent and never overwrites an existing value
- cached reads + write-through invalidation
- switch writes are audited as security-relevant platform events
- the switch is the single gate read by middleware and features
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.models.platform_setting import PlatformSetting  # noqa: E402
from app.db.models.tenant_audit_event import (  # noqa: E402
    TenantAuditEvent,
    TenantAuditEventType,
)
from app.db.session import Base  # noqa: E402
from app.services.tenancy.platform_settings_service import (  # noqa: E402
    MULTI_TENANCY_ENABLED_KEY,
    PlatformSettingsService,
)


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
        await session.rollback()


@pytest.fixture
def service():
    """Fresh service instance per test (isolated cache)."""
    return PlatformSettingsService()


class TestDefaultOff:
    async def test_default_false_without_row(self, db, service):
        """The switch defaults to false on any DB without the row."""
        assert await service.is_multi_tenancy_enabled(db) is False

    async def test_error_reading_switch_fails_safe_to_false(self, db, service):
        """DB errors must fail safe to OFF (inert platform), never ON."""
        broken = AsyncMock(side_effect=RuntimeError("no table"))
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(db, "execute", broken)
            assert await service.is_multi_tenancy_enabled(db) is False

    async def test_raw_bool_and_dict_payloads_decode(self, db, service):
        assert await service.get_bool(db, "unknown-key", default=True) is True
        # A legacy raw-bool payload still decodes.
        db.add(PlatformSetting(key="legacy", value=True))
        await db.flush()
        assert await service.get_bool(db, "legacy") is True


class TestSeeding:
    async def test_seed_defaults_seeds_false(self, db, service):
        await service.seed_defaults(db)
        await db.commit()
        row = (
            await db.execute(
                select(PlatformSetting).where(PlatformSetting.key == MULTI_TENANCY_ENABLED_KEY)
            )
        ).scalar_one_or_none()
        assert row is not None
        assert row.value == {"enabled": False}

    async def test_seed_is_idempotent_and_never_overwrites(self, db, service):
        await service.set_setting(db, MULTI_TENANCY_ENABLED_KEY, True)
        await service.seed_defaults(db)  # must NOT reset to false
        assert await service.is_multi_tenancy_enabled(db) is True


class TestCachedReadWrite:
    async def test_set_then_read_true(self, db, service):
        await service.set_setting(db, MULTI_TENANCY_ENABLED_KEY, True)
        assert await service.is_multi_tenancy_enabled(db) is True

    async def test_write_through_invalidates_cache(self, db, service):
        await service.set_setting(db, MULTI_TENANCY_ENABLED_KEY, True)
        assert await service.is_multi_tenancy_enabled(db) is True
        await service.set_setting(db, MULTI_TENANCY_ENABLED_KEY, False)
        assert await service.is_multi_tenancy_enabled(db) is False

    async def test_cache_serves_within_ttl_without_db(self, db, service):
        await service.set_setting(db, MULTI_TENANCY_ENABLED_KEY, True)
        # Populate the cache first (the write itself invalidates it).
        assert await service.is_multi_tenancy_enabled(db) is True
        # Sabotage the DB read: the cached value must still serve.
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                db, "execute", AsyncMock(side_effect=RuntimeError("down"))
            )
            assert await service.is_multi_tenancy_enabled(db) is True

    async def test_invalidate_forces_db_reread(self, db, service):
        await service.set_setting(db, MULTI_TENANCY_ENABLED_KEY, True)
        service.invalidate()
        assert await service.is_multi_tenancy_enabled(db) is True


class TestAudit:
    async def test_switch_write_audited_security_relevant(self, db, service):
        await service.set_setting(db, MULTI_TENANCY_ENABLED_KEY, True)
        result = await db.execute(
            select(TenantAuditEvent).where(
                TenantAuditEvent.event_type == TenantAuditEventType.platform_setting_updated
            )
        )
        events = result.scalars().all()
        assert len(events) == 1
        assert events[0].is_security_relevant is True
        assert events[0].detail["new"] == {"enabled": True}
        assert events[0].detail["previous"] is None

    async def test_non_switch_setting_not_security_relevant(self, db, service):
        await service.set_setting(db, "some_other_setting", {"value": 1})
        result = await db.execute(select(TenantAuditEvent))
        events = result.scalars().all()
        assert len(events) == 1
        assert events[0].is_security_relevant is False
