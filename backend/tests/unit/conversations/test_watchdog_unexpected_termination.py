"""Watchdog: a stuck in-progress turn resolves as ``unexpectedly_terminated``.

Task B of the ``resumable-agent-turn-persistence`` follow-up.  A live turn keeps
its activity fresh through the Communication Hub heartbeat touch, so a **stale**
``thinking`` / ``using_tool`` / ``delegating`` row means the turn died mid-flight
(crash / server restart / killed worker).  The reaper must resolve it as
``failed`` with the dedicated ``unexpectedly_terminated`` reason — never as a
timeout and never as ``resume_failed`` — so the UI can state that nothing was
applied and offer to resend the request.

Protected behaviour that must NOT change:

- a fresh (recently touched) working row is never reaped;
- a dead session keeps the deliberate-stop semantics (``failed``/``cancelled``);
- a live ``waiting_for_human`` pause stays protected.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.conversations.activity_reaper as reaper_module
from app.db.models.agents import AgentInputType, AgentJob, AgentJobStatus, AgentType
from app.db.models.conversation_activity import ActivityState
from app.db.models.conversation_turn_resume import ResumeOutcome, ResumeState
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.intervene import (
    InterveneRequest,
    InterveneRequestStatus,
    InterventionType,
)
from app.services.conversations.activity_reaper import ConversationActivityReaper
from app.services.conversations.activity_store import ConversationActivityStore
from app.services.conversations.turn_resolution import (
    REASON_UNEXPECTEDLY_TERMINATED,
    message_key_for_reason,
    outcome_message_for_reason,
    terminal_activity_state_for_reason,
)
from app.services.conversations.turn_resume_store import ConversationTurnResumeStore

NOW = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_threshold(monkeypatch):
    monkeypatch.setattr(reaper_module, "get_stale_threshold_seconds", lambda: 180)


@pytest.fixture
def reaper() -> ConversationActivityReaper:
    return ConversationActivityReaper()


async def _make_session(
    db: AsyncSession, status: ConversationStatus = ConversationStatus.active
) -> ConversationSession:
    conv = ConversationSession(status=status)
    db.add(conv)
    await db.flush()
    return conv


async def _make_activity(
    db: AsyncSession,
    conv: ConversationSession,
    state: ActivityState,
    *,
    last_updated: datetime,
    active_resume_id=None,
    pending_intervene_request_id=None,
    detail=None,
):
    activity = await ConversationActivityStore().upsert(
        conv.id,
        db,
        state=state,
        active_resume_id=active_resume_id,
        pending_intervene_request_id=pending_intervene_request_id,
        detail=detail,
    )
    activity.last_updated_at = last_updated
    await db.flush()
    return activity


async def _activity(db: AsyncSession, conv: ConversationSession):
    return await ConversationActivityStore().get(conv.id, db)


class TestReasonVocabulary:
    def test_reason_is_distinct_and_actionable(self):
        assert REASON_UNEXPECTEDLY_TERMINATED == "unexpectedly_terminated"
        message = outcome_message_for_reason(REASON_UNEXPECTEDLY_TERMINATED)
        assert "stopped unexpectedly" in message
        assert "Nothing was applied" in message
        assert "resend" in message
        # Never claims a write happened, never blames the operator.
        assert "could not be resumed" not in message
        assert (
            message_key_for_reason(REASON_UNEXPECTEDLY_TERMINATED)
            == "chat.resume.unexpectedlyTerminated"
        )

    def test_maps_to_failed_not_timeout(self):
        assert (
            terminal_activity_state_for_reason(REASON_UNEXPECTEDLY_TERMINATED)
            is ActivityState.failed
        )


class TestStaleWorkingRowResolution:
    @pytest.mark.asyncio
    async def test_stale_thinking_resolves_failed_unexpectedly_terminated(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        await _make_activity(
            db_session,
            conv,
            ActivityState.thinking,
            last_updated=NOW - timedelta(minutes=10),
        )

        await reaper.reap(db_session, now=NOW)

        activity = await _activity(db_session, conv)
        assert activity is not None
        assert activity.state is ActivityState.failed
        assert activity.is_terminal is True
        # Hydration source: the reason the UI renders its card from, even when
        # no resume record exists for this turn.
        assert (
            activity.detail["terminal_reason_code"] == REASON_UNEXPECTEDLY_TERMINATED
        )
        assert (
            activity.detail["terminal_message_key"]
            == "chat.resume.unexpectedlyTerminated"
        )

    @pytest.mark.asyncio
    async def test_stale_using_tool_closes_linked_resume_record(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        resume = await ConversationTurnResumeStore().create_or_reuse(
            conv.id, db_session
        )
        await _make_activity(
            db_session,
            conv,
            ActivityState.using_tool,
            last_updated=NOW - timedelta(minutes=10),
            active_resume_id=resume.id,
        )

        await reaper.reap(db_session, now=NOW)

        refreshed = await ConversationTurnResumeStore().get(resume.id, db_session)
        assert refreshed is not None
        assert refreshed.is_terminal is True
        assert refreshed.state is ResumeState.unresumable
        assert refreshed.terminal_reason_code == REASON_UNEXPECTEDLY_TERMINATED
        # The reason vocabulary maps to a generic resume outcome (no new enum).
        assert refreshed.resume_outcome is ResumeOutcome.resume_failed

        activity = await _activity(db_session, conv)
        assert activity.state is ActivityState.failed
        assert activity.is_terminal is True
        assert (
            activity.detail["terminal_reason_code"] == REASON_UNEXPECTEDLY_TERMINATED
        )

    @pytest.mark.asyncio
    async def test_stale_delegating_resolving_resume_is_closed(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        resume = await ConversationTurnResumeStore().create_or_reuse(
            conv.id, db_session
        )
        await ConversationTurnResumeStore().mark_resuming(resume.id, db_session)
        await _make_activity(
            db_session,
            conv,
            ActivityState.delegating,
            last_updated=NOW - timedelta(minutes=10),
            active_resume_id=resume.id,
        )

        await reaper.reap(db_session, now=NOW)

        refreshed = await ConversationTurnResumeStore().get(resume.id, db_session)
        assert refreshed.terminal_reason_code == REASON_UNEXPECTEDLY_TERMINATED
        assert (await _activity(db_session, conv)).state is ActivityState.failed

    @pytest.mark.asyncio
    async def test_stale_working_row_expires_linked_confirmation(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        agent_type = AgentType(
            name=f"watchdog-{uuid.uuid4().hex}",
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
        request = InterveneRequest(
            agent_session_id=job.id,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.approval,
            reason="create skill",
            status=InterveneRequestStatus.pending,
            conversation_session_id=conv.id,
        )
        db_session.add(request)
        await db_session.flush()
        resume = await ConversationTurnResumeStore().create_or_reuse(
            conv.id, db_session, intervene_request_id=request.id
        )
        await _make_activity(
            db_session,
            conv,
            ActivityState.thinking,
            last_updated=NOW - timedelta(minutes=10),
            active_resume_id=resume.id,
            pending_intervene_request_id=request.id,
        )

        await reaper.reap(db_session, now=NOW)

        refreshed_request = await db_session.get(InterveneRequest, request.id)
        assert refreshed_request.status is InterveneRequestStatus.expired
        assert (await _activity(db_session, conv)).state is ActivityState.failed


class TestProtectedBehaviour:
    @pytest.mark.asyncio
    async def test_freshly_touched_working_row_is_not_reaped(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        await _make_activity(
            db_session,
            conv,
            ActivityState.using_tool,
            last_updated=NOW - timedelta(seconds=30),
        )

        await reaper.reap(db_session, now=NOW)

        activity = await _activity(db_session, conv)
        assert activity.state is ActivityState.using_tool
        assert activity.is_terminal is False
        assert activity.detail is None or "terminal_reason_code" not in (
            activity.detail or {}
        )

    @pytest.mark.asyncio
    async def test_dead_session_keeps_cancelled_semantics(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session, status=ConversationStatus.closed)
        await _make_activity(
            db_session,
            conv,
            ActivityState.using_tool,
            last_updated=NOW - timedelta(seconds=5),
        )

        await reaper.reap(db_session, now=NOW)

        activity = await _activity(db_session, conv)
        assert activity.state is ActivityState.failed
        assert activity.detail["terminal_reason_code"] == "cancelled"

    @pytest.mark.asyncio
    async def test_live_waiting_pause_stays_protected(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        agent_type = AgentType(
            name=f"watchdog-{uuid.uuid4().hex}",
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
        request = InterveneRequest(
            agent_session_id=job.id,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.approval,
            reason="create skill",
            status=InterveneRequestStatus.pending,
            conversation_session_id=conv.id,
        )
        db_session.add(request)
        await db_session.flush()
        resume = await ConversationTurnResumeStore().create_or_reuse(
            conv.id,
            db_session,
            intervene_request_id=request.id,
            expires_at=NOW + timedelta(minutes=10),
        )
        await _make_activity(
            db_session,
            conv,
            ActivityState.waiting_for_human,
            last_updated=NOW - timedelta(hours=2),
            active_resume_id=resume.id,
            pending_intervene_request_id=request.id,
        )
        # A checkpoint must exist for the pause to be considered intact.
        from app.services.conversations.turn_checkpoint_store import (
            ConversationTurnCheckpointStore,
        )

        await ConversationTurnCheckpointStore().upsert_payload(
            resume.id,
            db_session,
            payload={"messages": []},
        )

        await reaper.reap(db_session, now=NOW)

        activity = await _activity(db_session, conv)
        assert activity.state is ActivityState.waiting_for_human
        assert activity.is_terminal is False
