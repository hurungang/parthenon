"""Conversation Activity Store — atomic upsert / read / terminal-resolve of the
persisted per-session agent activity record.

Control Center is the only writer of the ``conversation_activities`` table
(AR and CH reach it exclusively via the internal data endpoints).  Exactly one
live row exists per conversation session (unique ``conversation_session_id``).
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation_activity import (
    TERMINAL_ACTIVITY_STATES,
    ActivityState,
    ConversationActivity,
)
from app.db.models.conversations import ConversationSession
from app.services.conversations.turn_resume_store import ConversationTurnResumeStore

logger = logging.getLogger(__name__)

#: Detail keys that describe a terminal outcome; never carried onto a live row.
_TERMINAL_DETAIL_KEYS = ("terminal_reason_code", "terminal_message_key")


def _without_terminal_reason(detail: Any) -> Any:
    """Strip a previous turn's terminal reason from a live row's detail."""
    if not isinstance(detail, dict):
        return detail
    if not any(key in detail for key in _TERMINAL_DETAIL_KEYS):
        return detail
    cleaned = {
        key: value for key, value in detail.items() if key not in _TERMINAL_DETAIL_KEYS
    }
    return cleaned or None


class ActivityResumeInvariantError(ValueError):
    """A ``waiting_for_human`` activity was requested without a live resume row.

    "Shown as waiting" must structurally equal "actually answerable": the
    activity record's ``active_resume_id`` must point at a live
    ``ConversationTurnResume`` before the waiting state may be persisted.
    """


class ConversationActivityStore:
    """Owns the single live ``ConversationActivity`` row per conversation session."""

    async def get(
        self,
        conversation_session_id: uuid.UUID,
        db: AsyncSession,
    ) -> ConversationActivity | None:
        """Return the current activity record for a session (``None`` when idle)."""
        result = await db.execute(
            select(ConversationActivity).where(
                ConversationActivity.conversation_session_id == conversation_session_id
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        conversation_session_id: uuid.UUID,
        db: AsyncSession,
        state: ActivityState,
        current_turn_id: uuid.UUID | None = None,
        tool_name: str | None = None,
        target_agent_type_id: uuid.UUID | None = None,
        pending_intervene_request_id: uuid.UUID | None = None,
        detail: dict[str, Any] | None = None,
        active_resume_id: uuid.UUID | None = None,
    ) -> ConversationActivity:
        """Create-or-update the single live activity row (atomic on the unique key).

        A terminal ``state`` marks ``is_terminal`` and stamps ``finished_at``;
        non-terminal transitions refresh the heartbeat via ``last_updated_at``.

        ``active_resume_id`` links the shown state to the durable resume record.
        It is kept across non-terminal transitions and cleared on terminal
        resolution.  A ``waiting_for_human`` upsert is rejected with
        :class:`ActivityResumeInvariantError` unless a live resume record can be
        resolved (explicitly supplied, or the session's live record).
        """
        if state is ActivityState.waiting_for_human:
            active_resume_id = await self._require_live_resume(
                conversation_session_id, db, active_resume_id
            )

        is_terminal = state in TERMINAL_ACTIVITY_STATES
        activity = await self.get(conversation_session_id, db)
        if activity is None:
            # Verify the session exists before creating the row (unique key
            # would otherwise surface as a raw IntegrityError).
            session_row = await db.get(ConversationSession, conversation_session_id)
            if session_row is None:
                raise LookupError(
                    f"Conversation session {conversation_session_id} not found"
                )
            activity = ConversationActivity(
                conversation_session_id=conversation_session_id,
                state=state,
                detail=detail,
            )
            db.add(activity)
        else:
            activity.state = state
            if detail is not None:
                activity.detail = detail
            if not is_terminal:
                # A live row must never hydrate a previous turn's terminal
                # reason (the detail may be carried over because a new turn
                # reports status-only context).
                activity.detail = _without_terminal_reason(activity.detail)

        activity.current_turn_id = current_turn_id
        activity.tool_name = tool_name
        activity.target_agent_type_id = target_agent_type_id
        activity.pending_intervene_request_id = pending_intervene_request_id
        if active_resume_id is not None:
            activity.active_resume_id = active_resume_id
        elif is_terminal:
            # A terminal activity can never be resumed.
            activity.active_resume_id = None
        # else: keep the existing live resume id across non-terminal transitions
        activity.is_terminal = is_terminal
        if is_terminal:
            activity.finished_at = datetime.now(timezone.utc)
        else:
            activity.finished_at = None

        await db.flush()
        return activity

    async def _require_live_resume(
        self,
        conversation_session_id: uuid.UUID,
        db: AsyncSession,
        active_resume_id: uuid.UUID | None,
    ) -> uuid.UUID:
        """Resolve (or verify) the live resume record backing a waiting state."""
        store = ConversationTurnResumeStore()
        if active_resume_id is not None:
            resume = await store.get(active_resume_id, db)
            if resume is None:
                raise ActivityResumeInvariantError(
                    f"Resume {active_resume_id} not found — cannot persist "
                    "waiting_for_human"
                )
            if resume.conversation_session_id != conversation_session_id:
                raise ActivityResumeInvariantError(
                    f"Resume {active_resume_id} does not belong to conversation "
                    f"{conversation_session_id}"
                )
            if resume.is_terminal:
                raise ActivityResumeInvariantError(
                    f"Resume {active_resume_id} is terminal — cannot persist "
                    "waiting_for_human"
                )
            return resume.id

        live = await store.get_live_for_session(conversation_session_id, db)
        if live is None:
            raise ActivityResumeInvariantError(
                f"Conversation {conversation_session_id} has no live resume "
                "record — refusing to persist waiting_for_human"
            )
        return live.id

    async def touch(
        self,
        conversation_session_id: uuid.UUID,
        db: AsyncSession,
    ) -> ConversationActivity | None:
        """Refresh the heartbeat of a **working** activity row (no state change).

        A live turn is kept fresh by Communication Hub forwarding its ~15s
        heartbeat as a touch, so the reaper's staleness bound can mean "the
        heartbeat stopped → the turn is dead" instead of "the model is quiet for
        a while → assume it failed". Only ``last_updated_at`` moves; the state,
        turn/tool references and the resume link are untouched.

        Deliberately a **no-op** for a terminal row (a finished turn can never be
        revived) and for a ``waiting_for_human`` row: a paused turn stops
        emitting beats by design, and refreshing a pause would defeat the
        answered-but-lost-resume staleness detection. Both cases return the
        unchanged row so the caller can hydrate from the response.
        """
        activity = await self.get(conversation_session_id, db)
        if activity is None:
            return None
        if activity.is_terminal or activity.state is ActivityState.waiting_for_human:
            return activity
        activity.last_updated_at = datetime.now(timezone.utc)
        await db.flush()
        return activity

    async def resolve_terminal(
        self,
        conversation_session_id: uuid.UUID,
        db: AsyncSession,
        state: ActivityState,
        *,
        detail: dict[str, Any] | None = None,
    ) -> ConversationActivity | None:
        """Resolve a session's activity to a terminal state.

        Sets ``is_terminal``/``finished_at`` and clears the resume checkpoint
        fields (``current_turn_id``, ``pending_intervene_request_id``,
        ``active_resume_id``) — a terminal activity can never be resumed.
        ``detail`` (when supplied) replaces the stored detail so a resolver can
        persist the terminal reason (``terminal_reason_code`` /
        ``terminal_message_key``) the UI hydrates after a reconnect.
        Returns ``None`` when the session has no live activity row.
        """
        if state not in TERMINAL_ACTIVITY_STATES:
            raise ValueError(
                f"State {state} is not a terminal activity state"
            )
        activity = await self.get(conversation_session_id, db)
        if activity is None:
            return None
        activity.state = state
        if detail is not None:
            activity.detail = detail
        elif state is ActivityState.finished:
            # A successful finish must never inherit a previous failure's
            # terminal reason from the detail (a reason-keyed card must not
            # render for a completed turn).
            activity.detail = _without_terminal_reason(activity.detail)
        activity.is_terminal = True
        activity.finished_at = datetime.now(timezone.utc)
        activity.current_turn_id = None
        activity.pending_intervene_request_id = None
        activity.active_resume_id = None
        activity.tool_name = None
        activity.target_agent_type_id = None
        await db.flush()
        return activity
