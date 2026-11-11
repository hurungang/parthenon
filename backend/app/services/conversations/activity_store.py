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

logger = logging.getLogger(__name__)


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
    ) -> ConversationActivity:
        """Create-or-update the single live activity row (atomic on the unique key).

        A terminal ``state`` marks ``is_terminal`` and stamps ``finished_at``;
        non-terminal transitions refresh the heartbeat via ``last_updated_at``.
        """
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

        activity.current_turn_id = current_turn_id
        activity.tool_name = tool_name
        activity.target_agent_type_id = target_agent_type_id
        activity.pending_intervene_request_id = pending_intervene_request_id
        activity.is_terminal = is_terminal
        if is_terminal:
            activity.finished_at = datetime.now(timezone.utc)
        else:
            activity.finished_at = None

        await db.flush()
        return activity

    async def resolve_terminal(
        self,
        conversation_session_id: uuid.UUID,
        db: AsyncSession,
        state: ActivityState,
    ) -> ConversationActivity | None:
        """Resolve a session's activity to a terminal state.

        Sets ``is_terminal``/``finished_at`` and clears the resume checkpoint
        fields (``current_turn_id``, ``pending_intervene_request_id``) — a
        terminal activity can never be resumed.  Returns ``None`` when the
        session has no live activity row.
        """
        if state not in TERMINAL_ACTIVITY_STATES:
            raise ValueError(
                f"State {state} is not a terminal activity state"
            )
        activity = await self.get(conversation_session_id, db)
        if activity is None:
            return None
        activity.state = state
        activity.is_terminal = True
        activity.finished_at = datetime.now(timezone.utc)
        activity.current_turn_id = None
        activity.pending_intervene_request_id = None
        activity.tool_name = None
        activity.target_agent_type_id = None
        await db.flush()
        return activity
