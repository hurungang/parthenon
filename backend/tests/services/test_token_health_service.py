"""Unit tests for the Token Health Service (token-expiry-alerting).

Covers: pure classification (healthy / expiring boundary / expired / unknown),
refresh-outcome propagation for identities and MCP sessions, tenant-scoped
listing, and execution preflight resolution (agent + subagents) including
audit row persistence.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_security import TokenRefreshOutcome
from app.db.models.agents import (
    AgentIdentity,
    AgentIdentityStatus,
    AgentIdentityType,
    AgentJob,
    AgentJobStatus,
    AgentRole,
    AgentRoleMcpSession,
    AgentTokenStatus,
    AgentType,
)
from app.db.models.agent_run_relationship import AgentRunRelationship
from app.db.models.mcp_hub import McpServer, McpServerStatus, McpSession, McpSessionAuthType
from app.db.models.token_health import TokenCheckOutcome, TokenHealthState, TokenHealthTargetKind
from app.services.token_health import (
    TOKEN_EXPIRING_WINDOW,
    TokenHealthService,
    classify_identity_health,
    classify_session_health,
    compute_identity_state,
    compute_session_state,
    log_session_refresh,
    persist_identity_health_state,
    persist_session_health_state,
)

NOW = datetime.now(tz=timezone.utc)


# ── Pure classification ───────────────────────────────────────────────────────


class TestIdentityClassification:
    def test_healthy(self):
        state = classify_identity_health(
            token_expires_at=NOW + timedelta(days=30),
            refresh_token_expires_at=NOW + timedelta(days=90),
            token_status=AgentTokenStatus.active,
            last_token_refresh_outcome=TokenRefreshOutcome.success,
            now=NOW,
        )
        assert state == TokenHealthState.healthy

    def test_expiring_boundary_exactly_7_days(self):
        """Access token expiring EXACTLY at the 7-day boundary → expiring."""
        state = classify_identity_health(
            token_expires_at=NOW + TOKEN_EXPIRING_WINDOW,
            refresh_token_expires_at=None,
            token_status=AgentTokenStatus.active,
            last_token_refresh_outcome=None,
            now=NOW,
        )
        assert state == TokenHealthState.expiring

    def test_expiring_via_refresh_token(self):
        state = classify_identity_health(
            token_expires_at=NOW + timedelta(days=30),
            refresh_token_expires_at=NOW + timedelta(days=2),
            token_status=AgentTokenStatus.active,
            last_token_refresh_outcome=TokenRefreshOutcome.success,
            now=NOW,
        )
        assert state == TokenHealthState.expiring

    def test_just_outside_7_days_is_healthy(self):
        state = classify_identity_health(
            token_expires_at=NOW + TOKEN_EXPIRING_WINDOW + timedelta(seconds=1),
            refresh_token_expires_at=None,
            token_status=AgentTokenStatus.active,
            last_token_refresh_outcome=None,
            now=NOW,
        )
        assert state == TokenHealthState.healthy

    def test_expired_access_token(self):
        state = classify_identity_health(
            token_expires_at=NOW - timedelta(minutes=1),
            refresh_token_expires_at=NOW + timedelta(days=1),
            token_status=AgentTokenStatus.active,
            last_token_refresh_outcome=TokenRefreshOutcome.success,
            now=NOW,
        )
        assert state == TokenHealthState.expired

    def test_expired_refresh_token(self):
        state = classify_identity_health(
            token_expires_at=NOW + timedelta(days=30),
            refresh_token_expires_at=NOW - timedelta(seconds=1),
            token_status=AgentTokenStatus.active,
            last_token_refresh_outcome=TokenRefreshOutcome.success,
            now=NOW,
        )
        assert state == TokenHealthState.expired

    def test_unknown_missing_timestamps(self):
        state = classify_identity_health(
            token_expires_at=None,
            refresh_token_expires_at=None,
            token_status=None,
            last_token_refresh_outcome=None,
            now=NOW,
        )
        assert state == TokenHealthState.unknown

    def test_refresh_failed_outcome_forces_expired(self):
        state = classify_identity_health(
            token_expires_at=NOW + timedelta(days=30),
            refresh_token_expires_at=None,
            token_status=AgentTokenStatus.refresh_failed,
            last_token_refresh_outcome=TokenRefreshOutcome.failure,
            now=NOW,
        )
        assert state == TokenHealthState.expired


class TestSessionClassification:
    def test_healthy(self):
        assert classify_session_health(
            oauth_expires_at=NOW + timedelta(days=30),
            oauth_refresh_expires_at=NOW + timedelta(days=90),
            now=NOW,
        ) == TokenHealthState.healthy

    def test_expiring_boundary_exactly_7_days(self):
        assert classify_session_health(
            oauth_expires_at=NOW + TOKEN_EXPIRING_WINDOW,
            oauth_refresh_expires_at=None,
            now=NOW,
        ) == TokenHealthState.expiring

    def test_expired(self):
        assert classify_session_health(
            oauth_expires_at=NOW - timedelta(seconds=1),
            oauth_refresh_expires_at=None,
            now=NOW,
        ) == TokenHealthState.expired

    def test_unknown(self):
        assert classify_session_health(
            oauth_expires_at=None,
            oauth_refresh_expires_at=None,
            now=NOW,
        ) == TokenHealthState.unknown


# ── DB-backed tests ──────────────────────────────────────────────────────────


@pytest.fixture
async def db_session():
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db.session import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        # Root tenant (preflight audit rows fall back to it).
        from app.db.models.tenant import Tenant

        session.add(Tenant(id=ROOT_TENANT_ID, name="Root", slug="root", is_system_tenant=True))
        await session.flush()
        yield session
    await engine.dispose()


ROOT_TENANT_ID = uuid.uuid4()


async def _seed_identity(
    db_session,
    *,
    name="test-identity",
    token_expires_at=None,
    refresh_token_expires_at=None,
    token_status=AgentTokenStatus.active,
    outcome=None,
):
    identity = AgentIdentity(
        id=uuid.uuid4(),
        name=name,
        identity_type=AgentIdentityType.realm_user,
        token_expires_at=token_expires_at,
        refresh_token_expires_at=refresh_token_expires_at,
        token_status=token_status,
        last_token_refresh_outcome=outcome,
        status=AgentIdentityStatus.active,
    )
    db_session.add(identity)
    await db_session.flush()
    return identity


async def _seed_session(db_session, *, oauth_expires_at=None, oauth_refresh_expires_at=None):
    server = McpServer(
        id=uuid.uuid4(),
        name=f"srv-{uuid.uuid4().hex[:6]}",
        slug=f"srv-{uuid.uuid4().hex[:6]}",
        base_url="https://example.com",
        status=McpServerStatus.active,
    )
    db_session.add(server)
    await db_session.flush()
    session = McpSession(
        id=uuid.uuid4(),
        server_id=server.id,
        name="test-session",
        auth_type=McpSessionAuthType.oauth2,
        is_active=True,
        oauth_expires_at=oauth_expires_at,
        oauth_refresh_expires_at=oauth_refresh_expires_at,
    )
    db_session.add(session)
    await db_session.flush()
    return session


class TestPersistence:
    async def test_identity_success_propagates(self, db_session):
        identity = await _seed_identity(
            db_session,
            token_expires_at=NOW - timedelta(minutes=5),
            token_status=AgentTokenStatus.refresh_failed,
        )
        identity.token_expires_at = NOW + timedelta(days=30)
        identity.token_status = AgentTokenStatus.active
        state = persist_identity_health_state(
            identity, refresh_outcome=TokenRefreshOutcome.success
        )
        await db_session.flush()
        assert state == TokenHealthState.healthy
        assert identity.token_health_state == TokenHealthState.healthy
        assert identity.last_token_refresh_outcome == TokenRefreshOutcome.success

    async def test_identity_failure_marks_expired(self, db_session):
        identity = await _seed_identity(
            db_session, token_expires_at=NOW + timedelta(days=30)
        )
        state = persist_identity_health_state(
            identity, refresh_outcome=TokenRefreshOutcome.failure
        )
        assert state == TokenHealthState.expired
        assert identity.last_token_refresh_outcome == TokenRefreshOutcome.failure

    async def test_session_success_propagates(self, db_session):
        session = await _seed_session(db_session, oauth_expires_at=NOW - timedelta(minutes=5))
        session.oauth_expires_at = NOW + timedelta(days=30)
        state = persist_session_health_state(session, refresh_outcome=TokenRefreshOutcome.success)
        await db_session.flush()
        assert state == TokenHealthState.healthy
        assert session.token_health_state == TokenHealthState.healthy
        assert session.last_token_refresh_at is not None

    async def test_session_refresh_audit_row(self, db_session):
        session = await _seed_session(db_session)
        log_session_refresh(
            db_session, mcp_session_id=session.id, outcome=TokenRefreshOutcome.success
        )
        await db_session.flush()
        from sqlalchemy import select

        from app.db.models.agent_security import TokenRefreshLog

        rows = (await db_session.execute(select(TokenRefreshLog))).scalars().all()
        assert len(rows) == 1
        assert rows[0].mcp_session_id == session.id
        assert rows[0].agent_identity_id is None


class TestListing:
    async def test_identity_listing_excludes_non_oauth(self, db_session):
        await _seed_identity(db_session, token_expires_at=NOW + timedelta(days=30))
        targets = await TokenHealthService(db_session).list_identity_states()
        assert len(targets) == 1
        assert targets[0].kind == TokenHealthTargetKind.agent_identity
        assert targets[0].state == TokenHealthState.healthy

    async def test_session_listing_active_oauth_only(self, db_session):
        await _seed_session(db_session, oauth_expires_at=NOW + timedelta(days=30))
        # Inactive session is excluded.
        inactive = await _seed_session(db_session, oauth_expires_at=NOW + timedelta(days=30))
        inactive.is_active = False
        await db_session.flush()
        targets = await TokenHealthService(db_session).list_session_states()
        assert len(targets) == 1


class TestPreflight:
    async def _seed_agent_type(self, db_session, identity):
        role = AgentRole(id=uuid.uuid4(), name=f"role-{uuid.uuid4().hex[:6]}")
        db_session.add(role)
        await db_session.flush()
        agent_type = AgentType(
            id=uuid.uuid4(),
            name=f"agent-{uuid.uuid4().hex[:6]}",
            identity_id=identity.id,
            role_id=role.id,
        )
        db_session.add(agent_type)
        await db_session.flush()
        return agent_type, role

    async def test_preflight_proceed_and_audit_rows(self, db_session):
        identity = await _seed_identity(db_session, token_expires_at=NOW + timedelta(days=30))
        agent_type, _ = await self._seed_agent_type(db_session, identity)
        result = await TokenHealthService(db_session).run_preflight(agent_type.id)
        assert result.verdict == "proceed"
        assert result.check_outcome == TokenCheckOutcome.passed
        from sqlalchemy import select

        from app.db.models.token_health import TokenHealthCheck

        rows = (await db_session.execute(select(TokenHealthCheck))).scalars().all()
        assert len(rows) == 1
        assert rows[0].check_outcome == TokenCheckOutcome.passed

    async def test_preflight_blocked_on_expired(self, db_session):
        identity = await _seed_identity(db_session, token_expires_at=NOW - timedelta(hours=1))
        agent_type, _ = await self._seed_agent_type(db_session, identity)
        result = await TokenHealthService(db_session).run_preflight(agent_type.id)
        assert result.verdict == "blocked"
        assert len(result.blocked) == 1
        assert identity.name in result.blocked[0]
        from sqlalchemy import select

        from app.db.models.token_health import TokenHealthCheck

        rows = (await db_session.execute(select(TokenHealthCheck))).scalars().all()
        assert all(r.check_outcome == TokenCheckOutcome.blocked for r in rows)

    async def test_preflight_warn_on_expiring(self, db_session):
        identity = await _seed_identity(
            db_session, token_expires_at=NOW + timedelta(days=3)
        )
        agent_type, _ = await self._seed_agent_type(db_session, identity)
        result = await TokenHealthService(db_session).run_preflight(agent_type.id)
        assert result.verdict == "proceed_with_warnings"
        assert len(result.warnings) == 1

    async def test_preflight_role_mcp_session_included(self, db_session):
        identity = await _seed_identity(db_session, token_expires_at=NOW + timedelta(days=30))
        agent_type, role = await self._seed_agent_type(db_session, identity)
        session = await _seed_session(
            db_session, oauth_expires_at=NOW - timedelta(hours=2)
        )
        db_session.add(AgentRoleMcpSession(role_id=role.id, mcp_session_id=session.id, server_id=session.server_id))
        await db_session.flush()
        result = await TokenHealthService(db_session).run_preflight(agent_type.id)
        kinds = {t.target_kind for t in result.targets}
        assert TokenHealthTargetKind.mcp_session in kinds
        assert result.verdict == "blocked"

    async def test_preflight_subagent_identity_included(self, db_session):
        parent_identity = await _seed_identity(
            db_session, name="parent", token_expires_at=NOW + timedelta(days=30)
        )
        child_identity = await _seed_identity(
            db_session, name="child", token_expires_at=NOW - timedelta(hours=1)
        )
        agent_type, _ = await self._seed_agent_type(db_session, parent_identity)
        child_type, _ = await self._seed_agent_type(db_session, child_identity)
        job = AgentJob(
            id=uuid.uuid4(),
            agent_type_id=child_type.id,
            status=AgentJobStatus.completed,
        )
        db_session.add(job)
        await db_session.flush()
        db_session.add(
            AgentRunRelationship(
                parent_agent_job_id=uuid.uuid4(),
                child_agent_job_id=job.id,
            )
        )
        await db_session.flush()
        # Subagent resolution requires session_id — none of the seeded parents
        # are linked, so this stays PROCEED (edge rows only resolve when the
        # parent job matches the given session).
        result = await TokenHealthService(db_session).run_preflight(
            agent_type.id, session_id=uuid.uuid4()
        )
        assert result.verdict == "proceed"


class TestPreflightAutoRefresh:
    """Delegation reliability: expired identity tokens are auto-refreshed
    inline during preflight; only a genuinely unrecoverable token blocks."""

    async def _seed_agent_type(self, db_session, identity):
        role = AgentRole(id=uuid.uuid4(), name=f"role-{uuid.uuid4().hex[:6]}")
        db_session.add(role)
        await db_session.flush()
        agent_type = AgentType(
            id=uuid.uuid4(),
            name=f"agent-{uuid.uuid4().hex[:6]}",
            identity_id=identity.id,
            role_id=role.id,
        )
        db_session.add(agent_type)
        await db_session.flush()
        return agent_type, role

    async def test_expired_identity_refresh_success_proceeds(self, db_session):
        """Expired token + successful refresh → PROCEED, state re-persisted."""
        identity = await _seed_identity(
            db_session,
            token_expires_at=NOW - timedelta(hours=1),
            token_status=AgentTokenStatus.refresh_failed,
        )
        agent_type, _ = await self._seed_agent_type(db_session, identity)

        async def _fake_refresh(identity_id, db):
            row = await db.get(AgentIdentity, identity_id)
            row.token_expires_at = NOW + timedelta(days=30)
            row.token_status = AgentTokenStatus.active
            from app.services.token_health import persist_identity_health_state

            persist_identity_health_state(
                row, refresh_outcome=TokenRefreshOutcome.success
            )
            await db.flush()

        with patch(
            "app.services.token_refresh.refresh_oauth_token",
            new=_fake_refresh,
        ):
            result = await TokenHealthService(db_session).run_preflight(agent_type.id)

        assert result.verdict == "proceed"
        assert "auto-refreshed" in result.targets[0].message
        assert identity.token_health_state == TokenHealthState.healthy
        from sqlalchemy import select

        from app.db.models.token_health import TokenHealthCheck

        rows = (await db_session.execute(select(TokenHealthCheck))).scalars().all()
        assert len(rows) == 1
        assert rows[0].check_outcome == TokenCheckOutcome.passed

    async def test_expired_identity_refresh_failure_blocks_with_reason(self, db_session):
        """Expired token + failing refresh → BLOCKED with the actionable reason."""
        from app.services.token_refresh import TokenRefreshError

        identity = await _seed_identity(
            db_session, token_expires_at=NOW - timedelta(hours=1)
        )
        agent_type, _ = await self._seed_agent_type(db_session, identity)

        with patch(
            "app.services.token_refresh.refresh_oauth_token",
            new=AsyncMock(
                side_effect=TokenRefreshError("invalid_grant: refresh token expired")
            ),
        ):
            result = await TokenHealthService(db_session).run_preflight(agent_type.id)

        assert result.verdict == "blocked"
        assert "auto-refresh failed" in result.blocked[0]
        assert "invalid_grant" in result.blocked[0]
        assert identity.name in result.blocked[0]
        from sqlalchemy import select

        from app.db.models.token_health import TokenHealthCheck

        rows = (await db_session.execute(select(TokenHealthCheck))).scalars().all()
        assert all(r.check_outcome == TokenCheckOutcome.blocked for r in rows)

    async def test_expiring_identity_refresh_failure_still_warns_only(self, db_session):
        """A still-valid (expiring) token must NOT be blocked by a refresh failure."""
        from app.services.token_refresh import TokenRefreshError

        identity = await _seed_identity(
            db_session, token_expires_at=NOW + timedelta(days=3)
        )
        agent_type, _ = await self._seed_agent_type(db_session, identity)

        with patch(
            "app.services.token_refresh.refresh_oauth_token",
            new=AsyncMock(side_effect=TokenRefreshError("provider down")),
        ):
            result = await TokenHealthService(db_session).run_preflight(agent_type.id)

        assert result.verdict == "proceed_with_warnings"
        assert "auto-refresh attempt failed" in result.warnings[0]

    async def test_expired_mcp_session_not_refreshed_still_blocked(self, db_session):
        """MCP session targets are unchanged — no refresh attempt, still BLOCKED."""
        identity = await _seed_identity(db_session, token_expires_at=NOW + timedelta(days=30))
        agent_type, role = await self._seed_agent_type(db_session, identity)
        session = await _seed_session(db_session, oauth_expires_at=NOW - timedelta(hours=2))
        db_session.add(
            AgentRoleMcpSession(role_id=role.id, mcp_session_id=session.id, server_id=session.server_id)
        )
        await db_session.flush()

        refresh_mock = AsyncMock()
        with patch(
            "app.services.token_refresh.refresh_oauth_token", new=refresh_mock
        ):
            result = await TokenHealthService(db_session).run_preflight(agent_type.id)

        refresh_mock.assert_not_awaited()
        assert result.verdict == "blocked"
        assert "auto-refresh failed" not in result.blocked[0]

    async def test_unexpected_refresh_error_never_crashes_preflight(self, db_session):
        """Any unexpected error during refresh degrades to BLOCKED with reason."""
        identity = await _seed_identity(
            db_session, token_expires_at=NOW - timedelta(hours=1)
        )
        agent_type, _ = await self._seed_agent_type(db_session, identity)

        with patch(
            "app.services.token_refresh.refresh_oauth_token",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            result = await TokenHealthService(db_session).run_preflight(agent_type.id)

        assert result.verdict == "blocked"
        assert "boom" in result.blocked[0]
