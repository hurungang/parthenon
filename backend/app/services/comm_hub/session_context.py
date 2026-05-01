"""Session Context Manager — stores and retrieves active session state in Redis."""

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TTL = 3600  # 1 hour


class SessionContextManager:
    """
    Stores and retrieves active session state (participants, message count, status)
    in Redis with configurable TTL.
    """

    def __init__(self, ttl_seconds: int = DEFAULT_SESSION_TTL) -> None:
        settings = get_settings()
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self._ttl = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"parthenon:context:{session_id}"

    async def set(self, session_id: str, context: dict[str, Any]) -> None:
        """Store session context in Redis with TTL."""
        key = self._key(session_id)
        await self._redis.setex(key, self._ttl, json.dumps(context))
        logger.debug("Set session context for %s (TTL=%ds)", session_id, self._ttl)

    async def get(self, session_id: str) -> dict[str, Any] | None:
        """
        Retrieve session context from Redis.

        Returns None if the session has expired or does not exist.
        """
        key = self._key(session_id)
        raw = await self._redis.get(key)
        if raw is None:
            logger.debug("Session context not found (expired or missing): %s", session_id)
            return None
        return json.loads(raw)

    async def update(self, session_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Merge updates into an existing session context and refresh TTL."""
        context = await self.get(session_id)
        if context is None:
            return None
        context.update(updates)
        await self.set(session_id, context)
        return context

    async def delete(self, session_id: str) -> None:
        """Delete a session context."""
        await self._redis.delete(self._key(session_id))

    async def close(self) -> None:
        """Close the Redis connection."""
        await self._redis.aclose()
