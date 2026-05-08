"""Integration tests verifying execution log completeness for the agent runtime.

These tests exercise AgentRuntimeExecutor end-to-end against a real (SQLite)
in-memory database and assert exactly which fields ARE and ARE NOT captured in
execution logs.

KNOWN GAPS documented by this test suite:
  GAP-1  SOPs/Skills assigned to the agent role are NOT visible in logs.
         The ``tools_resolved`` event records only flat MCP tool names derived
         from role permissions.  The higher-level SOP/Skill names that form the
         agent's capability are never logged.

  GAP-2  ``save_result`` is NOT emitted as a tool_call execution log entry.
         ``_persist_result()`` writes a ``ResultRecord`` directly to the DB and
         never calls ``_log_execution_event``.  Operators cannot tell from logs
         alone whether the result was persisted.

  GAP-3  Prompt information (system_instruction, user_prompt) and execution
         events live in separate DB tables/endpoints:
           - ``AgentPromptLog``      → GET /agents/sessions/{id}/execution-logs
           - ``ExecutionLogEntry``   → GET /agents/sessions/{id}/logs
         Both must be retrieved to reconstruct the full execution trace.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import (
    AgentJob,
    AgentJobStatus,
    AgentInputType,
    AgentOutputType,
    AgentPromptLog,
    AgentRole,
    AgentRoleSOP,
    AgentType,
)
from app.db.models.session_logs import ExecutionLogEntry
from app.db.models.skills import Sop, SopStep, SopStepType
from app.services.agents.runtime_executor import AgentRuntimeExecutor
from app.services.agents.session_service import AgentSessionService


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _build_minimal_agent_type(
    db: AsyncSession,
    *,
    system_instruction: str = "You are a helpful assistant.",
    role_id: uuid.UUID | None = None,
) -> AgentType:
    """Create a minimal AgentType persisted in *db* and return it."""
    agent_type = AgentType(
        name=f"LogTest-{uuid.uuid4().hex[:8]}",
        model_id="gpt-4o-mini",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
        system_instruction=system_instruction,
        role_id=role_id,
    )
    db.add(agent_type)
    await db.flush()
    return agent_type


async def _build_running_job(
    db: AsyncSession,
    agent_type_id: uuid.UUID,
    input_data: dict | None = None,
) -> AgentJob:
    """Enqueue then mark-running a session for *agent_type_id*."""
    session_service = AgentSessionService()
    job = await session_service.enqueue(
        agent_type_id=agent_type_id,
        input_data=input_data or {"query": "What is the current database name?"},
        user_id=None,
        db=db,
    )
    job = await session_service.mark_running(job.id, db)
    await db.flush()
    return job


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def agent_type_with_sop(db_session: AsyncSession):
    """AgentType bound to a role that has one SOP attached."""
    # Create a minimal SOP
    sop = Sop(
        name=f"TestSOP-{uuid.uuid4().hex[:8]}",
        description="Use supabase tool to get database name",
    )
    db_session.add(sop)
    await db_session.flush()

    # Create a role and link the SOP to it
    role = AgentRole(
        name=f"TestRole-{uuid.uuid4().hex[:8]}",
        description="Role for log completeness testing",
    )
    db_session.add(role)
    await db_session.flush()

    sop_binding = AgentRoleSOP(role_id=role.id, sop_id=sop.id)
    db_session.add(sop_binding)
    await db_session.flush()

    # Create AgentType referencing the role
    agent_type = await _build_minimal_agent_type(
        db_session,
        system_instruction="Use the supabase tool to get the current database name.",
        role_id=role.id,
    )
    return agent_type, role, sop


# ── Tests: Prompt log (system instruction + user prompt) ──────────────────────


@pytest.mark.asyncio
async def test_prompt_log_captures_system_instruction(db_session: AsyncSession):
    """AgentPromptLog must persist the full system_instruction before the first LLM call."""
    expected_instruction = "You are a database inspector assistant."
    agent_type = await _build_minimal_agent_type(
        db_session, system_instruction=expected_instruction
    )
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(AgentPromptLog).where(AgentPromptLog.session_id == job.id)
    )
    log_entries = result.scalars().all()

    assert len(log_entries) >= 1, (
        "FAIL: No AgentPromptLog row was written. "
        "_capture_prompt_log() was not called before the first LLM iteration."
    )
    assert log_entries[0].system_instruction == expected_instruction, (
        f"FAIL: system_instruction mismatch. "
        f"Expected: {expected_instruction!r}  "
        f"Got: {log_entries[0].system_instruction!r}"
    )


@pytest.mark.asyncio
async def test_prompt_log_captures_user_prompt(db_session: AsyncSession):
    """AgentPromptLog must persist the user prompt derived from job.input_data."""
    agent_type = await _build_minimal_agent_type(db_session)
    job = await _build_running_job(
        db_session,
        agent_type.id,
        input_data={"query": "What is the current database name?"},
    )
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(AgentPromptLog).where(AgentPromptLog.session_id == job.id)
    )
    log_entries = result.scalars().all()

    assert len(log_entries) >= 1, (
        "FAIL: No AgentPromptLog row written — user prompt not captured."
    )
    captured_prompt = log_entries[0].user_prompt
    assert captured_prompt is not None, (
        "FAIL: AgentPromptLog.user_prompt is None. "
        "_format_user_prompt() returned None or _capture_prompt_log() received None."
    )
    assert "database" in captured_prompt.lower(), (
        f"FAIL: Expected user prompt to contain 'database'. Got: {captured_prompt!r}"
    )


@pytest.mark.asyncio
async def test_prompt_log_table_is_populated(db_session: AsyncSession):
    """The execution_logs table (AgentPromptLog) must have a row after execution."""
    agent_type = await _build_minimal_agent_type(db_session)
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(AgentPromptLog).where(AgentPromptLog.session_id == job.id)
    )
    rows = result.scalars().all()
    assert len(rows) >= 1, (
        "FAIL: execution_logs table (AgentPromptLog) has no rows for this session. "
        "Prompt logging is broken."
    )


# ── Tests: Execution event log (observe-reason-act iterations) ────────────────


@pytest.mark.asyncio
async def test_execution_log_contains_session_started_event(db_session: AsyncSession):
    """ExecutionLogEntry must contain a session_started event."""
    agent_type = await _build_minimal_agent_type(db_session)
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .where(ExecutionLogEntry.event_type == "session_started")
    )
    entries = result.scalars().all()

    assert len(entries) >= 1, (
        "FAIL: No session_started event found in execution_log_entries. "
        "_execute_job() did not emit the session_started log event."
    )


@pytest.mark.asyncio
async def test_execution_log_contains_tools_resolved_event(db_session: AsyncSession):
    """ExecutionLogEntry must contain a tools_resolved event with allowed_tools."""
    agent_type = await _build_minimal_agent_type(db_session)
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .where(ExecutionLogEntry.event_type == "tools_resolved")
    )
    entries = result.scalars().all()

    assert len(entries) >= 1, (
        "FAIL: No tools_resolved event found. "
        "AgentPermissionManager result is not being logged."
    )
    data = entries[0].data
    assert "allowed_tools" in data, (
        f"FAIL: tools_resolved.data missing 'allowed_tools' key. Got: {data}"
    )


@pytest.mark.asyncio
async def test_execution_log_contains_observe_events(db_session: AsyncSession):
    """ExecutionLogEntry must contain at least one observe event (ORA loop running)."""
    agent_type = await _build_minimal_agent_type(db_session)
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .where(ExecutionLogEntry.event_type == "observe")
    )
    entries = result.scalars().all()

    assert len(entries) >= 1, (
        "FAIL: No observe events found. "
        "The observe-reason-act loop is not executing — "
        "_run_task_loop() may not be calling _observe()."
    )


@pytest.mark.asyncio
async def test_execution_log_contains_llm_call_events(db_session: AsyncSession):
    """ExecutionLogEntry must contain at least one llm_request event (reason phase running)."""
    agent_type = await _build_minimal_agent_type(db_session)
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .where(ExecutionLogEntry.event_type == "llm_request")
    )
    entries = result.scalars().all()

    assert len(entries) >= 1, (
        "FAIL: No llm_request events found. "
        "The reason phase is not executing — "
        "_run_task_loop() may not be calling _reason()."
    )
    data = entries[0].data
    assert "model_id" in data, (
        f"FAIL: llm_request.data missing 'model_id'. Got: {data}"
    )


@pytest.mark.asyncio
async def test_execution_log_contains_session_completed_event(db_session: AsyncSession):
    """ExecutionLogEntry must contain a session_completed event on success."""
    agent_type = await _build_minimal_agent_type(db_session)
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .where(ExecutionLogEntry.event_type == "session_completed")
    )
    entries = result.scalars().all()

    assert len(entries) >= 1, (
        "FAIL: No session_completed event found. "
        "run() did not emit the session_completed log event after mark_completed()."
    )


@pytest.mark.asyncio
async def test_execution_log_ordered_chronologically(db_session: AsyncSession):
    """All ExecutionLogEntry rows for a session must appear in timestamp order."""
    agent_type = await _build_minimal_agent_type(db_session)
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .order_by(ExecutionLogEntry.timestamp)
    )
    entries = result.scalars().all()

    assert len(entries) >= 3, (
        f"Expected at least 3 log events (started, observe, llm_request). "
        f"Got {len(entries)}: {[e.event_type for e in entries]}"
    )

    # Verify event ordering: session_started comes before observe, observe before llm_request
    event_types = [e.event_type for e in entries]
    assert "session_started" in event_types, "session_started event missing"
    assert "observe" in event_types, "observe event missing"
    assert "llm_request" in event_types, "llm_request event missing"

    started_idx = next(i for i, t in enumerate(event_types) if t == "session_started")
    observe_idx = next(i for i, t in enumerate(event_types) if t == "observe")
    llm_idx = next(i for i, t in enumerate(event_types) if t == "llm_request")

    assert started_idx < observe_idx, (
        f"session_started ({started_idx}) must come before observe ({observe_idx})"
    )
    assert observe_idx < llm_idx, (
        f"observe ({observe_idx}) must come before llm_request ({llm_idx})"
    )


# ── Tests: GAP documentation — missing log data ───────────────────────────────


@pytest.mark.asyncio
async def test_gap1_sops_not_visible_in_execution_logs(
    db_session: AsyncSession, agent_type_with_sop
):
    """GAP-1: SOP/Skill names assigned to the agent role are NOT captured in logs.

    The ``tools_resolved`` event only shows flat MCP tool permission names.
    The SOP name is never logged — operators cannot tell from execution logs which
    SOPs guided the agent's behaviour.

    FIX REQUIRED: _execute_job() should emit a dedicated ``sops_loaded`` or
    ``skills_loaded`` event listing the SOP/Skill names (and IDs) attached to the
    role before the first LLM call.
    """
    agent_type, role, sop = agent_type_with_sop
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry).where(ExecutionLogEntry.session_id == job.id)
    )
    all_entries = result.scalars().all()

    # GAP-1 FIX: sops_skills_loaded event must reference the SOP name
    sop_name = sop.name
    entries_with_sop = [
        e for e in all_entries
        if sop_name in (e.message or "") or sop_name in str(e.data)
    ]

    assert len(entries_with_sop) >= 1, (
        f"GAP-1 NOT FIXED: SOP name '{sop_name}' (id={sop.id}) assigned to role "
        f"'{role.name}' (id={role.id}) is NOT visible in any execution log entry. "
        "_log_sops_skills() must emit a sops_skills_loaded event before the first LLM call."
    )

    # Verify the event type is correct
    sops_loaded_entries = [
        e for e in all_entries if e.event_type == "sops_skills_loaded"
    ]
    assert len(sops_loaded_entries) >= 1, (
        "No sops_skills_loaded event found. Expected _log_sops_skills() to emit one."
    )
    data = sops_loaded_entries[0].data
    assert "sops" in data, f"sops_skills_loaded.data missing 'sops' key. Got: {data}"
    assert "skills" in data, f"sops_skills_loaded.data missing 'skills' key. Got: {data}"
    assert any(s["name"] == sop_name for s in data["sops"]), (
        f"SOP '{sop_name}' not found in sops_skills_loaded.data['sops']: {data['sops']}"
    )


@pytest.mark.asyncio
async def test_gap2_save_result_not_logged_as_tool_call(db_session: AsyncSession):
    """GAP-2: save_result persistence is NOT emitted as a tool_call event.

    _persist_result() writes a ResultRecord directly to the database but never
    calls _log_execution_event().  The save_result action is invisible in the
    execution log stream.

    FIX REQUIRED: _persist_result() should emit a ``tool_call`` or dedicated
    ``save_result`` execution log event after the ResultRecord is successfully
    written, including the record ID and payload summary.
    """
    agent_type = await _build_minimal_agent_type(db_session)
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .where(ExecutionLogEntry.event_type.in_(["tool_call", "save_result"]))
    )
    tool_call_entries = result.scalars().all()

    save_result_entries = [
        e for e in tool_call_entries
        if "save_result" in e.message or "save_result" in str(e.data)
    ]

    # GAP-2 FIX: _persist_result() must emit a save_result log event
    assert len(save_result_entries) >= 1, (
        "GAP-2 NOT FIXED: No tool_call or save_result event was emitted when "
        "_persist_result() wrote the ResultRecord. "
        "_persist_result() must call _log_execution_event with event_type='save_result'."
    )

    # Verify the save_result event (not the tool_call dispatch event) contains metadata
    save_result_typed = [e for e in save_result_entries if e.event_type == "save_result"]
    assert save_result_typed, (
        "save_result entries found but none have event_type='save_result'. "
        f"Types present: {[e.event_type for e in save_result_entries]}"
    )
    data = save_result_typed[0].data
    assert "output_keys" in data, (
        f"save_result event missing 'output_keys' in data. Got: {data}"
    )


@pytest.mark.asyncio
async def test_gap3_prompt_and_execution_logs_are_separate_tables(db_session: AsyncSession):
    """GAP-3: system_instruction/user_prompt live in a separate table from event logs.

    AgentPromptLog  → table ``execution_logs``      → endpoint /execution-logs
    ExecutionLogEntry → table ``execution_log_entries`` → endpoint /logs

    A client must query BOTH endpoints to reconstruct the full execution trace.
    This is architecturally awkward and easy to miss.

    NOTE: This is a design observation, not necessarily a bug.  The gap is
    documented here so future work can consider consolidating or cross-linking
    the two tables.
    """
    agent_type = await _build_minimal_agent_type(
        db_session, system_instruction="You are a database inspector."
    )
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    # Verify both tables are populated
    prompt_result = await db_session.execute(
        select(AgentPromptLog).where(AgentPromptLog.session_id == job.id)
    )
    prompt_logs = prompt_result.scalars().all()

    event_result = await db_session.execute(
        select(ExecutionLogEntry).where(ExecutionLogEntry.session_id == job.id)
    )
    event_logs = event_result.scalars().all()

    assert len(prompt_logs) >= 1, (
        "execution_logs (AgentPromptLog) table has no rows — prompt logging broken."
    )
    assert len(event_logs) >= 1, (
        "execution_log_entries (ExecutionLogEntry) table has no rows — event logging broken."
    )

    # GAP-3 FIX: system_instruction must also appear in a prompt_captured
    # ExecutionLogEntry so clients can reconstruct the full trace from one table.
    system_instruction = "You are a database inspector."
    event_logs_with_instruction = [
        e for e in event_logs if system_instruction in str(e.data)
    ]

    assert len(event_logs_with_instruction) >= 1, (
        "GAP-3 NOT FIXED: system_instruction not found in any ExecutionLogEntry. "
        "_capture_prompt_log() must emit a 'prompt_captured' ExecutionLogEntry "
        "whose data includes system_instruction so the full trace is visible "
        "from the execution_log_entries table alone."
    )

    # Verify a prompt_captured event exists with the right structure
    prompt_captured_entries = [e for e in event_logs if e.event_type == "prompt_captured"]
    assert len(prompt_captured_entries) >= 1, (
        "No prompt_captured event in execution_log_entries. "
        "_capture_prompt_log() must emit this event."
    )
    pc_data = prompt_captured_entries[0].data
    assert "system_instruction" in pc_data, (
        f"prompt_captured.data missing 'system_instruction'. Got: {pc_data}"
    )
    assert "user_prompt" in pc_data, (
        f"prompt_captured.data missing 'user_prompt'. Got: {pc_data}"
    )


# ── Tests: Full execution trace completeness ──────────────────────────────────


@pytest.mark.asyncio
async def test_full_execution_trace_contains_all_required_fields(db_session: AsyncSession):
    """Full execution trace must contain: system_instruction, user_prompt,
    session_started, tools_resolved, observe, llm_call, session_completed events.

    This is the master coverage assertion — all required log components in one test.
    """
    expected_instruction = "You are a test agent for log coverage."
    expected_query = "Perform log coverage test"

    agent_type = await _build_minimal_agent_type(
        db_session, system_instruction=expected_instruction
    )
    job = await _build_running_job(
        db_session,
        agent_type.id,
        input_data={"query": expected_query},
    )
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    # 1. Prompt log: system_instruction and user_prompt
    prompt_result = await db_session.execute(
        select(AgentPromptLog).where(AgentPromptLog.session_id == job.id)
    )
    prompt_logs = prompt_result.scalars().all()

    assert len(prompt_logs) >= 1, "MISSING: AgentPromptLog row not written"
    assert prompt_logs[0].system_instruction == expected_instruction, (
        f"MISSING/WRONG: system_instruction. "
        f"Expected {expected_instruction!r}, got {prompt_logs[0].system_instruction!r}"
    )
    assert prompt_logs[0].user_prompt is not None, "MISSING: user_prompt is None"

    # 2. Execution events
    event_result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .order_by(ExecutionLogEntry.timestamp)
    )
    event_logs = event_result.scalars().all()
    event_types = {e.event_type for e in event_logs}

    required_events = {"session_started", "tools_resolved", "observe", "llm_request"}
    missing_events = required_events - event_types
    assert not missing_events, (
        f"MISSING execution log events: {missing_events}. "
        f"Events present: {event_types}"
    )

    # session_completed or error must be present
    terminal_events = {"session_completed", "error"}
    assert event_types & terminal_events, (
        f"MISSING terminal event (session_completed or error). "
        f"Events present: {event_types}"
    )


# ── Tests: none-input auto-prompt generation ──────────────────────────────────


@pytest.mark.asyncio
async def test_no_input_agent_auto_generates_sop_prompt(db_session: AsyncSession):
    """Agent with input_type=none and primary_sop_id must auto-generate a SOP prompt."""
    sop_name = "Get Supabase Info"
    sop = Sop(name=sop_name, description="Retrieve database info via Supabase tool")
    db_session.add(sop)
    await db_session.flush()

    role = AgentRole(name=f"NoInputRole-{uuid.uuid4().hex[:8]}", description="No-input role")
    db_session.add(role)
    await db_session.flush()

    db_session.add(AgentRoleSOP(role_id=role.id, sop_id=sop.id))
    await db_session.flush()

    agent_type = AgentType(
        name=f"NoInputAgent-{uuid.uuid4().hex[:8]}",
        model_id="gpt-4o-mini",
        input_type=AgentInputType.none,
        output_type=AgentOutputType.auto,
        system_instruction="You follow SOPs automatically.",
        role_id=role.id,
        primary_sop_id=sop.id,
    )
    db_session.add(agent_type)
    await db_session.flush()

    session_service = AgentSessionService()
    job = await session_service.enqueue(
        agent_type_id=agent_type.id,
        input_data={},
        user_id=None,
        db=db_session,
    )
    job = await session_service.mark_running(job.id, db_session)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    # Verify AgentPromptLog captures the auto-generated SOP prompt
    prompt_result = await db_session.execute(
        select(AgentPromptLog).where(AgentPromptLog.session_id == job.id)
    )
    prompt_logs = prompt_result.scalars().all()
    assert len(prompt_logs) >= 1, "No AgentPromptLog row written for none-input agent."

    expected_prompt = f"Follow the SOP '{sop_name}' to complete the task"
    assert prompt_logs[0].user_prompt == expected_prompt, (
        f"Expected auto-generated prompt: {expected_prompt!r}\n"
        f"Got: {prompt_logs[0].user_prompt!r}"
    )

    # Verify the prompt_captured ExecutionLogEntry also reflects the SOP prompt
    prompt_captured_result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .where(ExecutionLogEntry.event_type == "prompt_captured")
    )
    prompt_captured_entries = prompt_captured_result.scalars().all()
    assert len(prompt_captured_entries) >= 1, "No prompt_captured event found."
    assert prompt_captured_entries[0].data.get("user_prompt") == expected_prompt, (
        f"prompt_captured.data['user_prompt'] does not match expected SOP prompt.\n"
        f"Expected: {expected_prompt!r}\n"
        f"Got: {prompt_captured_entries[0].data.get('user_prompt')!r}"
    )


@pytest.mark.asyncio
async def test_no_input_agent_with_primary_sop_uses_correct_prompt(db_session: AsyncSession):
    """Agent with input_type=none must use primary_sop_id, not just the first role SOP."""
    sop_first = Sop(name=f"FirstSop-{uuid.uuid4().hex[:8]}", description="First SOP in role")
    sop_primary = Sop(name=f"PrimarySop-{uuid.uuid4().hex[:8]}", description="Explicitly assigned primary SOP")
    db_session.add_all([sop_first, sop_primary])
    await db_session.flush()

    role = AgentRole(name=f"MultiSopRole-{uuid.uuid4().hex[:8]}", description="Role with multiple SOPs")
    db_session.add(role)
    await db_session.flush()

    # Add both SOPs to the role; sop_first is added first
    db_session.add(AgentRoleSOP(role_id=role.id, sop_id=sop_first.id))
    db_session.add(AgentRoleSOP(role_id=role.id, sop_id=sop_primary.id))
    await db_session.flush()

    # primary_sop_id points to sop_primary, NOT sop_first
    agent_type = AgentType(
        name=f"PrimarySOPAgent-{uuid.uuid4().hex[:8]}",
        model_id="gpt-4o-mini",
        input_type=AgentInputType.none,
        output_type=AgentOutputType.auto,
        system_instruction="You follow SOPs automatically.",
        role_id=role.id,
        primary_sop_id=sop_primary.id,
    )
    db_session.add(agent_type)
    await db_session.flush()

    session_service = AgentSessionService()
    job = await session_service.enqueue(
        agent_type_id=agent_type.id,
        input_data={},
        user_id=None,
        db=db_session,
    )
    job = await session_service.mark_running(job.id, db_session)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    prompt_result = await db_session.execute(
        select(AgentPromptLog).where(AgentPromptLog.session_id == job.id)
    )
    prompt_logs = prompt_result.scalars().all()
    assert len(prompt_logs) >= 1, "No AgentPromptLog row written for none-input agent."

    expected_prompt = f"Follow the SOP '{sop_primary.name}' to complete the task"
    wrong_prompt = f"Follow the SOP '{sop_first.name}' to complete the task"
    assert prompt_logs[0].user_prompt == expected_prompt, (
        f"Expected prompt using primary SOP: {expected_prompt!r}\n"
        f"Got: {prompt_logs[0].user_prompt!r}\n"
        f"(Wrong if it used first role SOP instead: {wrong_prompt!r})"
    )


# ── Fixture: AgentType with primary_sop_id and SOP steps ──────────────────────


@pytest_asyncio.fixture
async def agent_type_with_primary_sop(db_session: AsyncSession):
    """AgentType with primary_sop_id set and multi-step SOP for full-trace tests."""
    sop = Sop(
        name=f"FullTraceSOP-{uuid.uuid4().hex[:8]}",
        description="A test SOP for full execution trace verification",
        instructions="Always save the final result using the save_result tool.",
    )
    db_session.add(sop)
    await db_session.flush()

    step1 = SopStep(
        sop_id=sop.id,
        order=0,
        step_type=SopStepType.skill_invocation,
        name="Gather information",
        description="Collect the required information from available tools",
    )
    step2 = SopStep(
        sop_id=sop.id,
        order=1,
        step_type=SopStepType.skill_invocation,
        name="Save result",
        description="Persist the findings using the save_result tool",
    )
    db_session.add_all([step1, step2])
    await db_session.flush()

    agent_type = AgentType(
        name=f"FullTraceAgent-{uuid.uuid4().hex[:8]}",
        model_id="gpt-4o-mini",
        input_type=AgentInputType.typed,
        output_type=AgentOutputType.auto,
        system_instruction="You are a test agent. Follow the SOP carefully.",
        primary_sop_id=sop.id,
    )
    db_session.add(agent_type)
    await db_session.flush()

    return agent_type, sop


# ── Tests: Full trace with SOP, LLM request/response, and tool call logging ───


@pytest.mark.asyncio
async def test_sop_content_loaded_into_execution_log(
    db_session: AsyncSession, agent_type_with_primary_sop
):
    """sop_loaded execution log event must contain the SOP name and steps."""
    agent_type, sop = agent_type_with_primary_sop
    job = await _build_running_job(
        db_session,
        agent_type.id,
        input_data={"query": "Execute the SOP"},
    )
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .where(ExecutionLogEntry.event_type == "sop_loaded")
    )
    entries = result.scalars().all()

    assert len(entries) >= 1, (
        f"MISSING: No sop_loaded event found. "
        f"_run_task_loop() must emit sop_loaded when primary_sop_id is set. "
        f"SOP: '{sop.name}' (id={sop.id})"
    )
    data = entries[0].data
    assert "sop_content" in data, (
        f"sop_loaded event missing 'sop_content' key. Got keys: {list(data.keys())}"
    )
    assert sop.name in data["sop_content"], (
        f"SOP name '{sop.name}' not found in sop_content: {data['sop_content'][:200]}"
    )
    assert "primary_sop_id" in data, "sop_loaded event missing 'primary_sop_id'"
    assert data["primary_sop_id"] == str(sop.id), (
        f"primary_sop_id mismatch. Expected {sop.id}, got {data['primary_sop_id']}"
    )


@pytest.mark.asyncio
async def test_sop_steps_appear_in_sop_content(
    db_session: AsyncSession, agent_type_with_primary_sop
):
    """SOP step names must appear inside the sop_content logged in sop_loaded event."""
    agent_type, sop = agent_type_with_primary_sop
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .where(ExecutionLogEntry.event_type == "sop_loaded")
    )
    entries = result.scalars().all()
    assert entries, "No sop_loaded event found"

    sop_content = entries[0].data.get("sop_content", "")
    # Both step names from the fixture must appear
    assert "Gather information" in sop_content, (
        f"Step 'Gather information' not found in sop_content: {sop_content[:300]}"
    )
    assert "Save result" in sop_content, (
        f"Step 'Save result' not found in sop_content: {sop_content[:300]}"
    )


@pytest.mark.asyncio
async def test_llm_request_event_contains_full_prompt(
    db_session: AsyncSession, agent_type_with_primary_sop
):
    """llm_request event must contain the full messages list and available tools."""
    agent_type, sop = agent_type_with_primary_sop
    job = await _build_running_job(
        db_session,
        agent_type.id,
        input_data={"query": "Check the SOP and act"},
    )
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .where(ExecutionLogEntry.event_type == "llm_request")
    )
    entries = result.scalars().all()
    assert len(entries) >= 1, "No llm_request event found"

    data = entries[0].data
    assert "messages" in data, f"llm_request missing 'messages'. Keys: {list(data.keys())}"
    assert "available_tools" in data, (
        f"llm_request missing 'available_tools'. Keys: {list(data.keys())}"
    )
    assert "save_result" in data["available_tools"], (
        f"save_result not listed in available_tools: {data['available_tools']}"
    )
    # System message must contain SOP content since primary_sop_id is set
    messages = data["messages"]
    assert messages, "llm_request messages list is empty"
    system_messages = [m for m in messages if m.get("role") == "system"]
    assert system_messages, "No system message found in llm_request messages"
    assert sop.name in system_messages[0]["content"], (
        f"SOP name '{sop.name}' not found in system message: "
        f"{system_messages[0]['content'][:300]}"
    )


@pytest.mark.asyncio
async def test_llm_response_event_is_logged(
    db_session: AsyncSession, agent_type_with_primary_sop
):
    """llm_response event must be logged after every LLM call (or stub call)."""
    agent_type, sop = agent_type_with_primary_sop
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .where(ExecutionLogEntry.event_type == "llm_response")
    )
    entries = result.scalars().all()
    assert len(entries) >= 1, (
        "MISSING: No llm_response event. _reason() must log this after every LLM call."
    )
    data = entries[0].data
    # Either real (has response_text/tool_calls) or stub (has stub=True)
    assert "stub" in data or "tool_calls" in data, (
        f"llm_response data missing expected keys. Got: {data}"
    )


@pytest.mark.asyncio
async def test_tool_call_event_logged_for_save_result(
    db_session: AsyncSession, agent_type_with_primary_sop
):
    """tool_call event must be logged when save_result is dispatched by the agent."""
    agent_type, sop = agent_type_with_primary_sop
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .where(ExecutionLogEntry.event_type == "tool_call")
    )
    entries = result.scalars().all()
    assert len(entries) >= 1, (
        "MISSING: No tool_call event. _act() must log each tool dispatch."
    )
    save_result_calls = [e for e in entries if e.data.get("tool") == "save_result"]
    assert save_result_calls, (
        f"No tool_call event for 'save_result'. "
        f"Tools called: {[e.data.get('tool') for e in entries]}"
    )
    data = save_result_calls[0].data
    assert "args" in data, f"tool_call event missing 'args'. Got: {data}"


@pytest.mark.asyncio
async def test_iteration_complete_event_logged(
    db_session: AsyncSession, agent_type_with_primary_sop
):
    """iteration_complete event must be logged after each observe-reason-act cycle."""
    agent_type, sop = agent_type_with_primary_sop
    job = await _build_running_job(db_session, agent_type.id)
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .where(ExecutionLogEntry.event_type == "iteration_complete")
    )
    entries = result.scalars().all()
    assert len(entries) >= 1, (
        "MISSING: No iteration_complete event. "
        "_act() must emit this event after each ORA cycle."
    )
    data = entries[0].data
    assert "iteration" in data, f"iteration_complete missing 'iteration'. Got: {data}"
    assert "tool_calls" in data, f"iteration_complete missing 'tool_calls'. Got: {data}"


@pytest.mark.asyncio
async def test_full_trace_with_sop_all_events_present(
    db_session: AsyncSession, agent_type_with_primary_sop
):
    """Complete execution trace must contain all required events including SOP and tool logging."""
    agent_type, sop = agent_type_with_primary_sop
    job = await _build_running_job(
        db_session,
        agent_type.id,
        input_data={"query": "Full trace verification test"},
    )
    await db_session.commit()

    executor = AgentRuntimeExecutor()
    await executor.run(job.id, db_session)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry)
        .where(ExecutionLogEntry.session_id == job.id)
        .order_by(ExecutionLogEntry.timestamp)
    )
    all_entries = result.scalars().all()
    event_types = {e.event_type for e in all_entries}

    required = {
        "session_started",
        "tools_resolved",
        "sop_loaded",
        "observe",
        "llm_request",
        "llm_response",
        "tool_call",
        "save_result",
        "iteration_complete",
        "session_completed",
    }
    missing = required - event_types
    assert not missing, (
        f"MISSING events in full trace: {missing}\n"
        f"Events present: {sorted(event_types)}"
    )

    # Ordering: session_started → sop_loaded → observe → llm_request → llm_response
    #           → tool_call → save_result → iteration_complete → session_completed
    ordered_types = [e.event_type for e in all_entries]

    def idx(name: str) -> int:
        return next(i for i, t in enumerate(ordered_types) if t == name)

    assert idx("session_started") < idx("sop_loaded"), "sop_loaded must come after session_started"
    assert idx("sop_loaded") < idx("observe"), "observe must come after sop_loaded"
    assert idx("observe") < idx("llm_request"), "llm_request must come after observe"
    assert idx("llm_request") < idx("llm_response"), "llm_response must come after llm_request"
    assert idx("llm_response") < idx("tool_call"), "tool_call must come after llm_response"
    assert idx("tool_call") < idx("iteration_complete"), (
        "iteration_complete must come after tool_call"
    )
    assert idx("iteration_complete") < idx("session_completed"), (
        "session_completed must come last"
    )

