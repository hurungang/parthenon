"""Terminal outcome delivery for paused conversational turns (task 5.3).

Replaces the legacy fixed "interrupted by a service restart" notice with a
reason-keyed, actionable outcome:

* a durably unresumable turn (no durable resume state / unresumable dispatch)
  persists **exactly one** outcome turn naming what happened and the next step,
  sets the terminal activity state, and pushes it to the live chat;
* an elapsed answer window closes as ``unresumable/expired`` with **no**
  dispatch and its own distinct text;
* a transport failure (Communication Hub unreachable) leaves the pause
  answerable — the Terminal Resolver owns the eventual outcome, so no outcome
  turn is fabricated here;
* a successfully resumed turn never receives an outcome notice.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
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
from app.db.models.conversation_activity import ActivityState
from app.db.models.conversation_turn_resume import (
    ConversationTurnResume,
    ResumeOutcome,
    ResumeState,
)
from app.db.models.conversations import (
    ConversationSession, ConversationStatus, ConversationTurn, TurnRole, TurnType,
)
from app.db.models.identity import Identity
from app.db.models.intervene import (
    InterveneRequest, InterveneRequestStatus, InterventionType,
)
from app.db.session import Base, get_db
from app.main import create_app
from app.services.conversations.activity_store import ConversationActivityStore
from app.services.conversations.turn_resolution import (
    REASON_CHECKPOINT_UNAVAILABLE,
    REASON_EXPIRED,
    outcome_message_for_reason,
)
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
    expires_at: datetime | None = None,
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
    if expires_at is not None:
        req.expires_at = expires_at
        resume = (
            await db.execute(
                select(ConversationTurnResume).where(
                    ConversationTurnResume.intervene_request_id == req.id
                )
            )
        ).scalar_one_or_none()
        if resume is not None:
            resume.expires_at = expires_at
    await db.commit()
    return conv, req


async def _agent_message_turns(
    db: AsyncSession, session_id: uuid.UUID
) -> list[ConversationTurn]:
    stmt = select(ConversationTurn).where(
        ConversationTurn.session_id == session_id,
        ConversationTurn.role == TurnRole.agent,
        ConversationTurn.turn_type == TurnType.message,
    )
    return list((await db.execute(stmt)).scalars().all())


async def _resume_of(db: AsyncSession, request_id: uuid.UUID) -> ConversationTurnResume:
    row = (
        await db.execute(
            select(ConversationTurnResume).where(
                ConversationTurnResume.intervene_request_id == request_id
            )
        )
    ).scalar_one()
    return row


class TestTerminalOutcomeDelivery:

    @pytest.mark.asyncio
    async def test_unresumable_dispatch_persists_one_reason_keyed_turn(
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

        expected = outcome_message_for_reason(REASON_CHECKPOINT_UNAVAILABLE)
        turns = await _agent_message_turns(db_session, conv.id)
        assert len(turns) == 1
        assert turns[0].content == expected
        assert "Nothing was applied" in turns[0].content
        assert str(turns[0].intervene_request_id) == str(req.id)

        resume = await _resume_of(db_session, req.id)
        assert resume.state is ResumeState.unresumable
        assert resume.resume_outcome is ResumeOutcome.resume_failed
        assert resume.terminal_reason_code == REASON_CHECKPOINT_UNAVAILABLE
        assert resume.outcome_turn_id == turns[0].id
        assert resume.write_applied is False

        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.is_terminal is True
        assert activity.state is ActivityState.failed

        fake_hub.return_value.dispatch_message.assert_awaited_once()
        kwargs = fake_hub.return_value.dispatch_message.await_args.kwargs
        assert kwargs["message_type"] == "chat_message"
        assert kwargs["content"]["sender_role"] == "agent"
        assert kwargs["content"]["content"] == expected

    @pytest.mark.asyncio
    async def test_expired_window_marks_expired_and_never_dispatches(
        self, db_session, async_client, shared_identity, shared_agent_type,
    ) -> None:
        conv, req = await _seed_pending_intervention(
            db_session,
            shared_agent_type.id,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )

        resume_mock = AsyncMock(return_value="resumed")
        with patch("app.api.v1.intervene._resume_agent_session", new=resume_mock):
            with patch(
                "app.api.v1.conversations._get_requesting_user_id", return_value=None
            ):
                response = await async_client.post(
                    f"/api/v1/conversations/{conv.id}/interventions/{req.id}/respond",
                    json={"request_id": str(req.id), "approval_value": True},
                )

        assert response.status_code == 200, response.text
        resume_mock.assert_not_awaited()

        resume = await _resume_of(db_session, req.id)
        assert resume.state is ResumeState.unresumable
        assert resume.terminal_reason_code == REASON_EXPIRED
        assert resume.write_applied is False

        turns = await _agent_message_turns(db_session, conv.id)
        assert len(turns) == 1
        assert turns[0].content == outcome_message_for_reason(REASON_EXPIRED)
        # Distinct wording from the lost-pause-point case.
        assert turns[0].content != outcome_message_for_reason(
            REASON_CHECKPOINT_UNAVAILABLE
        )

        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.state is ActivityState.timed_out

    @pytest.mark.asyncio
    async def test_transport_failure_keeps_turn_resumable(
        self, db_session, async_client, shared_identity, shared_agent_type,
    ) -> None:
        """CH unreachable → dispatch status None.  The pause stays answerable and
        no outcome turn is fabricated (the Terminal Resolver owns it)."""
        conv, req = await _seed_pending_intervention(db_session, shared_agent_type.id)

        with patch(
            "app.api.v1.intervene._resume_agent_session",
            new=AsyncMock(return_value=None),
        ):
            with patch("app.services.control_center.comm_hub_client.CommunicationHubClient"):
                with patch(
                    "app.api.v1.conversations._get_requesting_user_id", return_value=None
                ):
                    response = await async_client.post(
                        f"/api/v1/conversations/{conv.id}/interventions/{req.id}/respond",
                        json={"request_id": str(req.id), "approval_value": True},
                    )

        assert response.status_code == 200, response.text
        assert await _agent_message_turns(db_session, conv.id) == []

        resume = await _resume_of(db_session, req.id)
        assert resume.is_terminal is False
        assert resume.state is ResumeState.resuming

    @pytest.mark.asyncio
    async def test_resumed_status_does_not_add_notice(
        self, db_session, async_client, shared_identity, shared_agent_type,
    ) -> None:
        """A successfully resumed turn must never receive an outcome notice."""
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
        assert await _agent_message_turns(db_session, conv.id) == []

    @pytest.mark.asyncio
    async def test_repeated_unresumable_responses_keep_one_outcome_turn(
        self, db_session, async_client, shared_identity, shared_agent_type,
    ) -> None:
        """The outcome turn is guarded by ``outcome_turn_id``: a second attempt
        against the same answered turn appends nothing."""
        from app.services.conversations.turn_resolution import (
            resolve_unresumable_turn,
        )

        conv, req = await _seed_pending_intervention(db_session, shared_agent_type.id)
        first = await resolve_unresumable_turn(
            db_session,
            conv.id,
            reason_code=REASON_CHECKPOINT_UNAVAILABLE,
            intervene_request_id=req.id,
        )
        await db_session.commit()
        second = await resolve_unresumable_turn(
            db_session,
            conv.id,
            reason_code=REASON_CHECKPOINT_UNAVAILABLE,
            intervene_request_id=req.id,
        )
        await db_session.commit()

        assert first is not None and second is not None
        assert first.outcome_turn_id == second.outcome_turn_id
        assert second.write_applied is False
        turns = await _agent_message_turns(db_session, conv.id)
        assert len(turns) == 1
