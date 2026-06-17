"""Integration tests: Database schema verification for conversation intervention fields.

Tests cover:
- New columns on conversation_turns (turn_type, intervene_request_id)
- New columns on intervene_requests (conversation_session_id, delegation_depth)
- Enum value verification for turn_type_enum
- NULL acceptance for intervene_request_id and conversation_session_id
- FK constraints on new columns
"""

import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversations import (
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
    TurnRole,
    TurnType,
)
from app.db.models.identity import Identity
from app.db.models.intervene import InterveneRequest, InterveneRequestStatus, InterventionType
from app.db.models.agents import AgentInputType, AgentJob, AgentJobStatus, AgentType


async def _seed(db: AsyncSession):
    """Create and persist identity, agent_type, agent_job with proper flush ordering."""
    ident = Identity(id=uuid.uuid4(), subject=f"schema-test-{uuid.uuid4().hex}")
    db.add(ident)
    await db.flush()

    at = AgentType(name=f"schema-at-{uuid.uuid4().hex}", input_type=AgentInputType.conversation)
    db.add(at)
    await db.flush()

    job = AgentJob(id=uuid.uuid4(), agent_type_id=at.id, status=AgentJobStatus.waiting_for_human)
    db.add(job)
    await db.flush()

    return ident, at, job


class TestSchemaColumnsExist:
    """Verify new columns exist on the relevant tables (via SQLAlchemy ORM)."""

    @pytest.mark.asyncio
    async def test_turn_type_column_on_conversation_turns(self, db_session: AsyncSession):
        session = ConversationSession(status=ConversationStatus.active)
        db_session.add(session)
        await db_session.flush()

        turn = ConversationTurn(session_id=session.id, role=TurnRole.user, content="Schema test")
        db_session.add(turn)
        await db_session.flush()
        await db_session.refresh(turn)

        assert hasattr(turn, "turn_type")
        assert turn.turn_type == TurnType.message

    @pytest.mark.asyncio
    async def test_intervene_request_id_column_on_conversation_turns(self, db_session: AsyncSession):
        session = ConversationSession(status=ConversationStatus.active)
        db_session.add(session)
        await db_session.flush()

        turn = ConversationTurn(
            session_id=session.id, role=TurnRole.user, content="Schema test", intervene_request_id=None,
        )
        db_session.add(turn)
        await db_session.flush()
        await db_session.refresh(turn)

        assert hasattr(turn, "intervene_request_id")
        assert turn.intervene_request_id is None

    @pytest.mark.asyncio
    async def test_conversation_session_id_on_intervene_requests(self, db_session: AsyncSession):
        _, at, job = await _seed(db_session)

        req = InterveneRequest(
            agent_session_id=job.id, agent_type_id=at.id,
            intervention_type=InterventionType.approval, reason="Schema test",
            status=InterveneRequestStatus.pending, conversation_session_id=None,
        )
        db_session.add(req)
        await db_session.flush()
        await db_session.refresh(req)

        assert hasattr(req, "conversation_session_id")
        assert req.conversation_session_id is None

    @pytest.mark.asyncio
    async def test_delegation_depth_column_on_intervene_requests(self, db_session: AsyncSession):
        _, at, job = await _seed(db_session)

        req = InterveneRequest(
            agent_session_id=job.id, agent_type_id=at.id,
            intervention_type=InterventionType.text, reason="Schema test",
            status=InterveneRequestStatus.pending,
        )
        db_session.add(req)
        await db_session.flush()
        await db_session.refresh(req)

        assert hasattr(req, "delegation_depth")
        assert req.delegation_depth == 0


class TestTurnTypeEnum:
    """Verify turn_type_enum values are correct."""

    def test_turntype_enum_values_complete(self):
        values = {e.value for e in TurnType}
        assert values == {"message", "intervene_request", "intervene_response"}

    def test_turntype_enum_string_values(self):
        for member in TurnType:
            assert isinstance(member.value, str)
            assert len(member.value) > 0
            assert " " not in member.value

    @pytest.mark.asyncio
    async def test_turn_type_persistence(self, db_session: AsyncSession):
        session = ConversationSession(status=ConversationStatus.active)
        db_session.add(session)
        await db_session.flush()

        for turn_type in TurnType:
            turn = ConversationTurn(
                session_id=session.id, role=TurnRole.system,
                content=f"Turn of type {turn_type.value}", turn_type=turn_type,
            )
            db_session.add(turn)
        await db_session.flush()

        from sqlalchemy import select
        stmt = select(ConversationTurn).where(ConversationTurn.session_id == session.id)
        result = await db_session.execute(stmt)
        turns = result.scalars().all()
        persisted_types = {t.turn_type for t in turns}
        assert persisted_types == set(TurnType)


class TestNullableColumns:
    """Verify nullable FK columns accept NULL."""

    @pytest.mark.asyncio
    async def test_intervene_request_id_accepts_null(self, db_session: AsyncSession):
        session = ConversationSession(status=ConversationStatus.active)
        db_session.add(session)
        await db_session.flush()

        for i in range(5):
            turn = ConversationTurn(
                session_id=session.id, role=TurnRole.user,
                content=f"Message {i}", turn_type=TurnType.message, intervene_request_id=None,
            )
            db_session.add(turn)
        await db_session.flush()

        from sqlalchemy import select, func
        stmt = select(func.count(ConversationTurn.id)).where(ConversationTurn.session_id == session.id)
        result = await db_session.execute(stmt)
        assert result.scalar() == 5

    @pytest.mark.asyncio
    async def test_conversation_session_id_accepts_null(self, db_session: AsyncSession):
        _, at, job = await _seed(db_session)

        req = InterveneRequest(
            agent_session_id=job.id, agent_type_id=at.id,
            intervention_type=InterventionType.approval, reason="No conversation context",
            status=InterveneRequestStatus.pending, conversation_session_id=None,
        )
        db_session.add(req)
        await db_session.flush()
        await db_session.refresh(req)

        assert req.conversation_session_id is None
        assert req.id is not None


class TestFKConstraints:
    """Verify foreign key relationships are set up correctly."""

    @pytest.mark.asyncio
    async def test_intervene_request_id_fk_to_intervene_requests(self, db_session: AsyncSession):
        _, at, job = await _seed(db_session)

        intervene_req = InterveneRequest(
            agent_session_id=job.id, agent_type_id=at.id,
            intervention_type=InterventionType.approval, reason="FK test",
            status=InterveneRequestStatus.pending,
        )
        db_session.add(intervene_req)
        await db_session.flush()

        session = ConversationSession(status=ConversationStatus.active)
        db_session.add(session)
        await db_session.flush()

        turn = ConversationTurn(
            session_id=session.id, role=TurnRole.system, content="FK test turn",
            turn_type=TurnType.intervene_request, intervene_request_id=intervene_req.id,
        )
        db_session.add(turn)
        await db_session.flush()
        await db_session.refresh(turn)

        assert turn.intervene_request_id == intervene_req.id

    @pytest.mark.asyncio
    async def test_conversation_session_id_fk_to_conversation_sessions(self, db_session: AsyncSession):
        _, at, job = await _seed(db_session)

        conv_session = ConversationSession(status=ConversationStatus.active)
        db_session.add(conv_session)
        await db_session.flush()

        req = InterveneRequest(
            agent_session_id=job.id, agent_type_id=at.id,
            intervention_type=InterventionType.approval, reason="FK test",
            status=InterveneRequestStatus.pending, conversation_session_id=conv_session.id,
        )
        db_session.add(req)
        await db_session.flush()
        await db_session.refresh(req)

        assert req.conversation_session_id == conv_session.id
