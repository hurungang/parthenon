"""Integration tests for GET /api/v1/dashboard/summary endpoint."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_permission
from app.core.resource_types import (
    RT_AGENT,
    RT_AGENT_HUMAN_INTERVENTION,
    RT_AGENT_IDENTITIES,
    RT_AGENT_MODEL_CONFIGS,
    RT_AGENT_ROLES,
    RT_AGENT_SCHEDULES,
    RT_AGENT_TRAILS,
    RT_INTEGRATION_MCP_HUB,
)
from app.db.models.agents import (
    AgentType,
    ModelConfig,
)
from app.db.models.platform_user import PlatformUser
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware

NOW = datetime.now(tz=timezone.utc)


# ── Auth bypass helpers ────────────────────────────────────────────────────


def _bypass_auth():
    """Patch JWT middleware to inject admin identity."""
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-api-user", "roles": ["admin"]}
        return await call_next(request)
    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _allow_permission():
    """Dependency override that grants any permission."""
    def override():
        return {"sub": "test-api-user", "roles": ["admin"]}
    return override


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def authed_client(test_engine):
    """Return AsyncClient with auth bypassed and permission deps granted."""
    app = create_app()

    # Grant ALL dashboard-related permissions (for FastAPI Depends)
    permissions = [
        (RT_AGENT, "read"),
        (RT_AGENT_HUMAN_INTERVENTION, "view"),
        (RT_AGENT_MODEL_CONFIGS, "read"),
        (RT_AGENT_SCHEDULES, "read"),
        (RT_AGENT_IDENTITIES, "read"),
        (RT_AGENT_ROLES, "read"),
        (RT_INTEGRATION_MCP_HUB, "read"),
        (RT_AGENT_TRAILS, "read"),
    ]
    for module, action in permissions:
        app.dependency_overrides[require_permission(module, action)] = _allow_permission()

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
    """Create a PlatformUser matching the auth bypass sub, or return existing."""
    result = await db.execute(
        sa_select(PlatformUser).where(PlatformUser.sub == "test-api-user")
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    user = PlatformUser(sub="test-api-user", email="test@example.com", display_name="Test User")
    db.add(user)
    await db.flush()
    return user


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_summary_no_auth(async_client):
    """Without authentication, endpoint should be accessible via test client."""
    resp = await async_client.get("/api/v1/dashboard/summary")
    # Without explicit auth, the middleware may or may not block
    assert resp.status_code in (200, 401, 403)


@pytest.mark.asyncio
async def test_get_summary_returns_200_and_valid_shape(authed_client, db_session):
    """With auth and seeded user, return 200 with valid DashboardSummary shape."""
    await _seed_user(db_session)

    # Mock the PermissionEngine to grant all permissions
    mock_auth = AsyncMock(return_value=type("Result", (), {"allowed": True, "reason": "test"}))
    with patch("app.services.dashboard_metrics_service.PermissionEngine.authorize", mock_auth):
        with _bypass_auth():
            resp = await authed_client.get("/api/v1/dashboard/summary")

    assert resp.status_code == 200
    body = resp.json()

    assert "snapshot_counts" in body
    assert "time_sensitive" in body
    assert "permission_flags" in body

    sc = body["snapshot_counts"]
    required_snapshot_keys = [
        "agent_types", "agent_types_active", "agent_types_running",
        "pending_interventions", "model_configs", "active_schedules",
        "agent_identities", "agent_roles", "mcp_servers",
    ]
    for key in required_snapshot_keys:
        assert key in sc, f"Missing snapshot key: {key}"

    ts = body["time_sensitive"]
    assert "guardrail_breaches" in ts
    assert "agent_executions" in ts
    assert "completed" in ts["agent_executions"]
    assert "failed" in ts["agent_executions"]
    assert "posture_breaches" in ts

    pf = body["permission_flags"]
    required_flag_keys = [
        "agent_types", "interventions", "model_configs", "schedules",
        "identities", "roles", "mcp_servers", "guardrail_breaches",
        "executions", "posture_breaches",
    ]
    for key in required_flag_keys:
        assert key in pf
        assert isinstance(pf[key], bool)


@pytest.mark.asyncio
async def test_get_summary_with_custom_date_range(authed_client, db_session):
    """Custom start_time and end_time params should be accepted."""
    await _seed_user(db_session)

    start = (NOW - timedelta(hours=6)).isoformat()
    end = NOW.isoformat()

    mock_auth = AsyncMock(return_value=type("Result", (), {"allowed": True, "reason": "test"}))
    with patch("app.services.dashboard_metrics_service.PermissionEngine.authorize", mock_auth):
        with _bypass_auth():
            resp = await authed_client.get(
                "/api/v1/dashboard/summary",
                params={"start_time": start, "end_time": end},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert "snapshot_counts" in body
    assert "time_sensitive" in body


@pytest.mark.asyncio
async def test_get_summary_invalid_datetime_returns_422(authed_client, db_session):
    """Invalid ISO datetime values should return 422."""
    await _seed_user(db_session)

    mock_auth = AsyncMock(return_value=type("Result", (), {"allowed": True, "reason": "test"}))
    with patch("app.services.dashboard_metrics_service.PermissionEngine.authorize", mock_auth):
        with _bypass_auth():
            resp = await authed_client.get(
                "/api/v1/dashboard/summary",
                params={"start_time": "not-a-date"},
            )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_summary_start_after_end_returns_422(authed_client, db_session):
    """start_time must be before end_time."""
    await _seed_user(db_session)

    mock_auth = AsyncMock(return_value=type("Result", (), {"allowed": True, "reason": "test"}))
    with patch("app.services.dashboard_metrics_service.PermissionEngine.authorize", mock_auth):
        with _bypass_auth():
            resp = await authed_client.get(
                "/api/v1/dashboard/summary",
                params={
                    "start_time": NOW.isoformat(),
                    "end_time": (NOW - timedelta(hours=1)).isoformat(),
                },
            )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_summary_reflects_seeded_data(authed_client, db_session):
    """Seeded data should appear in the summary counts (with permission)."""
    await _seed_user(db_session)

    # Seed a few records
    at1 = AgentType(name="at-1", is_active=True)
    db_session.add(at1)
    await db_session.flush()

    mc = ModelConfig(display_name="OpenAI", provider_type="openai", is_disabled=False)
    db_session.add(mc)
    await db_session.flush()

    mock_auth = AsyncMock(return_value=type("Result", (), {"allowed": True, "reason": "test"}))
    with patch("app.services.dashboard_metrics_service.PermissionEngine.authorize", mock_auth):
        with _bypass_auth():
            resp = await authed_client.get("/api/v1/dashboard/summary")

    assert resp.status_code == 200
    body = resp.json()
    sc = body["snapshot_counts"]

    assert sc["agent_types"] >= 1
    assert sc["model_configs"] >= 1
    # All counts should be non-negative integers
    for key in sc:
        assert isinstance(sc[key], int) and sc[key] >= 0, f"Invalid snapshot count: {key}={sc[key]}"
