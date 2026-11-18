"""Unit tests — advancing the resume record when an intervention is answered.

Phase 5.1: the operator's answer and the resume-record transition commit in the
same transaction (``waiting_for_human`` → ``resuming``, answering user,
attempt).  A terminal record returns its stored outcome instead of
re-dispatching, and an elapsed answer window closes as ``unresumable/expired``
with no dispatch at all.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInputType, AgentType
from app.db.models.conversation_activity import ActivityState
from app.db.models.conversation_turn_resume import (
    ConversationTurnResume,
    ResumeOutcome,
    ResumeState,
)
from app.db.models.conversations import (
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
    TurnRole,
)
from app.db.models.identity import Identity
from app.db.models.intervene import InterveneRequest, InterventionType
from app.services.conversations.activity_store import ConversationActivityStore
from app.services.conversations.turn_resolution import (
    REASON_EXPIRED,
    advance_answered_intervention,
)
from app.services.conversations.turn_resume_store import ConversationTurnResumeStore

NOW = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)


async def _seed(
    db: AsyncSession,
    *,
    expires_at: datetime | None = None,
) -> tuple[ConversationSession, InterveneRequest, ConversationTurnResume, Identity]:
    conv = ConversationSession(status=ConversationStatus.active)
    db.add(conv)

    agent_type = AgentType(
        name=f"advance-at-{uuid.uuid4().hex}",
        input_type=AgentInputType.conversation,
    )
    db.add(agent_type)
    await db.flush()

    req = InterveneRequest(
        agent_type_id=agent_type.id,
        intervention_type=InterventionType.approval,
        reason="**Create Skill: Advance**",
        conversation_session_id=conv.id,
        expires_at=expires_at,
    )
    db.add(req)

    operator = Identity(
        id=uuid.uuid4(),
        subject=f"advance-{uuid.uuid4().hex}",
        display_name="Operator",
    )
    db.add(operator)
    await db.flush()

    record = await ConversationTurnResumeStore().create_or_reuse(
        conv.id, db, intervene_request_id=req.id, expires_at=expires_at
    )
    return conv, req, record, operator


class TestAdvanceAnsweredIntervention:
    @pytest.mark.asyncio
    async def test_answer_moves_the_record_to_resuming(
        self, db_session: AsyncSession
    ):
        _conv, req, record, operator = await _seed(
            db_session, expires_at=NOW + timedelta(minutes=5)
        )

        advance = await advance_answered_intervention(
            db_session, req, operator_user_id=operator.id, now=NOW
        )

        assert advance.dispatch is True
        assert advance.already_terminal is False
        assert advance.expired is False
        assert advance.resume_id == record.id

        refreshed = await db_session.get(ConversationTurnResume, record.id)
        await db_session.refresh(refreshed)
        assert refreshed is not None
        assert refreshed.state is ResumeState.resuming
        assert refreshed.applied_by_user_id == operator.id
        assert refreshed.attempt_count == 1
        assert refreshed.last_attempt_at is not None
        assert refreshed.write_applied is False

    @pytest.mark.asyncio
    async def test_answer_moves_the_persisted_activity_out_of_waiting(
        self, db_session: AsyncSession
    ):
        """A resumed pause must never hydrate/pong as still-pending.

        The activity is what a reconnect hydration and the watchdog
        ``status_pong`` render from: if it stayed ``waiting_for_human`` after
        the answer, the amber "waiting for your input" bar would reappear for
        a turn that is already processing again.
        """
        conv, req, record, operator = await _seed(
            db_session, expires_at=NOW + timedelta(minutes=5)
        )
        activity_store = ConversationActivityStore()
        await activity_store.upsert(
            conv.id,
            db_session,
            ActivityState.waiting_for_human,
            pending_intervene_request_id=req.id,
            active_resume_id=record.id,
        )

        advance = await advance_answered_intervention(
            db_session, req, operator_user_id=operator.id, now=NOW
        )

        assert advance.dispatch is True
        activity = await activity_store.get(conv.id, db_session)
        assert activity is not None
        assert activity.state is ActivityState.thinking
        assert activity.is_terminal is False
        # The live resume link is kept across the non-terminal transition.
        assert activity.active_resume_id == record.id
        # The answered confirmation is no longer pending on the activity.
        assert activity.pending_intervene_request_id is None

    @pytest.mark.asyncio
    async def test_repeat_answer_for_in_flight_turn_does_not_double_count(
        self, db_session: AsyncSession
    ):
        _conv, req, record, operator = await _seed(
            db_session, expires_at=NOW + timedelta(minutes=5)
        )
        await advance_answered_intervention(
            db_session, req, operator_user_id=operator.id, now=NOW
        )
        again = await advance_answered_intervention(
            db_session, req, operator_user_id=operator.id, now=NOW
        )

        # The durable dispatch stays idempotent; Communication Hub's guard and
        # the Agent Runtime claim are what prevent a second resume.
        assert again.dispatch is True
        refreshed = await db_session.get(ConversationTurnResume, record.id)
        await db_session.refresh(refreshed)
        assert refreshed is not None
        assert refreshed.state is ResumeState.resuming
        assert refreshed.attempt_count == 1

    @pytest.mark.asyncio
    async def test_terminal_record_returns_the_stored_outcome(
        self, db_session: AsyncSession
    ):
        conv, req, record, operator = await _seed(db_session)
        store = ConversationTurnResumeStore()
        await store.resolve(
            record.id, db_session, ResumeOutcome.denied
        )
        await db_session.commit()

        advance = await advance_answered_intervention(
            db_session, req, operator_user_id=operator.id, now=NOW
        )

        assert advance.dispatch is False
        assert advance.already_terminal is True
        assert advance.reason_code == "denied"

        refreshed = await db_session.get(ConversationTurnResume, record.id)
        await db_session.refresh(refreshed)
        assert refreshed is not None
        assert refreshed.resume_outcome is ResumeOutcome.denied
        assert refreshed.write_applied is False
        # No outcome turn was fabricated for the duplicate answer.
        turns = (
            await db_session.execute(
                select(ConversationTurn).where(
                    ConversationTurn.session_id == conv.id,
                    ConversationTurn.role == TurnRole.agent,
                )
            )
        ).scalars().all()
        assert turns == []

    @pytest.mark.asyncio
    async def test_elapsed_window_closes_expired_without_dispatch(
        self, db_session: AsyncSession
    ):
        conv, req, record, operator = await _seed(
            db_session, expires_at=NOW - timedelta(seconds=1)
        )

        advance = await advance_answered_intervention(
            db_session, req, operator_user_id=operator.id, now=NOW
        )

        assert advance.dispatch is False
        assert advance.expired is True
        assert advance.reason_code == REASON_EXPIRED

        refreshed = await db_session.get(ConversationTurnResume, record.id)
        await db_session.refresh(refreshed)
        assert refreshed is not None
        assert refreshed.state is ResumeState.unresumable
        assert refreshed.resume_outcome is ResumeOutcome.expired
        assert refreshed.terminal_reason_code == REASON_EXPIRED
        assert refreshed.write_applied is False
        assert refreshed.outcome_turn_id is not None
        assert refreshed.applied_by_user_id is None

        turns = (
            await db_session.execute(
                select(ConversationTurn).where(
                    ConversationTurn.session_id == conv.id,
                    ConversationTurn.role == TurnRole.agent,
                )
            )
        ).scalars().all()
        assert len(turns) == 1

        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.state is ActivityState.timed_out
        assert activity.is_terminal is True

    @pytest.mark.asyncio
    async def test_agent_job_intervention_takes_the_legacy_path(
        self, db_session: AsyncSession
    ):
        """No conversation session → no durable advance, dispatch unchanged."""
        from app.db.models.agents import AgentJob, AgentJobStatus

        conv = ConversationSession(status=ConversationStatus.active)
        db_session.add(conv)
        agent_type = AgentType(
            name=f"advance-job-{uuid.uuid4().hex}",
            input_type=AgentInputType.conversation,
        )
        db_session.add(agent_type)
        await db_session.flush()
        job = AgentJob(
            id=uuid.uuid4(),
            agent_type_id=agent_type.id,
            status=AgentJobStatus.waiting_for_human,
        )
        db_session.add(job)
        await db_session.flush()
        req = InterveneRequest(
            agent_session_id=job.id,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.approval,
            reason="job-scoped",
        )
        db_session.add(req)
        await db_session.flush()

        advance = await advance_answered_intervention(
            db_session, req, operator_user_id=None, now=NOW
        )
        assert advance.dispatch is False
        assert advance.already_terminal is False
        assert advance.resume_id is None
