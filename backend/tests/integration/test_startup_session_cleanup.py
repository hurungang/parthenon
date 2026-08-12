from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason='Requires running services (CC, AR, or CH)')

import uuid

import pytest

from app.db.models.agents import (
    AgentInputType,
    AgentJob,
    AgentJobStatus,
    AgentOutputType,
    AgentType,
    SessionStopCategory,
)
from app.services.agents.session_recovery_service import SessionRecoveryService


async def _create_agent_type(db_session, suffix: str) -> AgentType:
    agent_type = AgentType(
        name=f"cleanup-agent-{suffix}",
        model_id="gpt-4o-mini",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
    )
    db_session.add(agent_type)
    await db_session.flush()
    return agent_type


@pytest.mark.asyncio
async def test_startup_cleanup_marks_queued_and_running_as_failed(db_session):
    suffix = uuid.uuid4().hex[:8]
    agent_type = await _create_agent_type(db_session, suffix)

    queued = AgentJob(agent_type_id=agent_type.id, status=AgentJobStatus.queued, input_data={})
    running = AgentJob(agent_type_id=agent_type.id, status=AgentJobStatus.running, input_data={})
    completed = AgentJob(agent_type_id=agent_type.id, status=AgentJobStatus.completed, input_data={})
    db_session.add_all([queued, running, completed])
    await db_session.flush()

    changed = await SessionRecoveryService().cleanup_non_terminal_sessions(db_session)
    await db_session.flush()

    assert changed == 2

    await db_session.refresh(queued)
    await db_session.refresh(running)
    await db_session.refresh(completed)

    refreshed_queued = queued
    refreshed_running = running
    refreshed_completed = completed

    assert refreshed_queued is not None
    assert refreshed_running is not None
    assert refreshed_completed is not None

    assert refreshed_queued.status == AgentJobStatus.failed
    assert refreshed_running.status == AgentJobStatus.failed
    assert refreshed_queued.stop_category == SessionStopCategory.functional_failure
    assert refreshed_running.stop_category == SessionStopCategory.functional_failure
    assert refreshed_queued.completed_at is not None
    assert refreshed_running.completed_at is not None
    assert refreshed_completed.status == AgentJobStatus.completed
