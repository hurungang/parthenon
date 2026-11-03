"""Conversation Store — persists conversation sessions, turns, and tool call records."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.conversations import (
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
    ToolCallRecord,
    TurnRole,
    TurnType,
)

logger = logging.getLogger(__name__)


class ConversationStore:
    """
    Persists every conversation session, turn, and tool call record.
    Provides query access by session ID.
    """

    async def create_session(
        self,
        db: AsyncSession,
        agent_type_id: Any | None = None,
        triggered_by_user_id: Any | None = None,
        channel: str = "web",
    ) -> ConversationSession:
        """Create a new conversation session."""
        session = ConversationSession(
            agent_type_id=agent_type_id,
            triggered_by_user_id=triggered_by_user_id,
            channel=channel,
            status=ConversationStatus.active,
        )
        db.add(session)
        await db.flush()
        await db.refresh(session)
        return session

    async def add_turn(
        self,
        session_id: Any,
        role: TurnRole,
        content: str,
        db: AsyncSession,
        token_count: int | None = None,
        turn_type: TurnType = TurnType.message,
        intervene_request_id: Any | None = None,
    ) -> ConversationTurn:
        """Append a turn to an existing session."""
        turn = ConversationTurn(
            session_id=session_id,
            role=role,
            content=content,
            token_count=token_count,
            turn_type=turn_type,
            intervene_request_id=intervene_request_id,
        )
        db.add(turn)
        await db.flush()

        # Increment turn count on session
        conv_session = await db.get(ConversationSession, session_id)
        if conv_session:
            conv_session.turn_count += 1
            await db.flush()

        await db.refresh(turn)
        return turn

    async def add_tool_call(
        self,
        turn_id: Any,
        tool_name: str,
        db: AsyncSession,
        tool_input: dict[str, Any] | None = None,
        tool_output: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> ToolCallRecord:
        """Record a tool call within a conversation turn."""
        record = ToolCallRecord(
            turn_id=turn_id,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            error=error,
            duration_ms=duration_ms,
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)
        return record

    async def update_title(
        self, session_id: Any, title: str, db: AsyncSession
    ) -> ConversationSession | None:
        """Set the title on a session and touch updated_at."""
        conv_session = await db.get(ConversationSession, session_id)
        if conv_session:
            conv_session.title = title
            conv_session.updated_at = datetime.now(timezone.utc)
            await db.flush()
            await db.refresh(conv_session)
        return conv_session

    async def archive_session(
        self, session_id: Any, db: AsyncSession
    ) -> ConversationSession | None:
        """Transition a session status to archived."""
        conv_session = await db.get(ConversationSession, session_id)
        if conv_session:
            conv_session.status = ConversationStatus.archived
            conv_session.updated_at = datetime.now(timezone.utc)
            await db.flush()
            await db.refresh(conv_session)
        return conv_session

    async def close_session(
        self, session_id: Any, db: AsyncSession
    ) -> ConversationSession | None:
        """Mark a session as closed."""
        conv_session = await db.get(ConversationSession, session_id)
        if conv_session:
            conv_session.status = ConversationStatus.closed
            conv_session.closed_at = datetime.now(timezone.utc)
            conv_session.updated_at = datetime.now(timezone.utc)
            await db.flush()
            await db.refresh(conv_session)
        return conv_session

    async def get_session_with_turns(
        self, session_id: Any, db: AsyncSession
    ) -> ConversationSession | None:
        """Retrieve a session with all turns and tool call records."""
        result = await db.execute(
            select(ConversationSession)
            .where(ConversationSession.id == session_id)
            .options(
                selectinload(ConversationSession.turns).selectinload(ConversationTurn.tool_calls)
            )
        )
        return result.scalar_one_or_none()

    async def list_sessions(
        self,
        db: AsyncSession,
        agent_type_id: Any | None = None,
        triggered_by_user_id: Any | None = None,
        status: ConversationStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationSession]:
        """List conversation sessions with optional filtering, ordered by updated_at DESC."""
        query = select(ConversationSession).order_by(
            ConversationSession.updated_at.desc()
        )
        if agent_type_id:
            query = query.where(ConversationSession.agent_type_id == agent_type_id)
        if triggered_by_user_id:
            query = query.where(ConversationSession.triggered_by_user_id == triggered_by_user_id)
        if status:
            query = query.where(ConversationSession.status == status)
        query = query.limit(limit).offset(offset)
        result = await db.execute(query)
        return list(result.scalars().all())

    # Status-filter semantics for the paginated sessions view
    # (FIX-20261101-120618 Work Item 1): "ended" = anything not active
    # (closed / archived / error); "all" = everything.
    _ENDED_STATUSES = ("closed", "archived", "error")

    async def list_sessions_page(
        self,
        db: AsyncSession,
        agent_type_id: Any | None = None,
        triggered_by_user_id: Any | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        all_time: bool = False,
        page: int = 1,
        page_size: int = 10,
        tenant_id: Any | None = None,
    ) -> tuple[list[ConversationSession], int]:
        """Paginated, filterable sessions listing ordered by updated_at DESC.

        FIX-20261101-120618 Work Item 1. When neither ``date_from`` nor
        ``date_to`` is given and ``all_time`` is False, a default lower bound
        of ``now − conversation_sessions_default_window_days`` is applied.

        ``status`` semantics: ``"active"`` → status == active; ``"ended"`` →
        closed/archived/error; ``"all"``/None → everything (None keeps
        backward-compatible unfiltered behaviour for programmatic callers).

        Returns ``(items, total)`` — ``total`` is the full filtered count so
        the UI can render pagination.
        """
        from app.core.config import get_settings

        query = select(ConversationSession)
        if agent_type_id:
            query = query.where(ConversationSession.agent_type_id == agent_type_id)
        if triggered_by_user_id:
            query = query.where(ConversationSession.triggered_by_user_id == triggered_by_user_id)
        if tenant_id:
            query = query.where(ConversationSession.tenant_id == tenant_id)

        if status == "active":
            query = query.where(ConversationSession.status == ConversationStatus.active)
        elif status == "ended":
            query = query.where(
                ConversationSession.status.in_(
                    [ConversationStatus(s) for s in self._ENDED_STATUSES]
                )
            )
        elif status == "all":
            pass  # no status constraint
        elif status:
            raise ValueError(
                f"Invalid status filter {status!r}; expected active|ended|all"
            )

        # Time window: explicit range wins; otherwise default window unless
        # all_time is requested.
        if not all_time:
            window_from = date_from
            if window_from is None and date_to is None:
                days = get_settings().conversation_sessions_default_window_days
                window_from = datetime.now(timezone.utc) - timedelta(days=days)
            if window_from is not None:
                query = query.where(ConversationSession.updated_at >= window_from)
            if date_to is not None:
                query = query.where(ConversationSession.updated_at <= date_to)

        # Total count over the filtered set (before pagination)
        count_query = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_query)).scalar_one()

        page = max(1, page)
        page_size = max(1, page_size)
        items_query = (
            query.order_by(ConversationSession.updated_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        result = await db.execute(items_query)
        return list(result.scalars().all()), total
