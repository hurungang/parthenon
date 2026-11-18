"""Unit tests — Terminal Resolver (Phase 5.2) and checkpoint retention (5.4).

The activity reaper is the Terminal Resolver for paused turns: it consults the
durable resume record instead of guessing from a heartbeat.

Branches covered:

- protected: live ``waiting_for_human``, unexpired, checkpoint present
- expired answer window → ``unresumable/expired`` + ``timed_out`` activity
- superseded by a newer pause → activity re-pointed at the live record
- cancelled intervention → terminal, record closed as ``cancelled``
- lost pause point (missing / consumed checkpoint) → ``resume_failed`` +
  ``failed`` activity, distinct reason codes
- abandoned ``resuming`` (claim gone past the abandon bound) → ``resume_failed``
- live claim on a ``resuming`` record → protected

Every resolution must leave the activity row, the resume record, and
``active_resume_id`` in agreement.  The retention sweep deletes payloads that
can never be loaded again while keeping the index row and its outcome.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.conversations.activity_reaper as reaper_module
from app.db.models.conversation_activity import ActivityState, ConversationActivity
from app.db.models.conversation_turn_resume import (
    ConversationTurnCheckpoint,
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
from app.db.models.intervene import (
    InterveneRequest,
    InterveneRequestStatus,
    InterventionType,
)
from app.services.conversations.activity_reaper import ConversationActivityReaper
from app.services.conversations.activity_store import ConversationActivityStore
from app.services.conversations.turn_checkpoint_store import (
    ConversationTurnCheckpointStore,
)
from app.services.conversations.turn_resolution import (
    REASON_CANCELLED,
    REASON_CHECKPOINT_CONSUMED,
    REASON_CHECKPOINT_UNAVAILABLE,
    REASON_EXPIRED,
    REASON_RESUME_FAILED,
    resolve_unresumable_turn,
)
from app.db.session import get_db
from app.services.conversations.turn_resume_store import ConversationTurnResumeStore

NOW = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fixed_threshold(monkeypatch):
    monkeypatch.setattr(reaper_module, "get_stale_threshold_seconds", lambda: 300)


@pytest.fixture
def reaper() -> ConversationActivityReaper:
    # Deterministic bounds: abandon after 120s without a live claim,
    # checkpoint persistence grace 60s.
    return ConversationActivityReaper(
        checkpoint_grace_seconds=60, abandon_grace_seconds=120
    )


async def _make_session(
    db: AsyncSession, status: ConversationStatus = ConversationStatus.active
) -> ConversationSession:
    session = ConversationSession(status=status)
    db.add(session)
    await db.flush()
    return session


async def _make_intervention(
    db: AsyncSession,
    conv: ConversationSession,
    *,
    status: InterveneRequestStatus = InterveneRequestStatus.pending,
    expires_at: datetime | None = None,
) -> InterveneRequest:
    from app.db.models.agents import AgentInputType, AgentType

    agent_type = AgentType(
        name=f"resolver-at-{uuid.uuid4().hex}",
        input_type=AgentInputType.conversation,
    )
    db.add(agent_type)
    await db.flush()
    req = InterveneRequest(
        agent_type_id=agent_type.id,
        intervention_type=InterventionType.approval,
        reason="approval preview",
        status=status,
        conversation_session_id=conv.id,
        expires_at=expires_at,
    )
    db.add(req)
    await db.flush()
    return req


async def _make_pause(
    db: AsyncSession,
    conv: ConversationSession,
    *,
    req: InterveneRequest | None = None,
    expires_at: datetime | None = None,
    state: ResumeState = ResumeState.waiting_for_human,
    created_at: datetime | None = None,
    checkpoint: bool = True,
    heartbeat: datetime = NOW,
) -> tuple[ConversationTurnResume, ConversationTurnCheckpoint | None]:
    record = await ConversationTurnResumeStore().create_or_reuse(
        conv.id,
        db,
        intervene_request_id=req.id if req is not None else None,
        expires_at=expires_at,
    )
    record.state = state
    record.last_attempt_at = created_at or NOW
    record.created_at = created_at or NOW
    if state is ResumeState.resuming:
        record.claimed_by_instance_id = None
        record.claim_expires_at = None
    await db.flush()

    payload_row = None
    if checkpoint:
        payload_row = await ConversationTurnCheckpointStore().upsert_payload(
            record.id,
            db,
            payload={"thread": str(conv.id)},
        )

    activity = await ConversationActivityStore().upsert(
        conv.id,
        db,
        state=ActivityState.waiting_for_human,
        pending_intervene_request_id=req.id if req is not None else None,
        active_resume_id=record.id,
    )
    activity.last_updated_at = heartbeat
    await db.flush()
    return record, payload_row


async def _reload(
    db: AsyncSession, conv: ConversationSession
) -> tuple[ConversationTurnResume | None, ConversationActivity | None]:
    activity = await ConversationActivityStore().get(conv.id, db)
    record = await ConversationTurnResumeStore().get_live_for_session(conv.id, db)
    if record is None:
        record = await ConversationTurnResumeStore().get_latest_for_session(conv.id, db)
    return record, activity


class TestProtectedPause:
    @pytest.mark.asyncio
    async def test_unexpired_checkpointed_pause_is_protected(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        record, _payload = await _make_pause(
            db_session,
            conv,
            req=req,
            expires_at=NOW + timedelta(minutes=10),
            # A pause stops emitting activity beats: staleness must not kill it.
            heartbeat=NOW - timedelta(hours=3),
        )

        assert await reaper.reap(db_session, now=NOW) == 0

        reloaded, activity = await _reload(db_session, conv)
        assert reloaded is not None and reloaded.id == record.id
        assert reloaded.is_terminal is False
        assert activity is not None
        assert activity.state is ActivityState.waiting_for_human
        assert activity.active_resume_id == record.id


class TestExpiry:
    @pytest.mark.asyncio
    async def test_elapsed_window_resolves_expired_with_agreement(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        record, _payload = await _make_pause(
            db_session,
            conv,
            req=req,
            expires_at=NOW - timedelta(minutes=1),
        )

        assert await reaper.reap(db_session, now=NOW) == 1

        reloaded, activity = await _reload(db_session, conv)
        assert reloaded is not None
        assert reloaded.id == record.id
        assert reloaded.state is ResumeState.unresumable
        assert reloaded.resume_outcome is ResumeOutcome.expired
        assert reloaded.terminal_reason_code == REASON_EXPIRED
        assert reloaded.write_applied is False
        assert activity is not None
        assert activity.state is ActivityState.timed_out
        assert activity.is_terminal is True
        assert activity.active_resume_id is None

    @pytest.mark.asyncio
    async def test_expired_intervention_resolves_even_without_record_expiry(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(
            db_session, conv, status=InterveneRequestStatus.expired
        )
        await _make_pause(db_session, conv, req=req, expires_at=NOW + timedelta(minutes=5))

        assert await reaper.reap(db_session, now=NOW) == 1
        record, activity = await _reload(db_session, conv)
        assert record is not None and record.resume_outcome is ResumeOutcome.expired
        assert activity is not None and activity.state is ActivityState.timed_out


class TestCancellation:
    @pytest.mark.asyncio
    async def test_cancelled_pause_closes_the_record_and_the_activity(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(
            db_session, conv, status=InterveneRequestStatus.cancelled
        )
        await _make_pause(db_session, conv, req=req, expires_at=NOW + timedelta(minutes=5))

        assert await reaper.reap(db_session, now=NOW) == 1

        record, activity = await _reload(db_session, conv)
        assert record is not None
        assert record.resume_outcome is ResumeOutcome.cancelled
        assert record.terminal_reason_code == REASON_CANCELLED
        assert activity is not None
        assert activity.state is ActivityState.timed_out
        assert activity.active_resume_id is None

    @pytest.mark.asyncio
    async def test_dead_session_closes_the_record_as_cancelled(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session, status=ConversationStatus.closed)
        req = await _make_intervention(db_session, conv)
        await _make_pause(db_session, conv, req=req, expires_at=NOW + timedelta(minutes=5))

        assert await reaper.reap(db_session, now=NOW) == 1
        record, activity = await _reload(db_session, conv)
        assert record is not None and record.resume_outcome is ResumeOutcome.cancelled
        assert activity is not None and activity.state is ActivityState.timed_out


class TestSupersede:
    @pytest.mark.asyncio
    async def test_superseded_pause_repoints_activity_at_the_live_record(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        old_req = await _make_intervention(db_session, conv)
        old_record, _ = await _make_pause(
            db_session, conv, req=old_req, expires_at=NOW + timedelta(minutes=5)
        )

        # A newer pause supersedes the old record (one live record per session).
        new_req = await _make_intervention(db_session, conv)
        new_record = await ConversationTurnResumeStore().create_or_reuse(
            conv.id, db_session, intervene_request_id=new_req.id
        )
        new_record.created_at = NOW
        await db_session.flush()
        await ConversationTurnCheckpointStore().upsert_payload(
            new_record.id, db_session, payload={"thread": str(conv.id)}
        )

        assert old_record.is_terminal is True
        assert old_record.resume_outcome is ResumeOutcome.superseded

        # Activity still points at the superseded record.
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        activity.active_resume_id = old_record.id
        await db_session.flush()

        resolved = await reaper.reap(db_session, now=NOW)
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.active_resume_id == new_record.id
        assert activity.state is ActivityState.waiting_for_human
        assert activity.is_terminal is False
        assert resolved == 0

    @pytest.mark.asyncio
    async def test_superseded_without_live_record_is_terminal(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        await _make_pause(db_session, conv, expires_at=NOW + timedelta(minutes=5))
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        record = await ConversationTurnResumeStore().get_live_for_session(
            conv.id, db_session
        )
        assert record is not None
        # Close the record as superseded and leave the activity waiting.
        await ConversationTurnResumeStore().resolve_unresumable(
            record.id, db_session, reason_code=REASON_EXPIRED
        )
        record.resume_outcome = ResumeOutcome.superseded
        await db_session.flush()

        assert await reaper.reap(db_session, now=NOW) == 1
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.is_terminal is True
        assert activity.state is ActivityState.timed_out


class TestLostPausePoint:
    @pytest.mark.asyncio
    async def test_missing_checkpoint_past_grace_is_unresumable(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        record, _ = await _make_pause(
            db_session,
            conv,
            req=req,
            expires_at=NOW + timedelta(minutes=5),
            checkpoint=False,
            created_at=NOW - timedelta(minutes=30),
        )

        assert await reaper.reap(db_session, now=NOW) == 1

        reloaded, activity = await _reload(db_session, conv)
        assert reloaded is not None and reloaded.id == record.id
        assert reloaded.resume_outcome is ResumeOutcome.resume_failed
        assert reloaded.terminal_reason_code == REASON_CHECKPOINT_UNAVAILABLE
        assert activity is not None
        assert activity.state is ActivityState.failed

    @pytest.mark.asyncio
    async def test_missing_checkpoint_within_grace_is_protected(
        self, db_session: AsyncSession, reaper
    ):
        """The index and the payload are written in quick succession — a payload
        that has not landed yet must not fail the pause."""
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        await _make_pause(
            db_session,
            conv,
            req=req,
            expires_at=NOW + timedelta(minutes=5),
            checkpoint=False,
            created_at=NOW - timedelta(seconds=10),
        )
        assert await reaper.reap(db_session, now=NOW) == 0

    @pytest.mark.asyncio
    async def test_consumed_checkpoint_is_unresumable(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        record, payload = await _make_pause(
            db_session, conv, req=req, expires_at=NOW + timedelta(minutes=5)
        )
        assert payload is not None
        await ConversationTurnCheckpointStore().mark_consumed(record.id, db_session)

        assert await reaper.reap(db_session, now=NOW) == 1
        reloaded, activity = await _reload(db_session, conv)
        assert reloaded is not None
        assert reloaded.terminal_reason_code == REASON_CHECKPOINT_CONSUMED
        assert activity is not None and activity.state is ActivityState.failed


class TestResuming:
    @pytest.mark.asyncio
    async def test_abandoned_resuming_resolves_resume_failed(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        record, _ = await _make_pause(
            db_session,
            conv,
            req=req,
            expires_at=NOW + timedelta(minutes=5),
            state=ResumeState.resuming,
            created_at=NOW - timedelta(minutes=10),
        )

        assert await reaper.reap(db_session, now=NOW) == 1

        reloaded, activity = await _reload(db_session, conv)
        assert reloaded is not None and reloaded.id == record.id
        assert reloaded.resume_outcome is ResumeOutcome.resume_failed
        assert reloaded.terminal_reason_code == REASON_RESUME_FAILED
        assert activity is not None and activity.state is ActivityState.failed

    @pytest.mark.asyncio
    async def test_live_claim_is_protected(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        record, _ = await _make_pause(
            db_session,
            conv,
            req=req,
            expires_at=NOW + timedelta(minutes=5),
            state=ResumeState.resuming,
            created_at=NOW - timedelta(minutes=10),
        )
        record.claimed_by_instance_id = "ar-instance-1"
        record.claim_expires_at = NOW + timedelta(seconds=30)
        await db_session.flush()

        assert await reaper.reap(db_session, now=NOW) == 0
        reloaded, activity = await _reload(db_session, conv)
        assert reloaded is not None and reloaded.is_terminal is False
        assert activity is not None
        assert activity.state is ActivityState.waiting_for_human


class TestActivityResumeProjection:
    """The activity read exposes the durable resume projection (task 5.5)."""

    @staticmethod
    def _client(db: AsyncSession):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from app.api.deps import (
            require_internal_tenant_context,
            require_service_certificate,
        )
        from app.api.v1.internal.session_data import InternalSessionDataRouter
        from app.core.tenant_context import TenantContext

        app = FastAPI()
        app.include_router(InternalSessionDataRouter, prefix="/api/v1")

        async def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[require_service_certificate] = lambda: None
        app.dependency_overrides[require_internal_tenant_context] = lambda: (
            TenantContext(tenant_id=uuid.uuid4(), slug="t", name="t")
        )
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    @pytest.mark.asyncio
    async def test_paused_activity_projects_resume_state(
        self, db_session: AsyncSession
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        record, _ = await _make_pause(
            db_session, conv, req=req, expires_at=NOW + timedelta(minutes=5)
        )
        await db_session.commit()

        async with self._client(db_session) as client:
            response = await client.get(
                f"/api/v1/internal/data/conversations/{conv.id}/activity"
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["state"] == "waiting_for_human"
        assert body["active_resume_id"] == str(record.id)
        assert body["resume_state"] == "waiting_for_human"
        assert body["terminal_reason_code"] is None
        assert body["write_applied"] is False

    @pytest.mark.asyncio
    async def test_terminal_activity_projects_the_reason_code(
        self, db_session: AsyncSession
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        record, _ = await _make_pause(
            db_session, conv, req=req, expires_at=NOW + timedelta(minutes=5)
        )
        resolved = await resolve_unresumable_turn(
            db_session,
            conv.id,
            reason_code=REASON_EXPIRED,
            intervene_request_id=req.id,
        )
        assert resolved is not None and resolved.id == record.id
        await db_session.commit()

        async with self._client(db_session) as client:
            response = await client.get(
                f"/api/v1/internal/data/conversations/{conv.id}/activity"
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["state"] == "timed_out"
        assert body["is_terminal"] is True
        assert body["resume_state"] == "unresumable"
        assert body["terminal_reason_code"] == REASON_EXPIRED
        assert body["active_resume_id"] is None


class TestDeadConfirmationExpiry:
    """A dead pause must never leave an actionable confirmation behind.

    ``InterveneRequestStore.list_pending_for_conversation`` returns only
    ``pending`` requests, so expiring the linked request is what stops the UI
    from offering a confirmation whose resume record already closed (production:
    an older pause's request stayed ``pending`` long after its resume row was
    ``expired``).
    """

    @staticmethod
    async def _request_status(db: AsyncSession, req_id) -> InterveneRequest:
        request = await db.get(InterveneRequest, req_id)
        assert request is not None
        return request

    @pytest.mark.asyncio
    async def test_resolve_unresumable_expires_the_pending_intervention(
        self, db_session: AsyncSession
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        record, _ = await _make_pause(
            db_session, conv, req=req, expires_at=NOW + timedelta(minutes=5)
        )

        resolved = await resolve_unresumable_turn(
            db_session,
            conv.id,
            reason_code=REASON_EXPIRED,
            resume=record,
            intervene_request_id=req.id,
        )
        assert resolved is not None

        request = await self._request_status(db_session, req.id)
        assert request.status is InterveneRequestStatus.expired
        assert request.responded_at is not None

    @pytest.mark.asyncio
    async def test_an_answered_intervention_is_never_clobbered(
        self, db_session: AsyncSession
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(
            db_session, conv, status=InterveneRequestStatus.responded
        )
        record, _ = await _make_pause(
            db_session, conv, req=req, expires_at=NOW + timedelta(minutes=5)
        )

        await resolve_unresumable_turn(
            db_session,
            conv.id,
            reason_code=REASON_RESUME_FAILED,
            resume=record,
            intervene_request_id=req.id,
        )

        request = await self._request_status(db_session, req.id)
        assert request.status is InterveneRequestStatus.responded

    @pytest.mark.asyncio
    async def test_reaper_expiry_branch_expires_the_pending_intervention(
        self, db_session: AsyncSession, reaper
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        await _make_pause(
            db_session,
            conv,
            req=req,
            expires_at=NOW - timedelta(minutes=1),
        )

        assert await reaper.reap(db_session, now=NOW) >= 1
        request = await self._request_status(db_session, req.id)
        assert request.status is InterveneRequestStatus.expired
        assert request.responded_at is not None

    @pytest.mark.asyncio
    async def test_reaper_heals_a_terminal_resume_with_a_pending_intervention(
        self, db_session: AsyncSession, reaper
    ):
        """The exact production shape: the resume row is already unresumable but
        the request is still pending."""
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        record, _ = await _make_pause(
            db_session, conv, req=req, expires_at=NOW + timedelta(minutes=5)
        )
        record.state = ResumeState.unresumable
        record.resume_outcome = ResumeOutcome.expired
        record.is_terminal = True
        record.terminal_reason_code = REASON_EXPIRED
        record.resolved_at = NOW - timedelta(minutes=5)
        await db_session.flush()

        await reaper.reap(db_session, now=NOW)

        request = await self._request_status(db_session, req.id)
        assert request.status is InterveneRequestStatus.expired

    @pytest.mark.asyncio
    async def test_reaper_expires_the_confirmation_of_a_superseded_pause(
        self, db_session: AsyncSession, reaper
    ):
        """A newer pause supersedes the old record — the old confirmation can
        never be answered, so the sweep expires it (the newer one stays)."""
        conv = await _make_session(db_session)
        old_req = await _make_intervention(db_session, conv)
        old_record, _ = await _make_pause(
            db_session, conv, req=old_req, expires_at=NOW + timedelta(minutes=5)
        )

        new_req = await _make_intervention(db_session, conv)
        new_record = await ConversationTurnResumeStore().create_or_reuse(
            conv.id, db_session, intervene_request_id=new_req.id
        )

        # The activity row still points at the superseded record.
        assert old_record.is_terminal is True
        await reaper.reap(db_session, now=NOW)

        old_request = await self._request_status(db_session, old_req.id)
        assert old_request.status is InterveneRequestStatus.expired
        # The new pause's confirmation stays answerable.
        new_request = await self._request_status(db_session, new_req.id)
        assert new_request.status is InterveneRequestStatus.pending
        activity = await ConversationActivityStore().get(conv.id, db_session)
        assert activity is not None
        assert activity.active_resume_id == new_record.id


class TestCheckpointRetention:
    @pytest.mark.asyncio
    async def test_purge_keeps_the_index_row_and_outcome_turn(
        self, db_session: AsyncSession
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        record, payload = await _make_pause(
            db_session, conv, req=req, expires_at=NOW + timedelta(minutes=5)
        )
        assert payload is not None

        resolved = await resolve_unresumable_turn(
            db_session,
            conv.id,
            reason_code=REASON_EXPIRED,
            intervene_request_id=req.id,
        )
        assert resolved is not None
        resolved.resolved_at = NOW - timedelta(hours=2)
        await db_session.flush()

        turns_before = (
            await db_session.execute(
                select(ConversationTurn).where(ConversationTurn.session_id == conv.id)
            )
        ).scalars().all()
        assert len(turns_before) == 1

        removed = await ConversationTurnCheckpointStore().purge(
            db_session, now=NOW, terminal_grace_seconds=3600
        )
        assert removed >= 1

        # Payload gone, index row + outcome turn + terminal state survive.
        row = (
            await db_session.execute(
                select(ConversationTurnCheckpoint).where(
                    ConversationTurnCheckpoint.resume_id == record.id
                )
            )
        ).scalar_one_or_none()
        assert row is None

        index_row = await ConversationTurnResumeStore().get(record.id, db_session)
        assert index_row is not None
        assert index_row.is_terminal is True
        assert index_row.outcome_turn_id is not None
        turns_after = (
            await db_session.execute(
                select(ConversationTurn).where(ConversationTurn.session_id == conv.id)
            )
        ).scalars().all()
        assert len(turns_after) == len(turns_before)

    @pytest.mark.asyncio
    async def test_purge_respects_the_terminal_grace_window(
        self, db_session: AsyncSession
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        record, _payload = await _make_pause(
            db_session, conv, req=req, expires_at=NOW + timedelta(minutes=5)
        )
        # Resolution marks the payload consumed; an unconsumed payload on a
        # freshly resolved record stays inside the grace window.
        record.state = ResumeState.unresumable
        record.resume_outcome = ResumeOutcome.expired
        record.is_terminal = True
        record.resolved_at = NOW
        await db_session.flush()

        _removed = await ConversationTurnCheckpointStore().purge(
            db_session, now=NOW, terminal_grace_seconds=3600
        )
        # The freshly resolved record is inside the grace window: its payload
        # must survive (other rows in the shared test DB may legitimately go).
        remaining = (
            await db_session.execute(
                select(ConversationTurnCheckpoint).where(
                    ConversationTurnCheckpoint.resume_id == record.id
                )
            )
        ).scalar_one_or_none()
        assert remaining is not None

    @pytest.mark.asyncio
    async def test_consumed_payload_cannot_be_loaded_again(
        self, db_session: AsyncSession
    ):
        conv = await _make_session(db_session)
        req = await _make_intervention(db_session, conv)
        record, _payload = await _make_pause(
            db_session, conv, req=req, expires_at=NOW + timedelta(minutes=5)
        )
        store = ConversationTurnCheckpointStore()
        assert await store.load_payload(record.id, db_session) is not None
        await ConversationTurnCheckpointStore().mark_consumed(record.id, db_session)
        assert await store.load_payload(record.id, db_session) is None

