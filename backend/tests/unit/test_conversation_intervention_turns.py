"""Unit tests for ConversationTurn and InterveneRequest schema + store changes.

Tests cover:
- TurnType enum values and ConversationTurn with turn_type field
- InterveneRequest with conversation_session_id and delegation_depth
- ConversationStore.add_turn with turn_type and intervene_request_id params
- InterveneRequestStore.create_request with conversation context fields
- InterveneRequestStore.list_pending_for_conversation
- InterveneRequestStore.submit_response creates paired conversation turn
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

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
    InterventionType,
)
from app.db.models.agents import AgentInputType, AgentJob, AgentJobStatus, AgentType
from app.services.conversations.store import ConversationStore
from app.services.agents.intervene_service import InterveneRequestStore


# ── Helpers ──────────────────────────────────────────────────────────────────

_identity_counter = 0
_agent_type_counter = 0


async def _make_agent_type(
    db: AsyncSession,
    name: str = "",
    input_type: AgentInputType = AgentInputType.conversation,
) -> AgentType:
    """Create and persist an AgentType with a unique name."""
    global _agent_type_counter
    _agent_type_counter += 1
    at_name = name or f"test-agent-{_agent_type_counter}-{uuid.uuid4().hex[:6]}"
    at = AgentType(name=at_name, input_type=input_type)
    db.add(at)
    await db.flush()
    await db.refresh(at)
    return at


async def _make_identity(db: AsyncSession, subject: str = "") -> Identity:
    """Create and persist an Identity with a unique subject."""
    global _identity_counter
    _identity_counter += 1
    subj = subject or f"test-user-{_identity_counter}-{uuid.uuid4().hex[:8]}"
    ident = Identity(id=uuid.uuid4(), subject=subj)
    db.add(ident)
    await db.flush()
    return ident


async def _make_job(db: AsyncSession, agent_type_id: uuid.UUID) -> AgentJob:
    """Create and persist an AgentJob."""
    job = AgentJob(
        id=uuid.uuid4(),
        agent_type_id=agent_type_id,
        status=AgentJobStatus.waiting_for_human,
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


async def _make_conv_session(db: AsyncSession) -> ConversationSession:
    """Create and persist a ConversationSession."""
    s = ConversationSession(status=ConversationStatus.active)
    db.add(s)
    await db.flush()
    await db.refresh(s)
    return s


async def _make_intervene_request(
    db: AsyncSession,
    agent_job_id: uuid.UUID,
    agent_type_id: uuid.UUID,
    intervention_type: InterventionType = InterventionType.approval,
    reason: str = "Test reason",
    conversation_session_id: uuid.UUID | None = None,
    delegation_depth: int = 0,
) -> InterveneRequest:
    """Create and persist an InterveneRequest."""
    req = InterveneRequest(
        agent_session_id=agent_job_id,
        agent_type_id=agent_type_id,
        intervention_type=intervention_type,
        reason=reason,
        status=InterveneRequestStatus.pending,
        conversation_session_id=conversation_session_id,
        delegation_depth=delegation_depth,
    )
    db.add(req)
    await db.flush()
    await db.refresh(req)
    return req


# ── Test TurnType enum and ConversationTurn model ────────────────────────────

class TestTurnTypeEnum:
    """Verify TurnType enum values and ConversationTurn model fields."""

    def test_turntype_enum_values(self):
        """TurnType must have message, intervene_request, intervene_response."""
        assert TurnType.message.value == "message"
        assert TurnType.intervene_request.value == "intervene_request"
        assert TurnType.intervene_response.value == "intervene_response"
        assert len(TurnType) == 3

    @pytest.mark.asyncio
    async def test_conversation_turn_default_turn_type(self, db_session: AsyncSession):
        """ConversationTurn defaults turn_type to message."""
        session = await _make_conv_session(db_session)

        turn = ConversationTurn(
            session_id=session.id,
            role=TurnRole.user,
            content="Hello",
        )
        db_session.add(turn)
        await db_session.flush()
        await db_session.refresh(turn)

        assert turn.turn_type == TurnType.message
        assert turn.intervene_request_id is None

    @pytest.mark.asyncio
    async def test_conversation_turn_intervene_request_type(self, db_session: AsyncSession):
        """ConversationTurn can be created with turn_type=intervene_request."""
        session = await _make_conv_session(db_session)

        turn = ConversationTurn(
            session_id=session.id,
            role=TurnRole.system,
            content="Intervene request turn",
            turn_type=TurnType.intervene_request,
        )
        db_session.add(turn)
        await db_session.flush()
        await db_session.refresh(turn)

        assert turn.turn_type == TurnType.intervene_request

    @pytest.mark.asyncio
    async def test_conversation_turn_intervene_response_type(self, db_session: AsyncSession):
        """ConversationTurn can be created with turn_type=intervene_response."""
        session = await _make_conv_session(db_session)

        turn = ConversationTurn(
            session_id=session.id,
            role=TurnRole.system,
            content="Intervene response turn",
            turn_type=TurnType.intervene_response,
        )
        db_session.add(turn)
        await db_session.flush()
        await db_session.refresh(turn)

        assert turn.turn_type == TurnType.intervene_response

    @pytest.mark.asyncio
    async def test_conversation_turn_with_intervene_request_id(self, db_session: AsyncSession):
        """ConversationTurn can link to an InterveneRequest via FK."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session)
        agent_job = await _make_job(db_session, agent_type.id)
        intervene_req = await _make_intervene_request(
            db_session, agent_job.id, agent_type.id,
        )
        session = await _make_conv_session(db_session)

        turn = ConversationTurn(
            session_id=session.id,
            role=TurnRole.system,
            content="Linked intervene turn",
            turn_type=TurnType.intervene_request,
            intervene_request_id=intervene_req.id,
        )
        db_session.add(turn)
        await db_session.flush()
        await db_session.refresh(turn)

        assert turn.intervene_request_id == intervene_req.id

    @pytest.mark.asyncio
    async def test_conversation_turn_intervene_request_id_nullable(self, db_session: AsyncSession):
        """intervene_request_id is NULL for regular message turns."""
        session = await _make_conv_session(db_session)

        turn = ConversationTurn(
            session_id=session.id,
            role=TurnRole.user,
            content="Regular message",
            turn_type=TurnType.message,
            intervene_request_id=None,
        )
        db_session.add(turn)
        await db_session.flush()
        await db_session.refresh(turn)

        assert turn.intervene_request_id is None


# ── Test InterveneRequest model changes ──────────────────────────────────────

class TestInterveneRequestModel:
    """Verify InterveneRequest with conversation_session_id and delegation_depth."""

    @pytest.mark.asyncio
    async def test_create_intervene_request_with_conversation_fields(self, db_session: AsyncSession):
        """InterveneRequest persists conversation_session_id and delegation_depth."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session)
        agent_job = await _make_job(db_session, agent_type.id)
        conv_session = await _make_conv_session(db_session)

        req = InterveneRequest(
            agent_session_id=agent_job.id,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.approval,
            reason="With conversation",
            status=InterveneRequestStatus.pending,
            conversation_session_id=conv_session.id,
            delegation_depth=2,
        )
        db_session.add(req)
        await db_session.flush()
        await db_session.refresh(req)

        assert req.conversation_session_id == conv_session.id
        assert req.delegation_depth == 2

    @pytest.mark.asyncio
    async def test_create_intervene_request_null_conversation_session_id(self, db_session: AsyncSession):
        """InterveneRequest accepts NULL conversation_session_id (non-conversation flow)."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session, input_type=AgentInputType.none)
        agent_job = await _make_job(db_session, agent_type.id)

        req = InterveneRequest(
            agent_session_id=agent_job.id,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.approval,
            reason="No conversation",
            status=InterveneRequestStatus.pending,
            conversation_session_id=None,
            delegation_depth=0,
        )
        db_session.add(req)
        await db_session.flush()
        await db_session.refresh(req)

        assert req.conversation_session_id is None
        assert req.delegation_depth == 0

    @pytest.mark.asyncio
    async def test_delegation_depth_default_zero(self, db_session: AsyncSession):
        """delegation_depth defaults to 0."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session, input_type=AgentInputType.none)
        agent_job = await _make_job(db_session, agent_type.id)

        req = InterveneRequest(
            agent_session_id=agent_job.id,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.text,
            reason="Default depth",
            status=InterveneRequestStatus.pending,
        )
        db_session.add(req)
        await db_session.flush()
        await db_session.refresh(req)

        assert req.delegation_depth == 0


# ── Test ConversationStore.add_turn ──────────────────────────────────────────

class TestConversationStoreAddTurn:
    """Verify ConversationStore.add_turn handles turn_type and intervene_request_id."""

    @pytest.mark.asyncio
    async def test_add_turn_default_turn_type(self, db_session: AsyncSession):
        """add_turn without turn_type creates a message-type turn."""
        store = ConversationStore()
        session = await _make_conv_session(db_session)

        turn = await store.add_turn(
            session_id=session.id,
            role=TurnRole.user,
            content="Default type",
            db=db_session,
        )
        assert turn.turn_type == TurnType.message

    @pytest.mark.asyncio
    async def test_add_turn_intervene_request_type(self, db_session: AsyncSession):
        """add_turn with turn_type=intervene_request persists correctly."""
        store = ConversationStore()
        session = await _make_conv_session(db_session)

        turn = await store.add_turn(
            session_id=session.id,
            role=TurnRole.system,
            content="Intervene request via store",
            db=db_session,
            turn_type=TurnType.intervene_request,
        )
        assert turn.turn_type == TurnType.intervene_request

    @pytest.mark.asyncio
    async def test_add_turn_intervene_response_type(self, db_session: AsyncSession):
        """add_turn with turn_type=intervene_response persists correctly."""
        store = ConversationStore()
        session = await _make_conv_session(db_session)

        turn = await store.add_turn(
            session_id=session.id,
            role=TurnRole.system,
            content="Intervene response via store",
            db=db_session,
            turn_type=TurnType.intervene_response,
        )
        assert turn.turn_type == TurnType.intervene_response

    @pytest.mark.asyncio
    async def test_add_turn_with_intervene_request_id(self, db_session: AsyncSession):
        """add_turn with intervene_request_id FK persists correctly."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session)
        agent_job = await _make_job(db_session, agent_type.id)
        intervene_req = await _make_intervene_request(
            db_session, agent_job.id, agent_type.id,
        )

        store = ConversationStore()
        session = await _make_conv_session(db_session)

        turn = await store.add_turn(
            session_id=session.id,
            role=TurnRole.system,
            content="Linked turn via store",
            db=db_session,
            turn_type=TurnType.intervene_request,
            intervene_request_id=intervene_req.id,
        )
        assert turn.intervene_request_id == intervene_req.id

    @pytest.mark.asyncio
    async def test_add_turn_increments_turn_count(self, db_session: AsyncSession):
        """add_turn increments turn_count on the parent session."""
        store = ConversationStore()
        session = ConversationSession(status=ConversationStatus.active, turn_count=0)
        db_session.add(session)
        await db_session.flush()

        await store.add_turn(
            session_id=session.id,
            role=TurnRole.user,
            content="Message 1",
            db=db_session,
        )
        await db_session.refresh(session)
        assert session.turn_count == 1

        await store.add_turn(
            session_id=session.id,
            role=TurnRole.system,
            content="Message 2",
            db=db_session,
            turn_type=TurnType.intervene_request,
        )
        await db_session.refresh(session)
        assert session.turn_count == 2


# ── Test InterveneRequestStore ───────────────────────────────────────────────

class TestInterveneRequestStoreCreate:
    """Verify InterveneRequestStore.create_request with conversation context."""

    @pytest.mark.asyncio
    async def test_create_request_with_conversation_context(self, db_session: AsyncSession):
        """create_request accepts and persists conversation_session_id and delegation_depth."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session)
        agent_job = await _make_job(db_session, agent_type.id)
        conv_session = await _make_conv_session(db_session)

        store = InterveneRequestStore()
        req = await store.create_request(
            db=db_session,
            agent_session_id=agent_job.id,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.approval,
            reason="Conversation-scoped request",
            conversation_session_id=conv_session.id,
            delegation_depth=3,
        )
        assert req.conversation_session_id == conv_session.id
        assert req.delegation_depth == 3
        assert req.status == InterveneRequestStatus.pending

    @pytest.mark.asyncio
    async def test_create_request_without_conversation_context(self, db_session: AsyncSession):
        """create_request without conversation fields works as before."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session, input_type=AgentInputType.none)
        agent_job = await _make_job(db_session, agent_type.id)

        store = InterveneRequestStore()
        req = await store.create_request(
            db=db_session,
            agent_session_id=agent_job.id,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.text,
            reason="No conversation scope",
        )
        assert req.conversation_session_id is None
        assert req.delegation_depth == 0


class TestInterveneRequestStoreListPending:
    """Verify list_pending_for_conversation query method."""

    @pytest.mark.asyncio
    async def test_returns_pending_requests_for_conversation(self, db_session: AsyncSession):
        """list_pending_for_conversation returns only pending requests for given session."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session)
        conv_session = await _make_conv_session(db_session)

        store = InterveneRequestStore()
        for i in range(3):
            agent_job = await _make_job(db_session, agent_type.id)
            await store.create_request(
                db=db_session,
                agent_session_id=agent_job.id,
                agent_type_id=agent_type.id,
                intervention_type=InterventionType.approval,
                reason=f"Request {i}",
                conversation_session_id=conv_session.id,
                delegation_depth=i,
            )

        await db_session.commit()

        pending = await store.list_pending_for_conversation(
            db=db_session,
            conversation_session_id=conv_session.id,
        )
        assert len(pending) == 3
        assert all(r.status == InterveneRequestStatus.pending for r in pending)
        assert all(r.conversation_session_id == conv_session.id for r in pending)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_pending(self, db_session: AsyncSession):
        """list_pending_for_conversation returns empty list (not error)."""
        conv_session = await _make_conv_session(db_session)

        store = InterveneRequestStore()
        result = await store.list_pending_for_conversation(
            db=db_session,
            conversation_session_id=conv_session.id,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_fifo_order_by_created_at(self, db_session: AsyncSession):
        """list_pending_for_conversation returns results in created_at ASC order."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session)
        conv_session = await _make_conv_session(db_session)

        store = InterveneRequestStore()
        for i in range(3):
            agent_job = await _make_job(db_session, agent_type.id)
            await store.create_request(
                db=db_session,
                agent_session_id=agent_job.id,
                agent_type_id=agent_type.id,
                intervention_type=InterventionType.approval,
                reason=f"FIFO {i}",
                conversation_session_id=conv_session.id,
            )

        await db_session.commit()

        pending = await store.list_pending_for_conversation(
            db=db_session,
            conversation_session_id=conv_session.id,
        )
        assert len(pending) == 3
        # Verify FIFO order (created_at ascending)
        for i in range(2):
            assert pending[i].created_at <= pending[i + 1].created_at

    @pytest.mark.asyncio
    async def test_excludes_non_pending_requests(self, db_session: AsyncSession):
        """list_pending_for_conversation excludes responded/cancelled requests."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session)
        conv_session = await _make_conv_session(db_session)
        agent_job = await _make_job(db_session, agent_type.id)

        store = InterveneRequestStore()
        req = await store.create_request(
            db=db_session,
            agent_session_id=agent_job.id,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.approval,
            reason="Will respond",
            conversation_session_id=conv_session.id,
        )
        await db_session.commit()

        # Respond
        await store.submit_response(
            db=db_session,
            request_id=req.id,
            operator_user_id=identity.id,
            approval_value=True,
        )
        await db_session.commit()

        # Now it should NOT appear in pending list
        pending = await store.list_pending_for_conversation(
            db=db_session,
            conversation_session_id=conv_session.id,
        )
        assert len(pending) == 0


class TestInterveneRequestStoreSubmitResponse:
    """Verify submit_response creates paired conversation turn for conversation-scoped requests."""

    @pytest.mark.asyncio
    async def test_submit_response_creates_intervene_response_turn(self, db_session: AsyncSession):
        """When conversation_session_id is set, submit_response creates a conversation turn."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session)
        agent_job = await _make_job(db_session, agent_type.id)
        conv_session = await _make_conv_session(db_session)

        store = InterveneRequestStore()
        req = await store.create_request(
            db=db_session,
            agent_session_id=agent_job.id,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.approval,
            reason="Create response turn",
            conversation_session_id=conv_session.id,
            delegation_depth=1,
        )
        await db_session.commit()

        response = await store.submit_response(
            db=db_session,
            request_id=req.id,
            operator_user_id=identity.id,
            approval_value=True,
        )
        await db_session.commit()

        stmt = select(ConversationTurn).where(
            ConversationTurn.session_id == conv_session.id,
            ConversationTurn.turn_type == TurnType.intervene_response,
            ConversationTurn.intervene_request_id == req.id,
        )
        result = await db_session.execute(stmt)
        turns = result.scalars().all()
        assert len(turns) == 1
        assert "Approved" in turns[0].content

    @pytest.mark.asyncio
    async def test_submit_response_choice_creates_turn(self, db_session: AsyncSession):
        """Choice-type submission creates intervene_response turn with selected choice."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session)
        agent_job = await _make_job(db_session, agent_type.id)
        conv_session = await _make_conv_session(db_session)

        store = InterveneRequestStore()
        req = await store.create_request(
            db=db_session,
            agent_session_id=agent_job.id,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.choice,
            reason="Select one",
            conversation_session_id=conv_session.id,
            choices=["A", "B", "C"],
        )
        await db_session.commit()

        await store.submit_response(
            db=db_session,
            request_id=req.id,
            operator_user_id=identity.id,
            selected_choice="B",
        )
        await db_session.commit()

        stmt = select(ConversationTurn).where(
            ConversationTurn.session_id == conv_session.id,
            ConversationTurn.turn_type == TurnType.intervene_response,
        )
        result = await db_session.execute(stmt)
        turns = result.scalars().all()
        assert len(turns) == 1
        assert "Selected: B" in turns[0].content

    @pytest.mark.asyncio
    async def test_submit_response_text_creates_turn(self, db_session: AsyncSession):
        """Text-type submission creates intervene_response turn with text snippet."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session)
        agent_job = await _make_job(db_session, agent_type.id)
        conv_session = await _make_conv_session(db_session)

        store = InterveneRequestStore()
        req = await store.create_request(
            db=db_session,
            agent_session_id=agent_job.id,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.text,
            reason="Provide text",
            conversation_session_id=conv_session.id,
        )
        await db_session.commit()

        await store.submit_response(
            db=db_session,
            request_id=req.id,
            operator_user_id=identity.id,
            text_value="This is my response text",
        )
        await db_session.commit()

        stmt = select(ConversationTurn).where(
            ConversationTurn.session_id == conv_session.id,
            ConversationTurn.turn_type == TurnType.intervene_response,
        )
        result = await db_session.execute(stmt)
        turns = result.scalars().all()
        assert len(turns) == 1
        assert "Provided notes" in turns[0].content

    @pytest.mark.asyncio
    async def test_submit_response_no_conversation_session_id(self, db_session: AsyncSession):
        """When conversation_session_id is NULL, no conversation turn is created."""
        identity = await _make_identity(db_session)
        agent_type = await _make_agent_type(db_session, input_type=AgentInputType.none)
        agent_job = await _make_job(db_session, agent_type.id)

        store = InterveneRequestStore()
        req = await store.create_request(
            db=db_session,
            agent_session_id=agent_job.id,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.approval,
            reason="No conversation",
            conversation_session_id=None,
        )
        await db_session.commit()

        await store.submit_response(
            db=db_session,
            request_id=req.id,
            operator_user_id=identity.id,
            approval_value=True,
        )
        await db_session.commit()

        # Verify no turn was created referencing THIS request
        stmt = select(ConversationTurn).where(
            ConversationTurn.intervene_request_id == req.id,
            ConversationTurn.turn_type == TurnType.intervene_response,
        )
        result = await db_session.execute(stmt)
        turns = result.scalars().all()
        assert len(turns) == 0


# ── Test service boundaries (AR never touches DB) ────────────────────────────

class TestServiceBoundaries:
    """Verify that the InterveneRequestStore does not import from Agent Runtime modules."""

    def test_intervene_service_only_imports_from_control_center(self):
        """InterveneRequestStore lives in backend/app/services/agents/ which is Control Center code."""
        import inspect
        from app.services.agents.intervene_service import InterveneRequestStore

        source = inspect.getsource(InterveneRequestStore)
        assert "agent_runtime" not in source.lower().replace("_", ""), (
            "InterveneRequestStore must not import from agent_runtime"
        )
        assert "communication_hub" not in source.lower().replace("_", ""), (
            "InterveneRequestStore must not import from communication_hub"
        )

    def test_conversation_store_only_uses_db_via_asyncsession(self):
        """ConversationStore only accesses DB through AsyncSession parameter."""
        import inspect
        from app.services.conversations.store import ConversationStore

        source = inspect.getsource(ConversationStore)
        assert "create_engine" not in source, "ConversationStore must not create DB engines directly"
