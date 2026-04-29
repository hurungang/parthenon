"""Agent Router (Communication Hub) — routes inter-agent messages via MessageBroker."""
import logging
from typing import Any

from app.services.comm_hub.broker import BrokerMessage, MessageBroker

logger = logging.getLogger(__name__)


class AgentRouter:
    """
    Routes inter-agent messages to target agent instance channels via MessageBroker.
    """

    def __init__(self, broker: MessageBroker | None = None) -> None:
        self._broker = broker or MessageBroker()

    async def route(
        self,
        source_session_id: str,
        target_session_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """
        Route a message from one agent session to another.

        Args:
            source_session_id: The sending agent's session ID.
            target_session_id: The receiving agent's session ID.
            content: Message content.
            metadata: Optional metadata to include with the message.

        Returns:
            Number of subscribers that received the message.
        """
        message = BrokerMessage(
            session_id=target_session_id,
            sender_role="agent",
            content=content,
            metadata={
                "source_session_id": source_session_id,
                **(metadata or {}),
            },
        )
        count = await self._broker.publish(message)
        logger.info(
            "Routed message from session %s to session %s (%d subscribers)",
            source_session_id,
            target_session_id,
            count,
        )
        return count
