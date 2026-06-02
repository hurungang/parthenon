"""Session recovery/cleanup helpers for service restarts."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import (
    AgentJob,
    AgentJobStatus,
    AgentTerminationCategory,
    SessionStopCategory,
)


class SessionRecoveryService:
    """Handles recovery policy for non-terminal sessions after restart."""

    async def cleanup_non_terminal_sessions(self, db: AsyncSession) -> int:
        """Mark queued/running sessions as failed on service startup.

        Product policy: do not carry previous live executions across service restarts.
        """
        now = datetime.now(timezone.utc)
        result = await db.execute(
            update(AgentJob)
            .where(AgentJob.status.in_([AgentJobStatus.queued, AgentJobStatus.running]))
            .values(
                status=AgentJobStatus.failed,
                completed_at=now,
                error_message="Session closed during service restart cleanup",
                stop_category=SessionStopCategory.functional_failure,
                termination_category=AgentTerminationCategory.policy_blocked,
            )
        )
        return int(result.rowcount or 0)
