"""Conversation Turn Resume Store — the single writer of the resume index.

``ConversationTurnResume`` is the authoritative lifecycle record for one paused
conversational turn (see ``docs/changes/resumable-agent-turn-persistence``).
Control Center owns it; Agent Runtime and Communication Hub reach it only
through the internal data endpoints, never the database.

Invariants enforced here:

* at most one *live* (non-terminal) record per conversation session — a new
  pause closes the previous one as ``superseded``;
* ``idempotency_key`` is unique per paused turn (duplicate answers can never
  apply the confirmed write twice);
* ``approved_applied`` requires ``write_applied`` — a denial or expiry never
  records an applied write;
* claim acquisition is a single conditional UPDATE (acquire when unclaimed or
  the lease expired); claim expiry never changes the lifecycle state;
* every illegal transition raises :class:`TurnResumeTransitionError`.

Tenant isolation is supplied by the request-scoped ``AsyncSession`` (the CC
tenant-scoping gateway constrains every ORM statement automatically); the
optional ``tenant_id`` argument is persisted on create so the owning tenant is
explicit on the row itself.
"""
from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_turn_resume import (
    TERMINAL_RESUME_STATES,
    ResumeOutcome,
    ResumeState,
    ConversationTurnResume,
)
from app.db.models.conversations import ConversationSession

logger = logging.getLogger(__name__)


class TurnResumeError(Exception):
    """Base class for resume-index store failures."""


class TurnResumeNotFoundError(TurnResumeError, LookupError):
    """The requested resume record (or its conversation session) does not exist."""


class TurnResumeTransitionError(TurnResumeError, ValueError):
    """The requested lifecycle transition is illegal for the record's state."""


class TurnResumeConflictError(TurnResumeError, ValueError):
    """A unique key (``idempotency_key``) already belongs to another turn."""


class ClaimStatus(str, enum.Enum):
    """Outcome of a turn-claim attempt."""

    acquired = "acquired"
    already_held = "already_held"
    not_found = "not_found"
    terminal = "terminal"


@dataclass(frozen=True)
class ClaimResult:
    """Structured result of :meth:`ConversationTurnResumeStore.claim`."""

    status: ClaimStatus
    resume: ConversationTurnResume | None = None
    holder_instance_id: str | None = None
    claim_expires_at: datetime | None = None


#: Outcomes that close the record as ``unresumable`` rather than ``resolved``.
UNRESUMABLE_OUTCOMES = frozenset(
    {ResumeOutcome.expired, ResumeOutcome.superseded, ResumeOutcome.resume_failed}
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_opaque_key() -> str:
    return uuid.uuid4().hex


def _state_value(value: ResumeState | str) -> str:
    return value.value if isinstance(value, ResumeState) else str(value)


class ConversationTurnResumeStore:
    """Owns create/supersede, reads, claim arbitration, and resolution."""

    # ── Reads ────────────────────────────────────────────────────────────────

    async def get(
        self,
        resume_id: uuid.UUID,
        db: AsyncSession,
    ) -> ConversationTurnResume | None:
        """Return a resume record by id (``None`` when absent)."""
        return await db.get(ConversationTurnResume, resume_id)

    async def get_live_for_session(
        self,
        conversation_session_id: uuid.UUID,
        db: AsyncSession,
    ) -> ConversationTurnResume | None:
        """Return the session's single live (non-terminal) resume record."""
        result = await db.execute(
            select(ConversationTurnResume).where(
                ConversationTurnResume.conversation_session_id
                == conversation_session_id,
                ConversationTurnResume.is_terminal.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_for_session(
        self,
        conversation_session_id: uuid.UUID,
        db: AsyncSession,
    ) -> ConversationTurnResume | None:
        """Return the newest resume record for a session (live or terminal)."""
        result = await db.execute(
            select(ConversationTurnResume)
            .where(
                ConversationTurnResume.conversation_session_id
                == conversation_session_id
            )
            .order_by(ConversationTurnResume.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_resume_key(
        self,
        resume_key: str,
        db: AsyncSession,
    ) -> ConversationTurnResume | None:
        """Return the record addressed by its opaque, instance-independent key."""
        result = await db.execute(
            select(ConversationTurnResume).where(
                ConversationTurnResume.resume_key == resume_key
            )
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
        db: AsyncSession,
    ) -> ConversationTurnResume | None:
        """Return the record owning a turn idempotency key (globally unique)."""
        result = await db.execute(
            select(ConversationTurnResume).where(
                ConversationTurnResume.idempotency_key == idempotency_key
            )
        )
        return result.scalar_one_or_none()

    async def lock_for_applied_check(
        self,
        idempotency_key: str,
        db: AsyncSession,
    ) -> ConversationTurnResume | None:
        """Load the turn's record under a row lock for the applied-marker check.

        The confirmed management-tool dispatch is the exactly-once chokepoint:
        the row lock serialises concurrent/retried dispatches of the same key
        so the second caller observes ``write_applied`` **after** the first
        committed — it can then replay the stored summary instead of applying
        the write a second time.  ``SELECT … FOR UPDATE`` is skipped on SQLite
        (single-writer test databases; the statement is a plain read there).
        """
        stmt = select(ConversationTurnResume).where(
            ConversationTurnResume.idempotency_key == idempotency_key
        )
        if db.bind is not None and db.bind.dialect.name != "sqlite":
            stmt = stmt.with_for_update()
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_intervention(
        self,
        intervene_request_id: uuid.UUID,
        db: AsyncSession,
    ) -> ConversationTurnResume | None:
        """Return the resume record created for one intervened pause."""
        result = await db.execute(
            select(ConversationTurnResume)
            .where(ConversationTurnResume.intervene_request_id == intervene_request_id)
            .order_by(ConversationTurnResume.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ── Create / supersede ───────────────────────────────────────────────────

    async def create_or_reuse(
        self,
        conversation_session_id: uuid.UUID,
        db: AsyncSession,
        *,
        intervene_request_id: uuid.UUID | None = None,
        turn_id: uuid.UUID | None = None,
        expires_at: datetime | None = None,
        resume_key: str | None = None,
        idempotency_key: str | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> ConversationTurnResume:
        """Register a pause, reusing the live record for the same intervention.

        Called from the intervention-persist path: a replayed pause intent for
        the same ``intervene_request_id`` returns the existing live record
        (idempotent).  Any *other* live record for the session is closed as
        ``superseded`` before the new one is inserted, so the partial unique
        index (one live record per session) always holds.

        ``expires_at`` is the caller's decision: on the conversation path
        Control Center computes it from tenant policy
        (``resolve_resume_expiry`` in ``turn_resume_settings``), never from a
        client-supplied value.
        """
        session_row = await db.get(ConversationSession, conversation_session_id)
        if session_row is None:
            raise TurnResumeNotFoundError(
                f"Conversation session {conversation_session_id} not found"
            )

        if intervene_request_id is not None:
            existing = await db.execute(
                select(ConversationTurnResume).where(
                    ConversationTurnResume.conversation_session_id
                    == conversation_session_id,
                    ConversationTurnResume.intervene_request_id
                    == intervene_request_id,
                    ConversationTurnResume.is_terminal.is_(False),
                )
            )
            reusable = existing.scalar_one_or_none()
            if reusable is not None:
                self._refresh_window(reusable, expires_at=expires_at, turn_id=turn_id)
                await db.flush()
                return reusable

        resolved_key = idempotency_key or _new_opaque_key()
        # A replayed intent may carry a key that already belongs to this very
        # paused turn — reuse instead of colliding with the unique index.
        key_owner = await self.get_by_idempotency_key(resolved_key, db)
        if key_owner is not None:
            same_live_turn = (
                key_owner.conversation_session_id == conversation_session_id
                and not key_owner.is_terminal
            )
            same_intervention = (
                intervene_request_id is None
                or key_owner.intervene_request_id == intervene_request_id
            )
            if same_live_turn and same_intervention:
                self._refresh_window(key_owner, expires_at=expires_at, turn_id=turn_id)
                await db.flush()
                return key_owner
            if same_live_turn:
                # A *new* pause inside a continued turn: the idempotency key is
                # per paused turn, so the previous pause's key must not be
                # reused for this new resume record. Allocate a fresh one (the
                # old live record is superseded below).
                logger.info(
                    "Resume key %s belongs to the previous pause of conversation "
                    "%s — allocating a fresh key for the new pause",
                    resolved_key,
                    conversation_session_id,
                )
                resolved_key = _new_opaque_key()
            else:
                raise TurnResumeConflictError(
                    f"Idempotency key {resolved_key!r} already belongs to "
                    f"resume {key_owner.id}"
                )

        live = await self.get_live_for_session(conversation_session_id, db)
        if live is not None:
            self._supersede(live)

        record = ConversationTurnResume(
            tenant_id=tenant_id if tenant_id is not None else session_row.tenant_id,
            conversation_session_id=conversation_session_id,
            turn_id=turn_id,
            intervene_request_id=intervene_request_id,
            state=ResumeState.waiting_for_human,
            resume_outcome=None,
            is_terminal=False,
            resume_key=resume_key or _new_opaque_key(),
            idempotency_key=resolved_key,
            write_applied=False,
            expires_at=expires_at,
        )
        db.add(record)
        await db.flush()
        logger.info(
            "Resume record %s registered for conversation %s (intervention=%s)",
            record.id,
            conversation_session_id,
            intervene_request_id,
        )
        return record

    # ── Claim arbitration ────────────────────────────────────────────────────

    async def claim(
        self,
        resume_id: uuid.UUID,
        db: AsyncSession,
        *,
        instance_id: str,
        lease_seconds: int,
    ) -> ClaimResult:
        """Atomically claim a live turn for ``instance_id``.

        Acquisition is a single conditional UPDATE: the turn is claimable when
        nobody holds it or the previous lease expired.  The claim increments
        ``attempt_count`` and stamps ``last_attempt_at``; the lifecycle state is
        deliberately left alone (claim expiry only frees the turn for failover).
        """
        record = await self.get(resume_id, db)
        if record is None:
            return ClaimResult(status=ClaimStatus.not_found)
        if record.is_terminal:
            return ClaimResult(
                status=ClaimStatus.terminal,
                resume=record,
                holder_instance_id=record.claimed_by_instance_id,
                claim_expires_at=record.claim_expires_at,
            )

        now = _utcnow()
        new_expiry = now + timedelta(seconds=max(1, lease_seconds))
        result = await db.execute(
            update(ConversationTurnResume)
            .where(
                ConversationTurnResume.id == resume_id,
                ConversationTurnResume.is_terminal.is_(False),
                or_(
                    ConversationTurnResume.claimed_by_instance_id.is_(None),
                    ConversationTurnResume.claim_expires_at.is_(None),
                    ConversationTurnResume.claim_expires_at < now,
                    # The holder may renew/self-reacquire its own live lease
                    # (claim renewal during a long resume) — otherwise a
                    # same-instance re-claim would be reported as contention
                    # and abort the resume mid-run.
                    ConversationTurnResume.claimed_by_instance_id == instance_id,
                ),
            )
            .values(
                claimed_by_instance_id=instance_id,
                claim_expires_at=new_expiry,
                attempt_count=ConversationTurnResume.attempt_count + 1,
                last_attempt_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if (result.rowcount or 0) == 0:
            # Someone else holds a live lease — report the holder verbatim.
            await db.refresh(record)
            if record.is_terminal:
                return ClaimResult(
                    status=ClaimStatus.terminal,
                    resume=record,
                    holder_instance_id=record.claimed_by_instance_id,
                    claim_expires_at=record.claim_expires_at,
                )
            return ClaimResult(
                status=ClaimStatus.already_held,
                resume=record,
                holder_instance_id=record.claimed_by_instance_id,
                claim_expires_at=record.claim_expires_at,
            )

        await db.refresh(record)
        return ClaimResult(
            status=ClaimStatus.acquired,
            resume=record,
            holder_instance_id=record.claimed_by_instance_id,
            claim_expires_at=record.claim_expires_at,
        )

    async def release(
        self,
        resume_id: uuid.UUID,
        db: AsyncSession,
        *,
        instance_id: str | None = None,
    ) -> bool:
        """Best-effort claim release (only the holder may release its claim)."""
        record = await self.get(resume_id, db)
        if record is None:
            return False
        conditions = [
            ConversationTurnResume.id == resume_id,
            ConversationTurnResume.is_terminal.is_(False),
            ConversationTurnResume.claimed_by_instance_id.is_not(None),
        ]
        if instance_id is not None:
            conditions.append(
                ConversationTurnResume.claimed_by_instance_id == instance_id
            )
        result = await db.execute(
            update(ConversationTurnResume)
            .where(*conditions)
            .values(claimed_by_instance_id=None, claim_expires_at=None)
            .execution_options(synchronize_session=False)
        )
        released = bool(result.rowcount)
        if released:
            await db.refresh(record)
        return released

    # ── Lifecycle transitions ────────────────────────────────────────────────

    async def mark_resuming(
        self,
        resume_id: uuid.UUID,
        db: AsyncSession,
        *,
        applied_by_user_id: uuid.UUID | None = None,
        bump_attempt: bool = True,
    ) -> ConversationTurnResume:
        """Move a waiting turn to ``resuming`` (idempotent for retries).

        Called in the same transaction that stores the operator's answer: the
        answering user is stamped on the record and the attempt counter is
        bumped once per transition (a repeated answer for the same live record
        does not inflate it).
        """
        record = await self._require(resume_id, db)
        if record.is_terminal:
            raise TurnResumeTransitionError(
                f"Resume {resume_id} is terminal ({record.resume_outcome}); "
                "cannot mark it resuming"
            )
        if record.state is ResumeState.resuming:
            if applied_by_user_id is not None:
                record.applied_by_user_id = applied_by_user_id
                await db.flush()
            return record
        if record.state is not ResumeState.waiting_for_human:
            raise TurnResumeTransitionError(
                f"Illegal transition {record.state} → {ResumeState.resuming}"
            )
        record.state = ResumeState.resuming
        if applied_by_user_id is not None:
            record.applied_by_user_id = applied_by_user_id
        if bump_attempt:
            record.attempt_count = (record.attempt_count or 0) + 1
        record.last_attempt_at = _utcnow()
        await db.flush()
        return record

    async def mark_write_applied(
        self,
        resume_id: uuid.UUID,
        db: AsyncSession,
        *,
        applied_effect_summary: dict | None = None,
        applied_by_user_id: uuid.UUID | None = None,
    ) -> ConversationTurnResume:
        """Stamp the exactly-once applied marker for the confirmed write.

        Must be called **in the same transaction as the write itself** so the
        marker and the write commit atomically: a crash before commit leaves
        neither, a crash after commit leaves both.  Re-stamping is refused so
        one paused turn can never record two applied writes.
        """
        record = await self._require(resume_id, db)
        if record.write_applied:
            raise TurnResumeTransitionError(
                f"Resume {resume_id} already recorded an applied write"
            )
        record.write_applied = True
        record.applied_at = _utcnow()
        if applied_effect_summary is not None:
            record.applied_effect_summary = applied_effect_summary
        if applied_by_user_id is not None:
            record.applied_by_user_id = applied_by_user_id
        await db.flush()
        logger.info(
            "Resume %s recorded the confirmed write (summary keys=%s)",
            resume_id,
            sorted((applied_effect_summary or {}).keys()),
        )
        return record

    async def resolve(
        self,
        resume_id: uuid.UUID,
        db: AsyncSession,
        outcome: ResumeOutcome,
        *,
        write_applied: bool = False,
        applied_by_user_id: uuid.UUID | None = None,
        applied_effect_summary: dict | None = None,
        outcome_turn_id: uuid.UUID | None = None,
    ) -> ConversationTurnResume:
        """Close a live turn with a terminal outcome.

        ``approved_applied`` requires ``write_applied=True``; every other
        outcome records that nothing was written.  ``expired`` / ``superseded``
        / ``resume_failed`` close the record as ``unresumable``; the rest as
        ``resolved``.
        """
        record = await self._require(resume_id, db)
        if record.is_terminal:
            raise TurnResumeTransitionError(
                f"Resume {resume_id} is already terminal "
                f"({record.state}/{record.resume_outcome})"
            )
        if outcome is ResumeOutcome.approved_applied and not write_applied:
            raise TurnResumeTransitionError(
                "approved_applied requires write_applied=True — a confirmed "
                "write must be recorded exactly once"
            )

        now = _utcnow()
        record.state = (
            ResumeState.unresumable
            if outcome in UNRESUMABLE_OUTCOMES
            else ResumeState.resolved
        )
        record.resume_outcome = outcome
        record.is_terminal = True
        record.resolved_at = now
        record.claimed_by_instance_id = None
        record.claim_expires_at = None
        if outcome in UNRESUMABLE_OUTCOMES:
            record.terminal_reason_code = outcome.value
        if write_applied:
            record.write_applied = True
            # Preserve the chokepoint stamp (the write happened then), never
            # re-timestamp it at resolution time.
            record.applied_at = record.applied_at or now
        if applied_by_user_id is not None:
            record.applied_by_user_id = applied_by_user_id
        if applied_effect_summary is not None:
            record.applied_effect_summary = applied_effect_summary
        if outcome_turn_id is not None:
            record.outcome_turn_id = outcome_turn_id
        await db.flush()
        logger.info(
            "Resume %s resolved: state=%s outcome=%s write_applied=%s",
            resume_id,
            record.state.value,
            outcome.value,
            record.write_applied,
        )
        return record

    async def resolve_unresumable(
        self,
        resume_id: uuid.UUID,
        db: AsyncSession,
        *,
        reason_code: str,
        message_key: str | None = None,
        state: ResumeState = ResumeState.unresumable,
        outcome: ResumeOutcome | None = None,
    ) -> ConversationTurnResume:
        """Close a turn that can never continue, with an actionable reason.

        The lifecycle state is ``unresumable`` (terminal).  The reason code is
        surfaced to the UI via ``terminal_message_key``; the outcome is derived
        from the reason when it matches the resume vocabularly, otherwise
        ``resume_failed``.
        """
        if state not in TERMINAL_RESUME_STATES:
            raise TurnResumeTransitionError(
                f"State {_state_value(state)} is not terminal"
            )
        record = await self._require(resume_id, db)
        if record.is_terminal:
            if record.state is ResumeState.unresumable:
                return record
            raise TurnResumeTransitionError(
                f"Resume {resume_id} already terminal as {record.state}"
            )

        if outcome is None:
            try:
                outcome = ResumeOutcome(reason_code)
            except ValueError:
                outcome = ResumeOutcome.resume_failed

        now = _utcnow()
        record.state = state
        record.resume_outcome = outcome
        record.is_terminal = True
        record.terminal_reason_code = reason_code
        record.terminal_message_key = message_key
        record.resolved_at = now
        record.claimed_by_instance_id = None
        record.claim_expires_at = None
        await db.flush()
        logger.info(
            "Resume %s marked %s (reason=%s message=%s)",
            resume_id,
            _state_value(state),
            reason_code,
            message_key,
        )
        return record

    # ── Internals ────────────────────────────────────────────────────────────

    async def _require(
        self,
        resume_id: uuid.UUID,
        db: AsyncSession,
    ) -> ConversationTurnResume:
        record = await self.get(resume_id, db)
        if record is None:
            raise TurnResumeNotFoundError(f"Resume {resume_id} not found")
        return record

    @staticmethod
    def _refresh_window(
        record: ConversationTurnResume,
        *,
        expires_at: datetime | None,
        turn_id: uuid.UUID | None,
    ) -> None:
        if expires_at is not None:
            record.expires_at = expires_at
        if turn_id is not None and record.turn_id is None:
            record.turn_id = turn_id

    @staticmethod
    def _supersede(record: ConversationTurnResume) -> None:
        """Close a live record because a newer pause took over the session."""
        record.state = ResumeState.unresumable
        record.resume_outcome = ResumeOutcome.superseded
        record.is_terminal = True
        record.terminal_reason_code = ResumeOutcome.superseded.value
        record.terminal_message_key = "chat.resume.superseded"
        record.resolved_at = _utcnow()
        record.claimed_by_instance_id = None
        record.claim_expires_at = None
