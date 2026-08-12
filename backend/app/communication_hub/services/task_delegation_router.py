"""Communication Hub — Task Delegation Event Router.

Routes non-conversational delegation status events and intervention requests
to execution log viewer clients through the Control Center execution log store.

Maintains an in-memory registry of active log viewer connections scoped to
``agent_job_id``. Events are injected into CC's execution log store so the
existing NDJSON stream poll loop (``stream_session_execution_logs``) delivers
them to connected viewers.

The router provides two delivery paths:

1. **Live push** — When a viewer is registered for an ``agent_job_id``, events
   are persisted to CC and the viewer receives them through the live NDJSON
   stream (poll-based, near real-time).

2. **Fallback to poll** — When no viewer is connected, events are still
   persisted to CC and available via REST ``GET .../logs``.

This is an additive component — conversational delegation routing through
``ActiveSessionTracker`` is preserved unchanged.
"""
from __future__ import annotations

import logging
from typing import Any

from app.communication_hub.data_client import ControlCenterDataClient

logger = logging.getLogger(__name__)


class TaskDelegationEventRouter:
    """Routes delegation status events and intervention requests for
    non-conversational agent executions to log viewer clients.

    Responsibilities:
    - Maintains an in-memory mapping of ``agent_job_id`` → set of connected
      viewer channel identifiers.
    - Persists delegation status events to CC's execution log store via
      ``ControlCenterDataClient.log_execution_event()``.
    - Persists non-conversational intervention requests to CC's log store so
      the existing NDJSON stream delivers them to execution log viewers.
    - Falls back to poll-based delivery when no live viewer is connected
      (events are persisted and picked up on next poll).
    """

    def __init__(
        self,
        data_client: ControlCenterDataClient | None = None,
    ) -> None:
        self._data_client = data_client
        # agent_job_id → set[str] of viewer channel identifiers
        self._viewers: dict[str, set[str]] = {}

    # ── Viewer registry ───────────────────────────────────────────────────────

    def register_viewer(self, agent_job_id: str, channel_id: str) -> None:
        """Register a viewer channel for the given agent job.

        Args:
            agent_job_id: The parent agent session ID (``AgentJob.id``).
            channel_id: An identifier for the viewer connection (e.g. a
                WebSocket connection ID or SSE client ID).
        """
        if agent_job_id not in self._viewers:
            self._viewers[agent_job_id] = set()
        self._viewers[agent_job_id].add(channel_id)
        logger.debug(
            "Viewer %s registered for agent job %s (total viewers: %d)",
            channel_id,
            agent_job_id,
            len(self._viewers[agent_job_id]),
        )

    def unregister_viewer(self, agent_job_id: str, channel_id: str) -> None:
        """Unregister a viewer channel for the given agent job.

        Args:
            agent_job_id: The parent agent session ID.
            channel_id: The viewer channel identifier to remove.
        """
        viewers = self._viewers.get(agent_job_id)
        if viewers:
            viewers.discard(channel_id)
            if not viewers:
                del self._viewers[agent_job_id]
                logger.debug(
                    "Last viewer unregistered for agent job %s — removed entry",
                    agent_job_id,
                )
            else:
                logger.debug(
                    "Viewer %s unregistered for agent job %s (%d remaining)",
                    channel_id,
                    agent_job_id,
                    len(viewers),
                )

    def is_viewer_connected(self, agent_job_id: str) -> bool:
        """Check if any viewer is connected for the given agent job.

        Args:
            agent_job_id: The parent agent session ID.

        Returns:
            True if at least one viewer is registered for this session.
        """
        return agent_job_id in self._viewers and bool(self._viewers[agent_job_id])

    def viewer_count(self, agent_job_id: str) -> int:
        """Return the number of connected viewers for an agent job."""
        viewers = self._viewers.get(agent_job_id)
        return len(viewers) if viewers else 0

    # ── Event push ────────────────────────────────────────────────────────────

    async def push_event(
        self,
        agent_job_id: str,
        event_type: str,
        message: str,
        data: dict[str, Any] | None = None,
        log_level: str = "INFO",
    ) -> None:
        """Persist a delegation status event to the execution log store.

        The event is written to CC's execution log store via
        ``ControlCenterDataClient.log_execution_event()``.  The existing
        NDJSON stream poll loop picks up new entries in near real-time
        and delivers them to connected log viewers.

        Args:
            agent_job_id: The parent agent session ID (``AgentJob.id``).
            event_type: The delegation event type (e.g. ``delegation_started``,
                ``delegation_waiting``, ``delegation_resumed``,
                ``delegation_depth_blocked``, ``delegation_timeout``,
                ``delegation_failed``).
            message: A human-readable description of the event.
            data: Structured metadata to attach to the event.
            log_level: Log severity level (default ``INFO``).
        """
        if not self._data_client:
            logger.warning(
                "No ControlCenterDataClient available — cannot persist "
                "delegation event %s for session %s",
                event_type,
                agent_job_id,
            )
            return

        await self._data_client.log_execution_event(
            session_id=agent_job_id,
            event_type=event_type,
            message=message,
            data=data or {},
            log_level=log_level,
        )

    # ── Intervention routing ──────────────────────────────────────────────────

    async def push_intervene_request(
        self,
        agent_job_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Route a non-conversational intervention request to the execution log.

        Persists a ``human_intervene`` log event so the NDJSON stream delivers
        it to connected execution log viewers. The payload includes the
        intervention type, reason, choices, and requesting sub-agent context.

        Args:
            agent_job_id: The parent agent session ID (``AgentJob.id``).
            payload: The intervention request payload from the sub-agent,
                containing keys such as ``request_id``, ``intervention_type``,
                ``reason``, ``choices``, ``agent_type``.
        """
        if not self._data_client:
            logger.warning(
                "No ControlCenterDataClient available — cannot route "
                "intervention for session %s",
                agent_job_id,
            )
            return

        reason = payload.get("reason", "Intervention required")
        await self.push_event(
            agent_job_id=agent_job_id,
            event_type="human_intervene",
            message=str(reason),
            data={
                "intervention_type": payload.get("intervention_type"),
                "reason": reason,
                "choices": payload.get("choices"),
                "sub_agent_type": payload.get("agent_type"),
                "request_id": str(payload.get("request_id") or payload.get("id", "")),
                "delegation_depth": payload.get("delegation_depth", 0),
            },
        )

        logger.info(
            "Non-conversational intervention request %s routed to "
            "execution log for agent job %s",
            payload.get("request_id", "unknown"),
            agent_job_id,
        )
