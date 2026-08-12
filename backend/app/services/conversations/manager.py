"""ConversationSessionManager — orchestrates session lifecycle."""
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentInputType, AgentType
from app.db.models.conversations import ConversationSession
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
        """Create a new conversation session for the given agent type.

        Validates that the agent type exists and has input_type=conversation.
        Raises ValueError for non-conversation agent types.
        """
        agent_type = await db.get(AgentType, agent_type_id)
        if agent_type is None:
            raise ValueError(f"AgentType {agent_type_id} not found")
        if agent_type.input_type != AgentInputType.conversation:
            raise ValueError(
                f"AgentType {agent_type_id} has input_type={agent_type.input_type!r}; "
                "only conversation agents support session creation"
            )

        session = await _store.create_session(
            db=db,
            agent_type_id=agent_type_id,
            triggered_by_user_id=triggered_by_user_id,
        )
        logger.info(
            "Created ConversationSession %s for agent_type %s user %s",
            session.id,
            agent_type_id,
            triggered_by_user_id,
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
