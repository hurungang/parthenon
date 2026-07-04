"""
Backend unit tests for DataTypeService and DataTypeController.

Tests cover:
  1. Create data type (201)
  2. Create duplicate name (409)
  3. Get by id
  4. Update fields
  5. Delete unreferenced (204)
  6. Delete referenced (409)
  7. Paginated list
  8. Usage query
  9. Invalid field type (422)
 10. Empty fields (422)
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_permission
from app.core.resource_types import RT_AGENT_DATA_TYPES
from app.db.models.agent_data_type import AgentDataType
from app.db.models.agents import AgentType
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware


# ── Auth & Mock Helpers ────────────────────────────────────────────────────────


def _bypass_auth():
    """Context manager patch that bypasses JWT middleware and injects admin identity."""
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-admin", "roles": ["admin"]}
        return await call_next(request)
    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _allow_permission():
    """Return a dependency override that grants data_type permission."""
    def override():
        return {"sub": "test-admin", "roles": ["admin"]}
    return override


@pytest_asyncio.fixture
async def authed_client(test_engine):
    """Return AsyncClient with permission deps bypassed and real in-memory DB."""
    app = create_app()

    # Override all data type permission deps
    app.dependency_overrides[require_permission(RT_AGENT_DATA_TYPES, "read")] = _allow_permission()
    app.dependency_overrides[require_permission(RT_AGENT_DATA_TYPES, "create")] = _allow_permission()
    app.dependency_overrides[require_permission(RT_AGENT_DATA_TYPES, "update")] = _allow_permission()
    app.dependency_overrides[require_permission(RT_AGENT_DATA_TYPES, "delete")] = _allow_permission()
    app.dependency_overrides[require_permission(RT_AGENT_DATA_TYPES, "manage")] = _allow_permission()

    # Share the same in-memory engine
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    with _bypass_auth():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _valid_payload(name: str | None = None, slug: str | None = None) -> dict[str, Any]:
    """Return a valid data type creation payload."""
    unique = uuid.uuid4().hex[:8]
    return {
        "name": name or f"test-type-{unique}",
        "slug": slug or f"test-type-{unique}",
        "description": "Test data type",
        "fields": [
            {
                "name": "title",
                "type": "string",
                "required": True,
            },
            {
                "name": "severity",
                "type": "enum",
                "enum_values": ["low", "medium", "high"],
                "required": True,
            },
            {
                "name": "count",
                "type": "number",
                "required": False,
                "default": 0,
            },
        ],
    }


# ── Tests ───────────────────────────────────────────────────────────────────────


class TestCreateDataType:
    """Tests for POST /api/v1/data-types."""

    @pytest.mark.asyncio
    async def test_create_data_type_returns_201(self, authed_client: AsyncClient):
        """POST /data-types returns 201 with the created data type."""
        payload = _valid_payload()
        resp = await authed_client.post("/api/v1/data-types", json=payload)
        assert resp.status_code == 201, f"Create failed: {resp.text}"
        data = resp.json()
        assert data["name"] == payload["name"]
        assert data["slug"] == payload["slug"]
        assert data["description"] == payload["description"]
        assert len(data["fields"]) == 3
        assert data["fields"][0]["name"] == "title"
        assert data["fields"][1]["name"] == "severity"
        assert data["fields"][1]["enum_values"] == ["low", "medium", "high"]
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    @pytest.mark.asyncio
    async def test_create_duplicate_name_returns_409(self, authed_client: AsyncClient):
        """POST /data-types with duplicate name returns 409."""
        payload = _valid_payload(name="unique-name", slug="unique-slug-1")
        resp = await authed_client.post("/api/v1/data-types", json=payload)
        assert resp.status_code == 201

        # Same name, different slug
        payload2 = _valid_payload(name="unique-name", slug="unique-slug-2")
        resp2 = await authed_client.post("/api/v1/data-types", json=payload2)
        assert resp2.status_code == 409, f"Expected 409, got {resp2.status_code}: {resp2.text}"

    @pytest.mark.asyncio
    async def test_create_empty_fields_returns_422(self, authed_client: AsyncClient):
        """POST /data-types with empty fields list returns 422."""
        payload = _valid_payload()
        payload["fields"] = []
        resp = await authed_client.post("/api/v1/data-types", json=payload)
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    @pytest.mark.asyncio
    async def test_create_duplicate_field_names_returns_422(self, authed_client: AsyncClient):
        """POST /data-types with duplicate field names returns 422."""
        payload = _valid_payload()
        payload["fields"] = [
            {"name": "field1", "type": "string"},
            {"name": "field1", "type": "number"},
        ]
        resp = await authed_client.post("/api/v1/data-types", json=payload)
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    @pytest.mark.asyncio
    async def test_create_invalid_field_type_returns_422(self, authed_client: AsyncClient):
        """POST /data-types with invalid field type returns 422."""
        payload = _valid_payload()
        payload["fields"] = [
            {"name": "test", "type": "invalid_type"},
        ]
        resp = await authed_client.post("/api/v1/data-types", json=payload)
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    @pytest.mark.asyncio
    async def test_create_enum_without_values_returns_422(self, authed_client: AsyncClient):
        """POST /data-types with enum field missing enum_values returns 422."""
        payload = _valid_payload()
        payload["fields"] = [
            {"name": "status", "type": "enum"},
        ]
        resp = await authed_client.post("/api/v1/data-types", json=payload)
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"


class TestGetDataType:
    """Tests for GET /api/v1/data-types/{id}."""

    @pytest.mark.asyncio
    async def test_get_by_id(self, authed_client: AsyncClient):
        """GET /data-types/{id} returns the data type."""
        payload = _valid_payload()
        create_resp = await authed_client.post("/api/v1/data-types", json=payload)
        assert create_resp.status_code == 201
        created = create_resp.json()

        resp = await authed_client.get(f"/api/v1/data-types/{created['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == created["id"]
        assert data["name"] == payload["name"]
        assert data["slug"] == payload["slug"]
        assert len(data["fields"]) == 3

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, authed_client: AsyncClient):
        """GET /data-types/{id} returns 404 for unknown id."""
        resp = await authed_client.get(f"/api/v1/data-types/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestUpdateDataType:
    """Tests for PUT /api/v1/data-types/{id}."""

    @pytest.mark.asyncio
    async def test_update_fields(self, authed_client: AsyncClient):
        """PUT /data-types/{id} updates data type fields."""
        payload = _valid_payload()
        create_resp = await authed_client.post("/api/v1/data-types", json=payload)
        assert create_resp.status_code == 201
        created = create_resp.json()

        update_payload = {
            "name": "updated-name",
            "description": "Updated description",
            "fields": [
                {"name": "new_field", "type": "boolean", "required": True},
            ],
        }
        resp = await authed_client.put(
            f"/api/v1/data-types/{created['id']}", json=update_payload
        )
        assert resp.status_code == 200, f"Update failed: {resp.text}"
        data = resp.json()
        assert data["name"] == "updated-name"
        assert data["description"] == "Updated description"
        assert len(data["fields"]) == 1
        assert data["fields"][0]["name"] == "new_field"
        assert data["fields"][0]["type"] == "boolean"

    @pytest.mark.asyncio
    async def test_update_not_found(self, authed_client: AsyncClient):
        """PUT /data-types/{id} returns 404 for unknown id."""
        resp = await authed_client.put(
            f"/api/v1/data-types/{uuid.uuid4()}",
            json={"name": "nobody"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_duplicate_name_returns_409(self, authed_client: AsyncClient):
        """PUT /data-types/{id} with conflicting name returns 409."""
        # Create two data types
        payload1 = _valid_payload(name="type-one", slug="type-one-slug")
        resp1 = await authed_client.post("/api/v1/data-types", json=payload1)
        assert resp1.status_code == 201

        payload2 = _valid_payload(name="type-two", slug="type-two-slug")
        resp2 = await authed_client.post("/api/v1/data-types", json=payload2)
        assert resp2.status_code == 201
        type2 = resp2.json()

        # Try to update type2 to use type1's name
        resp3 = await authed_client.put(
            f"/api/v1/data-types/{type2['id']}",
            json={"name": "type-one"},
        )
        assert resp3.status_code == 409, f"Expected 409, got {resp3.status_code}: {resp3.text}"


class TestDeleteDataType:
    """Tests for DELETE /api/v1/data-types/{id}."""

    @pytest.mark.asyncio
    async def test_delete_unreferenced_returns_204(self, authed_client: AsyncClient):
        """DELETE /data-types/{id} returns 204 for unreferenced type."""
        payload = _valid_payload()
        create_resp = await authed_client.post("/api/v1/data-types", json=payload)
        assert create_resp.status_code == 201
        created = create_resp.json()

        resp = await authed_client.delete(f"/api/v1/data-types/{created['id']}")
        assert resp.status_code == 204, f"Delete failed: {resp.text}"

        # Verify it's gone
        get_resp = await authed_client.get(f"/api/v1/data-types/{created['id']}")
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_not_found(self, authed_client: AsyncClient):
        """DELETE /data-types/{id} returns 404 for unknown id."""
        resp = await authed_client.delete(f"/api/v1/data-types/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_referenced_returns_409(self, authed_client: AsyncClient, db_session: AsyncSession):
        """DELETE /data-types/{id} returns 409 when referenced by an agent type."""
        from app.db.models.agents import AgentInputType, AgentOutputType

        # Create a data type first
        payload = _valid_payload()
        create_resp = await authed_client.post("/api/v1/data-types", json=payload)
        assert create_resp.status_code == 201
        created = create_resp.json()
        data_type_id = uuid.UUID(created["id"])

        # Create an agent type that references this data type via db_session
        agent_type = AgentType(
            name=f"ref-agent-{uuid.uuid4().hex[:8]}",
            output_data_type_id=data_type_id,
            input_type=AgentInputType.typed,
            output_type=AgentOutputType.typed,
        )
        db_session.add(agent_type)
        await db_session.commit()

        # Now try to delete the data type
        resp = await authed_client.delete(f"/api/v1/data-types/{created['id']}")
        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
        data = resp.json()
        detail = data["detail"]
        assert "referencing_agent_types" in detail
        assert len(detail["referencing_agent_types"]) >= 1
        assert detail["referencing_agent_types"][0]["name"] == agent_type.name


class TestListDataTypes:
    """Tests for GET /api/v1/data-types."""

    @pytest_asyncio.fixture
    async def clean_db(self, test_engine):
        """Clean the agent_data_types table before and after these tests."""
        from app.db.session import Base
        async with test_engine.begin() as conn:
            await conn.execute(
                Base.metadata.tables["agent_data_types"].delete()
            )

    @pytest.mark.asyncio
    async def test_list_empty(self, authed_client: AsyncClient, clean_db):
        """GET /data-types returns empty list when no data types exist."""
        resp = await authed_client.get("/api/v1/data-types")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []
        assert data["page"] == 1
        assert data["page_size"] == 20

    @pytest.mark.asyncio
    async def test_list_pagination(self, authed_client: AsyncClient, clean_db):
        """GET /data-types supports pagination."""
        # Create 3 data types
        for i in range(3):
            payload = _valid_payload(name=f"page-test-{i}", slug=f"page-test-{i}")
            resp = await authed_client.post("/api/v1/data-types", json=payload)
            assert resp.status_code == 201

        # Get first page with page_size=2
        resp = await authed_client.get(
            "/api/v1/data-types", params={"page": 1, "page_size": 2}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["page_size"] == 2

        # Get second page
        resp2 = await authed_client.get(
            "/api/v1/data-types", params={"page": 2, "page_size": 2}
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert len(data2["items"]) == 1
        assert data2["total"] == 3

    @pytest.mark.asyncio
    async def test_list_search(self, authed_client: AsyncClient, clean_db):
        """GET /data-types supports search query."""
        payload = _valid_payload(name="searchable-type", slug="searchable-slug")
        await authed_client.post("/api/v1/data-types", json=payload)

        # Search by name
        resp = await authed_client.get(
            "/api/v1/data-types", params={"search": "searchable"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        names = [item["name"] for item in data["items"]]
        assert "searchable-type" in names

        # Search by non-matching term
        resp2 = await authed_client.get(
            "/api/v1/data-types", params={"search": "zzzznothing"}
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["total"] == 0
