"""Communication Hub — Intervention Router.

Detects conversation-scoped human_intervene requests and routes them to
connected WebSocket clients instead of the operator dashboard. Non-conversation
interventions fall through to the existing dashboard flow unchanged.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Awaitable, Callable

from app.communication_hub.data_client import ControlCenterDataClient
from app.communication_hub.intervention_queue import InterventionQueue

logger = logging.getLogger(__name__)

# Callable for sending a WebSocket message to a specific session
SendToSessionFn = Callable[[str, dict[str, Any]], Awaitable[None]]


class InterventionRouter:
    """Routes conversation-scoped intervention signals to WebSocket clients.

    Responsibilities:
    - Inspects each human_intervene suspend signal for conversation_session_id
    - Routes to connected WebSocket client when found (conversation-scoped)
    - Falls through to existing dashboard flow when not found (standalone)
    - Manages per-session FIFO intervention queue
    - Logs routing decisions for observability
    """

    def __init__(
        self,
        data_client: ControlCenterDataClient | None = None,
        send_to_session: SendToSessionFn | None = None,
    ) -> None:
        self._data_client = data_client
        self._send_to_session = send_to_session
        self._queue = InterventionQueue(data_client=data_client)

    @property
    def queue(self) -> InterventionQueue:
        return self._queue

    def set_send_to_session(self, fn: SendToSessionFn) -> None:
        """Register the WebSocket send callback for delivering messages."""
        self._send_to_session = fn

    async def route_intervention_signal(
        self,
        session_id: str,
        message_type: str,
        content: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Inspect a dispatch signal for conversation-scoped intervention.

        Returns True if the signal was routed to a WebSocket client (consumed),
        False if it should fall through to the existing dashboard flow.
        """
        if message_type != "intervene_request" and message_type != "intervention":
            # Not an intervention signal — fall through
            return False

        conversation_session_id = content.get("conversation_session_id")
        if not conversation_session_id:
            # Non-conversational intervention — fall through to dashboard
            logger.debug(
                "Intervention request %s has no conversation_session_id — "
                "falling through to dashboard flow",
                content.get("request_id", "unknown"),
            )
            return False

        conv_sid = str(conversation_session_id)
        request_id = content.get("request_id") or content.get("id")

        logger.info(
            "Routing conversational intervention %s to session %s",
            request_id,
            conv_sid,
        )

        # Build and push the intervene_request WebSocket message
        message = self._build_intervene_request_message(content, metadata)

        if self._send_to_session and self._has_connected_client(conv_sid):
            try:
                await self._send_to_session(conv_sid, message)
                self._queue.mark_active(conv_sid)
                logger.info(
                    "Intervention request %s delivered to WebSocket client for session %s",
                    request_id,
                    conv_sid,
                )
                return True
            except Exception as exc:
                logger.warning(
                    "Failed to deliver intervention %s to session %s: %s — "
                    "request will be re-delivered on reconnect",
                    request_id,
                    conv_sid,
                    exc,
                )
        else:
            # Client not connected — enqueue for reconnect delivery
            if request_id:
                q_len = self._queue.enqueue(conv_sid, str(request_id))
                logger.info(
                    "Intervention request %s enqueued for session %s "
                    "(client not connected, queue length=%d)",
                    request_id,
                    conv_sid,
                    q_len,
                )

        # Even if delivery fails, we consumed the signal (it's conversation-scoped)
        return True

    async def deliver_on_reconnect(self, conversation_session_id: str) -> list[dict[str, Any]]:
        """Deliver any pending intervention requests on WebSocket reconnect.

        Returns list of intervention messages delivered (for audit/debug).
        """
        delivered: list[dict[str, Any]] = []
        conv_sid = str(conversation_session_id)

        if not self._data_client:
            return delivered

        try:
            pending = await self._queue.reload_from_db(conv_sid)
        except Exception as exc:
            logger.warning(
                "Failed to reload pending interventions for reconnect on session %s: %s",
                conv_sid,
                exc,
            )
            return delivered

        for req in pending:
            message = self._build_intervene_request_message_from_db(req)
            if self._send_to_session:
                try:
                    await self._send_to_session(conv_sid, message)
                    self._queue.mark_active(conv_sid)
                    delivered.append(message)
                except Exception as exc:
                    logger.warning(
                        "Failed to deliver pending intervention on reconnect: %s",
                        exc,
                    )
                    break

        return delivered

    async def handle_intervention_response(
        self,
        conversation_session_id: str,
        request_id: str,
        response_value: dict[str, Any],
    ) -> None:
        """Handle a user's intervention response from the WebSocket client.

        Persists the response via Control Center and dequeues the next
        pending intervention if any.
        """
        conv_sid = str(conversation_session_id)
        self._queue.clear_active(conv_sid)

        # Try to deliver next queued intervention
        next_request_id = self._queue.dequeue(conv_sid)
        if next_request_id and self._data_client and self._send_to_session:
            try:
                # Fetch and deliver the next pending request
                pending = await self._queue.reload_from_db(conv_sid)
                for req in pending:
                    if str(req.get("id")) == next_request_id:
                        message = self._build_intervene_request_message_from_db(req)
                        await self._send_to_session(conv_sid, message)
                        self._queue.mark_active(conv_sid)
                        break
            except Exception as exc:
                logger.warning(
                    "Failed to deliver next queued intervention for session %s: %s",
                    conv_sid,
                    exc,
                )

    async def handle_intervention_cancel(
        self,
        conversation_session_id: str,
        request_id: str,
    ) -> None:
        """Handle user cancellation of an intervention dialog.

        Clears the active intervention and delivers next queued if any.
        """
        conv_sid = str(conversation_session_id)
        self._queue.clear_active(conv_sid)

        # Deliver next queued intervention
        next_request_id = self._queue.dequeue(conv_sid)
        if next_request_id and self._data_client and self._send_to_session:
            try:
                pending = await self._queue.reload_from_db(conv_sid)
                for req in pending:
                    if str(req.get("id")) == next_request_id:
                        message = self._build_intervene_request_message_from_db(req)
                        await self._send_to_session(conv_sid, message)
                        self._queue.mark_active(conv_sid)
                        break
            except Exception as exc:
                logger.warning(
                    "Failed to deliver next queued intervention after cancel: %s",
                    exc,
                )

    def _has_connected_client(self, conversation_session_id: str) -> bool:
        """Check if a WebSocket client is connected for the given session.

        This is a best-effort check; actual delivery may still fail.
        """
        # The session manager tracks connected sessions
        from app.api.ws.chat import ActiveSessionTracker
        return ActiveSessionTracker.is_connected(conversation_session_id)

    @staticmethod
    def _build_intervene_request_message(
        content: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a WebSocket intervene_request message from raw dispatch content."""
        return {
            "type": "intervene_request",
            "request_id": str(content.get("request_id") or content.get("id", "")),
            "intervention_type": content.get("intervention_type", "approval"),
            "reason": content.get("reason", ""),
            "choices": content.get("choices"),
            "agent_type": content.get("agent_type") or (metadata or {}).get("agent_type"),
            "delegation_depth": content.get("delegation_depth", 0),
            "conversation_session_id": str(content.get("conversation_session_id", "")),
        }

    @staticmethod
    def _build_intervene_request_message_from_db(
        db_record: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a WebSocket intervene_request message from a DB record."""
        return {
            "type": "intervene_request",
            "request_id": str(db_record.get("id", "")),
            "intervention_type": db_record.get("intervention_type", "approval"),
            "reason": db_record.get("reason", ""),
            "choices": db_record.get("choices"),
            "agent_type": db_record.get("agent_name"),
            "delegation_depth": db_record.get("delegation_depth", 0),
            "conversation_session_id": str(db_record.get("conversation_session_id", "")),
        }
