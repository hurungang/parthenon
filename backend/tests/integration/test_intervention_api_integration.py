"""Integration tests: Conversation intervention API endpoints.

Tests cover:
- POST /conversations/{id}/interventions/{req_id}/respond — success, 404, 403
- GET /conversations/{id}/interventions/pending — returns pending, empty
- Existing conversation endpoints return turn_type and intervene_request_id

Uses module-scoped fixtures for shared seed data (identity, agent_type) since
the StaticPool in-memory SQLite is shared across all tests in the module and
unique constraints prevent duplicate subjects.
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
    ConversationSession, ConversationStatus, ConversationTurn, TurnRole, TurnType,
)
from app.db.models.identity import Identity
from app.db.models.intervene import (
    InterveneRequest, InterveneRequestStatus, InterventionType,
)
from app.db.session import Base, get_db
from app.main import create_app
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


@pytest_asyncio.fixture(scope="module")
async def test_engine():
    engine = create_async_engine(
        _INTEGRATION_URL, connect_args={"check_same_thread": False},
        poolclass=StaticPool, use_insertmanyvalues=False, echo=False,
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
        bind=test_engine, class_=AsyncSession, expire_on_commit=False,
        autocommit=False, autoflush=False,
    )
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="module")
async def shared_identity(test_engine) -> Identity:
    """Module-scoped identity with subject matching the patched JWT claim."""
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with SessionLocal() as session:
        ident = Identity(id=uuid.uuid4(), subject="test-user-sub", display_name="Test User")
        session.add(ident)
        await session.commit()
        return ident


@pytest_asyncio.fixture(scope="module")
async def shared_agent_type(test_engine) -> AgentType:
    """Module-scoped conversation agent type."""
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with SessionLocal() as session:
        at = AgentType(
            name=f"Shared-CA-{uuid.uuid4().hex}",
            input_type=AgentInputType.conversation, output_type=AgentOutputType.auto,
        )
        session.add(at)
        await session.commit()
        return at


@pytest_asyncio.fixture
async def async_client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    from app.api.deps import require_permission
    from app.core.resource_types import RT_AGENT_HUMAN_INTERVENTION, RT_AGENT_TRAILS
    from app.middleware.auth import JWTAuthMiddleware
    from unittest.mock import patch

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-user-sub"}
        return await call_next(request)

    patcher = patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)
    patcher.start()

    def _allow_all():
        return {"sub": "test-user-sub", "platform_user_id": None}

    app.dependency_overrides[require_permission(RT_AGENT_TRAILS, "read")] = _allow_all
    app.dependency_overrides[require_permission(RT_AGENT_HUMAN_INTERVENTION, "view")] = _allow_all
    app.dependency_overrides[require_permission(RT_AGENT_HUMAN_INTERVENTION, "respond")] = _allow_all

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    patcher.stop()
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _create_conv_session(
    db: AsyncSession, agent_type_id: uuid.UUID, user_id: uuid.UUID | None = None,
) -> ConversationSession:
    s = ConversationSession(
        agent_type_id=agent_type_id, triggered_by_user_id=user_id, status=ConversationStatus.active,
    )
    db.add(s)
    await db.flush()
    await db.refresh(s)
    return s


async def _create_job(db: AsyncSession, agent_type_id: uuid.UUID) -> AgentJob:
    job = AgentJob(id=uuid.uuid4(), agent_type_id=agent_type_id, status=AgentJobStatus.waiting_for_human)
    db.add(job)
    await db.flush()
    return job


# ── Test: GET /conversations/{id}/interventions/pending ──────────────────────

class TestPendingInterventionsEndpoint:

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_pending(self, db_session, async_client, shared_identity, shared_agent_type):
        conv_session = await _create_conv_session(db_session, shared_agent_type.id, shared_identity.id)
        await db_session.commit()

        with patch("app.api.v1.conversations._get_requesting_user_id", return_value=shared_identity.id):
            response = await async_client.get(
                f"/api/v1/conversations/{conv_session.id}/interventions/pending"
            )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_returns_pending_interventions(self, db_session, async_client, shared_identity, shared_agent_type):
        conv_session = await _create_conv_session(db_session, shared_agent_type.id, shared_identity.id)
        await db_session.commit()

        from app.services.agents.intervene_service import InterveneRequestStore
        store = InterveneRequestStore()
        agent_job = await _create_job(db_session, shared_agent_type.id)

        req = await store.create_request(
            db=db_session, agent_session_id=agent_job.id, agent_type_id=shared_agent_type.id,
            intervention_type=InterventionType.approval, reason="Test pending",
            conversation_session_id=conv_session.id, delegation_depth=1,
        )
        await db_session.commit()

        with patch("app.api.v1.conversations._get_requesting_user_id", return_value=shared_identity.id):
            response = await async_client.get(
                f"/api/v1/conversations/{conv_session.id}/interventions/pending"
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == str(req.id)
        assert data[0]["delegation_depth"] == 1

    @pytest.mark.asyncio
    async def test_404_for_nonexistent_session(self, async_client):
        fake_id = uuid.uuid4()
        with patch("app.api.v1.conversations._get_requesting_user_id", return_value=None):
            response = await async_client.get(
                f"/api/v1/conversations/{fake_id}/interventions/pending"
            )
        assert response.status_code == 404


# ── Test: POST /conversations/{id}/interventions/{req_id}/respond ────────────

class TestRespondToInterventionEndpoint:

    @pytest.mark.asyncio
    async def test_respond_success_approval(self, db_session, async_client, shared_identity, shared_agent_type):
        conv_session = await _create_conv_session(db_session, shared_agent_type.id, shared_identity.id)
        await db_session.commit()

        from app.services.agents.intervene_service import InterveneRequestStore
        store = InterveneRequestStore()
        agent_job = await _create_job(db_session, shared_agent_type.id)

        req = await store.create_request(
            db=db_session, agent_session_id=agent_job.id, agent_type_id=shared_agent_type.id,
            intervention_type=InterventionType.approval, reason="Approve?",
            conversation_session_id=conv_session.id, delegation_depth=0,
        )
        await db_session.commit()

        with patch("app.api.v1.conversations._get_requesting_user_id", return_value=shared_identity.id):
            response = await async_client.post(
                f"/api/v1/conversations/{conv_session.id}/interventions/{req.id}/respond",
                json={"request_id": str(req.id), "approval_value": True},
            )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["approval_value"] is True
        assert data["request_id"] == str(req.id)

        stmt = select(ConversationTurn).where(
            ConversationTurn.session_id == conv_session.id,
            ConversationTurn.turn_type == TurnType.intervene_response,
        )
        result = await db_session.execute(stmt)
        turns = result.scalars().all()
        assert len(turns) == 1

    @pytest.mark.asyncio
    async def test_respond_success_choice(self, db_session, async_client, shared_identity, shared_agent_type):
        conv_session = await _create_conv_session(db_session, shared_agent_type.id, shared_identity.id)
        await db_session.commit()

        from app.services.agents.intervene_service import InterveneRequestStore
        store = InterveneRequestStore()
        agent_job = await _create_job(db_session, shared_agent_type.id)

        req = await store.create_request(
            db=db_session, agent_session_id=agent_job.id, agent_type_id=shared_agent_type.id,
            intervention_type=InterventionType.choice, reason="Pick one",
            choices=["A", "B"], conversation_session_id=conv_session.id,
        )
        await db_session.commit()

        with patch("app.api.v1.conversations._get_requesting_user_id", return_value=shared_identity.id):
            response = await async_client.post(
                f"/api/v1/conversations/{conv_session.id}/interventions/{req.id}/respond",
                json={"request_id": str(req.id), "selected_choice": "A"},
            )
        assert response.status_code == 200
        assert response.json()["selected_choice"] == "A"

    @pytest.mark.asyncio
    async def test_respond_success_text(self, db_session, async_client, shared_identity, shared_agent_type):
        conv_session = await _create_conv_session(db_session, shared_agent_type.id, shared_identity.id)
        await db_session.commit()

        from app.services.agents.intervene_service import InterveneRequestStore
        store = InterveneRequestStore()
        agent_job = await _create_job(db_session, shared_agent_type.id)

        req = await store.create_request(
            db=db_session, agent_session_id=agent_job.id, agent_type_id=shared_agent_type.id,
            intervention_type=InterventionType.text, reason="Enter text",
            conversation_session_id=conv_session.id,
        )
        await db_session.commit()

        with patch("app.api.v1.conversations._get_requesting_user_id", return_value=shared_identity.id):
            response = await async_client.post(
                f"/api/v1/conversations/{conv_session.id}/interventions/{req.id}/respond",
                json={"request_id": str(req.id), "text_value": "My text response"},
            )
        assert response.status_code == 200
        assert response.json()["text_value"] == "My text response"

    @pytest.mark.asyncio
    async def test_404_conversation_not_found(self, async_client):
        fake_conv_id = uuid.uuid4()
        fake_req_id = uuid.uuid4()
        with patch("app.api.v1.conversations._get_requesting_user_id", return_value=None):
            response = await async_client.post(
                f"/api/v1/conversations/{fake_conv_id}/interventions/{fake_req_id}/respond",
                json={"request_id": str(fake_req_id), "approval_value": True},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_404_request_not_found(self, db_session, async_client, shared_identity, shared_agent_type):
        conv_session = await _create_conv_session(db_session, shared_agent_type.id, shared_identity.id)
        await db_session.commit()

        fake_req_id = uuid.uuid4()
        with patch("app.api.v1.conversations._get_requesting_user_id", return_value=shared_identity.id):
            response = await async_client.post(
                f"/api/v1/conversations/{conv_session.id}/interventions/{fake_req_id}/respond",
                json={"request_id": str(fake_req_id), "approval_value": True},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_422_path_body_mismatch(self, db_session, async_client, shared_identity, shared_agent_type):
        conv_session = await _create_conv_session(db_session, shared_agent_type.id, shared_identity.id)
        await db_session.commit()

        from app.services.agents.intervene_service import InterveneRequestStore
        store = InterveneRequestStore()
        agent_job = await _create_job(db_session, shared_agent_type.id)

        req = await store.create_request(
            db=db_session, agent_session_id=agent_job.id, agent_type_id=shared_agent_type.id,
            intervention_type=InterventionType.approval, reason="Mismatch",
            conversation_session_id=conv_session.id,
        )
        await db_session.commit()

        other_id = uuid.uuid4()
        with patch("app.api.v1.conversations._get_requesting_user_id", return_value=shared_identity.id):
            response = await async_client.post(
                f"/api/v1/conversations/{conv_session.id}/interventions/{req.id}/respond",
                json={"request_id": str(other_id), "approval_value": True},
            )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_422_invalid_response_body(self, db_session, async_client, shared_identity, shared_agent_type):
        conv_session = await _create_conv_session(db_session, shared_agent_type.id, shared_identity.id)
        await db_session.commit()

        from app.services.agents.intervene_service import InterveneRequestStore
        store = InterveneRequestStore()
        agent_job = await _create_job(db_session, shared_agent_type.id)

        req = await store.create_request(
            db=db_session, agent_session_id=agent_job.id, agent_type_id=shared_agent_type.id,
            intervention_type=InterventionType.approval, reason="Invalid body",
            conversation_session_id=conv_session.id,
        )
        await db_session.commit()

        with patch("app.api.v1.conversations._get_requesting_user_id", return_value=shared_identity.id):
            response = await async_client.post(
                f"/api/v1/conversations/{conv_session.id}/interventions/{req.id}/respond",
                json={"request_id": str(req.id)},
            )
        assert response.status_code == 422


# ── Test: Existing endpoints return new fields ───────────────────────────────

class TestExistingEndpointsReturnNewFields:

    @pytest.mark.asyncio
    async def test_get_conversation_returns_turn_type(self, db_session, async_client, shared_identity, shared_agent_type):
        conv_session = await _create_conv_session(db_session, shared_agent_type.id, shared_identity.id)
        await db_session.commit()

        from app.services.conversations.store import ConversationStore
        store = ConversationStore()
        await store.add_turn(session_id=conv_session.id, role=TurnRole.user, content="Hello", db=db_session, turn_type=TurnType.message)
        await store.add_turn(session_id=conv_session.id, role=TurnRole.system, content="IR", db=db_session, turn_type=TurnType.intervene_request)
        await db_session.commit()

        response = await async_client.get(f"/api/v1/conversations/{conv_session.id}")
        assert response.status_code == 200
        data = response.json()
        assert "turns" in data
        assert len(data["turns"]) == 2
        turn_types = [t["turn_type"] for t in data["turns"]]
        assert "message" in turn_types
        assert "intervene_request" in turn_types

    @pytest.mark.asyncio
    async def test_resume_returns_intervene_request_id(self, db_session, async_client, shared_identity, shared_agent_type):
        conv_session = await _create_conv_session(db_session, shared_agent_type.id, shared_identity.id)
        await db_session.commit()

        from app.services.agents.intervene_service import InterveneRequestStore
        from app.services.conversations.store import ConversationStore

        int_store = InterveneRequestStore()
        agent_job = await _create_job(db_session, shared_agent_type.id)

        req = await int_store.create_request(
            db=db_session, agent_session_id=agent_job.id, agent_type_id=shared_agent_type.id,
            intervention_type=InterventionType.approval, reason="Linked turn test",
            conversation_session_id=conv_session.id,
        )
        await db_session.commit()

        conv_store = ConversationStore()
        await conv_store.add_turn(
            session_id=conv_session.id, role=TurnRole.system, content="IR turn",
            db=db_session, turn_type=TurnType.intervene_request, intervene_request_id=req.id,
        )
        await db_session.commit()

        with patch("app.api.v1.conversations._get_requesting_user_id", return_value=shared_identity.id):
            response = await async_client.post(f"/api/v1/conversations/{conv_session.id}/resume")
        assert response.status_code == 200
        data = response.json()
        assert "turns" in data
        int_turns = [t for t in data["turns"] if t["turn_type"] == "intervene_request"]
        assert len(int_turns) >= 1
        assert int_turns[0]["intervene_request_id"] == str(req.id)
