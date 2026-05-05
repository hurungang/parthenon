"""SessionDispatcher — background worker that polls queued AgentJobs and dispatches them."""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from opentelemetry import trace
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentJob, AgentJobStatus
from app.db.session import AsyncSessionLocal

if TYPE_CHECKING:
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Default dispatch configuration
_POLL_INTERVAL_SECONDS: float = 2.0
_MAX_CONCURRENT_SESSIONS: int = 4


class SessionDispatcher:
    """
    Background worker that continuously polls for queued AgentJobs and dispatches
    them to AgentRuntimeExecutor.

    Concurrency is bounded by a semaphore so at most _MAX_CONCURRENT_SESSIONS
    sessions execute in parallel.

    Usage::

        dispatcher = SessionDispatcher()
        asyncio.create_task(dispatcher.run())
    """

    def __init__(
        self,
        poll_interval: float = _POLL_INTERVAL_SECONDS,
        max_concurrent: int = _MAX_CONCURRENT_SESSIONS,
    ) -> None:
        self._poll_interval = poll_interval
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running = False

    async def run(self) -> None:
        """Start the dispatch loop. Call once from the application startup event."""
        self._running = True
        logger.info("SessionDispatcher started (poll_interval=%.1fs)", self._poll_interval)
        while self._running:
            try:
                await self._poll_and_dispatch()
            except Exception:
                logger.exception("SessionDispatcher poll cycle raised an unexpected error")
            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        """Request the dispatcher to stop after the current poll cycle."""
        self._running = False

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _poll_and_dispatch(self) -> None:
        """Claim queued sessions and launch them as background tasks."""
        async with AsyncSessionLocal() as db:
            sessions = await self._claim_queued_sessions(db)
            await db.commit()

        for session_id in sessions:
            asyncio.create_task(self._dispatch_session(session_id))

    async def _claim_queued_sessions(self, db: AsyncSession) -> list[uuid.UUID]:
        """
        Atomically claim up to max_concurrent queued sessions by setting their
        status to 'running'. Uses SELECT … FOR UPDATE SKIP LOCKED to avoid
        double-dispatch across concurrent workers.
        """
        available_slots = self._semaphore._value  # noqa: SLF001
        if available_slots <= 0:
            return []

        # SELECT FOR UPDATE SKIP LOCKED — PostgreSQL-specific
        result = await db.execute(
            select(AgentJob.id)
            .where(AgentJob.status == AgentJobStatus.queued)
            .order_by(AgentJob.created_at)
            .limit(available_slots)
            .with_for_update(skip_locked=True)
        )
        session_ids = [row[0] for row in result.fetchall()]

        if session_ids:
            from datetime import datetime, timezone
            await db.execute(
                update(AgentJob)
                .where(AgentJob.id.in_(session_ids))
                .values(status=AgentJobStatus.running, started_at=datetime.now(timezone.utc))
            )
            logger.info("Claimed %d session(s) for dispatch", len(session_ids))

        return session_ids

    async def _dispatch_session(self, session_id: uuid.UUID) -> None:
        """Execute a single session inside the concurrency semaphore."""
        async with self._semaphore:
            with tracer.start_as_current_span(
                "dispatcher.dispatch_session",
                attributes={"session_id": str(session_id)},
            ):
                try:
                    from app.services.agents.runtime_executor import AgentRuntimeExecutor
                    executor = AgentRuntimeExecutor()
                    async with AsyncSessionLocal() as db:
                        await executor.run(session_id, db)
                        await db.commit()
                except Exception as exc:
                    logger.exception(
                        "Session %s failed during executor run: %s", session_id, exc
                    )
                    # Mark failed in a fresh session
                    try:
                        async with AsyncSessionLocal() as db:
                            from app.services.agents.session_service import AgentSessionService
                            svc = AgentSessionService()
                            await svc.mark_failed(session_id, str(exc), db)
                            await db.commit()
                    except Exception:
                        logger.exception(
                            "Failed to mark session %s as failed after executor error",
                            session_id,
                        )
