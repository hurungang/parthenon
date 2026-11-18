"""Conversation Activity Reaper — the Terminal Resolver for paused turns.

Runs as a background task in the Control Center app lifespan.  Control Center
is the only DB accessor; the reaper scans non-terminal ``ConversationActivity``
rows and resolves those that can never resume.

For a **paused** row (``waiting_for_human``) the durable resume record is the
authority, not a heartbeat heuristic:

===========================================  ==================================
Resume record                                Resolution
===========================================  ==================================
live ``waiting_for_human``, unexpired,        protected (answerable)
checkpoint present
live, but the answerable window elapsed      record ``unresumable/expired``,
                                             activity ``timed_out``
live, checkpoint missing/consumed past the   record ``unresumable/<checkpoint…>``,
persistence grace                            activity ``failed``
live ``resuming`` and abandoned past the     record ``unresumable/resume_failed``,
claim/staleness bound                        activity ``failed``
``resolved``                                 activity ``finished``
``unresumable`` / ``superseded`` /           activity terminal for its reason
``cancelled``
``superseded`` while a newer live record     activity re-pointed at the live
exists                                       record (stays waiting)
===========================================  ==================================

Working states (``thinking`` / ``using_tool`` / ``delegating``) keep the
heartbeat semantics — a stale heartbeat or a dead session means the turn can
never complete — and additionally close an abandoned live resume record so the
record and the activity always agree.  A **stale** working row means the turn
died mid-flight (a crash or server restart stopped the heartbeat): it resolves
as ``failed`` with the dedicated ``unexpectedly_terminated`` reason, never as a
timeout or a resume failure, so the UI can tell the operator nothing was applied
and offer to resend the request.  A dead session keeps the deliberate-stop
semantics (``failed`` / ``cancelled``).

Every resolution writes the resume record and the activity row in the same
sweep transaction.  A periodic retention sweep deletes checkpoint payloads that
can never be loaded again while keeping the resume index row (audit + outcome).
"""
import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_activity import (
    ActivityState,
    ConversationActivity,
)
from app.db.models.conversation_turn_resume import (
    ConversationTurnCheckpoint,
    ConversationTurnResume,
    ResumeState,
)
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.intervene import InterveneRequest, InterveneRequestStatus
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
    REASON_SUPERSEDED,
    REASON_UNEXPECTEDLY_TERMINATED,
    expire_linked_intervention,
    message_key_for_reason,
    terminal_activity_state_for_reason,
    window_elapsed,
)
from app.services.conversations.turn_resume_store import ConversationTurnResumeStore

logger = logging.getLogger(__name__)

#: Session statuses that mean the activity can never resume.
DEAD_SESSION_STATUSES = frozenset(
    {ConversationStatus.closed, ConversationStatus.archived, ConversationStatus.error}
)

#: Intervene-request statuses that mean a paused turn can never resume.
NON_RESUMABLE_INTERVENTION_STATUSES = frozenset(
    {InterveneRequestStatus.expired, InterveneRequestStatus.cancelled}
)

DEFAULT_STALE_SECONDS = 180
DEFAULT_INTERVAL_SECONDS = 60


def get_stale_threshold_seconds() -> int:
    """Configurable staleness threshold (``CONVERSATION_ACTIVITY_STALE_SECONDS``).

    A *live* turn keeps its activity fresh through the CH heartbeat touch
    (``POST .../activity/touch`` every ~15s), so this bound only has to cover a
    **dead** turn: the moment the heartbeat stops, the row must resolve to a
    terminal state within a few minutes instead of spinning forever. The
    default is therefore two missed heartbeat windows (180s), not the historical
    30 minutes that made a dead ``using_tool`` row indistinguishable from a
    quiet live one. Paused turns (``waiting_for_human``) are never resolved by
    this bound — their durable resume record decides.
    """
    raw = os.getenv("CONVERSATION_ACTIVITY_STALE_SECONDS")
    if not raw:
        return DEFAULT_STALE_SECONDS
    try:
        return max(30, int(raw))
    except ValueError:
        logger.warning(
            "Invalid CONVERSATION_ACTIVITY_STALE_SECONDS=%r — using default %ds",
            raw, DEFAULT_STALE_SECONDS,
        )
        return DEFAULT_STALE_SECONDS


def _claim_ttl_seconds() -> int:
    from app.core.config import get_settings

    return max(1, get_settings().conversation_turn_claim_ttl_seconds)


def _ensure_tz(value: datetime | None) -> datetime | None:
    """Normalize a naive DB timestamp to UTC-aware for comparisons."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _unique_records(
    *records: ConversationTurnResume | None,
) -> list[ConversationTurnResume]:
    """De-duplicate referenced resume records by id (order preserved)."""
    seen: set[uuid.UUID] = set()
    unique: list[ConversationTurnResume] = []
    for record in records:
        if record is None or record.id in seen:
            continue
        seen.add(record.id)
        unique.append(record)
    return unique


@dataclass(frozen=True)
class TerminalDecision:
    """One sweep decision for a non-terminal activity row.

    ``repoint_resume_id`` is the non-terminal case: the activity keeps waiting
    but must point at the session's current live resume record (its previous
    one was superseded by a newer pause).
    """

    activity_state: ActivityState | None = None
    repoint_resume_id: uuid.UUID | None = None
    #: Live resume record to close as unresumable, with its reason code.
    close_resume_id: uuid.UUID | None = None
    reason_code: str | None = None


class ConversationActivityReaper:
    """Periodically resolves stale / unresolvable conversation activity."""

    def __init__(
        self,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        *,
        checkpoint_grace_seconds: int | None = None,
        abandon_grace_seconds: int | None = None,
    ) -> None:
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None
        self._checkpoint_grace_override = checkpoint_grace_seconds
        self._abandon_grace_override = abandon_grace_seconds

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._run_loop(), name="conversation-activity-reaper"
        )
        logger.info(
            "ConversationActivityReaper started (interval=%ss, stale=%ss)",
            self._interval_seconds,
            get_stale_threshold_seconds(),
        )

    def shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
            logger.info("ConversationActivityReaper stopped")

    async def _run_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval_seconds)
                from app.db.session import AsyncSessionLocal

                async with AsyncSessionLocal() as db:
                    resolved = await self.reap(db)
                    # Retention sweep in the same pass: checkpoint payloads that
                    # can never be loaded again are deleted, the index row stays.
                    purged = await ConversationTurnCheckpointStore().purge(db)
                    await db.commit()
                if resolved or purged:
                    logger.info(
                        "Activity reaper resolved %d stale activity row(s) and "
                        "purged %d checkpoint payload(s)",
                        resolved,
                        purged,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Conversation activity reaper sweep failed; continuing."
                )

    # ── Sweep ────────────────────────────────────────────────────────────────

    async def reap(self, db: AsyncSession, now: datetime | None = None) -> int:
        """One sweep: resolve eligible non-terminal rows. Returns the count resolved."""
        current = now or datetime.now(timezone.utc)
        stale_before = current - timedelta(seconds=get_stale_threshold_seconds())

        result = await db.execute(
            select(ConversationActivity, ConversationSession)
            .join(
                ConversationSession,
                ConversationSession.id == ConversationActivity.conversation_session_id,
            )
            .where(ConversationActivity.is_terminal.is_(False))
        )
        rows = result.all()
        if not rows:
            return 0

        request_statuses = await self._load_request_statuses(db, rows)
        resumes_by_id, live_by_session = await self._load_resume_records(db, rows)
        checkpoint_states = await self._load_checkpoint_states(
            db, set(resumes_by_id)
        )

        store = ConversationActivityStore()
        resume_store = ConversationTurnResumeStore()
        checkpoint_store = ConversationTurnCheckpointStore()
        resolved = 0
        for activity, session in rows:
            active_resume = (
                resumes_by_id.get(activity.active_resume_id)
                if activity.active_resume_id is not None
                else None
            )
            live_resume = live_by_session.get(activity.conversation_session_id)

            # FIX-20261113: a confirmation is only actionable while its turn is
            # live. Whenever a referenced resume record is already terminal, the
            # still-pending linked intervention must be expired in this same
            # sweep transaction — otherwise the REST pending-interventions fetch
            # keeps surfacing a dead confirmation (production: an older pause's
            # request stayed `pending` long after its resume row was `expired`).
            for referenced in _unique_records(active_resume, live_resume):
                if referenced.is_terminal:
                    await expire_linked_intervention(db, referenced)

            decision = self._decide(
                activity=activity,
                session=session,
                active_resume=active_resume,
                live_resume=live_resume,
                checkpoint_states=checkpoint_states,
                request_statuses=request_statuses,
                current=current,
                stale_before=stale_before,
            )
            if decision is None:
                continue

            if decision.repoint_resume_id is not None:
                activity.active_resume_id = decision.repoint_resume_id
                await db.flush()
                logger.info(
                    "Activity for conversation %s re-pointed at live resume %s",
                    activity.conversation_session_id,
                    decision.repoint_resume_id,
                )
                continue

            if decision.close_resume_id is not None:
                reason = decision.reason_code or REASON_RESUME_FAILED
                closed_record: ConversationTurnResume | None = None
                try:
                    closed_record = await resume_store.resolve_unresumable(
                        decision.close_resume_id,
                        db,
                        reason_code=reason,
                        message_key=message_key_for_reason(reason),
                    )
                except Exception:  # noqa: BLE001 - a racing closer must not abort the sweep
                    logger.warning(
                        "Could not close resume %s as unresumable during the "
                        "sweep",
                        decision.close_resume_id,
                        exc_info=True,
                    )
                    # A racing closer may already have closed it — still expire
                    # the linked confirmation from the loaded row.
                    closed_record = resumes_by_id.get(decision.close_resume_id)
                await checkpoint_store.mark_consumed(decision.close_resume_id, db)
                # The turn can never be answered any more: expire the pending
                # confirmation in the same transaction so it stops being offered.
                await expire_linked_intervention(db, closed_record)

            if decision.activity_state is not None:
                # Persist the terminal reason alongside the state so a
                # reconnecting client hydrates the same reason-keyed card even
                # when no resume record exists (e.g. a stale working row that
                # died before any pause).  The existing detail (agent type and
                # status context) is preserved.
                terminal_detail: dict | None = None
                if decision.reason_code:
                    terminal_detail = {
                        **(activity.detail or {}),
                        "terminal_reason_code": decision.reason_code,
                        "terminal_message_key": message_key_for_reason(
                            decision.reason_code
                        ),
                    }
                await store.resolve_terminal(
                    activity.conversation_session_id,
                    db,
                    state=decision.activity_state,
                    detail=terminal_detail,
                )
                resolved += 1
                logger.info(
                    "Terminal Resolver closed conversation %s → %s (reason=%s)",
                    activity.conversation_session_id,
                    decision.activity_state.value,
                    decision.reason_code,
                )
        return resolved

    # ── Batch loads ──────────────────────────────────────────────────────────

    async def _load_request_statuses(
        self,
        db: AsyncSession,
        rows: list,
    ) -> dict[uuid.UUID, InterveneRequestStatus]:
        request_ids = {
            activity.pending_intervene_request_id
            for activity, _session in rows
            if activity.pending_intervene_request_id is not None
        }
        if not request_ids:
            return {}
        req_result = await db.execute(
            select(InterveneRequest.id, InterveneRequest.status).where(
                InterveneRequest.id.in_(request_ids)
            )
        )
        return {req_id: req_status for req_id, req_status in req_result.all()}

    async def _load_resume_records(
        self,
        db: AsyncSession,
        rows: list,
    ) -> tuple[
        dict[uuid.UUID, ConversationTurnResume],
        dict[uuid.UUID, ConversationTurnResume],
    ]:
        """Batch-load referenced records and each session's one live record."""
        referenced_ids = {
            activity.active_resume_id
            for activity, _session in rows
            if activity.active_resume_id is not None
        }
        session_ids = {activity.conversation_session_id for activity, _s in rows}
        conditions = [
            and_(
                ConversationTurnResume.conversation_session_id.in_(session_ids),
                ConversationTurnResume.is_terminal.is_(False),
            )
        ]
        if referenced_ids:
            conditions.append(ConversationTurnResume.id.in_(referenced_ids))
        result = await db.execute(
            select(ConversationTurnResume).where(or_(*conditions))
        )
        records = list(result.scalars().all())
        by_id = {record.id: record for record in records}
        live_by_session: dict[uuid.UUID, ConversationTurnResume] = {}
        for record in records:
            if not record.is_terminal:
                live_by_session.setdefault(record.conversation_session_id, record)
        return by_id, live_by_session

    async def _load_checkpoint_states(
        self,
        db: AsyncSession,
        resume_ids: set[uuid.UUID],
    ) -> dict[uuid.UUID, ConversationTurnCheckpoint]:
        if not resume_ids:
            return {}
        result = await db.execute(
            select(ConversationTurnCheckpoint).where(
                ConversationTurnCheckpoint.resume_id.in_(resume_ids)
            )
        )
        return {
            checkpoint.resume_id: checkpoint
            for checkpoint in result.scalars().all()
        }

    # ── Decision ─────────────────────────────────────────────────────────────

    def _decide(
        self,
        *,
        activity: ConversationActivity,
        session: ConversationSession,
        active_resume: ConversationTurnResume | None,
        live_resume: ConversationTurnResume | None,
        checkpoint_states: dict[uuid.UUID, ConversationTurnCheckpoint],
        request_statuses: dict[uuid.UUID, InterveneRequestStatus],
        current: datetime,
        stale_before: datetime,
    ) -> TerminalDecision | None:
        last_updated = _ensure_tz(activity.last_updated_at)
        is_stale = last_updated is not None and last_updated < stale_before
        session_dead = session.status in DEAD_SESSION_STATUSES

        if activity.state is ActivityState.waiting_for_human:
            return self._resolve_waiting_for_human(
                activity=activity,
                active_resume=active_resume,
                live_resume=live_resume,
                checkpoint_states=checkpoint_states,
                request_statuses=request_statuses,
                session_dead=session_dead,
                is_stale=is_stale,
                current=current,
            )

        # Working states (thinking / using_tool / delegating): a stale
        # heartbeat or a dead session means the turn can never complete.
        if session_dead:
            return TerminalDecision(
                activity_state=ActivityState.failed,
                close_resume_id=live_resume.id if live_resume is not None else None,
                reason_code=REASON_CANCELLED,
            )
        if is_stale:
            # A stale heartbeat means the live turn stopped beating without a
            # terminal status event — the turn died mid-flight (crash, restart,
            # or a killed worker).  This is NOT a timeout and NOT a failed
            # resume: nothing was applied and the operator can simply repeat the
            # request, so it carries its own actionable reason code.  Close the
            # abandoned resume record in the same sweep so record and activity
            # agree.
            return TerminalDecision(
                activity_state=ActivityState.failed,
                close_resume_id=live_resume.id if live_resume is not None else None,
                reason_code=REASON_UNEXPECTEDLY_TERMINATED,
            )
        return None

    def _resolve_waiting_for_human(
        self,
        *,
        activity: ConversationActivity,
        active_resume: ConversationTurnResume | None,
        live_resume: ConversationTurnResume | None,
        checkpoint_states: dict[uuid.UUID, ConversationTurnCheckpoint],
        request_statuses: dict[uuid.UUID, InterveneRequestStatus],
        session_dead: bool,
        is_stale: bool,
        current: datetime,
    ) -> TerminalDecision | None:
        """Resolve a paused row from its durable resume record."""
        record = active_resume or live_resume
        request_id = activity.pending_intervene_request_id
        request_status = (
            request_statuses.get(request_id) if request_id is not None else None
        )

        if record is None:
            # Legacy pause without a durable record: keep the pre-durable
            # intervention-state semantics.
            return self._resolve_legacy_waiting(
                request_status=request_status,
                session_dead=session_dead,
                is_stale=is_stale,
            )

        if record.is_terminal:
            if (
                record.resume_outcome is not None
                and record.resume_outcome.value == REASON_SUPERSEDED
                and live_resume is not None
                and live_resume.id != record.id
            ):
                # A newer pause owns the session: keep waiting on it instead of
                # terminalising the single per-session activity row.
                return TerminalDecision(repoint_resume_id=live_resume.id)
            state = self._terminal_activity_state_for_record(record)
            return TerminalDecision(
                activity_state=state,
                reason_code=record.terminal_reason_code,
            )

        # ── Live record ──────────────────────────────────────────────────────
        if session_dead:
            return TerminalDecision(
                activity_state=ActivityState.timed_out,
                close_resume_id=record.id,
                reason_code=REASON_CANCELLED,
            )
        if window_elapsed(record, now=current) or (
            request_status is InterveneRequestStatus.expired
        ):
            return TerminalDecision(
                activity_state=ActivityState.timed_out,
                close_resume_id=record.id,
                reason_code=REASON_EXPIRED,
            )
        if request_status is InterveneRequestStatus.cancelled:
            return TerminalDecision(
                activity_state=ActivityState.timed_out,
                close_resume_id=record.id,
                reason_code=REASON_CANCELLED,
            )

        lost_reason = self._checkpoint_lost_reason(
            record, checkpoint_states, current=current
        )
        if lost_reason is not None:
            return TerminalDecision(
                activity_state=ActivityState.failed,
                close_resume_id=record.id,
                reason_code=lost_reason,
            )

        if record.state is ResumeState.resuming:
            if self._resume_abandoned(record, current=current, is_stale=is_stale):
                return TerminalDecision(
                    activity_state=ActivityState.failed,
                    close_resume_id=record.id,
                    reason_code=REASON_RESUME_FAILED,
                )
            return None

        # ``waiting_for_human`` on a live, unexpired, checkpointed record.
        # Heartbeat staleness is NOT evidence of death here: a paused turn
        # deliberately stops emitting activity beats, so only the answer state
        # and the durable record bounds decide.
        if request_status is InterveneRequestStatus.responded and is_stale:
            # The operator answered but the turn never moved: the dispatched
            # resume was lost.  The answer can no longer be applied.
            return TerminalDecision(
                activity_state=ActivityState.failed,
                close_resume_id=record.id,
                reason_code=REASON_RESUME_FAILED,
            )
        if request_status is None and is_stale:
            # Legacy orphan: a pause with no resolvable intervention reference
            # whose durable record nothing is driving.
            return TerminalDecision(
                activity_state=ActivityState.timed_out,
                close_resume_id=record.id,
                reason_code=REASON_RESUME_FAILED,
            )
        return None

    def _resolve_legacy_waiting(
        self,
        *,
        request_status: InterveneRequestStatus | None,
        session_dead: bool,
        is_stale: bool,
    ) -> TerminalDecision | None:
        """Pre-durable pause semantics (no resume record to consult)."""
        if request_status is InterveneRequestStatus.pending:
            if not session_dead:
                return None
            return TerminalDecision(activity_state=ActivityState.timed_out)
        if request_status in NON_RESUMABLE_INTERVENTION_STATUSES:
            return TerminalDecision(activity_state=ActivityState.timed_out)
        if request_status is InterveneRequestStatus.responded:
            if is_stale:
                return TerminalDecision(activity_state=ActivityState.timed_out)
            return None
        # No (resolvable) intervention reference: a stale or abandoned waiting
        # row is orphaned.
        if is_stale:
            return TerminalDecision(activity_state=ActivityState.timed_out)
        if session_dead:
            return TerminalDecision(activity_state=ActivityState.failed)
        return None

    # ── Bounds ───────────────────────────────────────────────────────────────

    def _checkpoint_grace_seconds(self) -> int:
        if self._checkpoint_grace_override is not None:
            return self._checkpoint_grace_override
        return max(60, _claim_ttl_seconds() * 2)

    def _abandon_grace_seconds(self) -> int:
        if self._abandon_grace_override is not None:
            return self._abandon_grace_override
        return max(120, _claim_ttl_seconds() * 4)

    def _checkpoint_lost_reason(
        self,
        record: ConversationTurnResume,
        checkpoint_states: dict[uuid.UUID, ConversationTurnCheckpoint],
        *,
        current: datetime,
    ) -> str | None:
        """Reason why the saved state can no longer rebuild the turn (or None).

        A just-persisted pause writes the index and the payload in quick
        succession, so a missing payload is only fatal after the persistence
        grace window — never a race with the pause itself.
        """
        checkpoint = checkpoint_states.get(record.id)
        if checkpoint is None:
            created_at = _ensure_tz(record.created_at)
            grace = timedelta(seconds=self._checkpoint_grace_seconds())
            if created_at is not None and created_at > current - grace:
                return None
            return REASON_CHECKPOINT_UNAVAILABLE
        if checkpoint.is_consumed:
            return REASON_CHECKPOINT_CONSUMED
        expires_at = _ensure_tz(checkpoint.expires_at)
        if expires_at is not None and expires_at <= current:
            return REASON_CHECKPOINT_UNAVAILABLE
        return None

    def _resume_abandoned(
        self,
        record: ConversationTurnResume,
        *,
        current: datetime,
        is_stale: bool,
    ) -> bool:
        """True when a ``resuming`` record is no longer being driven."""
        claim_expires = _ensure_tz(record.claim_expires_at)
        if claim_expires is not None and claim_expires > current:
            # A live lease: an instance is actively continuing the turn.
            return False
        attempt_at = _ensure_tz(record.last_attempt_at) or _ensure_tz(record.created_at)
        if attempt_at is None:
            return is_stale
        return attempt_at < current - timedelta(seconds=self._abandon_grace_seconds())

    @staticmethod
    def _terminal_activity_state_for_record(
        record: ConversationTurnResume,
    ) -> ActivityState:
        if record.state is ResumeState.resolved:
            return ActivityState.finished
        if record.terminal_reason_code:
            return terminal_activity_state_for_reason(record.terminal_reason_code)
        outcome = record.resume_outcome.value if record.resume_outcome else None
        return terminal_activity_state_for_reason(outcome)


_reaper: ConversationActivityReaper | None = None


def get_activity_reaper() -> ConversationActivityReaper:
    """Return the process-wide reaper singleton (created on first use)."""
    global _reaper
    if _reaper is None:
        _reaper = ConversationActivityReaper()
    return _reaper
