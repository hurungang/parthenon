"""SessionDispatcher — background worker that dispatches AgentJobs to the executor.

Supports two dispatch modes that work together:

1. **Trigger-based** (primary): Control Center calls ``POST /execute`` on Agent
   Runtime, which places the ``session_id`` into ``session_queue`` (an
   ``asyncio.Queue``).  The dispatcher's run loop waits on this queue and
   dispatches sessions immediately as they arrive.

2. **Poll-based** (fallback/recovery): When no trigger arrives within
   ``poll_interval`` seconds the dispatcher polls Control Center's
   ``/internal/data/sessions/claim-queued`` endpoint.  This recovers sessions
   that were created while Agent Runtime was restarting or unreachable.

Phase 5 wires the trigger queue; Phase 3 wired the CC data client.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import TYPE_CHECKING

from opentelemetry import trace

if TYPE_CHECKING:
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.agent_runtime.data_client import ControlCenterDataClient

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Default dispatch configuration
# Poll interval for fallback recovery mode (trigger-based is primary dispatch method)
_DEFAULT_POLL_INTERVAL_SECONDS: float = 30.0
_MAX_CONCURRENT_SESSIONS: int = 4


def _get_poll_interval() -> float:
    """Get poll interval from environment or use default."""
    interval_str = os.environ.get("SESSION_DISPATCHER_POLL_INTERVAL_SECONDS")
    if interval_str:
        try:
            return float(interval_str)
        except ValueError:
            logger.warning(
                "Invalid SESSION_DISPATCHER_POLL_INTERVAL_SECONDS=%s, using default %.1fs",
                interval_str,
                _DEFAULT_POLL_INTERVAL_SECONDS,
            )
    return _DEFAULT_POLL_INTERVAL_SECONDS


class SessionDispatcher:
    """
    Background worker that dispatches AgentJobs to AgentRuntimeExecutor.

    Concurrency is bounded by a semaphore so at most _MAX_CONCURRENT_SESSIONS
    sessions execute in parallel.

    Session state management is delegated to Control Center via the data client;
    this process has no direct database access.

    Usage::

        data_client = ControlCenterDataClient(cert_manager)
        session_queue = asyncio.Queue()        # populated by POST /execute
        dispatcher = SessionDispatcher(
            data_client=data_client,
            session_queue=session_queue,
        )
        asyncio.create_task(dispatcher.run())
    """

    def __init__(
        self,
        data_client: "ControlCenterDataClient",
        poll_interval: float | None = None,
        max_concurrent: int = _MAX_CONCURRENT_SESSIONS,
        session_queue: asyncio.Queue | None = None,
    ) -> None:
        self._data_client = data_client
        self._poll_interval = poll_interval if poll_interval is not None else _get_poll_interval()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._session_queue = session_queue
        self._running = False

    async def run(self) -> None:
        """Start the dispatch loop. Call once from the application startup event.

        When a ``session_queue`` is provided, the loop blocks on it for up to
        ``poll_interval`` seconds waiting for trigger-based sessions.  When the
        wait times out (no trigger arrived) it falls back to polling Control
        Center for any queued sessions not yet claimed.
        """
        self._running = True
        logger.info("SessionDispatcher started (poll_interval=%.1fs)", self._poll_interval)
        while self._running:
            try:
                if self._session_queue is not None:
                    await self._drain_trigger_queue_then_poll()
                else:
                    await self._poll_and_dispatch()
                    await asyncio.sleep(self._poll_interval)
            except Exception:
                logger.exception("SessionDispatcher poll cycle raised an unexpected error")

    async def _drain_trigger_queue_then_poll(self) -> None:
        """Wait on the trigger queue; fall back to CC polling on timeout."""
        try:
            # Block until a trigger arrives or the poll interval elapses
            session_id = await asyncio.wait_for(
                self._session_queue.get(),  # type: ignore[union-attr]
                timeout=self._poll_interval,
            )
            asyncio.create_task(self._dispatch_session(session_id))
            # Drain any additional sessions already in the queue
            while not self._session_queue.empty():  # type: ignore[union-attr]
                try:
                    extra_id = self._session_queue.get_nowait()  # type: ignore[union-attr]
                    asyncio.create_task(self._dispatch_session(extra_id))
                except asyncio.QueueEmpty:
                    break
        except asyncio.TimeoutError:
            # No trigger arrived — fall back to polling CC for recovery
            await self._poll_and_dispatch()

    def stop(self) -> None:
        """Request the dispatcher to stop after the current poll cycle."""
        self._running = False

    # ── Internal ─────────────────────────────────────────────────────────────────────────────

    async def _poll_and_dispatch(self) -> None:
        """Claim queued sessions from CC and launch them as background tasks."""
        available_slots = self._semaphore._value  # noqa: SLF001
        if available_slots <= 0:
            return

        session_ids = await self._data_client.claim_queued_sessions(limit=available_slots)
        for session_id in session_ids:
            asyncio.create_task(self._dispatch_session(session_id))

    async def _dispatch_session(self, session_id: uuid.UUID) -> None:
        """Execute a single session inside the concurrency semaphore."""
        async with self._semaphore:
            with tracer.start_as_current_span(
                "dispatcher.dispatch_session",
                attributes={"session_id": str(session_id)},
            ):
                try:
                    from app.services.agents.runtime_executor import AgentRuntimeExecutor
                    executor = AgentRuntimeExecutor(data_client=self._data_client)
                    await executor.run(session_id, self._data_client)
                except Exception as exc:
                    logger.exception(
                        "Session %s failed during executor run: %s", session_id, exc
                    )
                    # Mark failed via CC data API — do NOT open a DB session here
                    try:
                        await self._data_client.mark_session_failed(session_id, str(exc))
                    except Exception:
                        logger.exception(
                            "Failed to mark session %s as failed after executor error",
                            session_id,
                        )
