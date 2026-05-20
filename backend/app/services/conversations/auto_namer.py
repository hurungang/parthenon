"""SessionAutoNamer — generates session titles via LLM and writes them back to the store."""
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentType
from app.services.conversations.store import ConversationStore

logger = logging.getLogger(__name__)

_store = ConversationStore()

# Maximum characters to use from the first message as fallback title
_FALLBACK_MAX_CHARS = 60
# Maximum title characters from LLM response
_TITLE_MAX_CHARS = 80


class SessionAutoNamer:
    """
    Background-task service that generates a short descriptive title for a new
    conversation session based on the first user message.

    The title is written to the database via ConversationStore and returned.
    Falls back gracefully to a truncated version of the first message if the
    LLM call fails.
    """

    async def generate_and_save(
        self,
        session_id: uuid.UUID,
        first_user_message: str,
        agent_type_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> str:
        """Generate a title, persist it, and return it.

        If the session already has a title, return it without regenerating.

        Args:
            session_id: ID of the ConversationSession to title.
            first_user_message: The raw text of the first user turn.
            agent_type_id: The agent type's ID (used to resolve model config).
            db: Active database session.

        Returns:
            The generated (or fallback) title string.
        """
        # Check if session already has a title
        from app.db.models.conversations import ConversationSession
        conv_session = await db.get(ConversationSession, session_id)
        if conv_session and conv_session.title:
            logger.debug("Session %s already has title: %r", session_id, conv_session.title)
            return conv_session.title

        title = await self._try_generate_via_llm(first_user_message, agent_type_id, db)
        if not title:
            title = self._fallback_title(first_user_message)

        await _store.update_title(session_id, title, db)
        await db.commit()
        logger.info("Auto-named ConversationSession %s -> %r", session_id, title)
        return title

    async def _try_generate_via_llm(
        self,
        first_user_message: str,
        agent_type_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> str | None:
        """Attempt to call the LLM to produce a concise title.

        Returns the title string on success, None on any failure.
        """
        if not agent_type_id:
            return None
        try:
            agent_type = await db.get(AgentType, agent_type_id)
            if agent_type is None or not agent_type.model_id:
                return None

            from app.services.agents.model_binding import ModelBindingError, ModelBindingLayer

            binding = ModelBindingLayer()
            model_config = await binding.resolve_model_config(agent_type.model_id, db)

            prompt_messages: list[dict[str, Any]] = [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant that generates concise, descriptive titles "
                        "for conversation sessions. Given the user's first message, produce a short "
                        "title of 5-10 words. Output ONLY the title text, no quotes, no punctuation at the end."
                    ),
                },
                {
                    "role": "user",
                    "content": f"First message: {first_user_message[:500]}",
                },
            ]

            response = await binding.complete(
                agent_type=agent_type,
                model_config=model_config,
                messages=prompt_messages,
                max_tokens=32,
            )

            # Extract the text from the response (OpenAI-compat format)
            choices = response.get("choices") or []
            if choices:
                raw_title = (choices[0].get("message") or {}).get("content", "").strip()
                if raw_title:
                    return raw_title[:_TITLE_MAX_CHARS]
        except Exception as exc:
            logger.warning(
                "SessionAutoNamer: LLM title generation failed for session, falling back: %s", exc
            )
        return None

    @staticmethod
    def _fallback_title(first_user_message: str) -> str:
        """Return a truncated version of the first message as a fallback title."""
        text = first_user_message.strip()
        if len(text) <= _FALLBACK_MAX_CHARS:
            return text
        return text[:_FALLBACK_MAX_CHARS].rstrip() + "…"
