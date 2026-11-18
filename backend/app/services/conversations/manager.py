"""ConversationSessionManager — orchestrates session lifecycle."""
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInputType, AgentType
from app.db.models.conversations import ConversationSession
from app.services.agents.optimization_mode import (
    BUSINESS_CHANNEL_DEFAULT,
    OPTIMIZATION_CHANNEL,
)
from app.services.conversations.store import ConversationStore

logger = logging.getLogger(__name__)

_store = ConversationStore()


class ConversationSessionManager:
    """
    Owns the lifecycle of ConversationSession objects:
    create, resume, end, archive.

    Validates session ownership on all mutating operations.
    """

    async def create(
        self,
        agent_type_id: uuid.UUID,
        triggered_by_user_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> ConversationSession:
        """Create a new BUSINESS conversation session for the given agent type.

        Business conversations keep the existing contract: the agent type must
        exist and have ``input_type=conversation`` (a typed agent type has no
        business chat surface). Raises ValueError for non-conversation agent
        types. Optimization conversations are created through
        :meth:`create_optimization`, which skips this business-only check.
        """
        return await self._create_session(
            agent_type_id=agent_type_id,
            triggered_by_user_id=triggered_by_user_id,
            db=db,
            channel=BUSINESS_CHANNEL_DEFAULT,
            require_conversational_input=True,
        )

    async def create_optimization(
        self,
        agent_type_id: uuid.UUID,
        triggered_by_user_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> ConversationSession:
        """Create an optimization conversation on the subject agent type.

        An optimization conversation is an ordinary ``ConversationSession``
        whose ``agent_type_id`` IS the subject and whose ``channel`` is
        ``"optimization"``. It is accepted for **typed and conversational**
        agent types (the business ``input_type == conversation`` guard applies
        only to business conversations).

        Nothing else is written: no plan work starts, no availability/model
        value is persisted, and the subject is fixed at insert (no update path
        exposes ``agent_type_id`` or ``channel``).
        """
        return await self._create_session(
            agent_type_id=agent_type_id,
            triggered_by_user_id=triggered_by_user_id,
            db=db,
            channel=OPTIMIZATION_CHANNEL,
            require_conversational_input=False,
        )

    async def _create_session(
        self,
        *,
        agent_type_id: uuid.UUID,
        triggered_by_user_id: uuid.UUID | None,
        db: AsyncSession,
        channel: str,
        require_conversational_input: bool,
    ) -> ConversationSession:
        """Shared session insert; the conversational guard is business-only."""
        agent_type = await db.get(AgentType, agent_type_id)
        if agent_type is None:
            raise ValueError(f"AgentType {agent_type_id} not found")
        if (
            require_conversational_input
            and agent_type.input_type != AgentInputType.conversation
        ):
            raise ValueError(
                f"AgentType {agent_type_id} has input_type={agent_type.input_type!r}; "
                "only conversation agents support session creation"
            )

        session = await _store.create_session(
            db=db,
            agent_type_id=agent_type_id,
            triggered_by_user_id=triggered_by_user_id,
            channel=channel,
        )
        logger.info(
            "Created ConversationSession %s for agent_type %s user %s (channel=%s)",
            session.id,
            agent_type_id,
            triggered_by_user_id,
            channel,
        )
        return session

    async def resume(
        self,
        session_id: uuid.UUID,
        requesting_user_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> ConversationSession:
        """Fetch full session history, validating ownership.

        Returns the session with all turns and tool call records loaded.
        Raises PermissionError if requesting_user_id does not match.
        Raises ValueError if session not found.
        """
        session = await _store.get_session_with_turns(session_id, db)
        if session is None:
            raise ValueError(f"ConversationSession {session_id} not found")
        self._check_ownership(session, requesting_user_id)
        return session

    async def end(
        self,
        session_id: uuid.UUID,
        requesting_user_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> ConversationSession:
        """Transition session status to closed, validating ownership.

        Raises PermissionError on ownership mismatch.
        Raises ValueError if session not found.
        """
        session = await db.get(ConversationSession, session_id)
        if session is None:
            raise ValueError(f"ConversationSession {session_id} not found")
        self._check_ownership(session, requesting_user_id)
        result = await _store.close_session(session_id, db)
        logger.info("Ended ConversationSession %s", session_id)
        return result  # type: ignore[return-value]

    async def archive(
        self,
        session_id: uuid.UUID,
        requesting_user_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> ConversationSession:
        """Transition session status to archived, validating ownership.

        Raises PermissionError on ownership mismatch.
        Raises ValueError if session not found.
        """
        session = await db.get(ConversationSession, session_id)
        if session is None:
            raise ValueError(f"ConversationSession {session_id} not found")
        self._check_ownership(session, requesting_user_id)
        result = await _store.archive_session(session_id, db)
        logger.info("Archived ConversationSession %s", session_id)
        return result  # type: ignore[return-value]

    # ── Private helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _check_ownership(
        session: ConversationSession,
        requesting_user_id: uuid.UUID | None,
    ) -> None:
        """Raise PermissionError if the requesting user does not own the session."""
        if session.triggered_by_user_id is None or requesting_user_id is None:
            # No ownership info — allow access (e.g., admin operations)
            return
        if session.triggered_by_user_id != requesting_user_id:
            raise PermissionError(
                f"ConversationSession {session.id} is not owned by user {requesting_user_id}"
            )
