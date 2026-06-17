"""Communication Hub — Intervention Queue.

Per-conversation-session FIFO queue for intervention requests. When a
delegated sub-agent requests intervention and another intervention is already
pending for the same conversation, the new request is enqueued. Delivered to
the UI in order as prior interventions are resolved or cancelled.

Backed by database (InterveneRequest records with status=pending) for
resilience across WebSocket disconnects and service restarts.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Any

from app.communication_hub.data_client import ControlCenterDataClient

logger = logging.getLogger(__name__)


class InterventionQueue:
    """Per-conversation-session FIFO queue for pending interventions.

    Thread-safe enqueue/dequeue operations. Queue state persists across
    WebSocket disconnects via database queries to Control Center.
    """

    def __init__(self, data_client: ControlCenterDataClient | None = None) -> None:
        # In-memory cache of per-session pending request IDs
        # Key: conversation_session_id, Value: list of request_ids in order
        self._queues: dict[str, list[str]] = defaultdict(list)
        # Track which sessions have a currently active intervention
        self._active: set[str] = set()
        self._data_client = data_client

    def enqueue(self, conversation_session_id: str, request_id: str) -> int:
        """Enqueue a request for the given conversation session.

        Returns the queue length after enqueue (including the active one, if any).
        """
        session_key = str(conversation_session_id)
        req_id = str(request_id)
        if req_id not in self._queues[session_key]:
            self._queues[session_key].append(req_id)
        active = 1 if session_key in self._active else 0
        return len(self._queues[session_key]) + active

    def dequeue(self, conversation_session_id: str) -> str | None:
        """Dequeue and return the next pending request_id for the session.

        Returns None if the queue is empty.
        """
        session_key = str(conversation_session_id)
        if not self._queues[session_key]:
            return None
        return self._queues[session_key].pop(0)

    def mark_active(self, conversation_session_id: str) -> None:
        """Mark that a session has an active (displayed) intervention."""
        self._active.add(str(conversation_session_id))

    def clear_active(self, conversation_session_id: str) -> None:
        """Clear the active intervention flag for a session."""
        session_key = str(conversation_session_id)
        self._active.discard(session_key)

    def has_active(self, conversation_session_id: str) -> bool:
        """Check if a session currently has an active intervention displayed."""
        return str(conversation_session_id) in self._active

    def has_pending(self, conversation_session_id: str) -> bool:
        """Check if a session has any pending interventions (active or queued)."""
        session_key = str(conversation_session_id)
        return session_key in self._active or len(self._queues[session_key]) > 0

    def queue_length(self, conversation_session_id: str) -> int:
        """Return the count of queued (not yet active) interventions."""
        session_key = str(conversation_session_id)
        return len(self._queues[session_key])

    def clear_session(self, conversation_session_id: str) -> None:
        """Clear all intervention state for a conversation session."""
        session_key = str(conversation_session_id)
        self._queues.pop(session_key, None)
        self._active.discard(session_key)

    async def reload_from_db(
        self, conversation_session_id: str
    ) -> list[dict[str, Any]]:
        """Reload pending interventions from Control Center via data client.

        Returns list of pending intervention dicts, or empty list on failure.
        """
        if not self._data_client:
            return []
        try:
            session_id = uuid.UUID(conversation_session_id)
            data = await self._data_client._get(
                f"/conversations/{session_id}/interventions/pending"
            )
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning(
                "Failed to reload pending interventions for session %s: %s",
                conversation_session_id,
                exc,
            )
            return []
