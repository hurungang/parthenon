"""
Backend integration tests for internal agent output endpoints.

Tests cover:
  1. Validate output — valid payload (200)
  2. Validate output — invalid payload (200 with errors)
  3. Validate output — data type not found (404)
  4. Create agent output (201)
  5. Create agent output — data type not found (404)
  6. Create agent output — agent type not found (404)
  7. Query agent outputs — empty list (200)
  8. Query agent outputs — with filter (200)
  9. Query agent outputs — pagination (200)
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_service_certificate
from app.db.models.agent_data_type import AgentDataType
from app.db.models.agent_output import AgentOutput
from app.db.models.agents import AgentType
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

    # Bypass service certificate requirement for all internal endpoints
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
            {"name": "is_active", "type": "boolean", "required": False},
        ],
    )
    db.add(dt)
    await db.flush()
    return dt


async def _create_agent_type(db: AsyncSession) -> AgentType:
    """Create an agent type directly in the database."""
    unique = uuid.uuid4().hex[:8]
    at = AgentType(
        name=f"test-agent-{unique}",
        description="Test agent type",
    )
    db.add(at)
    await db.flush()
    return at


# ── Tests: Validate Output ────────────────────────────────────────────────────


class TestValidateOutput:
    """Tests for POST /api/v1/internal/validate-output."""

    @pytest.mark.asyncio
    async def test_validate_valid_payload(self, authed_client: AsyncClient, test_engine):
        """Valid payload returns valid=True."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            dt = await _create_data_type(db)
            await db.commit()

        resp = await authed_client.post("/api/v1/internal/validate-output", json={
            "data_type_id": str(dt.id),
            "payload": {
                "title": "Test Incident",
                "severity": "high",
                "count": 5,
                "is_active": True,
            },
        })
        assert resp.status_code == 200, f"Validate failed: {resp.text}"
        data = resp.json()
        assert data["valid"] is True
        assert len(data["errors"]) == 0

    @pytest.mark.asyncio
    async def test_validate_invalid_payload(self, authed_client: AsyncClient, test_engine):
        """Invalid payload returns valid=False with field errors."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            dt = await _create_data_type(db)
            await db.commit()

        resp = await authed_client.post("/api/v1/internal/validate-output", json={
            "data_type_id": str(dt.id),
            "payload": {
                "title": "Test",
                "severity": "invalid_value",
                "count": "not-a-number",
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert len(data["errors"]) >= 2  # severity + count (is_active is optional)
        error_fields = {e["field"] for e in data["errors"]}
        assert "severity" in error_fields
        assert "count" in error_fields

    @pytest.mark.asyncio
    async def test_validate_missing_required_field(self, authed_client: AsyncClient, test_engine):
        """Missing required field (title, severity) returns errors."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            dt = await _create_data_type(db)
            await db.commit()

        resp = await authed_client.post("/api/v1/internal/validate-output", json={
            "data_type_id": str(dt.id),
            "payload": {"count": 42},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        error_fields = {e["field"] for e in data["errors"]}
        assert "title" in error_fields
        assert "severity" in error_fields

    @pytest.mark.asyncio
    async def test_validate_data_type_not_found(self, authed_client: AsyncClient):
        """Non-existent data type returns 404."""
        fake_id = uuid.uuid4()
        resp = await authed_client.post("/api/v1/internal/validate-output", json={
            "data_type_id": str(fake_id),
            "payload": {"title": "Test"},
        })
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


# ── Tests: Create Agent Output ────────────────────────────────────────────────


class TestCreateAgentOutput:
    """Tests for POST /api/v1/internal/agent-outputs."""

    @pytest.mark.asyncio
    async def test_create_agent_output_201(self, authed_client: AsyncClient, test_engine):
        """POST /internal/agent-outputs returns 201 with the created output."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            dt = await _create_data_type(db)
            at = await _create_agent_type(db)
            await db.commit()

        session_id = uuid.uuid4()

        resp = await authed_client.post("/api/v1/internal/agent-outputs", json={
            "data_type_id": str(dt.id),
            "agent_type_id": str(at.id),
            "execution_session_id": str(session_id),
            "field_values": {
                "title": "Incident Report",
                "severity": "high",
                "count": 42,
            },
            "validation_status": "valid",
            "raw_output": '{"title": "Incident Report", "severity": "high"}',
        })
        assert resp.status_code == 201, f"Create failed: {resp.text}"
        data = resp.json()
        assert data["data_type_id"] == str(dt.id)
        assert data["agent_type_id"] == str(at.id)
        assert data["execution_session_id"] == str(session_id)
        assert data["validation_status"] == "valid"
        assert data["field_values"]["title"] == "Incident Report"
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_create_agent_output_data_type_not_found(self, authed_client: AsyncClient, test_engine):
        """Non-existent data type returns 404."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            at = await _create_agent_type(db)
            await db.commit()

        resp = await authed_client.post("/api/v1/internal/agent-outputs", json={
            "data_type_id": str(uuid.uuid4()),
            "agent_type_id": str(at.id),
            "execution_session_id": str(uuid.uuid4()),
            "field_values": {"title": "Test"},
            "validation_status": "valid",
        })
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_create_agent_output_agent_type_not_found(self, authed_client: AsyncClient, test_engine):
        """Non-existent agent type returns 404."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            dt = await _create_data_type(db)
            await db.commit()

        resp = await authed_client.post("/api/v1/internal/agent-outputs", json={
            "data_type_id": str(dt.id),
            "agent_type_id": str(uuid.uuid4()),
            "execution_session_id": str(uuid.uuid4()),
            "field_values": {"title": "Test"},
            "validation_status": "valid",
        })
        assert resp.status_code == 404


# ── Tests: Query Agent Outputs ────────────────────────────────────────────────


class TestQueryAgentOutputs:
    """Tests for GET /api/v1/internal/agent-outputs."""

    @pytest.mark.asyncio
    async def test_query_returns_200(self, authed_client: AsyncClient):
        """Query returns 200 with pagination structure."""
        resp = await authed_client.get("/api/v1/internal/agent-outputs")
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page_size" in data
        assert isinstance(data["items"], list)
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_query_with_filter(self, authed_client: AsyncClient, test_engine):
        """Filter by data_type_id returns matching outputs."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            dt = await _create_data_type(db)
            at = await _create_agent_type(db)
            session_id = uuid.uuid4()

            # Create one output
            output = AgentOutput(
                data_type_id=dt.id,
                agent_type_id=at.id,
                execution_session_id=session_id,
                field_values={"title": "Test"},
                validation_status="valid",
                raw_output="{}",
            )
            db.add(output)
            await db.commit()

        resp = await authed_client.get(
            f"/api/v1/internal/agent-outputs?data_type_id={dt.id}",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(item["execution_session_id"] == str(session_id) for item in data["items"])

    @pytest.mark.asyncio
    async def test_query_pagination(self, authed_client: AsyncClient, test_engine):
        """Pagination returns correct subset."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            dt = await _create_data_type(db)
            at = await _create_agent_type(db)

            # Create 3 outputs
            for i in range(3):
                output = AgentOutput(
                    data_type_id=dt.id,
                    agent_type_id=at.id,
                    execution_session_id=uuid.uuid4(),
                    field_values={"title": f"Test {i}"},
                    validation_status="valid",
                    raw_output="{}",
                )
                db.add(output)
            await db.commit()

        resp = await authed_client.get(
            f"/api/v1/internal/agent-outputs?page=1&page_size=2",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 2
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["total"] >= 3
