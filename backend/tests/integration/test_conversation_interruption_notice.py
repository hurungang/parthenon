"""FIX (conversational resume orphan) — CC unblocks the chat when AR reports
``not_awaiting`` (or the resume call fails).

When the suspended conversational turn was orphaned by a service restart, AR
returns ``status="not_awaiting"``.  CC must persist a terminal assistant turn
with an actionable interruption message and push it to the live chat via the
Communication Hub, so the user's chat never stays stuck in "thinking".
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.models.agents import AgentInputType, AgentOutputType, AgentType
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

_EXPECTED_MESSAGE = (
    "This conversation was interrupted by a service restart and the pending "
    "action was lost. Please resend your request."
)


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
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with SessionLocal() as session:
        ident = Identity(id=uuid.uuid4(), subject="interruption-notice-user", display_name="Test User")
        session.add(ident)
        await session.commit()
        return ident


@pytest_asyncio.fixture(scope="module")
async def shared_agent_type(test_engine) -> AgentType:
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with SessionLocal() as session:
        at = AgentType(
            name=f"Notice-CA-{uuid.uuid4().hex}",
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

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "interruption-notice-user"}
        return await call_next(request)

    patcher = patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)
    patcher.start()

    def _allow_all():
        return {"sub": "interruption-notice-user", "platform_user_id": None}

    app.dependency_overrides[require_permission(RT_AGENT_TRAILS, "read")] = _allow_all
    app.dependency_overrides[require_permission(RT_AGENT_HUMAN_INTERVENTION, "view")] = _allow_all
    app.dependency_overrides[require_permission(RT_AGENT_HUMAN_INTERVENTION, "respond")] = _allow_all

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    patcher.stop()
    app.dependency_overrides.clear()


async def _seed_pending_intervention(
    db: AsyncSession, agent_type_id: uuid.UUID,
    agent_session_id: uuid.UUID | None = None,
) -> tuple[ConversationSession, InterveneRequest]:
    conv = ConversationSession(
        agent_type_id=agent_type_id, triggered_by_user_id=None,
        status=ConversationStatus.active,
    )
    db.add(conv)
    await db.flush()

    from app.services.agents.intervene_service import InterveneRequestStore
    req = await InterveneRequestStore().create_request(
        db=db, agent_session_id=agent_session_id, agent_type_id=agent_type_id,
        intervention_type=InterventionType.approval, reason="Approve?",
        conversation_session_id=conv.id, delegation_depth=0,
    )
    await db.commit()
    return conv, req


class TestInterruptionNotice:

    @pytest.mark.asyncio
    async def test_not_awaiting_persists_agent_turn_and_pushes_live(
        self, db_session, async_client, shared_identity, shared_agent_type,
    ) -> None:
        conv, req = await _seed_pending_intervention(db_session, shared_agent_type.id)

        fake_hub = AsyncMock()
        fake_hub.return_value.dispatch_message = AsyncMock(
            return_value={"dispatched": True, "subscribers": 1}
        )

        with patch(
            "app.api.v1.intervene._resume_agent_session",
            new=AsyncMock(return_value="not_awaiting"),
        ):
            with patch(
                "app.services.control_center.comm_hub_client.CommunicationHubClient",
                return_value=fake_hub.return_value,
            ):
                with patch(
                    "app.api.v1.conversations._get_requesting_user_id",
                    return_value=None,
                ):
                    response = await async_client.post(
                        f"/api/v1/conversations/{conv.id}/interventions/{req.id}/respond",
                        json={"request_id": str(req.id), "approval_value": True},
                    )

        assert response.status_code == 200, response.text

        # Terminal assistant turn persisted with the actionable message.
        stmt = select(ConversationTurn).where(
            ConversationTurn.session_id == conv.id,
            ConversationTurn.role == TurnRole.agent,
            ConversationTurn.turn_type == TurnType.message,
        )
        turns = (await db_session.execute(stmt)).scalars().all()
        assert len(turns) == 1
        assert turns[0].content == _EXPECTED_MESSAGE
        assert str(turns[0].intervene_request_id) == str(req.id)

        # Live push best-effort via CH dispatch with the chat_message payload.
        fake_hub.return_value.dispatch_message.assert_awaited_once()
        kwargs = fake_hub.return_value.dispatch_message.await_args.kwargs
        assert kwargs["message_type"] == "chat_message"
        assert kwargs["content"]["sender_role"] == "agent"
        assert kwargs["content"]["content"] == _EXPECTED_MESSAGE

    @pytest.mark.asyncio
    async def test_resume_failure_also_persists_notice(
        self, db_session, async_client, shared_identity, shared_agent_type,
    ) -> None:
        conv, req = await _seed_pending_intervention(db_session, shared_agent_type.id)

        with patch(
            "app.api.v1.intervene._resume_agent_session",
            new=AsyncMock(return_value=None),  # resume call failed
        ):
            with patch(
                "app.services.control_center.comm_hub_client.CommunicationHubClient",
            ):
                with patch(
                    "app.api.v1.conversations._get_requesting_user_id",
                    return_value=None,
                ):
                    response = await async_client.post(
                        f"/api/v1/conversations/{conv.id}/interventions/{req.id}/respond",
                        json={"request_id": str(req.id), "approval_value": True},
                    )

        assert response.status_code == 200, response.text
        stmt = select(ConversationTurn).where(
            ConversationTurn.session_id == conv.id,
            ConversationTurn.role == TurnRole.agent,
        )
        turns = (await db_session.execute(stmt)).scalars().all()
        assert any(t.content == _EXPECTED_MESSAGE for t in turns)

    @pytest.mark.asyncio
    async def test_resumed_status_does_not_add_notice(
        self, db_session, async_client, shared_identity, shared_agent_type,
    ) -> None:
        """Normal resume path must NOT inject the interruption notice."""
        conv, req = await _seed_pending_intervention(
            db_session, shared_agent_type.id, agent_session_id=uuid.uuid4()
        )

        with patch(
            "app.api.v1.intervene._resume_agent_session",
            new=AsyncMock(return_value="resumed"),
        ):
            with patch(
                "app.api.v1.conversations._get_requesting_user_id",
                return_value=None,
            ):
                response = await async_client.post(
                    f"/api/v1/conversations/{conv.id}/interventions/{req.id}/respond",
                    json={"request_id": str(req.id), "approval_value": True},
                )

        assert response.status_code == 200, response.text
        stmt = select(ConversationTurn).where(
            ConversationTurn.session_id == conv.id,
            ConversationTurn.role == TurnRole.agent,
        )
        turns = (await db_session.execute(stmt)).scalars().all()
        assert turns == []
