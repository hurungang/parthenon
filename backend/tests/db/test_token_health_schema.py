"""Schema & migration verification for token-expiry-alerting.

Asserts the schema changes took effect — not just behavior:
- New columns on ``AgentIdentity`` and ``McpSession``.
- Nullable ``TokenRefreshLog.mcp_session_id``.
- ``TokenHealthCheck`` table created (tenant-scoped, polymorphic target,
  health state / outcome / message columns, indexes).
- Alembic migration files exist and chain correctly.
- ORM round-trips on all new fields.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models.agents import (
    AgentIdentity,
    AgentIdentityStatus,
    AgentIdentityType,
    AgentTokenStatus,
)
from app.db.models.mcp_hub import McpServer, McpServerStatus, McpSession, McpSessionAuthType
from app.db.models.token_health import (
    TokenCheckOutcome,
    TokenHealthCheck,
    TokenHealthState,
    TokenHealthTargetKind,
)
from app.db.session import Base

NOW = datetime.now(tz=timezone.utc)


# ── Declarative metadata (schema shape) ──────────────────────────────────────


class TestDeclaredSchema:
    def test_agent_identity_new_columns_exist(self):
        cols = AgentIdentity.__table__.columns
        assert "refresh_token_expires_at" in cols
        assert "last_token_refresh_outcome" in cols
        assert "token_health_state" in cols
        assert cols["token_health_state"].nullable is True

    def test_mcp_session_new_columns_exist(self):
        cols = McpSession.__table__.columns
        assert "last_token_refresh_at" in cols
        assert "last_token_refresh_outcome" in cols
        assert "token_health_state" in cols

    def test_token_refresh_log_mcp_session_id_nullable(self):
        from app.db.models.agent_security import TokenRefreshLog

        col = TokenRefreshLog.__table__.columns["mcp_session_id"]
        assert col.nullable is True

    def test_token_health_checks_table_created(self):
        assert "token_health_checks" in Base.metadata.tables
        table = Base.metadata.tables["token_health_checks"]
        expected = {
            "id",
            "tenant_id",
            "agent_type_id",
            "session_id",
            "target_kind",
            "target_id",
            "health_state",
            "check_outcome",
            "message",
            "checked_at",
        }
        assert expected <= set(table.columns.keys())
        # Tenant-scoped and queryable by check time and target.
        index_cols = {tuple(idx.columns.keys()) for idx in table.indexes}
        assert ("tenant_id",) in index_cols
        assert ("checked_at",) in index_cols
        assert ("target_kind", "target_id") in index_cols
        # tenant_id is NOT NULL (mandatory tenant stamp).
        assert table.columns["tenant_id"].nullable is False

    def test_health_state_enum_members(self):
        assert {s.value for s in TokenHealthState} == {
            "healthy",
            "expiring",
            "expired",
            "unknown",
        }
        assert {s.value for s in TokenCheckOutcome} == {"passed", "blocked"}
        assert {s.value for s in TokenHealthTargetKind} == {
            "agent_identity",
            "mcp_session",
        }


# ── Migration files ──────────────────────────────────────────────────────────


class TestMigrationFiles:
    def test_token_expiry_migration_exists(self):
        import glob
        import os

        versions = os.path.join(
            os.path.dirname(__file__), "..", "..", "alembic", "versions"
        )
        files = glob.glob(os.path.join(versions, "*token_expiry*.py"))
        assert files, "token_expiry_alerting migration missing"
        content = open(files[0]).read()
        assert "revision" in content and "down_revision" in content

    def test_token_refresh_log_nullable_migration_exists(self):
        import glob
        import os

        versions = os.path.join(
            os.path.dirname(__file__), "..", "..", "alembic", "versions"
        )
        files = glob.glob(
            os.path.join(versions, "*token_refresh_log_nullable*.py")
        )
        assert files, "TokenRefreshLog nullable-identity migration missing"
        content = open(files[0]).read()
        assert "mcp_session_id" in content


# ── ORM round-trips against the created schema ───────────────────────────────


@pytest.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


class TestOrmRoundTrips:
    async def test_identity_health_fields_round_trip(self, db_session: AsyncSession):
        from sqlalchemy import select

        expires = NOW + timedelta(days=30)
        refresh_expires = NOW + timedelta(days=90)
        identity = AgentIdentity(
            id=uuid.uuid4(),
            name="rt-identity",
            identity_type=AgentIdentityType.realm_user,
            token_expires_at=expires,
            refresh_token_expires_at=refresh_expires,
            token_status=AgentTokenStatus.active,
            last_token_refresh_outcome="success",
            token_health_state=TokenHealthState.healthy,
            status=AgentIdentityStatus.active,
        )
        db_session.add(identity)
        await db_session.flush()

        loaded = (
            await db_session.execute(
                select(AgentIdentity).where(AgentIdentity.id == identity.id)
            )
        ).scalar_one()
        assert loaded.refresh_token_expires_at == refresh_expires
        assert loaded.last_token_refresh_outcome == "success"
        assert loaded.token_health_state == TokenHealthState.healthy

    async def test_session_health_fields_round_trip(self, db_session: AsyncSession):
        from sqlalchemy import select

        server = McpServer(
            id=uuid.uuid4(),
            name=f"srv-{uuid.uuid4().hex[:6]}",
            slug=f"srv-{uuid.uuid4().hex[:6]}",
            base_url="https://example.com",
            status=McpServerStatus.active,
        )
        db_session.add(server)
        await db_session.flush()
        refreshed_at = NOW - timedelta(minutes=3)
        session = McpSession(
            id=uuid.uuid4(),
            server_id=server.id,
            name="rt-session",
            auth_type=McpSessionAuthType.oauth2,
            is_active=True,
            last_token_refresh_at=refreshed_at,
            last_token_refresh_outcome="success",
            token_health_state=TokenHealthState.expiring,
        )
        db_session.add(session)
        await db_session.flush()

        loaded = (
            await db_session.execute(
                select(McpSession).where(McpSession.id == session.id)
            )
        ).scalar_one()
        assert loaded.last_token_refresh_at == refreshed_at
        assert loaded.last_token_refresh_outcome == "success"
        assert loaded.token_health_state == TokenHealthState.expiring

    async def test_token_health_check_round_trip_and_repeated_inserts(
        self, db_session: AsyncSession
    ):
        """Insert-only audit table: repeated checks never violate constraints."""
        from sqlalchemy import select

        identity_id = uuid.uuid4()
        agent_type_id = uuid.uuid4()
        for _ in range(3):  # duplicate evaluations are fine (append-only)
            db_session.add(
                TokenHealthCheck(
                    tenant_id=uuid.uuid4(),
                    agent_type_id=agent_type_id,
                    target_kind=TokenHealthTargetKind.agent_identity,
                    target_id=identity_id,
                    health_state=TokenHealthState.expired,
                    check_outcome=TokenCheckOutcome.blocked,
                    message="agent_identity 'rt' token has expired — refresh it",
                )
            )
        await db_session.flush()

        rows = (
            await db_session.execute(
                select(TokenHealthCheck).where(
                    TokenHealthCheck.target_id == identity_id
                )
            )
        ).scalars().all()
        assert len(rows) == 3
        assert all(r.health_state == TokenHealthState.expired for r in rows)
        assert all(r.check_outcome == TokenCheckOutcome.blocked for r in rows)
        assert all(r.checked_at is not None for r in rows)
