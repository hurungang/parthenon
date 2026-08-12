"""
Backend integration tests for the query_result system tool.

Tests cover:
  1. query_result with exact data type name match (slug)
  2. query_result with exact data type name match (name)
  3. query_result with date range filter
  4. query_result with unknown data type name (404)
  5. query_result with no matching results (empty list)
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_service_certificate
from app.db.models.agent_data_type import AgentDataType
from app.db.models.agent_output import AgentOutput, AgentOutputValidationStatus
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


async def _seed_agent_output(
    db: AsyncSession,
    data_type_id: uuid.UUID,
    agent_type_id: uuid.UUID,
    field_values: dict | None = None,
    created_at_override: str | None = None,
) -> AgentOutput:
    """Create a typed AgentOutput record directly."""
    output = AgentOutput(
        data_type_id=data_type_id,
        agent_type_id=agent_type_id,
        execution_session_id=uuid.uuid4(),
        field_values=field_values or {"title": "Test", "severity": "high"},
        validation_status=AgentOutputValidationStatus.valid,
        raw_output="{}",
    )
    db.add(output)
    await db.flush()
    return output


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestQueryResultTool:
    """Tests for the query_result system tool."""

    @pytest.mark.asyncio
    async def test_query_by_slug(self, authed_client: AsyncClient, test_engine):
        """query_result with data type slug returns matching results."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            dt = await _create_data_type(db, name="Incident Report", slug="incident_report")
            at = await _create_agent_type(db)
            output = await _seed_agent_output(db, dt.id, at.id)
            await db.commit()
            session_id = str(output.execution_session_id)

        resp = await authed_client.post("/api/v1/internal/system-tools/query-result", json={
            "session_id": str(uuid.uuid4()),
            "tool_args": {
                "data_type_name": "incident_report",
            },
        })
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()
        result = data["result"]
        assert result["total"] >= 1
        assert result["data_type_name"] == "Incident Report"
        assert result["data_type_slug"] == "incident_report"
        assert any(item["execution_session_id"] == session_id for item in result["results"])

    @pytest.mark.asyncio
    async def test_query_by_name(self, authed_client: AsyncClient, test_engine):
        """query_result with data type name returns matching results."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            # Use a unique name/slug to avoid collision with test_query_by_slug
            unique = uuid.uuid4().hex[:8]
            dt = await _create_data_type(db, name=f"ByName-{unique}", slug=f"byname-{unique}")
            at = await _create_agent_type(db)
            output = await _seed_agent_output(db, dt.id, at.id)
            await db.commit()
            session_id = str(output.execution_session_id)

        resp = await authed_client.post("/api/v1/internal/system-tools/query-result", json={
            "session_id": str(uuid.uuid4()),
            "tool_args": {
                "data_type_name": dt.name,
            },
        })
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()
        result = data["result"]
        assert result["total"] >= 1
        assert any(item["execution_session_id"] == session_id for item in result["results"])

    @pytest.mark.asyncio
    async def test_query_with_date_range(self, authed_client: AsyncClient, test_engine):
        """query_result with date_from filter returns filtered results."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            dt = await _create_data_type(db, name="Test DT", slug="test-dt")
            at = await _create_agent_type(db)
            # Create one output (will have current timestamp)
            output = await _seed_agent_output(db, dt.id, at.id)
            await db.commit()
            session_id = str(output.execution_session_id)

        # Query with date_from set to far in the future — should return 0 results
        resp = await authed_client.post("/api/v1/internal/system-tools/query-result", json={
            "session_id": str(uuid.uuid4()),
            "tool_args": {
                "data_type_name": "test-dt",
                "filters": {
                    "date_from": "2099-01-01T00:00:00",
                },
            },
        })
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()
        result = data["result"]
        assert result["total"] == 0, (
            f"Expected 0 results for future date_from, got {result['total']}"
        )
        assert len(result["results"]) == 0

    @pytest.mark.asyncio
    async def test_query_unknown_data_type(self, authed_client: AsyncClient):
        """query_result with unknown data type name returns 404."""
        resp = await authed_client.post("/api/v1/internal/system-tools/query-result", json={
            "session_id": str(uuid.uuid4()),
            "tool_args": {
                "data_type_name": "nonexistent_data_type",
            },
        })
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"

    @pytest.mark.asyncio
    async def test_query_no_matching_results(self, authed_client: AsyncClient, test_engine):
        """query_result for a data type with no outputs returns empty list."""
        async with async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )() as db:
            dt = await _create_data_type(db, name="Empty DT", slug="empty-dt")
            await db.commit()

        resp = await authed_client.post("/api/v1/internal/system-tools/query-result", json={
            "session_id": str(uuid.uuid4()),
            "tool_args": {
                "data_type_name": "empty-dt",
            },
        })
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()
        result = data["result"]
        assert result["total"] == 0
        assert len(result["results"]) == 0
        assert result["data_type_name"] == "Empty DT"

    @pytest.mark.asyncio
    async def test_query_missing_data_type_name(self, authed_client: AsyncClient):
        """query_result without data_type_name returns 400."""
        resp = await authed_client.post("/api/v1/internal/system-tools/query-result", json={
            "session_id": str(uuid.uuid4()),
            "tool_args": {},
        })
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
