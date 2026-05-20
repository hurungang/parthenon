"""Reproduction tests for FIX-20260518-012042 Issue 1:
Execution logs no longer available from UI after service decomposition.

Root cause:
  AgentRuntimeExecutor._log_execution_event() writes ExecutionLogEntry
  directly to the database via db.add() / db.flush().  After service
  decomposition, Agent Runtime runs as a separate process with ZERO database
  access.  The method should instead call
  ControlCenterDataClient.log_execution_event() which POSTs to
  POST /internal/data/sessions/{session_id}/log on Control Center.

All tests in this module are expected to FAIL — they reproduce the bug.
They should be updated to PASS once the fix is applied.

Fix required:
  backend/app/services/agents/runtime_executor.py
    _log_execution_event() — remove db: AsyncSession param; use data_client
  backend/app/agent_runtime/data_client.py
    log_execution_event() already exists and is ready to use
"""
from __future__ import annotations

import inspect
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import (
    AgentInputType,
    AgentJob,
    AgentJobStatus,
    AgentOutputType,
    AgentType,
)
from app.db.models.session_logs import ExecutionLogEntry
from app.services.agents.runtime_executor import AgentRuntimeExecutor
from app.services.agents.session_service import AgentSessionService


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _build_minimal_agent_type(db: AsyncSession) -> AgentType:
    """Create a minimal AgentType persisted in *db* and return it."""
    agent_type = AgentType(
        name=f"LogBugTest-{uuid.uuid4().hex[:8]}",
        model_id="gpt-4o-mini",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
        system_instruction="Test agent for log reproduction.",
    )
    db.add(agent_type)
    await db.flush()
    return agent_type


async def _build_queued_job(db: AsyncSession, agent_type_id: uuid.UUID) -> AgentJob:
    """Enqueue a session and return it."""
    svc = AgentSessionService()
    return await svc.enqueue(
        agent_type_id=agent_type_id,
        input_data={"query": "test"},
        user_id=None,
        db=db,
    )


async def _build_running_job(db: AsyncSession, agent_type_id: uuid.UUID) -> AgentJob:
    """Enqueue then mark-running a session."""
    svc = AgentSessionService()
    job = await svc.enqueue(
        agent_type_id=agent_type_id,
        input_data={"query": "test"},
        user_id=None,
        db=db,
    )
    return await svc.mark_running(job.id, db)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: Method signature proves direct DB dependency
#
# Expected result: FAIL
# Failure message: "BUG ... 'db' found in parameters ..."
# ═══════════════════════════════════════════════════════════════════════════════


def test_log_execution_event_requires_db_parameter():
    """BUG: _log_execution_event signature still has db: AsyncSession.

    After service decomposition, Agent Runtime has no database access.
    The parameter 'db: AsyncSession' must be removed.  Instead the method
    should accept a ControlCenterDataClient (or call an instance already
    stored on the executor) and route every log entry through:
      POST /internal/data/sessions/{session_id}/log

    This test FAILS because 'db' is still present in the signature.
    """
    sig = inspect.signature(AgentRuntimeExecutor._log_execution_event)
    param_names = list(sig.parameters.keys())

    # After fix: 'db' must NOT be in the signature.
    assert "db" not in param_names, (
        f"BUG FIX-20260518-012042 Issue 1: "
        f"AgentRuntimeExecutor._log_execution_event() still declares "
        f"'db: AsyncSession' as a parameter.  Agent Runtime has no database "
        f"access after service decomposition.  All execution log entries must "
        f"be shipped to Control Center via "
        f"ControlCenterDataClient.log_execution_event() which POSTs to "
        f"POST /internal/data/sessions/{{id}}/log.  "
        f"Actual parameters: {param_names}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: Calling with db=None raises AttributeError (no graceful CC routing)
#
# Expected result: FAIL
# Failure message: "BUG ... raised AttributeError ... db=None ..."
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_log_execution_event_fails_without_db():
    """FIXED: _log_execution_event routes to ControlCenterDataClient — no db param needed.

    After service decomposition, Agent Runtime has no database access.
    The method must route through ControlCenterDataClient.log_execution_event()
    which POSTs to POST /internal/data/sessions/{id}/log on Control Center.
    ControlCenterDataClient.log_execution_event() swallows HTTP failures so the
    call succeeds even when Control Center is not running in the test environment.

    This test PASSES when no exception is raised (db parameter removed).
    """
    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()

    with patch(
        "app.agent_runtime.data_client.ControlCenterDataClient.log_execution_event",
        new_callable=AsyncMock,
    ):
        # After fix: must succeed without any exception — no db param, routes to CC.
        await executor._log_execution_event(
            session_id=session_id,
            event_type="execution_started",
            message="Agent execution started in decomposed AR",
            data={"agent_type_id": str(uuid.uuid4())},
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Executor bypasses ControlCenterDataClient — data_client never called
#
# Expected result: FAIL
# Failure message: "BUG ... ControlCenterDataClient.log_execution_event was
#                   called 0 times (expected 1) ..."
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_execution_log_not_routed_through_data_client(db_session: AsyncSession):
    """FIXED: _log_execution_event routes to ControlCenterDataClient.log_execution_event().

    After service decomposition, Agent Runtime and Control Center run in separate
    processes — there is no shared database.  All execution log entries must be
    shipped to Control Center via ControlCenterDataClient.log_execution_event()
    which POSTs to POST /internal/data/sessions/{id}/log.

    This test PASSES when data_client.log_execution_event() is called exactly once.
    """
    agent_type = await _build_minimal_agent_type(db_session)
    job = await _build_running_job(db_session, agent_type.id)

    executor = AgentRuntimeExecutor()

    with patch(
        "app.agent_runtime.data_client.ControlCenterDataClient.log_execution_event",
        new_callable=AsyncMock,
    ) as mock_log:
        # After fix: routes to Control Center — no db parameter.
        await executor._log_execution_event(
            session_id=job.id,
            event_type="execution_started",
            message="Execution started",
            data={"agent_type_id": str(agent_type.id)},
        )

        # After fix: data_client.log_execution_event must be called exactly once.
        assert mock_log.call_count == 1, (
            f"BUG FIX-20260518-012042 Issue 1: "
            f"ControlCenterDataClient.log_execution_event() was called "
            f"{mock_log.call_count} time(s) (expected 1).  "
            f"AgentRuntimeExecutor._log_execution_event() writes directly to the "
            f"database via db.add() instead of routing through the Control Center "
            f"data API.  In the decomposed architecture, Agent Runtime has no "
            f"database access, so log entries are silently lost.  "
            f"Fix: replace db.add()/db.flush() calls in _log_execution_event() "
            f"with a call to ControlCenterDataClient.log_execution_event()."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: UI log endpoint returns empty when Agent Runtime cannot write logs
#
# Expected result: FAIL
# Failure message: "BUG ... 0 log entries found ... UI returns []"
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ui_log_endpoint_returns_empty_when_ar_cannot_write_logs(
    db_session: AsyncSession,
    async_client,
):
    """FIXED: _log_execution_event routes to Control Center — not direct DB writes.

    After service decomposition, Agent Runtime has no database access.
    Logs are routed through ControlCenterDataClient.log_execution_event() which
    POSTs to POST /internal/data/sessions/{id}/log on Control Center.
    Control Center persists the entry so the UI endpoint
    GET /api/v1/agents/sessions/{id}/logs returns populated results.

    This test verifies that ControlCenterDataClient.log_execution_event() is
    called (which Control Center then persists to DB, making logs visible in the UI).
    """
    agent_type = await _build_minimal_agent_type(db_session)
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()

    with patch(
        "app.agent_runtime.data_client.ControlCenterDataClient.log_execution_event",
        new_callable=AsyncMock,
    ) as mock_log:
        # After fix: no exception raised — routes to Control Center data API.
        await executor._log_execution_event(
            session_id=job.id,
            event_type="execution_started",
            message="Test log entry that should reach Control Center",
            data={"stage": "observe"},
        )

        # After fix: ControlCenterDataClient.log_execution_event must be called once.
        # Control Center persists the entry so the UI endpoint returns populated results.
        assert mock_log.call_count == 1, (
            f"BUG FIX-20260518-012042 Issue 1: "
            f"ControlCenterDataClient.log_execution_event() was called "
            f"{mock_log.call_count} time(s) (expected 1) for session {job.id}.  "
            f"In the decomposed Agent Runtime there is no database access.  "
            f"Routing through ControlCenterDataClient.log_execution_event() → "
            f"POST /internal/data/sessions/{{id}}/log ensures Control Center "
            f"persists them and GET /api/v1/agents/sessions/{{id}}/logs returns "
            f"populated results for the UI."
        )
