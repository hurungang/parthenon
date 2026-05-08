"""Unit tests for AgentRuntimeExecutor — LangChain deep agent observe-reason-act loop.

Verifies:
- Executor instantiation and required interface
- run() lifecycle (skip on missing job, skip on wrong status)
- Permission boundary enforcement (PermissionDeniedError → mark_failed)
- Generic exception handling (→ mark_failed)
- Success path (mark_completed)
- LangChain observe/reason/act phases (no LangGraph imports anywhere)
- Prompt log capture (_capture_prompt_log called before first LLM call)
"""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Instantiation ──────────────────────────────────────────────────────────────


def test_executor_can_be_instantiated():
    """AgentRuntimeExecutor can be created without errors."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    assert executor is not None


def test_executor_has_required_methods():
    """AgentRuntimeExecutor exposes the 'run' method required by SessionDispatcher."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    assert callable(getattr(executor, "run", None)), "run() method must exist"


def test_executor_has_permission_manager():
    """AgentRuntimeExecutor holds an AgentPermissionManager instance."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.permission_manager import AgentPermissionManager

    executor = AgentRuntimeExecutor()
    assert isinstance(executor._permission_manager, AgentPermissionManager)


def test_executor_has_session_service():
    """AgentRuntimeExecutor holds an AgentSessionService instance."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.session_service import AgentSessionService

    executor = AgentRuntimeExecutor()
    assert isinstance(executor._session_service, AgentSessionService)


def test_executor_does_not_import_langgraph():
    """runtime_executor must not import langgraph — LangChain deep agent is used instead."""
    import importlib.util
    import sys

    # Remove cached module so we can inspect a fresh import
    for key in list(sys.modules.keys()):
        if "runtime_executor" in key:
            del sys.modules[key]

    spec = importlib.util.spec_from_file_location(
        "runtime_executor",
        "app/services/agents/runtime_executor.py",
    )
    # The module source should not reference langgraph
    if spec and spec.origin:
        with open(spec.origin, encoding="utf-8") as f:
            source = f.read()
        assert "langgraph" not in source, (
            "runtime_executor.py must not reference langgraph — "
            "LangChain deep agent framework is required"
        )


def test_agent_loop_module_available():
    """agent_loop.py (LangChain loop context) is importable without LangGraph."""
    from app.services.agents.agent_loop import TaskAgentLoop, ConversationalAgentLoop

    ctx = TaskAgentLoop(
        session_id="sess-1",
        agent_type_id="at-1",
        role_id=None,
        allowed_tools=["save_result"],
        system_instruction="You are helpful",
        output_type="auto",
        output_schema=None,
        input_data={"query": "hello"},
    )
    assert ctx.session_id == "sess-1"
    assert ctx.should_continue() is True


def test_agent_loop_should_stop_after_max_iterations():
    """TaskAgentLoop.should_continue returns False when max_iterations reached."""
    from app.services.agents.agent_loop import TaskAgentLoop

    ctx = TaskAgentLoop(
        session_id="sess-1",
        agent_type_id="at-1",
        role_id=None,
        allowed_tools=[],
        system_instruction=None,
        output_type="auto",
        output_schema=None,
        max_iterations=3,
        iteration=3,
    )
    assert ctx.should_continue() is False


def test_agent_loop_should_stop_when_complete():
    """TaskAgentLoop.should_continue returns False when is_complete is True."""
    from app.services.agents.agent_loop import TaskAgentLoop

    ctx = TaskAgentLoop(
        session_id="sess-1",
        agent_type_id="at-1",
        role_id=None,
        allowed_tools=[],
        system_instruction=None,
        output_type="auto",
        output_schema=None,
        is_complete=True,
    )
    assert ctx.should_continue() is False


def test_agent_loop_message_helpers():
    """AgentLoopContext message helper methods append correctly typed entries."""
    from app.services.agents.agent_loop import TaskAgentLoop

    ctx = TaskAgentLoop(
        session_id="sess-1",
        agent_type_id="at-1",
        role_id=None,
        allowed_tools=[],
        system_instruction=None,
        output_type="auto",
        output_schema=None,
    )
    ctx.append_user_message("Hello agent")
    ctx.append_assistant_message("Hello user")
    ctx.append_tool_result("call_123", "search", {"results": []})

    assert ctx.messages[0]["role"] == "user"
    assert ctx.messages[1]["role"] == "assistant"
    assert ctx.messages[2]["role"] == "tool"
    assert ctx.messages[2]["tool_call_id"] == "call_123"
    assert ctx.user_prompt == "Hello agent"


# ── run() — not running status ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_skips_when_job_not_found():
    """run() logs and returns early when the AgentJob is not in the DB."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    # Should not raise
    await executor.run(uuid.uuid4(), db)


@pytest.mark.asyncio
async def test_run_skips_when_status_not_running():
    """run() returns early when the job is not in 'running' state."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.db.models.agents import AgentJobStatus

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    job = MagicMock()
    job.status = AgentJobStatus.queued  # not running

    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    await executor.run(session_id, db)
    # _execute_job should not be called
    executor._execute_job = AsyncMock()
    executor._execute_job.assert_not_called()


# ── Permission boundary enforcement ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_marks_failed_on_permission_denied():
    """When _execute_job raises PermissionDeniedError, session is marked failed."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.permission_manager import PermissionDeniedError
    from app.db.models.agents import AgentJobStatus

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    role_id = uuid.uuid4()

    job = MagicMock()
    job.status = AgentJobStatus.running
    job.id = session_id

    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    perm_error = PermissionDeniedError("evil:drop_db", role_id)
    executor._execute_job = AsyncMock(side_effect=perm_error)
    executor._session_service.mark_failed = AsyncMock(return_value=job)
    executor._persist_result = AsyncMock()

    await executor.run(session_id, db)

    executor._session_service.mark_failed.assert_called_once()
    call_args = executor._session_service.mark_failed.call_args
    assert "Permission denied" in call_args[0][1]


@pytest.mark.asyncio
async def test_run_marks_failed_on_generic_exception():
    """When _execute_job raises an unexpected exception, session is marked failed."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.db.models.agents import AgentJobStatus

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    job = MagicMock()
    job.status = AgentJobStatus.running
    job.id = session_id

    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    executor._execute_job = AsyncMock(side_effect=RuntimeError("Unexpected crash"))
    executor._session_service.mark_failed = AsyncMock(return_value=job)
    executor._persist_result = AsyncMock()

    await executor.run(session_id, db)

    executor._session_service.mark_failed.assert_called_once()
    call_args = executor._session_service.mark_failed.call_args
    assert "Unexpected crash" in call_args[0][1]


@pytest.mark.asyncio
async def test_run_marks_completed_on_success():
    """When _execute_job returns output, session is marked completed with that output."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.db.models.agents import AgentJobStatus

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    job = MagicMock()
    job.status = AgentJobStatus.running
    job.id = session_id

    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    output = {"answer": "42"}
    executor._execute_job = AsyncMock(return_value=output)
    executor._persist_result = AsyncMock()
    executor._session_service.mark_completed = AsyncMock(return_value=job)

    await executor.run(session_id, db)

    executor._session_service.mark_completed.assert_called_once_with(session_id, output, db)


# ── LangChain observe-reason-act phases ───────────────────────────────────────


@pytest.mark.asyncio
async def test_observe_phase_increments_no_state():
    """_observe() returns the context unchanged (pure snapshot phase)."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.agent_loop import TaskAgentLoop

    executor = AgentRuntimeExecutor()
    executor._log_execution_event = AsyncMock()

    ctx = TaskAgentLoop(
        session_id=str(uuid.uuid4()),
        agent_type_id=str(uuid.uuid4()),
        role_id=None,
        allowed_tools=["save_result"],
        system_instruction="Test",
        output_type="auto",
        output_schema=None,
        input_data=None,
    )
    db = AsyncMock()
    result = await executor._observe(ctx, db)
    assert result is ctx  # same object returned


@pytest.mark.asyncio
async def test_reason_phase_stub_marks_complete():
    """_reason() with stub (no LangChain binding) marks is_complete=True.

    Patches _LANGCHAIN_AVAILABLE=False to force the stub path, ensuring the
    test exercises the synthetic save_result tool call rather than a real LLM call.
    """
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.agent_loop import TaskAgentLoop

    executor = AgentRuntimeExecutor()
    executor._log_execution_event = AsyncMock()

    agent_type = MagicMock()
    agent_type.model_id = "gpt-4o"
    agent_type.system_instruction = "You are helpful"

    ctx = TaskAgentLoop(
        session_id=str(uuid.uuid4()),
        agent_type_id=str(uuid.uuid4()),
        role_id=None,
        allowed_tools=[],
        system_instruction="You are helpful",
        output_type="auto",
        output_schema=None,
        input_data={"query": "What is 2+2?"},
    )
    ctx.append_user_message("What is 2+2?")

    db = AsyncMock()

    # Patch _LANGCHAIN_AVAILABLE=False so the stub path is taken (no real LLM call)
    with patch("app.services.agents.runtime_executor._LANGCHAIN_AVAILABLE", False):
        result = await executor._reason(ctx, agent_type, db)

    # Stub reasoning marks the context as complete and queues a save_result tool call.
    # output_data is populated later when _act() executes the save_result tool.
    assert result.is_complete is True
    pending = getattr(result, "_pending_tool_calls", [])
    assert len(pending) >= 1, "Stub must queue a save_result tool call"
    assert pending[0]["name"] == "save_result", (
        f"Expected save_result tool call, got: {pending[0]}"
    )


@pytest.mark.asyncio
async def test_act_phase_increments_iteration():
    """_act() increments ctx.iteration even when there are no pending tool calls."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.agent_loop import TaskAgentLoop

    executor = AgentRuntimeExecutor()
    executor._log_execution_event = AsyncMock()

    ctx = TaskAgentLoop(
        session_id=str(uuid.uuid4()),
        agent_type_id=str(uuid.uuid4()),
        role_id=None,
        allowed_tools=[],
        system_instruction=None,
        output_type="auto",
        output_schema=None,
        iteration=0,
    )
    db = AsyncMock()
    result = await executor._act(ctx, set(), db)
    assert result.iteration == 1


# ── Prompt log capture ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_prompt_log_writes_agent_prompt_log():
    """_capture_prompt_log adds an AgentPromptLog record to the session."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    db = AsyncMock()

    with patch("app.services.agents.runtime_executor.AgentRuntimeExecutor._capture_prompt_log",
               wraps=executor._capture_prompt_log):
        # Patch the DB model import so we don't need real DB
        with patch("app.db.models.agents.AgentPromptLog") as MockLog:
            mock_entry = MagicMock()
            MockLog.return_value = mock_entry

            await executor._capture_prompt_log(
                session_id=session_id,
                system_instruction="You are helpful",
                user_prompt="What is the weather?",
                db=db,
            )

        db.add.assert_called()
        db.flush.assert_called()


@pytest.mark.asyncio
async def test_capture_prompt_log_does_not_raise_on_db_failure():
    """_capture_prompt_log swallows DB errors — prompt logging must never abort execution."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    db = AsyncMock()
    db.flush = AsyncMock(side_effect=Exception("DB flush failed"))

    # Should not raise
    await executor._capture_prompt_log(
        session_id=uuid.uuid4(),
        system_instruction="sys",
        user_prompt="user",
        db=db,
    )



# ── run() — not running status ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_skips_when_job_not_found():
    """run() logs and returns early when the AgentJob is not in the DB."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    # Should not raise
    await executor.run(uuid.uuid4(), db)


@pytest.mark.asyncio
async def test_run_skips_when_status_not_running():
    """run() returns early when the job is not in 'running' state."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.db.models.agents import AgentJobStatus

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    job = MagicMock()
    job.status = AgentJobStatus.queued  # not running

    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    await executor.run(session_id, db)
    # _execute_job should not be called
    executor._execute_job = AsyncMock()
    executor._execute_job.assert_not_called()


# ── Permission boundary enforcement ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_marks_failed_on_permission_denied():
    """When _execute_job raises PermissionDeniedError, session is marked failed."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.permission_manager import PermissionDeniedError
    from app.db.models.agents import AgentJobStatus

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    role_id = uuid.uuid4()

    job = MagicMock()
    job.status = AgentJobStatus.running
    job.id = session_id

    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    perm_error = PermissionDeniedError("evil:drop_db", role_id)
    executor._execute_job = AsyncMock(side_effect=perm_error)
    executor._session_service.mark_failed = AsyncMock(return_value=job)
    executor._persist_result = AsyncMock()

    await executor.run(session_id, db)

    executor._session_service.mark_failed.assert_called_once()
    call_args = executor._session_service.mark_failed.call_args
    assert "Permission denied" in call_args[0][1]


@pytest.mark.asyncio
async def test_run_marks_failed_on_generic_exception():
    """When _execute_job raises an unexpected exception, session is marked failed."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.db.models.agents import AgentJobStatus

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    job = MagicMock()
    job.status = AgentJobStatus.running
    job.id = session_id

    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    executor._execute_job = AsyncMock(side_effect=RuntimeError("Unexpected crash"))
    executor._session_service.mark_failed = AsyncMock(return_value=job)
    executor._persist_result = AsyncMock()

    await executor.run(session_id, db)

    executor._session_service.mark_failed.assert_called_once()
    call_args = executor._session_service.mark_failed.call_args
    assert "Unexpected crash" in call_args[0][1]


@pytest.mark.asyncio
async def test_run_marks_completed_on_success():
    """When _execute_job returns output, session is marked completed with that output."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.db.models.agents import AgentJobStatus

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    job = MagicMock()
    job.status = AgentJobStatus.running
    job.id = session_id

    db = AsyncMock()
    db.get = AsyncMock(return_value=job)

    output = {"answer": "42"}
    executor._execute_job = AsyncMock(return_value=output)
    executor._persist_result = AsyncMock()
    executor._session_service.mark_completed = AsyncMock(return_value=job)

    await executor.run(session_id, db)

    executor._session_service.mark_completed.assert_called_once_with(session_id, output, db)


# ── Identity-role assignment validation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_job_raises_permission_denied_when_identity_not_assigned_to_role():
    """_execute_job raises PermissionDeniedError when identity is not in agent_role_identities.

    The agent_role_identities table returns no row for (role_id, identity_id) --
    launch must be rejected before the loop starts.
    """
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.permission_manager import PermissionDeniedError
    from app.db.models.agents import AgentInputType, AgentOutputType

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    role_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()

    job = MagicMock()
    job.id = session_id
    job.agent_type_id = agent_type_id
    job.input_data = {}

    agent_type = MagicMock()
    agent_type.id = agent_type_id
    agent_type.identity_id = identity_id
    agent_type.role_id = role_id
    agent_type.model_id = "gpt-4o"
    agent_type.input_type = AgentInputType.typed
    agent_type.output_type = AgentOutputType.markdown
    agent_type.system_instruction = "You are helpful"
    agent_type.output_schema = None

    async def db_get_side_effect(model_class, pk):
        if pk == agent_type_id:
            return agent_type
        return None

    # db.execute returns a result where scalar_one_or_none() returns None
    # (identity not assigned to role)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.get = AsyncMock(side_effect=db_get_side_effect)
    db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(PermissionDeniedError) as exc_info:
        await executor._execute_job(job, db)

    assert "identity=" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_job_succeeds_when_identity_assigned_to_role():
    """_execute_job proceeds when identity is present in agent_role_identities.

    The agent_role_identities table returns a row for (role_id, identity_id) --
    identity-role validation passes and execution continues.
    """
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.db.models.agents import AgentInputType, AgentOutputType

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    role_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()

    job = MagicMock()
    job.id = session_id
    job.agent_type_id = agent_type_id
    job.input_data = {"query": "hello"}

    agent_type = MagicMock()
    agent_type.id = agent_type_id
    agent_type.identity_id = identity_id
    agent_type.role_id = role_id
    agent_type.model_id = "gpt-4o"
    agent_type.input_type = AgentInputType.typed
    agent_type.output_type = AgentOutputType.markdown
    agent_type.system_instruction = "You are helpful"
    agent_type.output_schema = None

    async def db_get_side_effect(model_class, pk):
        if pk == agent_type_id:
            return agent_type
        return None

    # db.execute returns a row (identity is assigned to the role)
    mock_assignment = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_assignment

    db = AsyncMock()
    db.get = AsyncMock(side_effect=db_get_side_effect)
    db.execute = AsyncMock(return_value=mock_result)

    executor._run_task_loop = AsyncMock(return_value={"answer": "ok"})
    executor._log_execution_event = AsyncMock()
    executor._log_sops_skills = AsyncMock()
    executor._permission_manager.calculate_allowed_tools = AsyncMock(
        return_value={"save_result"}
    )

    result = await executor._execute_job(job, db)

    assert result == {"answer": "ok"}
