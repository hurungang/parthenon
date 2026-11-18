"""Unit tests — resume projection in the conversation sessions listing (5.5).

``GET /conversations/sessions`` badges waiting / resumed / resolved /
unresumable sessions from the durable resume record.  The projection is loaded
with one extra query for the whole page (never per row), and a session that
never paused carries no projection.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInputType, AgentType
from app.db.models.conversation_turn_resume import ResumeOutcome, ResumeState
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.intervene import InterveneRequest, InterventionType
from app.schemas.conversations import ConversationSessionRead
from app.services.conversations.store import ConversationStore
from app.services.conversations.turn_resume_store import ConversationTurnResumeStore

NOW = datetime.now(timezone.utc)


async def _agent_type(db: AsyncSession) -> AgentType:
    agent_type = AgentType(
        name=f"sessions-projection-{uuid.uuid4().hex}",
        input_type=AgentInputType.conversation,
    )
    db.add(agent_type)
    await db.flush()
    return agent_type


async def _session(db: AsyncSession, agent_type_id) -> ConversationSession:
    conv = ConversationSession(
        agent_type_id=agent_type_id,
        status=ConversationStatus.active,
        updated_at=NOW,
    )
    db.add(conv)
    await db.flush()
    return conv


async def _intervention(db: AsyncSession, conv: ConversationSession, at) -> InterveneRequest:
    req = InterveneRequest(
        agent_type_id=conv.agent_type_id,
        intervention_type=InterventionType.approval,
        reason="preview",
        conversation_session_id=conv.id,
        expires_at=at,
    )
    db.add(req)
    await db.flush()
    return req


class TestSessionsResumeProjection:
    @pytest.mark.asyncio
    async def test_page_projects_live_and_terminal_resume_state(
        self, db_session: AsyncSession
    ):
        agent_type = await _agent_type(db_session)
        waiting = await _session(db_session, agent_type.id)
        resolved = await _session(db_session, agent_type.id)
        idle = await _session(db_session, agent_type.id)
        store = ConversationTurnResumeStore()

        waiting_req = await _intervention(
            db_session, waiting, NOW + timedelta(minutes=10)
        )
        waiting_record = await store.create_or_reuse(
            waiting.id,
            db_session,
            intervene_request_id=waiting_req.id,
            expires_at=NOW + timedelta(minutes=10),
        )

        resolved_req = await _intervention(db_session, resolved, NOW + timedelta(minutes=5))
        resolved_record = await store.create_or_reuse(
            resolved.id, db_session, intervene_request_id=resolved_req.id
        )
        await store.resolve(
            resolved_record.id,
            db_session,
            ResumeOutcome.approved_applied,
            write_applied=True,
        )
        await db_session.commit()

        items, total = await ConversationStore().list_sessions_page(
            db_session,
            agent_type_id=agent_type.id,
            status="all",
            page=1,
            page_size=10,
            all_time=True,
        )
        assert total == 3

        by_id = {str(item.id): item for item in items}
        waiting_item = by_id[str(waiting.id)]
        resolved_item = by_id[str(resolved.id)]
        idle_item = by_id[str(idle.id)]

        assert waiting_item.resume_state == ResumeState.waiting_for_human.value
        assert waiting_item.resume_outcome is None
        assert waiting_item.resume_expires_at is not None
        assert waiting_item.id == waiting_record.conversation_session_id

        assert resolved_item.resume_state == ResumeState.resolved.value
        assert resolved_item.resume_outcome == ResumeOutcome.approved_applied.value
        assert resolved_item.resume_expires_at is None

        assert idle_item.resume_state is None
        assert idle_item.resume_outcome is None
        assert idle_item.resume_expires_at is None

        # The schema projects the fields (and tolerates their absence).
        payload = ConversationSessionRead.model_validate(waiting_item)
        assert payload.resume_state == "waiting_for_human"
        idle_payload = ConversationSessionRead.model_validate(idle_item)
        assert idle_payload.resume_state is None

    @pytest.mark.asyncio
    async def test_live_record_wins_over_a_superseded_one(
        self, db_session: AsyncSession
    ):
        agent_type = await _agent_type(db_session)
        conv = await _session(db_session, agent_type.id)
        store = ConversationTurnResumeStore()

        old_req = await _intervention(db_session, conv, NOW + timedelta(minutes=5))
        await store.create_or_reuse(
            conv.id, db_session, intervene_request_id=old_req.id
        )
        new_req = await _intervention(db_session, conv, NOW + timedelta(minutes=5))
        new_record = await store.create_or_reuse(
            conv.id, db_session, intervene_request_id=new_req.id
        )
        await db_session.commit()

        items, _total = await ConversationStore().list_sessions_page(
            db_session,
            agent_type_id=agent_type.id,
            status="all",
            page=1,
            page_size=10,
            all_time=True,
        )
        item = next(i for i in items if i.id == conv.id)
        assert item.resume_state == ResumeState.waiting_for_human.value
        assert item.resume_expires_at == new_record.expires_at

    @pytest.mark.asyncio
    async def test_projection_uses_one_query_for_the_page(
        self, db_session: AsyncSession
    ):
        agent_type = await _agent_type(db_session)
        store = ConversationTurnResumeStore()
        for _ in range(5):
            conv = await _session(db_session, agent_type.id)
            req = await _intervention(db_session, conv, NOW + timedelta(minutes=5))
            await store.create_or_reuse(
                conv.id, db_session, intervene_request_id=req.id
            )
        await db_session.commit()

        statements: list[str] = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        engine = db_session.bind
        event.listen(engine.sync_engine, "before_cursor_execute", _record)
        try:
            items, _total = await ConversationStore().list_sessions_page(
                db_session,
                agent_type_id=agent_type.id,
                status="all",
                page=1,
                page_size=10,
                all_time=True,
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _record)

        assert len(items) == 5
        resume_queries = [
            s for s in statements if "conversation_turn_resumes" in s.lower()
        ]
        assert len(resume_queries) == 1, statements
