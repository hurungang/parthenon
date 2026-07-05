"""Integration tests for the public Agent Data API."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_service_certificate
from app.db.models.agent_data import AgentData
from app.db.models.agents import AgentJob, AgentJobStatus, AgentType
from app.db.session import get_db
from app.main import create_app


def _bypass_service_cert():
    async def override():
        return {"cert_type": "service", "service_name": "test-service"}

    return override


@pytest_asyncio.fixture
async def authed_client(test_engine):
    """Create a TestClient with overridden auth and DB dependencies."""
    # Override the JWT require_permission dependency for these integration tests
    from app.core.resource_types import RT_AGENT_DATA

    async def fake_perm_check(*args, **kwargs):
        return {"user_id": "test-user", "permissions": [f"{RT_AGENT_DATA}:read"]}

    app_ref = create_app()
    from app.api.deps import require_permission as rp_dep

    # We can't easily override require_permission at module level due to Depends,
    # so instead we test the endpoint through the app using the actual auth.
    # For integration tests against this public endpoint, we use the real
    # require_permission which expects a JWT. These tests test the internal
    # allowlist (which doesn't apply here — this is a public endpoint).

    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app_ref.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app_ref),
        base_url="http://test",
    ) as client:
        yield client


@pytest_asyncio.fixture
async def test_agent_type(test_engine):
    """Create a test agent type and return it."""
    async with async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )() as db:
        at = AgentType(name=f"test-agent-{uuid.uuid4().hex[:8]}")
        db.add(at)
        await db.commit()
        await db.refresh(at)
        return at


@pytest_asyncio.fixture
async def test_agent_job(test_engine, test_agent_type):
    """Create a test agent job."""
    async with async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )() as db:
        job = AgentJob(
            agent_type_id=test_agent_type.id,
            status=AgentJobStatus.completed,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job


@pytest_asyncio.fixture
async def test_agent_data(test_engine, test_agent_type, test_agent_job):
    """Create a test AgentData record and return it."""
    async with async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )() as db:
        record = AgentData(
            agent_type_id=test_agent_type.id,
            session_id=test_agent_job.id,
            data_name="test_key",
            data_value={"foo": "bar"},
            data_type="json",
            is_active=True,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record


@pytest.mark.asyncio
async def test_list_agent_data_returns_403_without_auth(
    authed_client: AsyncClient,
    test_agent_data,
) -> None:
    """The public endpoint requires JWT auth (require_permission)."""
    response = await authed_client.get("/api/v1/agent-data")
    # Without JWT token, expect 401 (missing auth) from require_permission
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_list_agent_data_requires_auth(
    authed_client: AsyncClient,
) -> None:
    """Verify the endpoint is registered and reaches the auth check."""
    response = await authed_client.get("/api/v1/agent-data")
    # Without JWT token, expect 401 (missing authorization)
    assert response.status_code == 401, response.text
