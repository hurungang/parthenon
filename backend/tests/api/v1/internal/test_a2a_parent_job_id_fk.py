"""Reproduction test for A2A delegation parent_job_id FK violation.

This test intentionally asserts the desired behavior for conversational
delegation: when requester_instance_id is a valid UUID that does not match an
existing AgentJob, the receiver session should still be created and persisted
with parent_job_id=None.

Current behavior (bug): the handler sets parent_job_id=requester_instance_id,
which triggers an FK violation on agent_jobs.parent_job_id.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import require_service_certificate
from app.db.models.agents import AgentJob, AgentType
from app.db.session import Base, get_db
from app.main import create_app


def _bypass_service_cert():
    """Override dependency to bypass service certificate validation."""

    async def override():
        return {"cert_type": "service", "service_name": "test-service"}

    return override


@pytest_asyncio.fixture
async def fk_test_engine():
    """Create an isolated SQLite engine with FK enforcement support."""

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def authed_client(fk_test_engine):
    """Return AsyncClient with service-cert override and shared test DB."""

    app = create_app()
    app.dependency_overrides[require_service_certificate] = _bypass_service_cert()

    SessionLocal = async_sessionmaker(
        bind=fk_test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_db():
        async with SessionLocal() as session:
            # Ensure FK constraints are enforced in SQLite tests.
            await session.execute(text("PRAGMA foreign_keys=ON"))
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_a2a_request_with_non_job_uuid_requester_creates_receiver_with_null_parent_job(
    authed_client: AsyncClient,
    fk_test_engine,
):
    """Conversational requester UUID must not be used as parent_job_id FK.

    Repro setup:
    - requester_instance_id is a valid UUID but does not exist in agent_jobs
      (simulates conv_session_id-based requester identity).

    Expected behavior:
    - CC creates the receiver AgentJob successfully
    - persisted AgentJob.parent_job_id is NULL
    """

    async with async_sessionmaker(
        bind=fk_test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )() as db:
        await db.execute(text("PRAGMA foreign_keys=ON"))

        target_agent_type = AgentType(
            name=f"a2a-target-{uuid.uuid4().hex[:8]}",
            description="A2A target agent for FK regression test",
            is_active=True,
        )
        db.add(target_agent_type)
        await db.flush()
        await db.commit()

        target_slug = target_agent_type.name

    requester_instance_id = str(uuid.uuid4())
    conv_session_id = str(uuid.uuid4())

    response = await authed_client.post(
        "/api/v1/internal/data/a2a/request",
        json={
            "target_agent_type_slug": target_slug,
            "requester_instance_id": requester_instance_id,
            "request_payload": {"message": "delegate this task"},
            "conv_session_id": conv_session_id,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    receiver_session_id = payload.get("receiver_session_id")
    assert receiver_session_id is not None

    async with async_sessionmaker(
        bind=fk_test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )() as db:
        result = await db.execute(
            select(AgentJob).where(AgentJob.id == uuid.UUID(str(receiver_session_id)))
        )
        created_job = result.scalar_one_or_none()

    assert created_job is not None
    assert created_job.parent_job_id is None
