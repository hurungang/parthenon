"""Integration tests: Non-conversational intervention flow preservation (regression).

Tests cover:
- Non-conversational intervention requests still work with NULL conversation_session_id
- Dashboard polling still returns intervention requests
- Session state transitions preserved
- Existing InterveneRequest records without conversation_session_id function normally
"""

import os
import uuid
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.models.agents import AgentInputType, AgentOutputType, AgentType, AgentJob, AgentJobStatus
from app.db.models.conversations import (
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
    TurnRole,
    TurnType,
)
from app.db.models.identity import Identity
from app.db.models.intervene import (
    InterveneRequest,
    InterveneRequestStatus,
    InterveneResponse,
    InterventionType,
)
from app.db.session import Base, get_db
from app.main import create_app

# ── SQLite + UUID compatibility ──────────────────────────────────────────────
from sqlalchemy.dialects.postgresql import UUID as _PG_UUID

_INTEGRATION_URL = "sqlite+aiosqlite:///:memory:"

_orig_pg_uuid_result_processor = _PG_UUID.result_processor


def _sqlite_tolerant_uuid_result_processor(self, dialect, coltype):
    orig_proc = _orig_pg_uuid_result_processor(self, dialect, coltype)
    if dialect.name != "sqlite" or orig_proc is None:
        return orig_proc

    def proc(value: object) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, int):
            return uuid.UUID(int=value)
        return orig_proc(value)

    return proc


_PG_UUID.result_processor = _sqlite_tolerant_uuid_result_processor


# ── Fixtures ─────────────────────────────────────────────────────────────────

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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
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
    from unittest.mock import patch

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-user-sub"}
        return await call_next(request)

    patcher = patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)
    patcher.start()

    def _allow_all():
        return {"sub": "test-user-sub"}

    app.dependency_overrides[require_permission("intervene", "view")] = _allow_all
    app.dependency_overrides[require_permission("intervene", "respond")] = _allow_all

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    patcher.stop()
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _create_seed_data(db_session: AsyncSession) -> dict:
    """Create minimal test seed data."""
    identity = Identity(id=uuid.uuid4(), subject=f"test-nonconv-{uuid.uuid4().hex}")
    db_session.add(identity)
    await db_session.flush()

    agent_type = AgentType(
        name=f"NonConv-Agent-{uuid.uuid4().hex}",
        input_type=AgentInputType.none,
        output_type=AgentOutputType.auto,
    )
    db_session.add(agent_type)
    await db_session.flush()

    agent_job = AgentJob(
        id=uuid.uuid4(),
        agent_type_id=agent_type.id,
        status=AgentJobStatus.waiting_for_human,
    )
    db_session.add(agent_job)
    await db_session.flush()

    return {
        "identity_id": identity.id,
        "agent_type_id": agent_type.id,
        "agent_job_id": agent_job.id,
    }


# ── Tests ────────────────────────────────────────────────────────────────────

class TestNonConversationalFlowPreservation:
    """Verify non-conversational intervention flow continues to work."""

    @pytest.mark.asyncio
    async def test_create_request_without_conversation_session_id(self, db_session: AsyncSession):
        """InterveneRequest can be created with NULL conversation_session_id."""
        from app.services.agents.intervene_service import InterveneRequestStore

        seed = await _create_seed_data(db_session)
        await db_session.commit()

        store = InterveneRequestStore()
        req = await store.create_request(
            db=db_session,
            agent_session_id=seed["agent_job_id"],
            agent_type_id=seed["agent_type_id"],
            intervention_type=InterventionType.approval,
            reason="Non-conversational approval request",
        )
        await db_session.commit()

        assert req.conversation_session_id is None, (
            "Non-conversational request must have NULL conversation_session_id"
        )
        assert req.delegation_depth == 0, (
            "Non-conversational request must have default delegation_depth=0"
        )
        assert req.status == InterveneRequestStatus.pending

    @pytest.mark.asyncio
    async def test_respond_without_conversation_session_id(self, db_session: AsyncSession):
        """Submitting response to non-conversational request works without creating turn."""
        from app.services.agents.intervene_service import InterveneRequestStore

        seed = await _create_seed_data(db_session)
        await db_session.commit()

        store = InterveneRequestStore()
        req = await store.create_request(
            db=db_session,
            agent_session_id=seed["agent_job_id"],
            agent_type_id=seed["agent_type_id"],
            intervention_type=InterventionType.approval,
            reason="Non-conversational response test",
        )
        await db_session.commit()

        response = await store.submit_response(
            db=db_session,
            request_id=req.id,
            operator_user_id=seed["identity_id"],
            approval_value=True,
        )
        await db_session.commit()

        assert response.id is not None
        assert response.approval_value is True

        # Verify NO conversation turn was created (since conversation_session_id is NULL)
        stmt = select(ConversationTurn).where(
            ConversationTurn.turn_type == TurnType.intervene_response
        )
        result = await db_session.execute(stmt)
        turns = result.scalars().all()
        assert len(turns) == 0, "Non-conversational response must not create conversation turns"

        # Verify status transitioned
        await db_session.refresh(req)
        assert req.status == InterveneRequestStatus.responded

    @pytest.mark.asyncio
    async def test_agent_job_status_transition_preserved(self, db_session: AsyncSession):
        """AgentJob status transitions from waiting_for_human to running on response."""
        from app.services.agents.intervene_service import InterveneRequestStore

        seed = await _create_seed_data(db_session)
        await db_session.commit()

        store = InterveneRequestStore()
        req = await store.create_request(
            db=db_session,
            agent_session_id=seed["agent_job_id"],
            agent_type_id=seed["agent_type_id"],
            intervention_type=InterventionType.choice,
            reason="Status transition test",
            choices=["A", "B"],
        )
        await db_session.commit()

        # Verify initial status
        agent_job = await db_session.get(AgentJob, seed["agent_job_id"])
        assert agent_job.status == AgentJobStatus.waiting_for_human

        # Submit response
        await store.submit_response(
            db=db_session,
            request_id=req.id,
            operator_user_id=seed["identity_id"],
            selected_choice="A",
        )
        await db_session.commit()

        # Verify status transitioned
        await db_session.refresh(agent_job)
        assert agent_job.status == AgentJobStatus.running, (
            f"Expected running, got {agent_job.status}"
        )

    @pytest.mark.asyncio
    async def test_non_conv_request_listed_in_dashboard(self, db_session: AsyncSession, async_client: AsyncClient):
        """Non-conversational intervention requests appear in GET /intervene/requests."""
        from app.services.agents.intervene_service import InterveneRequestStore

        seed = await _create_seed_data(db_session)
        await db_session.commit()

        store = InterveneRequestStore()
        req = await store.create_request(
            db=db_session,
            agent_session_id=seed["agent_job_id"],
            agent_type_id=seed["agent_type_id"],
            intervention_type=InterventionType.text,
            reason="Dashboard visibility test",
        )
        await db_session.commit()

        # List via API
        response = await async_client.get("/api/v1/intervene/requests")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

        # Find our request
        found = [r for r in data if r["id"] == str(req.id)]
        assert len(found) == 1
        assert found[0]["conversation_session_id"] is None
        assert found[0]["delegation_depth"] == 0

    @pytest.mark.asyncio
    async def test_non_conv_cancel_flow(self, db_session: AsyncSession, async_client: AsyncClient):
        """Non-conversational cancel flow works unchanged."""
        from app.services.agents.intervene_service import InterveneRequestStore

        seed = await _create_seed_data(db_session)
        await db_session.commit()

        store = InterveneRequestStore()
        req = await store.create_request(
            db=db_session,
            agent_session_id=seed["agent_job_id"],
            agent_type_id=seed["agent_type_id"],
            intervention_type=InterventionType.approval,
            reason="Cancel flow test",
        )
        await db_session.commit()

        response = await async_client.post(f"/api/v1/intervene/requests/{req.id}/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelled"

        # Verify database state
        await db_session.refresh(req)
        assert req.status == InterveneRequestStatus.cancelled
        assert req.conversation_session_id is None  # still NULL

    @pytest.mark.asyncio
    async def test_non_conv_metrics_unchanged(self, db_session: AsyncSession, async_client: AsyncClient):
        """GET /intervene/metrics still works for non-conversational requests."""
        from app.services.agents.intervene_service import InterveneRequestStore

        seed = await _create_seed_data(db_session)
        await db_session.commit()

        store = InterveneRequestStore()
        await store.create_request(
            db=db_session,
            agent_session_id=seed["agent_job_id"],
            agent_type_id=seed["agent_type_id"],
            intervention_type=InterventionType.approval,
            reason="Metrics test",
        )
        await db_session.commit()

        response = await async_client.get("/api/v1/intervene/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "pending_count" in data
        assert "avg_response_time_seconds" in data
        assert "resolution_rate" in data

    @pytest.mark.asyncio
    async def test_mixed_conversational_and_non_conv(self, db_session: AsyncSession):
        """Both conversational and non-conversational requests coexist peacefully."""
        from app.services.agents.intervene_service import InterveneRequestStore

        seed = await _create_seed_data(db_session)
        await db_session.commit()

        # Create a conversation session for the conversational request
        conv_session = ConversationSession(
            agent_type_id=seed["agent_type_id"],
            status=ConversationStatus.active,
        )
        db_session.add(conv_session)
        await db_session.flush()

        # Create second agent job for conversational request
        conv_job = AgentJob(
            id=uuid.uuid4(),
            agent_type_id=seed["agent_type_id"],
            status=AgentJobStatus.waiting_for_human,
        )
        db_session.add(conv_job)
        await db_session.flush()

        store = InterveneRequestStore()

        # Non-conversational request
        non_conv = await store.create_request(
            db=db_session,
            agent_session_id=seed["agent_job_id"],
            agent_type_id=seed["agent_type_id"],
            intervention_type=InterventionType.approval,
            reason="Non-conv",
            conversation_session_id=None,
        )

        # Conversational request
        conv = await store.create_request(
            db=db_session,
            agent_session_id=conv_job.id,
            agent_type_id=seed["agent_type_id"],
            intervention_type=InterventionType.choice,
            reason="Conv",
            conversation_session_id=conv_session.id,
            delegation_depth=1,
        )
        await db_session.commit()

        # Verify both persisted correctly
        assert non_conv.conversation_session_id is None
        assert non_conv.delegation_depth == 0
        assert conv.conversation_session_id == conv_session.id
        assert conv.delegation_depth == 1

        # Verify list_pending_for_conversation returns only conv request
        pending = await store.list_pending_for_conversation(
            db=db_session,
            conversation_session_id=conv_session.id,
        )
        assert len(pending) == 1
        assert pending[0].id == conv.id
