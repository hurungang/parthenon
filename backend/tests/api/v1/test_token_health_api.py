"""API tests for the token-expiry-alerting endpoints.

Covers GET /api/v1/dashboard/token-health (counts, itemized details,
permission flags) and POST /api/v1/internal/token-health/preflight
(PROCEED/WARN/BLOCKED + fail-closed 401 without signed tenant headers).
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_internal_tenant_context
from app.db.models.agents import (
    AgentIdentity,
    AgentIdentityStatus,
    AgentIdentityType,
    AgentTokenStatus,
    AgentType,
)
from app.db.models.mcp_hub import McpServer, McpServerStatus, McpSession, McpSessionAuthType
from app.db.models.platform_user import PlatformUser
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware

NOW = datetime.now(tz=timezone.utc)


def _bypass_auth():
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-api-user", "roles": ["admin"]}
        request.state.is_super_admin = False
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


@pytest_asyncio.fixture
async def api_client(test_engine):
    app = create_app()
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _seed_user(db: AsyncSession):
    result = await db.execute(
        __import__("sqlalchemy").select(PlatformUser).where(PlatformUser.sub == "test-api-user")
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = PlatformUser(sub="test-api-user", email="test@example.com", display_name="Test User")
        db.add(user)
        await db.flush()
    return user


async def _seed_expired_identity(db: AsyncSession, name="expired-identity"):
    identity = AgentIdentity(
        id=uuid.uuid4(),
        name=name,
        identity_type=AgentIdentityType.realm_user,
        token_expires_at=NOW - timedelta(hours=1),
        token_status=AgentTokenStatus.active,
        status=AgentIdentityStatus.active,
    )
    db.add(identity)
    await db.flush()
    return identity


async def _seed_expiring_session(db: AsyncSession, name="expiring-session"):
    server = McpServer(
        id=uuid.uuid4(),
        name=f"srv-{uuid.uuid4().hex[:6]}",
        slug=f"srv-{uuid.uuid4().hex[:6]}",
        base_url="https://example.com",
        status=McpServerStatus.active,
    )
    db.add(server)
    await db.flush()
    session = McpSession(
        id=uuid.uuid4(),
        server_id=server.id,
        name=name,
        auth_type=McpSessionAuthType.oauth2,
        is_active=True,
        oauth_expires_at=NOW + timedelta(days=3),
    )
    db.add(session)
    await db.flush()
    return session


# ── Dashboard token-health ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_token_health_counts_and_details(api_client, db_session):
    await _seed_user(db_session)
    await _seed_expired_identity(db_session)
    await _seed_expiring_session(db_session)

    mock_auth = AsyncMock(return_value=type("Result", (), {"allowed": True}))
    with patch(
        "app.services.permissions.permission_engine.PermissionEngine.authorize", mock_auth
    ):
        with _bypass_auth():
            resp = await api_client.get("/api/v1/dashboard/token-health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["permission_flags"]["identities"] is False
    assert body["permission_flags"]["mcp_sessions"] is False
    assert body["identities"]["expired_count"] >= 1
    assert body["mcp_sessions"]["expiring_count"] >= 1
    identity_items = [i for i in body["identities"]["items"] if i["name"] == "expired-identity"]
    assert identity_items and identity_items[0]["health_state"] == "expired"
    assert identity_items[0]["remediation_path"] == "/agents/identities"
    session_items = [i for i in body["mcp_sessions"]["items"] if i["name"] == "expiring-session"]
    assert session_items and session_items[0]["health_state"] == "expiring"
    assert session_items[0]["remediation_path"] == "/mcp"


@pytest.mark.asyncio
async def test_token_health_permission_denied_flags(api_client, db_session):
    """Without granted permissions the categories are flagged, not 403."""
    await _seed_user(db_session)
    await _seed_expired_identity(db_session)

    mock_deny = AsyncMock(return_value=type("Result", (), {"allowed": False}))
    with patch(
        "app.services.permissions.permission_engine.PermissionEngine.authorize", mock_deny
    ):
        with _bypass_auth():
            resp = await api_client.get("/api/v1/dashboard/token-health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["permission_flags"]["identities"] is True
    assert body["permission_flags"]["mcp_sessions"] is True
    assert body["identities"]["expired_count"] == 0
    assert body["identities"]["items"] == []


# ── Internal preflight ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_internal_preflight_without_signed_headers_fails_closed(api_client, db_session):
    """Multi-tenancy ON: headerless internal preflight requests → 401."""
    with patch(
        "app.services.tenancy.platform_settings_service."
        "PlatformSettingsService.is_multi_tenancy_enabled",
        AsyncMock(return_value=True),
    ):
        resp = await api_client.post(
            "/api/v1/internal/token-health/preflight",
            json={"agent_type_id": str(uuid.uuid4())},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_internal_preflight_blocked_writes_audit_rows_with_tenant_stamp(
    api_client, db_session
):
    """Every preflight evaluation — including blocked runs — writes one
    TokenHealthCheck audit row per evaluated target, stamped with the agent
    type's own tenant (root fallback only when unassigned)."""
    from sqlalchemy import select

    from app.db.models.token_health import TokenHealthCheck
    from app.db.models.tenant import Tenant

    tenant_b = Tenant(id=uuid.uuid4(), name="B", slug="tenant-b")
    db_session.add(tenant_b)
    await db_session.flush()

    identity = await _seed_expired_identity(db_session)
    identity.tenant_id = tenant_b.id
    await db_session.flush()
    agent_type = AgentType(
        id=uuid.uuid4(),
        name=f"agent-{uuid.uuid4().hex[:6]}",
        identity_id=identity.id,
        tenant_id=tenant_b.id,
    )
    db_session.add(agent_type)
    await db_session.flush()
    result = await db_session.execute(
        select(Tenant).where(Tenant.is_system_tenant.is_(True))
    )
    if result.scalar_one_or_none() is None:
        db_session.add(
            Tenant(id=uuid.uuid4(), name="Root", slug="root", is_system_tenant=True)
        )
        await db_session.flush()

    resp = await api_client.post(
        "/api/v1/internal/token-health/preflight",
        json={"agent_type_id": str(agent_type.id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "blocked"

    rows = (await db_session.execute(select(TokenHealthCheck))).scalars().all()
    assert len(rows) == 1
    assert rows[0].check_outcome == "blocked"
    assert rows[0].health_state == "expired"
    assert rows[0].tenant_id == tenant_b.id  # stamped with the agent type's tenant
    assert identity.name in rows[0].message
    # Audit rows are insert-only — re-evaluating appends, never updates.
    resp2 = await api_client.post(
        "/api/v1/internal/token-health/preflight",
        json={"agent_type_id": str(agent_type.id)},
    )
    assert resp2.status_code == 200
    rows_after = (await db_session.execute(select(TokenHealthCheck))).scalars().all()
    assert len(rows_after) == 2


@pytest.mark.asyncio
async def test_preflight_proceeds_after_remediation_round_trip(api_client, db_session):
    """WHEN the expired token is refreshed, THEN preflight returns PROCEED."""
    identity = await _seed_expired_identity(db_session)
    agent_type = AgentType(
        id=uuid.uuid4(),
        name=f"agent-{uuid.uuid4().hex[:6]}",
        identity_id=identity.id,
    )
    db_session.add(agent_type)
    await db_session.flush()

    resp = await api_client.post(
        "/api/v1/internal/token-health/preflight",
        json={"agent_type_id": str(agent_type.id)},
    )
    assert resp.status_code == 200
    assert resp.json()["verdict"] == "blocked"

    # Remediation: identity token refreshed.
    identity.token_expires_at = NOW + timedelta(days=30)
    identity.token_status = AgentTokenStatus.active
    await db_session.flush()

    resp2 = await api_client.post(
        "/api/v1/internal/token-health/preflight",
        json={"agent_type_id": str(agent_type.id)},
    )
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["verdict"] == "proceed"
    assert body["blocked"] == []


@pytest.mark.asyncio
async def test_internal_preflight_single_tenant_classifies(api_client, db_session):
    """Single-tenancy (root-bound) internal headerless calls are evaluated."""
    from app.db.models.tenant import Tenant

    identity = await _seed_expired_identity(db_session)
    agent_type = AgentType(
        id=uuid.uuid4(),
        name=f"agent-{uuid.uuid4().hex[:6]}",
        identity_id=identity.id,
    )
    db_session.add(agent_type)
    await db_session.flush()
    # Root tenant fallback for audit rows.
    result = await db_session.execute(
        __import__("sqlalchemy").select(Tenant).where(Tenant.is_system_tenant.is_(True))
    )
    if result.scalar_one_or_none() is None:
        db_session.add(
            Tenant(id=uuid.uuid4(), name="Root", slug="root", is_system_tenant=True)
        )
        await db_session.flush()

    resp = await api_client.post(
        "/api/v1/internal/token-health/preflight",
        json={"agent_type_id": str(agent_type.id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "blocked"
    assert any("expired-identity" in message for message in body["blocked"])
    # No token material in the response.
    assert "access_token" not in resp.text
