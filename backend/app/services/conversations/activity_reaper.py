"""Conversation Activity Reaper — resolves stale or non-resumable activity to a
terminal state.

Runs as a background task in the Control Center app lifespan.  Control Center
is the only DB accessor; the reaper scans non-terminal ``ConversationActivity``
rows and resolves those that can never resume:

- ``last_updated_at`` older than the configurable staleness threshold
  (``CONVERSATION_ACTIVITY_STALE_SECONDS``, default ~30 minutes), or
- the owning conversation session is ``closed`` / ``archived`` / ``error``.

``waiting_for_human`` rows are protected while their ``InterveneRequest`` is
still ``pending`` and the session is still active.  A ``waiting_for_human``
pause whose request has expired or been cancelled (or whose session is dead)
can never resume and is resolved to a terminal state (task 6.3: restart-
abandoned paused turns).
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_activity import (
    ActivityState,
    ConversationActivity,
)
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.intervene import InterveneRequest, InterveneRequestStatus
from app.services.conversations.activity_store import ConversationActivityStore

logger = logging.getLogger(__name__)

#: Session statuses that mean the activity can never resume.
DEAD_SESSION_STATUSES = frozenset(
    {ConversationStatus.closed, ConversationStatus.archived, ConversationStatus.error}
)

#: Intervene-request statuses that mean a paused turn can never resume.
NON_RESUMABLE_INTERVENTION_STATUSES = frozenset(
    {InterveneRequestStatus.expired, InterveneRequestStatus.cancelled}
)

DEFAULT_STALE_SECONDS = 30 * 60
DEFAULT_INTERVAL_SECONDS = 60


def get_stale_threshold_seconds() -> int:
    """Configurable staleness threshold (``CONVERSATION_ACTIVITY_STALE_SECONDS``)."""
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


def _ensure_tz(value: datetime | None) -> datetime | None:
    """Normalize a naive DB timestamp to UTC-aware for comparisons."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class ConversationActivityReaper:
    """Periodically resolves stale / orphaned conversation activity to terminal."""

    def __init__(self, interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> None:
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

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
                    await db.commit()
                if resolved:
                    logger.info(
                        "Activity reaper resolved %d stale activity row(s)", resolved
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Conversation activity reaper sweep failed; continuing."
                )

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

        # Batch-load the intervene request statuses referenced by
        # waiting_for_human rows so protection checks need one query.
        request_ids = {
            activity.pending_intervene_request_id
            for activity, _session in rows
            if activity.state == ActivityState.waiting_for_human
            and activity.pending_intervene_request_id is not None
        }
        request_statuses: dict[uuid.UUID, InterveneRequestStatus] = {}
        if request_ids:
            req_result = await db.execute(
                select(InterveneRequest.id, InterveneRequest.status).where(
                    InterveneRequest.id.in_(request_ids)
                )
            )
            request_statuses = {
                req_id: req_status for req_id, req_status in req_result.all()
            }

        store = ConversationActivityStore()
        resolved = 0
        for activity, session in rows:
            terminal_state = self._resolve_state(
                activity, session, request_statuses, stale_before
            )
            if terminal_state is None:
                continue
            await store.resolve_terminal(
                activity.conversation_session_id, db, state=terminal_state
            )
            resolved += 1
        return resolved

    def _resolve_state(
        self,
        activity: ConversationActivity,
        session: ConversationSession,
        request_statuses: dict[uuid.UUID, InterveneRequestStatus],
        stale_before: datetime,
    ) -> ActivityState | None:
        """Return the terminal state to apply, or ``None`` to leave the row untouched."""
        last_updated = _ensure_tz(activity.last_updated_at)
        is_stale = last_updated is not None and last_updated < stale_before
        session_dead = session.status in DEAD_SESSION_STATUSES

        if activity.state == ActivityState.waiting_for_human:
            return self._resolve_waiting_for_human(
                activity, session_dead, is_stale, request_statuses
            )

        # Working states (thinking / using_tool / delegating): a stale
        # heartbeat or a dead session means the turn can never complete.
        if session_dead:
            return ActivityState.failed
        if is_stale:
            # A stale heartbeat most plausibly means the turn watchdog
            # expired without a terminal status event.
            return ActivityState.timed_out
        return None

    def _resolve_waiting_for_human(
        self,
        activity: ConversationActivity,
        session_dead: bool,
        is_stale: bool,
        request_statuses: dict[uuid.UUID, InterveneRequestStatus],
    ) -> ActivityState | None:
        """A paused turn resumes only while its intervention is pending AND the
        session is active (never touched in that case).  Task 6.3: an
        expired/cancelled intervention can never resume even on an active
        session — the stuck "waiting" indicator must be resolved."""
        request_id = activity.pending_intervene_request_id
        request_status = (
            request_statuses.get(request_id) if request_id is not None else None
        )

        if request_status is InterveneRequestStatus.pending:
            # Protected: still pending on a live session.
            if not session_dead:
                return None
            return ActivityState.timed_out
        if request_status in NON_RESUMABLE_INTERVENTION_STATUSES:
            # The pause can never resume — expired/cancelled intervention.
            return ActivityState.timed_out
        if request_status is InterveneRequestStatus.responded:
            # The operator answered; if the row still isn't resumed and went
            # stale, the turn died (e.g. AR restart lost the resume registry).
            if is_stale:
                return ActivityState.timed_out
            return None
        # No (resolvable) intervention reference: a stale or abandoned waiting
        # row is orphaned.
        if is_stale:
            return ActivityState.timed_out
        if session_dead:
            return ActivityState.failed
        return None


_reaper: ConversationActivityReaper | None = None


def get_activity_reaper() -> ConversationActivityReaper:
    """Return the process-wide reaper singleton (created on first use)."""
    global _reaper
    if _reaper is None:
        _reaper = ConversationActivityReaper()
    return _reaper
