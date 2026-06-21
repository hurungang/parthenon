"""
Backend integration tests for enhanced save_result with typed output support.

Tests cover:
  1. save_result with typed agent type — creates AgentOutput (200)
  2. save_result with typed agent type and invalid payload — validation_error (200)
  3. save_result with untyped agent type — falls through to ResultRecord (200)
  4. save_result with typed agent type but data type missing — fallback (200)
  5. save_result with nonexistent session — 404
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.api.deps import require_service_certificate
from app.db.models.agent_data_type import AgentDataType
from app.db.models.agent_output import AgentOutput
from app.db.models.agents import AgentJob, AgentType
from app.db.session import get_db
from app.main import create_app


# ── Helpers ───────────────────────────────────────────────────────────────────


def _bypass_service_cert():
    """Override dependency to bypass service certificate check."""
    async def override():
        return {"cert_type": "service", "service_name": "test-service"}
    return override


@pytest_asyncio.fixture
async def authed_client(test_engine):
    """Return AsyncClient with service cert dep overridden and real in-memory DB."""
    app = create_app()

    # Bypass service certificate requirement
    app.dependency_overrides[require_service_certificate] = _bypass_service_cert()

    # Share the same in-memory engine
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


async def _create_data_type(
    db: AsyncSession,
    name: str | None = None,
    slug: str | None = None,
) -> AgentDataType:
    """Create a data type directly in the database."""
    unique = uuid.uuid4().hex[:8]
    dt = AgentDataType(
        name=name or f"test-dt-{unique}",
        slug=slug or f"test-dt-{unique}",
        description="Test data type",
        fields=[
            {"name": "title", "type": "string", "required": True},
            {"name": "severity", "type": "enum", "enum_values": ["low", "medium", "high"], "required": True},
            {"name": "count", "type": "number", "required": False},
        ],
    )
    db.add(dt)
    await db.flush()
    return dt


async def _create_typed_agent_type(
    db: AsyncSession,
    data_type_id: uuid.UUID,
) -> AgentType:
    """Create an agent type with an assigned output data type."""
    unique = uuid.uuid4().hex[:8]
    at = AgentType(
        name=f"typed-agent-{unique}",
        description="Agent type with typed output",
        output_data_type_id=data_type_id,
    )
    db.add(at)
    await db.flush()
    return at


async def _create_untyped_agent_type(db: AsyncSession) -> AgentType:
    """Create an agent type WITHOUT an assigned output data type."""
    unique = uuid.uuid4().hex[:8]
    at = AgentType(
        name=f"untyped-agent-{unique}",
        description="Agent type without typed output",
        output_data_type_id=None,
    )
    db.add(at)
    await db.flush()
    return at


async def _create_agent_job(db: AsyncSession, agent_type_id: uuid.UUID) -> AgentJob:
    """Create an AgentJob (session) for testing."""
    session_id = uuid.uuid4()
    from app.db.models.agents import AgentJobStatus, AgentTerminationCategory
    job = AgentJob(
        id=session_id,
        agent_type_id=agent_type_id,
        status=AgentJobStatus.running,
        termination_category=AgentTerminationCategory.none,
        input_data={},
        output_data={},
    )
    db.add(job)
    await db.flush()
    return job


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestSaveResultTyped:
    """Tests for save_result with typed agent type."""

    @pytest.mark.asyncio
    async def test_typed_agent_valid_payload(self, authed_client: AsyncClient, test_engine):
        """save_result with typed agent & valid payload creates AgentOutput with status=valid."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            dt = await _create_data_type(db)
            at = await _create_typed_agent_type(db, dt.id)
            job = await _create_agent_job(db, at.id)
            await db.commit()
            session_id = str(job.id)

        resp = await authed_client.post("/api/v1/internal/system-tools/save-result", json={
            "session_id": session_id,
            "tool_args": {
                "data": {"title": "Incident Report", "severity": "high", "count": 5},
                "title": "Test Result",
            },
        })
        assert resp.status_code == 200, f"save_result failed: {resp.text}"
        data = resp.json()
        result = data["result"]
        assert result["status"] == "saved"
        assert "output_id" in result
        assert result["validation_status"] == "valid"

        # Verify AgentOutput was created in the database
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            result2 = await db.execute(
                select(AgentOutput).where(AgentOutput.execution_session_id == job.id)
            )
            output = result2.scalar_one_or_none()
            assert output is not None
            assert str(output.data_type_id) == str(dt.id)
            assert str(output.agent_type_id) == str(at.id)
            assert output.validation_status.value == "valid"
            assert output.field_values is not None

    @pytest.mark.asyncio
    async def test_typed_agent_invalid_payload(self, authed_client: AsyncClient, test_engine):
        """save_result with typed agent & invalid payload creates AgentOutput with status=validation_error."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            dt = await _create_data_type(db)
            at = await _create_typed_agent_type(db, dt.id)
            job = await _create_agent_job(db, at.id)
            await db.commit()
            session_id = str(job.id)

        # Payload with invalid enum value, missing required 'title' field, and invalid number
        resp = await authed_client.post("/api/v1/internal/system-tools/save-result", json={
            "session_id": session_id,
            "tool_args": {
                "data": {"severity": "invalid", "count": "not-a-number"},
                "title": "Invalid Result",
            },
        })
        assert resp.status_code == 200, f"save_result failed: {resp.text}"
        data = resp.json()
        result = data["result"]
        assert result["status"] == "saved"
        assert result["validation_status"] == "validation_error"
        assert len(result["validation_errors"]) > 0

        # Verify AgentOutput was created with validation_error status
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            result2 = await db.execute(
                select(AgentOutput).where(AgentOutput.execution_session_id == job.id)
            )
            output = result2.scalar_one_or_none()
            assert output is not None
            assert output.validation_status.value == "validation_error"
            assert output.field_values is None  # field_values is None for invalid payloads

    @pytest.mark.asyncio
    async def test_untyped_agent_fallback(self, authed_client: AsyncClient, test_engine):
        """save_result with untyped agent type falls through to ResultRecord path."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            at = await _create_untyped_agent_type(db)
            job = await _create_agent_job(db, at.id)
            await db.commit()
            session_id = str(job.id)

        resp = await authed_client.post("/api/v1/internal/system-tools/save-result", json={
            "session_id": session_id,
            "tool_args": {
                "content": "This is a plain text result",
                "title": "Untyped Result",
            },
        })
        assert resp.status_code == 200, f"save_result failed: {resp.text}"
        data = resp.json()
        result = data["result"]
        assert result["status"] == "saved"
        # Untyped path returns session_id but NOT output_id
        assert "session_id" in result
        assert "output_id" not in result

        # Verify no AgentOutput was created
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            result2 = await db.execute(
                select(AgentOutput).where(AgentOutput.execution_session_id == job.id)
            )
            output = result2.scalar_one_or_none()
            assert output is None, (
                "Expected no AgentOutput for untyped agent save_result"
            )

    @pytest.mark.asyncio
    async def test_data_type_not_found_fallback(self, authed_client: AsyncClient, test_engine):
        """save_result with output_data_type_id pointing to nonexistent data type falls back."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            # Create agent type with a data type ID that doesn't exist in the DB
            fake_dt_id = uuid.uuid4()
            unique = uuid.uuid4().hex[:8]
            at = AgentType(
                name=f"broken-agent-{unique}",
                description="Agent type with missing data type ref",
                output_data_type_id=fake_dt_id,
            )
            db.add(at)
            await db.flush()
            job = await _create_agent_job(db, at.id)
            await db.commit()
            session_id = str(job.id)

        resp = await authed_client.post("/api/v1/internal/system-tools/save-result", json={
            "session_id": session_id,
            "tool_args": {
                "content": "Fallback content",
                "title": "Fallback Result",
            },
        })
        assert resp.status_code == 200, f"save_result failed: {resp.text}"
        data = resp.json()
        result = data["result"]
        assert result["status"] == "saved"
        # Falls back to untyped path — no output_id
        assert "output_id" not in result

    @pytest.mark.asyncio
    async def test_session_not_found(self, authed_client: AsyncClient):
        """save_result with nonexistent session ID returns 404."""
        resp = await authed_client.post("/api/v1/internal/system-tools/save-result", json={
            "session_id": str(uuid.uuid4()),
            "tool_args": {
                "content": "Test",
                "title": "Test",
            },
        })
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
