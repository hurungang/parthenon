"""Message Broker — Redis pub/sub with per-session typed channels."""
import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class BrokerMessage:
    """Strongly-typed message structure for the communication hub."""

    def __init__(
        self,
        session_id: str,
        sender_role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.session_id = session_id
        self.sender_role = sender_role
        self.content = content
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "sender_role": self.sender_role,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BrokerMessage":
        msg = cls(
            session_id=data["session_id"],
            sender_role=data["sender_role"],
            content=data["content"],
            metadata=data.get("metadata", {}),
        )
        msg.timestamp = data.get("timestamp", msg.timestamp)
        return msg


def _session_channel(session_id: str) -> str:
    """Return the Redis pub/sub channel name for a session."""
    return f"parthenon:session:{session_id}"


class MessageBroker:
    """
    Redis pub/sub broker with per-session typed message channels.
    Each session gets its own channel: parthenon:session:{session_id}
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    async def publish(self, message: BrokerMessage) -> int:
        """
        Publish a message to the session's channel.

        Returns the number of subscribers that received the message.
        """
        channel = _session_channel(message.session_id)
        payload = json.dumps(message.to_dict())
        count: int = await self._redis.publish(channel, payload)
        logger.debug(
            "Published to channel %s (%d subscribers)", channel, count
        )
        return count

    async def subscribe(self, session_id: str):  # type: ignore[return]
        """
        Subscribe to a session channel.

        Returns an async generator yielding BrokerMessage objects.
        """
        channel = _session_channel(session_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        logger.debug("Subscribed to channel %s", channel)

        try:
            async for raw_message in pubsub.listen():
                if raw_message["type"] == "message":
                    try:
                        data = json.loads(raw_message["data"])
                        yield BrokerMessage.from_dict(data)
                    except (json.JSONDecodeError, KeyError) as exc:
                        logger.warning("Failed to parse broker message: %s", exc)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    async def close(self) -> None:
        """Close the Redis connection."""
        await self._redis.aclose()
