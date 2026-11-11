"""Unit tests — ConversationActivityReaper resolution semantics.

The reaper must resolve stale / orphaned activity to a terminal state (never a
perpetual "working"/"waiting") while protecting a still-pending intervention on
an active session:

- stale ``thinking``/``using_tool``/``delegating`` heartbeat → ``timed_out``
- dead session (closed/archived/error) → ``failed`` (even if not stale)
- fresh active working activity → untouched
- ``waiting_for_human`` with a pending intervention on an active session →
  protected (never reaped)
- ``waiting_for_human`` with an expired/cancelled intervention → ``timed_out``
  even on an active session (task 6.3 — restart-abandoned paused turns)
- ``waiting_for_human`` responded + stale → ``timed_out``; responded + fresh →
  protected
- orphaned ``waiting_for_human`` (no resolvable request) stale → ``timed_out``
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.conversations.activity_reaper as reaper_module
from app.db.models.conversation_activity import ActivityState
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.intervene import InterveneRequest, InterveneRequestStatus, InterventionType
from app.db.models.agents import AgentInputType, AgentType, AgentJob, AgentJobStatus
from app.services.conversations.activity_reaper import ConversationActivityReaper
from app.services.conversations.activity_store import ConversationActivityStore

NOW = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_threshold(monkeypatch):
    """Deterministic staleness threshold (5 minutes)."""
    monkeypatch.setattr(reaper_module, "get_stale_threshold_seconds", lambda: 300)


@pytest.fixture
def reaper() -> ConversationActivityReaper:
    return ConversationActivityReaper()


async def _make_session(
    db: AsyncSession, status: ConversationStatus = ConversationStatus.active
) -> ConversationSession:
    session = ConversationSession(status=status)
    db.add(session)
    await db.flush()
    return session


async def _make_activity(
    db: AsyncSession,
    conv: ConversationSession,
    state: ActivityState,
    *,
    last_updated: datetime = NOW,
    pending_intervene_request_id=None,
    current_turn_id=None,
) -> None:
    store = ConversationActivityStore()
    activity = await store.upsert(
        conv.id,
        db,
        state=state,
        pending_intervene_request_id=pending_intervene_request_id,
        current_turn_id=current_turn_id,
    )
    # Force a deterministic heartbeat (server_default/now() is DB time).
    activity.last_updated_at = last_updated
    await db.flush()


async def _activity_of(db: AsyncSession, conv: ConversationSession):
    """Re-read the live activity row (async-safe — no lazy relationship loads)."""
    return await ConversationActivityStore().get(conv.id, db)


async def _make_pending_intervention(db: AsyncSession, conv=None) -> InterveneRequest:
    at = AgentType(name=f"reaper-at-{uuid.uuid4().hex}", input_type=AgentInputType.conversation)
    db.add(at)
    await db.flush()
    job = AgentJob(id=uuid.uuid4(), agent_type_id=at.id, status=AgentJobStatus.waiting_for_human)
    db.add(job)
    await db.flush()
    req = InterveneRequest(
        agent_session_id=job.id,
        agent_type_id=at.id,
        intervention_type=InterventionType.approval,
        reason="reaper test",
        status=InterveneRequestStatus.pending,
        conversation_session_id=conv.id if conv else None,
    )
    db.add(req)
    await db.flush()
    return req


class TestWorkingStateResolution:
    @pytest.mark.asyncio
    async def test_stale_heartbeat_resolves_to_timed_out(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        await _make_activity(
            db_session, conv, ActivityState.thinking, last_updated=NOW - timedelta(hours=1)
        )
        assert await reaper.reap(db_session, now=NOW) == 1
        activity = await _activity_of(db_session, conv)
        assert activity.state == ActivityState.timed_out
        assert activity.is_terminal is True

    @pytest.mark.asyncio
    async def test_fresh_working_activity_is_untouched(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        await _make_activity(
            db_session, conv, ActivityState.delegating, last_updated=NOW - timedelta(seconds=30)
        )
        assert await reaper.reap(db_session, now=NOW) == 0
        activity = await _activity_of(db_session, conv)
        assert activity.state == ActivityState.delegating

    @pytest.mark.asyncio
    async def test_dead_session_resolves_to_failed_even_when_fresh(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session, status=ConversationStatus.closed)
        await _make_activity(
            db_session, conv, ActivityState.using_tool, last_updated=NOW - timedelta(seconds=5)
        )
        assert await reaper.reap(db_session, now=NOW) == 1
        activity = await _activity_of(db_session, conv)
        assert activity.state == ActivityState.failed

    @pytest.mark.asyncio
    async def test_terminal_rows_are_never_revisited(self, db_session: AsyncSession, reaper):
        conv = await _make_session(db_session)
        await _make_activity(
            db_session, conv, ActivityState.finished, last_updated=NOW - timedelta(days=30)
        )
        assert await reaper.reap(db_session, now=NOW) == 0


class TestWaitingForHumanProtection:
    @pytest.mark.asyncio
    async def test_pending_intervention_on_active_session_is_protected(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        req = await _make_pending_intervention(db_session, conv)
        await _make_activity(
            db_session,
            conv,
            ActivityState.waiting_for_human,
            last_updated=NOW - timedelta(hours=2),
            pending_intervene_request_id=req.id,
        )
        assert await reaper.reap(db_session, now=NOW) == 0
        activity = await _activity_of(db_session, conv)
        assert activity.state == ActivityState.waiting_for_human
        assert activity.is_terminal is False

    @pytest.mark.asyncio
    async def test_expired_intervention_resolves_even_on_active_session(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        req = await _make_pending_intervention(db_session, conv)
        req.status = InterveneRequestStatus.expired
        await db_session.flush()
        await _make_activity(
            db_session,
            conv,
            ActivityState.waiting_for_human,
            last_updated=NOW - timedelta(seconds=10),
            pending_intervene_request_id=req.id,
        )
        assert await reaper.reap(db_session, now=NOW) == 1
        activity = await _activity_of(db_session, conv)
        assert activity.state == ActivityState.timed_out

    @pytest.mark.asyncio
    async def test_cancelled_intervention_resolves_even_on_active_session(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        req = await _make_pending_intervention(db_session, conv)
        req.status = InterveneRequestStatus.cancelled
        await db_session.flush()
        await _make_activity(
            db_session,
            conv,
            ActivityState.waiting_for_human,
            last_updated=NOW - timedelta(seconds=10),
            pending_intervene_request_id=req.id,
        )
        assert await reaper.reap(db_session, now=NOW) == 1
        activity = await _activity_of(db_session, conv)
        assert activity.state == ActivityState.timed_out

    @pytest.mark.asyncio
    async def test_pending_intervention_on_dead_session_resolves(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session, status=ConversationStatus.error)
        req = await _make_pending_intervention(db_session, conv)
        await _make_activity(
            db_session,
            conv,
            ActivityState.waiting_for_human,
            last_updated=NOW - timedelta(seconds=10),
            pending_intervene_request_id=req.id,
        )
        assert await reaper.reap(db_session, now=NOW) == 1
        activity = await _activity_of(db_session, conv)
        assert activity.state == ActivityState.timed_out

    @pytest.mark.asyncio
    async def test_responded_intervention_fresh_is_protected_stale_resolves(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        req = await _make_pending_intervention(db_session, conv)
        req.status = InterveneRequestStatus.responded
        await db_session.flush()
        await _make_activity(
            db_session,
            conv,
            ActivityState.waiting_for_human,
            last_updated=NOW - timedelta(seconds=10),
            pending_intervene_request_id=req.id,
        )
        # Fresh: operator answered, resume expected momentarily — protected.
        assert await reaper.reap(db_session, now=NOW) == 0
        activity = await _activity_of(db_session, conv)
        assert activity.state == ActivityState.waiting_for_human

        # Stale: the AR restart lost the resume registry — the turn is dead.
        activity.last_updated_at = NOW - timedelta(hours=1)
        await db_session.flush()
        assert await reaper.reap(db_session, now=NOW) == 1
        assert (await _activity_of(db_session, conv)).state == ActivityState.timed_out

    @pytest.mark.asyncio
    async def test_orphaned_waiting_row_stale_resolves_to_timed_out(
        self, db_session: AsyncSession, reaper
    ):
        """A waiting row with no resolvable intervention reference."""
        conv = await _make_session(db_session)
        await _make_activity(
            db_session,
            conv,
            ActivityState.waiting_for_human,
            last_updated=NOW - timedelta(hours=3),
            pending_intervene_request_id=None,
        )
        assert await reaper.reap(db_session, now=NOW) == 1
        activity = await _activity_of(db_session, conv)
        assert activity.state == ActivityState.timed_out

    @pytest.mark.asyncio
    async def test_dangling_request_reference_does_not_error(
        self, db_session: AsyncSession, reaper
    ):
        """Activity referencing an intervention that no longer exists must be
        resolvable without error (fresh → protected, stale → timed_out)."""
        conv = await _make_session(db_session)
        await _make_activity(
            db_session,
            conv,
            ActivityState.waiting_for_human,
            last_updated=NOW - timedelta(seconds=10),
            pending_intervene_request_id=uuid.uuid4(),  # dangling
        )
        assert await reaper.reap(db_session, now=NOW) == 0
        activity = await _activity_of(db_session, conv)
        activity.last_updated_at = NOW - timedelta(hours=2)
        await db_session.flush()
        assert await reaper.reap(db_session, now=NOW) == 1
        assert (await _activity_of(db_session, conv)).state == ActivityState.timed_out
