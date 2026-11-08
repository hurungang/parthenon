"""Reproduction test: GET /api/v1/intervene/requests with a NULL agent_session_id.

Context (FIX-20261031-133253): conversation-scoped intervene requests persist
``agent_session_id = NULL`` in the DB. ``InterveneRequestRead`` currently
declares ``agent_session_id: uuid.UUID`` (required), so FastAPI's response
validation raises a ResponseValidationError (uuid_type) for every such row and
the endpoint returns HTTP 500. Expected behavior: the row serializes fine with
``agent_session_id: null`` and the endpoint returns 200.

Follows the conventions of test_intervene.py (SQLite in-memory StaticPool,
auth dependency overrides), but without the module-level skip marker.
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.models.agents import AgentType
from app.db.models.intervene import (
    InterveneRequest,
    InterveneRequestStatus,
    InterventionType,
)
from app.db.session import Base, get_db
from app.main import create_app

# ── Fixtures (same pattern as tests/integration/conftest.py) ────────────────

_INTEGRATION_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="module")
async def test_engine():
    engine = create_async_engine(
        _INTEGRATION_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        use_insertmanyvalues=False,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def async_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    SessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    from app.api.deps import require_permission
    from app.middleware.auth import JWTAuthMiddleware

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-user-sub"}
        return await call_next(request)

    patcher = patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)
    patcher.start()

    def _allow_all():
        return {"sub": "test-user-sub"}

    app.dependency_overrides[require_permission("agent::human_intervention", "view")] = _allow_all
    app.dependency_overrides[require_permission("agent::human_intervention", "respond")] = _allow_all

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    patcher.stop()
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def conversation_scoped_request(db_session: AsyncSession) -> InterveneRequest:
    """Seed an intervene request with agent_session_id = NULL (conversation-scoped)."""
    agent_type = AgentType(id=uuid.uuid4(), name=f"assistant-{uuid.uuid4().hex[:8]}")
    db_session.add(agent_type)
    await db_session.flush()

    req = InterveneRequest(
        id=uuid.uuid4(),
        agent_session_id=None,  # conversation-scoped: no agent_jobs row
        agent_type_id=agent_type.id,
        conversation_session_id=None,
        intervention_type=InterventionType.approval,
        reason="May I proceed?",
        status=InterveneRequestStatus.pending,
        delegation_depth=0,
    )
    db_session.add(req)
    await db_session.commit()
    # Refresh so column attributes (e.g. created_at, server_default) are loaded
    # in-memory; then materialize the (empty) response relationship explicitly
    # to avoid an async lazy-load during schema validation outside greenlet ctx.
    await db_session.refresh(req)
    req.response = None
    return req


# ── Reproduction tests ──────────────────────────────────────────────────────


class TestNullAgentSessionSerialization:
    @pytest.mark.asyncio
    async def test_read_schema_accepts_null_agent_session_id(
        self, conversation_scoped_request: InterveneRequest
    ):
        """InterveneRequestRead must serialize a row with agent_session_id=None."""
        from app.schemas.intervene import InterveneRequestRead

        parsed = InterveneRequestRead.model_validate(conversation_scoped_request)
        assert parsed.agent_session_id is None, (
            "InterveneRequestRead rejected agent_session_id=None — "
            "schema still declares it as required uuid.UUID"
        )

    @pytest.mark.asyncio
    async def test_list_requests_returns_200_with_null_agent_session_id(
        self, async_client, conversation_scoped_request: InterveneRequest
    ):
        """GET /api/v1/intervene/requests must return 200 for NULL agent_session_id rows."""
        response = await async_client.get("/api/v1/intervene/requests")
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        data = response.json()
        row = next(r for r in data if r["id"] == str(conversation_scoped_request.id))
        assert row["agent_session_id"] is None
        assert row["reason"] == "May I proceed?"
        assert row["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_request_by_id_returns_200_with_null_agent_session_id(
        self, async_client, conversation_scoped_request: InterveneRequest
    ):
        """GET /api/v1/intervene/requests/{id} must return 200 for such rows too."""
        response = await async_client.get(
            f"/api/v1/intervene/requests/{conversation_scoped_request.id}"
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert data["agent_session_id"] is None
