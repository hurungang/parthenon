"""Overdue optimization live-test sweep (Control Center).

A live-test approval is only answerable inside its ``expires_at`` window. This
sweep is the durable backstop that guarantees an unanswered request never stays
actionable — and that the conversation is left **replay-only with no retry**:

* the ``pending`` ledger row becomes ``expired``;
* its linked ``InterveneRequest`` is closed (no dead confirmation is offered);
* the paused turn is resolved as ``unresumable/expired`` and exactly one
  bounded-stop outcome turn is appended;
* the persisted activity resolves to its terminal (timed-out) state.

The answer path also performs a lazy expiry check, so racing the sweep can never
execute an overdue request. Control Center is the only DB writer; Agent Runtime
and Communication Hub are never involved (nothing is executed here).

Runs as a background task in the Control Center lifespan (same cadence family as
the conversation activity reaper) plus one pass at startup.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 60


class LiveTestExpirySweeper:
    """Periodically closes overdue ``pending`` live-test requests."""

    def __init__(self, interval_seconds: int | None = None) -> None:
        self._interval_override = interval_seconds
        self._task: asyncio.Task | None = None

    def _interval_seconds(self) -> int:
        if self._interval_override is not None:
            return max(1, int(self._interval_override))
        try:
            from app.core.config import get_settings

            return max(
                1, int(get_settings().optimizer_live_test_sweep_interval_seconds)
            )
        except Exception:  # noqa: BLE001 — a missing setting keeps the default
            return DEFAULT_INTERVAL_SECONDS

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._run_loop(), name="optimization-live-test-expiry"
        )
        logger.info(
            "LiveTestExpirySweeper started (interval=%ss)", self._interval_seconds()
        )

    def shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
            logger.info("LiveTestExpirySweeper stopped")

    async def _run_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval_seconds())
                await self.sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Live-test expiry sweep failed; continuing."
                )

    # ── Sweep ────────────────────────────────────────────────────────────────

    async def sweep_once(self) -> int:
        """One sweep over every tenant (unscoped session)."""
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            expired = await sweep_expired_live_tests(db)
            await db.commit()
        if expired:
            logger.info(
                "Live-test expiry sweep closed %d overdue request(s)", expired
            )
        return expired


async def sweep_expired_live_tests(db: AsyncSession) -> int:
    """Close overdue live-test requests in the caller's transaction."""
    from app.services.agents.optimization_live_test_service import (
        get_live_test_service,
    )

    return await get_live_test_service().expire_overdue(db)


_sweeper: LiveTestExpirySweeper | None = None


def get_live_test_sweeper() -> LiveTestExpirySweeper:
    """Return the process-wide sweeper singleton (created on first use)."""
    global _sweeper
    if _sweeper is None:
        _sweeper = LiveTestExpirySweeper()
    return _sweeper


__all__ = [
    "LiveTestExpirySweeper",
    "get_live_test_sweeper",
    "sweep_expired_live_tests",
]
