"""Unit tests — ConversationTurnResumeStore lifecycle, supersede, and claims.

Covers the Control Center resume index contract for resumable-agent-turn-
persistence (Phase 2.1):

- create registers one live ``waiting_for_human`` record; a replay for the same
  intervention reuses it (no duplicate)
- a new pause supersedes the previous live record (``superseded``, terminal)
  while the one-live-record invariant holds
- idempotency key uniqueness is enforced across turns
- claim acquire / contention (second claimer refused while the lease is live) /
  re-acquire after lease expiry / not-found / terminal
- release only succeeds for the holder
- ``approved_applied`` requires ``write_applied``; denial/expiry never apply a
  write; double-resolution raises
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_turn_resume import (
    ConversationTurnResume,
    ResumeOutcome,
    ResumeState,
)
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.services.conversations.turn_resume_store import (
    ClaimStatus,
    ConversationTurnResumeStore,
    TurnResumeConflictError,
    TurnResumeNotFoundError,
    TurnResumeTransitionError,
)


@pytest.fixture
def store() -> ConversationTurnResumeStore:
    return ConversationTurnResumeStore()


async def _make_session(db: AsyncSession) -> ConversationSession:
    session = ConversationSession(status=ConversationStatus.active)
    db.add(session)
    await db.flush()
    return session


async def _session_rows(
    db: AsyncSession, conversation_session_id
) -> list[ConversationTurnResume]:
    result = await db.execute(
        select(ConversationTurnResume).where(
            ConversationTurnResume.conversation_session_id == conversation_session_id
        )
    )
    return list(result.scalars().all())


class TestCreateOrReuse:
    @pytest.mark.asyncio
    async def test_create_registers_single_live_waiting_record(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)

        assert record.id is not None
        assert record.state == ResumeState.waiting_for_human
        assert record.is_terminal is False
        assert record.resume_outcome is None
        assert record.resume_key
        assert record.idempotency_key
        assert record.write_applied is False
        assert len(await _session_rows(db_session, conv.id)) == 1

    @pytest.mark.asyncio
    async def test_replay_for_same_intervention_reuses_the_record(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        request_id = uuid.uuid4()

        first = await store.create_or_reuse(
            conv.id, db_session, intervene_request_id=request_id
        )
        replay = await store.create_or_reuse(
            conv.id, db_session, intervene_request_id=request_id
        )

        assert replay.id == first.id
        assert len(await _session_rows(db_session, conv.id)) == 1

    @pytest.mark.asyncio
    async def test_reuse_refreshes_expiry_window(self, db_session: AsyncSession, store):
        conv = await _make_session(db_session)
        request_id = uuid.uuid4()
        later = datetime.now(timezone.utc) + timedelta(minutes=10)

        first = await store.create_or_reuse(
            conv.id, db_session, intervene_request_id=request_id
        )
        await store.create_or_reuse(
            conv.id, db_session, intervene_request_id=request_id, expires_at=later
        )

        assert first.expires_at is not None

    @pytest.mark.asyncio
    async def test_new_pause_supersedes_previous_live_record(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        first = await store.create_or_reuse(
            conv.id, db_session, intervene_request_id=uuid.uuid4()
        )
        second = await store.create_or_reuse(
            conv.id, db_session, intervene_request_id=uuid.uuid4()
        )

        await db_session.refresh(first)
        assert second.id != first.id
        # The old record is terminal as superseded (never left live).
        assert first.is_terminal is True
        assert first.state == ResumeState.unresumable
        assert first.resume_outcome == ResumeOutcome.superseded
        assert first.resolved_at is not None
        # Exactly one live record remains.
        live = await store.get_live_for_session(conv.id, db_session)
        assert live is not None and live.id == second.id

    @pytest.mark.asyncio
    async def test_idempotency_key_is_globally_unique(
        self, db_session: AsyncSession, store
    ):
        first_conv = await _make_session(db_session)
        other_conv = await _make_session(db_session)
        await store.create_or_reuse(
            first_conv.id, db_session, idempotency_key="turn-key-1"
        )

        with pytest.raises(TurnResumeConflictError):
            await store.create_or_reuse(
                other_conv.id, db_session, idempotency_key="turn-key-1"
            )

    @pytest.mark.asyncio
    async def test_replay_with_same_idempotency_key_reuses_same_turn(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        first = await store.create_or_reuse(
            conv.id, db_session, idempotency_key="turn-key-2"
        )
        replay = await store.create_or_reuse(
            conv.id, db_session, idempotency_key="turn-key-2"
        )
        assert replay.id == first.id

    @pytest.mark.asyncio
    async def test_new_pause_in_a_continued_turn_gets_a_fresh_key(
        self, db_session: AsyncSession, store
    ):
        """A resumed turn that pauses again must get its own resume record and
        its own per-pause idempotency key (the key is per paused turn, so the
        previous pause's key must not be reused for the new record)."""
        conv = await _make_session(db_session)
        first = await store.create_or_reuse(
            conv.id,
            db_session,
            intervene_request_id=uuid.uuid4(),
            idempotency_key="turn-key-3",
        )
        second = await store.create_or_reuse(
            conv.id,
            db_session,
            intervene_request_id=uuid.uuid4(),
            idempotency_key="turn-key-3",
        )

        assert second.id != first.id
        assert second.idempotency_key != "turn-key-3"
        assert second.idempotency_key
        # The old record is superseded; exactly one live record remains.
        await db_session.refresh(first)
        assert first.resume_outcome == ResumeOutcome.superseded
        live = await store.get_live_for_session(conv.id, db_session)
        assert live is not None and live.id == second.id

    @pytest.mark.asyncio
    async def test_unknown_session_raises(self, db_session: AsyncSession, store):
        with pytest.raises(TurnResumeNotFoundError):
            await store.create_or_reuse(uuid.uuid4(), db_session)


class TestReads:
    @pytest.mark.asyncio
    async def test_reads_by_key_and_liveness(self, db_session: AsyncSession, store):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(
            conv.id, db_session, resume_key="opaque-key", idempotency_key="idem-key"
        )

        assert (await store.get_by_resume_key("opaque-key", db_session)).id == record.id
        assert (
            await store.get_by_idempotency_key("idem-key", db_session)
        ).id == record.id
        assert (await store.get_live_for_session(conv.id, db_session)).id == record.id
        assert await store.get_by_resume_key("missing", db_session) is None

    @pytest.mark.asyncio
    async def test_live_lookup_returns_none_after_resolution(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)
        await store.resolve(record.id, db_session, ResumeOutcome.denied)
        assert await store.get_live_for_session(conv.id, db_session) is None


class TestClaim:
    @pytest.mark.asyncio
    async def test_first_claim_acquires_and_counts_attempt(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)

        result = await store.claim(
            record.id, db_session, instance_id="ar-1", lease_seconds=45
        )

        assert result.status is ClaimStatus.acquired
        assert result.holder_instance_id == "ar-1"
        assert result.resume is not None
        assert result.resume.attempt_count == 1
        assert result.resume.last_attempt_at is not None
        # Claiming never changes the lifecycle state.
        assert result.resume.state is ResumeState.waiting_for_human

    @pytest.mark.asyncio
    async def test_holder_can_renew_its_own_live_lease(
        self, db_session: AsyncSession, store
    ):
        """A long resume renews its own claim; self-renew must not be contention."""
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)

        first = await store.claim(
            record.id, db_session, instance_id="ar-1", lease_seconds=45
        )
        renewed = await store.claim(
            record.id, db_session, instance_id="ar-1", lease_seconds=45
        )

        assert first.status is ClaimStatus.acquired
        assert renewed.status is ClaimStatus.acquired
        assert renewed.holder_instance_id == "ar-1"
        assert renewed.claim_expires_at is not None

    @pytest.mark.asyncio
    async def test_second_claimer_refused_while_lease_is_live(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)

        first = await store.claim(
            record.id, db_session, instance_id="ar-1", lease_seconds=45
        )
        second = await store.claim(
            record.id, db_session, instance_id="ar-2", lease_seconds=45
        )

        assert first.status is ClaimStatus.acquired
        assert second.status is ClaimStatus.already_held
        assert second.holder_instance_id == "ar-1"
        assert second.claim_expires_at is not None

        refreshed = await store.get(record.id, db_session)
        assert refreshed.claimed_by_instance_id == "ar-1"
        assert refreshed.attempt_count == 1

    @pytest.mark.asyncio
    async def test_reacquire_after_lease_expiry(self, db_session: AsyncSession, store):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)
        await store.claim(record.id, db_session, instance_id="ar-1", lease_seconds=45)

        # Simulate failover: the lease expired without a release.
        record.claim_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db_session.flush()

        result = await store.claim(
            record.id, db_session, instance_id="ar-2", lease_seconds=45
        )
        assert result.status is ClaimStatus.acquired
        assert result.holder_instance_id == "ar-2"
        assert result.resume.attempt_count == 2

    @pytest.mark.asyncio
    async def test_claim_terminal_and_not_found(self, db_session: AsyncSession, store):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)
        await store.resolve(record.id, db_session, ResumeOutcome.denied)

        terminal = await store.claim(
            record.id, db_session, instance_id="ar-1", lease_seconds=45
        )
        missing = await store.claim(
            uuid.uuid4(), db_session, instance_id="ar-1", lease_seconds=45
        )

        assert terminal.status is ClaimStatus.terminal
        assert missing.status is ClaimStatus.not_found

    @pytest.mark.asyncio
    async def test_release_only_succeeds_for_the_holder(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)
        await store.claim(record.id, db_session, instance_id="ar-1", lease_seconds=45)

        assert await store.release(record.id, db_session, instance_id="ar-2") is False
        assert await store.release(record.id, db_session, instance_id="ar-1") is True

        refreshed = await store.get(record.id, db_session)
        assert refreshed.claimed_by_instance_id is None
        assert refreshed.claim_expires_at is None


class TestTransitions:
    @pytest.mark.asyncio
    async def test_mark_resuming_then_idempotent(self, db_session: AsyncSession, store):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)

        resuming = await store.mark_resuming(record.id, db_session)
        again = await store.mark_resuming(record.id, db_session)

        assert resuming.state is ResumeState.resuming
        assert again.state is ResumeState.resuming

    @pytest.mark.asyncio
    async def test_illegal_transitions_raise(self, db_session: AsyncSession, store):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)
        await store.resolve(record.id, db_session, ResumeOutcome.denied)

        with pytest.raises(TurnResumeTransitionError):
            await store.mark_resuming(record.id, db_session)
        with pytest.raises(TurnResumeTransitionError):
            await store.resolve(record.id, db_session, ResumeOutcome.denied)

    @pytest.mark.asyncio
    async def test_approved_applied_requires_write_applied(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)

        with pytest.raises(TurnResumeTransitionError):
            await store.resolve(
                record.id, db_session, ResumeOutcome.approved_applied
            )

        applied = await store.resolve(
            record.id,
            db_session,
            ResumeOutcome.approved_applied,
            write_applied=True,
            applied_effect_summary={"created": "agent_type:demo"},
        )
        assert applied.state is ResumeState.resolved
        assert applied.write_applied is True
        assert applied.applied_at is not None
        assert applied.applied_effect_summary == {"created": "agent_type:demo"}

    @pytest.mark.asyncio
    async def test_denial_resolves_without_write(self, db_session: AsyncSession, store):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)

        closed = await store.resolve(record.id, db_session, ResumeOutcome.denied)

        assert closed.state is ResumeState.resolved
        assert closed.is_terminal is True
        assert closed.write_applied is False
        assert closed.applied_at is None
        assert closed.resolved_at is not None

    @pytest.mark.asyncio
    async def test_expired_closes_unresumable(self, db_session: AsyncSession, store):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)

        closed = await store.resolve(record.id, db_session, ResumeOutcome.expired)

        assert closed.state is ResumeState.unresumable
        assert closed.resume_outcome == ResumeOutcome.expired
        assert closed.terminal_reason_code == "expired"
        assert closed.write_applied is False

    @pytest.mark.asyncio
    async def test_resolve_unresumable_sets_reason_and_message(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)

        closed = await store.resolve_unresumable(
            record.id,
            db_session,
            reason_code="checkpoint_missing",
            message_key="chat.resume.checkpointUnavailable",
        )

        assert closed.state is ResumeState.unresumable
        assert closed.is_terminal is True
        assert closed.terminal_reason_code == "checkpoint_missing"
        assert closed.terminal_message_key == "chat.resume.checkpointUnavailable"
        assert closed.resume_outcome == ResumeOutcome.resume_failed


class TestAppliedEffects:
    """Per-call applied effects: one paused turn may approve a batch of writes."""

    @pytest.mark.asyncio
    async def test_two_distinct_effect_keys_merge(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)
        first = {
            "tool": "create_skill",
            "verb": "create",
            "resource": "skills",
            "record_id": "skill-1",
            "name": "one",
        }
        second = {
            "tool": "create_sop",
            "verb": "create",
            "resource": "sops",
            "record_id": "sop-1",
            "name": "two",
        }

        await store.mark_write_applied(
            record.id, db_session, applied_effect_summary=first, effect_key="k1"
        )
        await db_session.refresh(record)
        applied_at = record.applied_at
        await store.mark_write_applied(
            record.id, db_session, applied_effect_summary=second, effect_key="k2"
        )

        await db_session.refresh(record)
        assert record.write_applied is True
        assert record.applied_at == applied_at  # first-write stamp preserved
        summary = record.applied_effect_summary
        assert summary["effects"] == {"k1": first, "k2": second}
        # Top-level compatibility fields mirror the latest effect.
        assert summary["tool"] == "create_sop"
        assert summary["record_id"] == "sop-1"

    @pytest.mark.asyncio
    async def test_duplicate_effect_key_raises(self, db_session: AsyncSession, store):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)
        summary = {
            "tool": "create_skill",
            "verb": "create",
            "resource": "skills",
            "record_id": "skill-1",
            "name": "one",
        }

        await store.mark_write_applied(
            record.id, db_session, applied_effect_summary=summary, effect_key="same"
        )

        with pytest.raises(TurnResumeTransitionError):
            await store.mark_write_applied(
                record.id,
                db_session,
                applied_effect_summary=summary,
                effect_key="same",
            )

    @pytest.mark.asyncio
    async def test_legacy_no_effect_key_still_refuses_a_second_write(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)

        await store.mark_write_applied(
            record.id, db_session, applied_effect_summary={"tool": "create_skill"}
        )

        with pytest.raises(TurnResumeTransitionError):
            await store.mark_write_applied(
                record.id, db_session, applied_effect_summary={"tool": "create_sop"}
            )

    @pytest.mark.asyncio
    async def test_resolve_preserves_effects_when_no_summary_is_passed(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)
        summary = {
            "tool": "create_skill",
            "verb": "create",
            "resource": "skills",
            "record_id": "skill-1",
            "name": "one",
        }
        await store.mark_write_applied(
            record.id, db_session, applied_effect_summary=summary, effect_key="k1"
        )

        closed = await store.resolve(
            record.id,
            db_session,
            ResumeOutcome.approved_applied,
            write_applied=True,
        )

        assert closed.is_terminal is True
        assert closed.applied_effect_summary["effects"]["k1"] == summary

    @pytest.mark.asyncio
    async def test_resolve_merges_without_dropping_existing_effects(
        self, db_session: AsyncSession, store
    ):
        conv = await _make_session(db_session)
        record = await store.create_or_reuse(conv.id, db_session)
        summary = {
            "tool": "create_skill",
            "verb": "create",
            "resource": "skills",
            "record_id": "skill-1",
            "name": "one",
        }
        await store.mark_write_applied(
            record.id, db_session, applied_effect_summary=summary, effect_key="k1"
        )

        closed = await store.resolve(
            record.id,
            db_session,
            ResumeOutcome.approved_applied,
            write_applied=True,
            applied_effect_summary={"note": "closed by completion call"},
        )

        assert closed.applied_effect_summary["effects"]["k1"] == summary
        assert closed.applied_effect_summary["note"] == "closed by completion call"
