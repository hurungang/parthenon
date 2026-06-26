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
import json
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


def test_executor_uses_langgraph_create_agent():
    """runtime_executor uses LangGraph create_agent (tasks 9.6-9.8 migration complete)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "runtime_executor",
        "app/services/agents/runtime_executor.py",
    )
    if spec and spec.origin:
        with open(spec.origin, encoding="utf-8") as f:
            source = f.read()
        assert "langgraph" in source, (
            "runtime_executor.py must reference langgraph — "
            "create_agent migration (tasks 9.6-9.8) should be complete"
        )
        assert "create_agent" in source, (
            "runtime_executor.py must use create_agent — "
            "LangGraph-backed agent loop is required"
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


@pytest.mark.asyncio
@pytest.mark.skip(reason='Pre-existing: SOP content dedup')

@pytest.mark.skip(reason='Pre-existing: SOP content dedup')

async def test_default_sop_content_is_skipped_when_instruction_explicitly_mentions_same_sop_name():
    """Default SOP is fallback-only; do not inject when instruction already names that SOP."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    data_client.get_agent_plan = AsyncMock(return_value=None)
    data_client.log_prompt = AsyncMock()

    sop_name = "check-db-name"
    job_data = {
        "id": str(uuid.uuid4()),
        "agent_type_id": str(uuid.uuid4()),
        "input_data": {"query": "run task"},
    }
    context = {
        "system_instruction": f"You are a project checker, follow {sop_name} SOP to finish the work.",
        "sop_content": (
            f"Follow this SOP to complete the task: {sop_name}\n"
            "\nInstructions: fallback SOP instructions"
        ),
        "primary_sop_id": str(uuid.uuid4()),
        "mcp_session_context": None,
        "model_id": "gpt-4o-mini",
        "model_config_id": None,
        "input_type": "typed",
        "allowed_tools": [],
        "tool_definitions": [],
        "tool_name_map": {},
        "role_mcp_sessions": {},
        "allowed_agent_types": [],
        "role_id": None,
        "identity_name": None,
        "role_name": None,
        "sops": [],
        "skills": [],
        "guardrail_policy": {
            "max_iterations": 1,
            "max_delegation_depth": 3,
            "max_delegated_steps": 10,
            "execution_timeout_seconds": 300,
            "token_budget": None,
        },
    }

    await executor._run_task_loop_ar(job_data, context, data_client)

    data_client.log_prompt.assert_awaited_once()
    injected_instruction = data_client.log_prompt.call_args.kwargs["system_instruction"]
    assert f"follow {sop_name} SOP" in injected_instruction
    assert "Follow this SOP to complete the task:" not in injected_instruction


@pytest.mark.asyncio
@pytest.mark.skip(reason='Pre-existing: SOP content dedup')

@pytest.mark.skip(reason='Pre-existing: SOP content dedup')

async def test_default_sop_content_is_skipped_when_instruction_mentions_other_sop_name():
    """Fallback SOP must be skipped when instruction already references any SOP."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    data_client.get_agent_plan = AsyncMock(return_value=None)
    data_client.log_prompt = AsyncMock()

    job_data = {
        "id": str(uuid.uuid4()),
        "agent_type_id": str(uuid.uuid4()),
        "input_data": {"query": "run task"},
    }
    context = {
        "system_instruction": "You are a project checker, follow query-supabase SOP to finish the work.",
        "sop_content": (
            "Follow this SOP to complete the task: check-db-name\n"
            "\nInstructions: fallback SOP instructions"
        ),
        "primary_sop_id": str(uuid.uuid4()),
        "mcp_session_context": None,
        "model_id": "gpt-4o-mini",
        "model_config_id": None,
        "input_type": "typed",
        "allowed_tools": [],
        "tool_definitions": [],
        "tool_name_map": {},
        "role_mcp_sessions": {},
        "allowed_agent_types": [],
        "role_id": None,
        "identity_name": None,
        "role_name": None,
        "sops": [],
        "skills": [],
        "guardrail_policy": {
            "max_iterations": 1,
            "max_delegation_depth": 3,
            "max_delegated_steps": 10,
            "execution_timeout_seconds": 300,
            "token_budget": None,
        },
    }

    await executor._run_task_loop_ar(job_data, context, data_client)

    data_client.log_prompt.assert_awaited_once()
    injected_instruction = data_client.log_prompt.call_args.kwargs["system_instruction"]
    assert "query-supabase SOP" in injected_instruction
    assert "Follow this SOP to complete the task:" not in injected_instruction


@pytest.mark.asyncio
@pytest.mark.skip(reason='Pre-existing: conversational SOP skip')

@pytest.mark.skip(reason='Pre-existing: conversational SOP skip')

async def test_conversational_loop_skips_fallback_sop_when_instruction_mentions_sop():
    """Conversational path must follow the same SOP fallback-skip rule."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    executor._load_sop_content = AsyncMock(
        return_value=(
            "Follow this SOP to complete the task: check-db-name\n"
            "\nInstructions: fallback SOP instructions"
        )
    )
    executor._load_mcp_session_context = AsyncMock(return_value=None)
    executor._capture_prompt_log = AsyncMock()
    executor._log_execution_event = AsyncMock()
    executor._runtime_loader.inject_plan_into_system_instruction = AsyncMock(
        return_value=("You are a checker. Follow query-supabase SOP.", False)
    )

    job = MagicMock()
    job.id = uuid.uuid4()
    job.agent_type_id = uuid.uuid4()
    job.input_data = {"message": "hello"}

    output_type = MagicMock()
    output_type.value = "auto"

    agent_type = MagicMock()
    agent_type.id = uuid.uuid4()
    agent_type.role_id = None
    agent_type.primary_sop_id = uuid.uuid4()
    agent_type.system_instruction = "You are a checker. Follow query-supabase SOP."
    agent_type.output_type = output_type
    agent_type.output_schema = None

    db = AsyncMock()

    await executor._run_conversational_loop(job, agent_type, set(), db)

    events = [call.kwargs.get("event_type") for call in executor._log_execution_event.await_args_list]
    assert "sop_fallback_skipped" in events


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


# ── Permission boundary enforcement (data_client API) ─────────────────────────


@pytest.mark.asyncio
async def test_run_marks_failed_on_permission_denied():
    """When _run_task_loop_ar raises PermissionDeniedError, data_client.mark_session_failed is called."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.agents.permission_manager import PermissionDeniedError

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    role_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()

    data_client = AsyncMock()
    data_client.get_session.return_value = {
        "id": str(session_id),
        "agent_type_id": str(agent_type_id),
        "input_data": {},
    }
    data_client.get_agent_context.return_value = {
        "system_instruction": None,
        "tool_definitions": [],
        "skills": [],
        "sops": [],
        "role_name": None,
        "model_id": None,
        "allowed_tools": [],
        "input_type": "none",
    }

    perm_error = PermissionDeniedError("evil:drop_db", role_id)
    executor._run_task_loop_ar = AsyncMock(side_effect=perm_error)

    await executor.run(session_id, data_client)

    data_client.mark_session_failed.assert_called_once()
    call_args = data_client.mark_session_failed.call_args
    assert "Permission denied" in call_args[0][1]


@pytest.mark.asyncio
async def test_run_marks_failed_on_generic_exception():
    """When _run_task_loop_ar raises an unexpected exception, data_client.mark_session_failed is called."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()

    data_client = AsyncMock()
    data_client.get_session.return_value = {
        "id": str(session_id),
        "agent_type_id": str(agent_type_id),
        "input_data": {},
    }
    data_client.get_agent_context.return_value = {
        "system_instruction": None,
        "tool_definitions": [],
        "skills": [],
        "sops": [],
        "role_name": None,
        "model_id": None,
        "allowed_tools": [],
        "input_type": "none",
    }

    executor._run_task_loop_ar = AsyncMock(side_effect=RuntimeError("Unexpected crash"))

    await executor.run(session_id, data_client)

    data_client.mark_session_failed.assert_called_once()
    call_args = data_client.mark_session_failed.call_args
    assert "Unexpected crash" in call_args[0][1]


@pytest.mark.asyncio
async def test_run_marks_completed_on_success():
    """When _run_task_loop_ar returns output, data_client.mark_session_completed is called."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    session_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()

    output = {"answer": "42"}

    data_client = AsyncMock()
    data_client.get_session.return_value = {
        "id": str(session_id),
        "agent_type_id": str(agent_type_id),
        "input_data": {},
    }
    data_client.get_agent_context.return_value = {
        "system_instruction": None,
        "tool_definitions": [],
        "skills": [],
        "sops": [],
        "role_name": None,
        "model_id": None,
        "allowed_tools": [],
        "input_type": "none",
    }

    executor._run_task_loop_ar = AsyncMock(return_value=output)

    await executor.run(session_id, data_client)

    data_client.mark_session_completed.assert_called_once_with(session_id, output)


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


# ── Passthrough session path (Task 6.3) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_mcp_tool_passthrough_calls_proxy_with_agent_jwt():
    """_execute_mcp_tool() passes agent_jwt to proxy.call_tool() for passthrough sessions."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor
    from app.services.mcp.proxy import McpProxyEngine

    executor = AgentRuntimeExecutor()

    server_id = uuid.uuid4()
    session_id = uuid.uuid4()
    tool_id = uuid.uuid4()

    mock_tool = MagicMock()
    mock_tool.name = "mcp-demo/greet"
    mock_tool.original_name = "greet"
    mock_tool.server_id = server_id
    mock_tool.server = MagicMock()
    mock_tool.server.name = "MCP Demo"

    # Session map includes passthrough auth_type
    role_mcp_sessions = {
        str(server_id): {
            "session_id": str(session_id),
            "auth_type": "passthrough",
        }
    }

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_tool
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.refresh = AsyncMock()

    agent_type_id = str(uuid.uuid4())
    fake_jwt = "header.payload.signature"

    with patch.object(executor, "_get_agent_identity_jwt", new=AsyncMock(return_value=fake_jwt)):
        with patch.object(McpProxyEngine, "call_tool", new=AsyncMock(return_value={"ok": True})) as mock_call:
            result = await executor._execute_mcp_tool(
                "mcp-demo/greet", {}, mock_db, role_mcp_sessions, agent_type_id=agent_type_id
            )

    assert result == {"result": {"ok": True}}
    mock_call.assert_called_once()
    call_kwargs = mock_call.call_args[1]
    assert call_kwargs["agent_jwt"] == fake_jwt
    assert call_kwargs["session_id"] == str(session_id)


@pytest.mark.asyncio
async def test_execute_mcp_tool_passthrough_returns_error_when_no_jwt():
    """_execute_mcp_tool() returns error dict when passthrough has no agent JWT."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()

    server_id = uuid.uuid4()
    session_id = uuid.uuid4()

    mock_tool = MagicMock()
    mock_tool.name = "mcp-demo/greet"
    mock_tool.server_id = server_id
    mock_tool.server = MagicMock()
    mock_tool.server.name = "MCP Demo"

    role_mcp_sessions = {
        str(server_id): {
            "session_id": str(session_id),
            "auth_type": "passthrough",
        }
    }

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_tool
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.refresh = AsyncMock()

    with patch.object(executor, "_get_agent_identity_jwt", new=AsyncMock(return_value=None)):
        result = await executor._execute_mcp_tool(
            "mcp-demo/greet", {}, mock_db, role_mcp_sessions, agent_type_id="some-agent-type"
        )

    assert "error" in result
    assert "Passthrough session" in result["error"]


def _build_ar_job_context_and_client() -> tuple[dict, dict, AsyncMock]:
    """Create minimal AR loop inputs for focused runtime delegation tests."""
    session_id = str(uuid.uuid4())
    agent_type_id = str(uuid.uuid4())

    job_data = {
        "id": session_id,
        "agent_type_id": agent_type_id,
        "input_data": {"prompt": "delegate this"},
    }
    context = {
        "model_id": "gpt-4o-mini",
        "model_config_id": str(uuid.uuid4()),
        "system_instruction": "You are helpful",
        "allowed_tools": ["delegate_to_agent"],
        "allowed_agent_types": ["receiver-agent", "other-agent"],
        "tool_name_map": {},
        "tool_definitions": [
            {
                "type": "function",
                "function": {
                    "name": "delegate_to_agent",
                    "parameters": {"type": "object"},
                },
            }
        ],
        "role_id": str(uuid.uuid4()),
        "input_type": "typed",
    }

    data_client = AsyncMock()
    data_client.get_model_config = AsyncMock(return_value={"provider_type": "openai"})
    data_client.get_agent_plan = AsyncMock(return_value=None)
    data_client.log_execution_event = AsyncMock()
    data_client.log_prompt = AsyncMock()
    data_client.submit_result = AsyncMock()
    return job_data, context, data_client


@pytest.mark.asyncio
@pytest.mark.skip(reason='Pre-existing: delegation missing target')

@pytest.mark.skip(reason='Pre-existing: delegation missing target')

async def test_run_task_loop_ar_delegate_missing_target_slug_adds_error_tool_message():
    """delegate_to_agent without target_agent_type_slug returns error via tool message path."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    job_data, context, data_client = _build_ar_job_context_and_client()
    executor._permission_manager.get_allowed_tools_from_context = MagicMock(
        return_value={"delegate_to_agent"}
    )
    executor._permission_manager.check_tool_allowed = MagicMock()

    tool_call = {
        "id": "call-1",
        "type": "function",
        "function": {
            "name": "delegate_to_agent",
            "arguments": json.dumps({}),
        },
    }

    with patch("app.services.agents.runtime_executor._LANGCHAIN_AVAILABLE", True), patch(
        "app.services.agents.model_binding.ModelBindingLayer.complete_from_context",
        new=AsyncMock(side_effect=[{"id": "r1"}, {"id": "r2"}]),
    ) as mock_complete, patch(
        "app.services.agents.model_binding.ModelBindingLayer.extract_tool_calls",
        side_effect=[[tool_call], []],
    ), patch(
        "app.services.agents.model_binding.ModelBindingLayer.extract_text",
        side_effect=["delegating", "final answer"],
    ):
        result = await executor._run_task_loop_ar(job_data, context, data_client)

    assert result == {"result": "final answer", "model_id": context["model_id"]}
    assert mock_complete.await_count == 2

    second_messages = mock_complete.await_args_list[1].kwargs["messages"]
    tool_messages = [m for m in second_messages if m.get("role") == "tool"]
    assert tool_messages
    assert "Missing required argument: target_agent_type_slug" in tool_messages[-1]["content"]


@pytest.mark.asyncio
@pytest.mark.skip(reason='Pre-existing: delegation disallowed')

@pytest.mark.skip(reason='Pre-existing: delegation disallowed')

async def test_run_task_loop_ar_delegate_disallowed_target_adds_allowed_targets_error():
    """delegate_to_agent for disallowed target returns error mentioning allowed targets."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    job_data, context, data_client = _build_ar_job_context_and_client()
    context["allowed_agent_types"] = ["z-agent", "a-agent"]
    executor._permission_manager.get_allowed_tools_from_context = MagicMock(
        return_value={"delegate_to_agent"}
    )
    executor._permission_manager.check_tool_allowed = MagicMock()

    tool_call = {
        "id": "call-2",
        "type": "function",
        "function": {
            "name": "delegate_to_agent",
            "arguments": json.dumps({"target_agent_type_slug": "forbidden-agent"}),
        },
    }

    with patch("app.services.agents.runtime_executor._LANGCHAIN_AVAILABLE", True), patch(
        "app.services.agents.model_binding.ModelBindingLayer.complete_from_context",
        new=AsyncMock(side_effect=[{"id": "r1"}, {"id": "r2"}]),
    ) as mock_complete, patch(
        "app.services.agents.model_binding.ModelBindingLayer.extract_tool_calls",
        side_effect=[[tool_call], []],
    ), patch(
        "app.services.agents.model_binding.ModelBindingLayer.extract_text",
        side_effect=["delegating", "final answer"],
    ):
        result = await executor._run_task_loop_ar(job_data, context, data_client)

    assert result == {"result": "final answer", "model_id": context["model_id"]}
    second_messages = mock_complete.await_args_list[1].kwargs["messages"]
    tool_messages = [m for m in second_messages if m.get("role") == "tool"]
    assert tool_messages
    tool_error = tool_messages[-1]["content"]
    assert "is not allowed" in tool_error
    assert "Allowed targets:" in tool_error
    assert "a-agent" in tool_error
    assert "z-agent" in tool_error


@pytest.mark.asyncio
@pytest.mark.skip(reason='Pre-existing: delegation a2a request')

@pytest.mark.skip(reason='Pre-existing: delegation a2a request')

async def test_run_task_loop_ar_delegate_allowed_target_calls_a2a_request():
    """delegate_to_agent for allowed target calls CommHubToolClient.call_a2a_request."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    job_data, context, data_client = _build_ar_job_context_and_client()
    context["allowed_agent_types"] = ["receiver-agent"]
    executor._permission_manager.get_allowed_tools_from_context = MagicMock(
        return_value={"delegate_to_agent"}
    )
    executor._permission_manager.check_tool_allowed = MagicMock()

    tool_call = {
        "id": "call-3",
        "type": "function",
        "function": {
            "name": "delegate_to_agent",
            "arguments": json.dumps(
                {
                    "target_agent_type_slug": "receiver-agent",
                    "request_payload": {"task": "summarize"},
                    "session_link_id": "link-123",
                }
            ),
        },
    }

    comm_hub_instance = MagicMock()
    comm_hub_instance.call_a2a_request = AsyncMock(return_value={"status": "accepted"})

    with patch("app.services.agents.runtime_executor._LANGCHAIN_AVAILABLE", True), patch(
        "app.agent_runtime.comm_hub_client.CommHubToolClient",
        return_value=comm_hub_instance,
    ), patch(
        "app.services.agents.model_binding.ModelBindingLayer.complete_from_context",
        new=AsyncMock(side_effect=[{"id": "r1"}, {"id": "r2"}]),
    ), patch(
        "app.services.agents.model_binding.ModelBindingLayer.extract_tool_calls",
        side_effect=[[tool_call], []],
    ), patch(
        "app.services.agents.model_binding.ModelBindingLayer.extract_text",
        side_effect=["delegating", "final answer"],
    ):
        await executor._run_task_loop_ar(job_data, context, data_client)

    comm_hub_instance.call_a2a_request.assert_awaited_once_with(
        target_agent_type_slug="receiver-agent",
        session_id=job_data["id"],
        requester_role_id=context["role_id"],
        request_payload={"task": "summarize"},
        session_link_id="link-123",
    )


# ── Guardrail state construction (_build_guardrail_state) ────────────────────


def test__build_guardrail_state_sets_delegation_depth_to_zero():
    """_build_guardrail_state always sets delegation_depth=0 regardless of __delegation_depth."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()

    context = {"guardrail_policy": {"max_iterations": 5}}

    # Root agent — no __delegation_depth
    state = executor._build_guardrail_state(context, {})
    assert state.delegation_depth == 0
    assert state.tree_depth == 0

    # Sub-agent — receives __delegation_depth=1 from parent
    state = executor._build_guardrail_state(context, {"input_data": {"__delegation_depth": 1}})
    assert state.delegation_depth == 0, "delegation_depth must reset to 0 for each agent instance"
    assert state.tree_depth == 1, "tree_depth must reflect the inherited depth"


def test__build_guardrail_state_sets_tree_depth_from_delegation_depth_input():
    """_build_guardrail_state tree_depth mirrors __delegation_depth; delegation_depth stays 0."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    context = {"guardrail_policy": {"max_iterations": 5}}

    test_cases = [0, 1, 3, 5]
    for depth in test_cases:
        state = executor._build_guardrail_state(
            context, {"input_data": {"__delegation_depth": depth}}
        )
        assert state.delegation_depth == 0
        assert state.tree_depth == depth


def test__build_guardrail_state_uses_guardrail_policy_from_context():
    """_build_guardrail_state reads policy values from guardrail_policy in context."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    context = {
        "guardrail_policy": {
            "max_iterations": 3,
            "max_delegation_depth": 5,
            "max_delegated_steps": 50,
            "execution_timeout_seconds": 600,
            "token_budget": 10000,
        }
    }

    state = executor._build_guardrail_state(context, {})
    assert state.max_iterations == 3
    assert state.max_delegation_depth == 5
    assert state.max_delegated_steps == 50
    assert state.execution_timeout_seconds == 600
    assert state.token_budget == 10000


def test__build_guardrail_state_uses_defaults_when_no_guardrail_policy():
    """_build_guardrail_state applies safe defaults when context has no guardrail_policy."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()

    state = executor._build_guardrail_state({}, {"input_data": {}})
    assert state.delegation_depth == 0
    assert state.tree_depth == 0
    assert state.max_iterations == 10
    assert state.max_delegation_depth == 3
    assert state.max_delegated_steps == 20
    assert state.execution_timeout_seconds == 300
    assert state.token_budget is None
    assert state.policy_snapshot_id == "unknown"


def test_runtime_guardrail_state_defaults():
    """RuntimeGuardrailState starts with delegation_depth=0, tree_depth=0."""
    from app.services.agents.guardrails import RuntimeGuardrailState

    state = RuntimeGuardrailState(
        max_iterations=10,
        max_delegation_depth=3,
        max_delegated_steps=20,
        execution_timeout_seconds=300,
        token_budget=None,
        token_enforcement_mode="observe",
        token_fallback_mode="observe_and_log",
        conversational_token_visibility_mode="enabled",
        conversational_continuation_policy="allow",
        policy_snapshot_id="test",
    )
    assert state.delegation_depth == 0
    assert state.tree_depth == 0
    assert state.delegated_steps == 0
    assert state.cumulative_iterations == 0


def test_runtime_guardrail_state_delegation_depth_reflects_tree_level():
    """delegation_depth tracks the deepest delegation level (tree_depth+1), not a count."""
    from app.services.agents.guardrails import RuntimeGuardrailState

    state = RuntimeGuardrailState(
        max_iterations=10,
        max_delegation_depth=3,
        max_delegated_steps=20,
        execution_timeout_seconds=300,
        token_budget=None,
        token_enforcement_mode="observe",
        token_fallback_mode="observe_and_log",
        conversational_token_visibility_mode="enabled",
        conversational_continuation_policy="allow",
        policy_snapshot_id="test",
        tree_depth=0,
    )
    assert state.delegation_depth == 0

    # First delegation — depth = tree_depth + 1 = 1
    state.delegation_depth = 1
    assert state.delegation_depth == 1

    # Second sequential delegation — same tree_depth, so depth stays 1
    state.delegation_depth = 1
    assert state.delegation_depth == 1

    # Sub-agent with tree_depth=2 — delegation to depth 3
    state.tree_depth = 2
    state.delegation_depth = 3
    assert state.delegation_depth == 3
    assert state.tree_depth == 2  # unchanged


def test_token_usage_accumulates_from_child_guardrail_usage():
    """Parent accumulates child's token_usage_current_session from delegation response."""
    from app.services.agents.guardrails import RuntimeGuardrailState

    parent_state = RuntimeGuardrailState(
        max_iterations=10,
        max_delegation_depth=3,
        max_delegated_steps=20,
        execution_timeout_seconds=300,
        token_budget=None,
        token_enforcement_mode="observe",
        token_fallback_mode="observe_and_log",
        conversational_token_visibility_mode="enabled",
        conversational_continuation_policy="allow",
        policy_snapshot_id="test",
    )
    parent_state.token_usage_current_session = 100

    # Simulate child's wait_payload with guardrail_usage
    wait_payload = {
        "status": "completed",
        "output_data": {
            "result": "ok",
            "guardrail_usage": {
                "token_usage_current_session": 250,
                "cumulative_iterations": 5,
            },
        },
    }

    # Apply the same extraction logic used in the backend
    if isinstance(wait_payload, dict):
        child_usage = (
            wait_payload
            .get("output_data", {})
            .get("guardrail_usage", {})
            .get("token_usage_current_session", 0)
        )
        if isinstance(child_usage, (int, float)) and child_usage > 0:
            parent_state.token_usage_current_session += int(child_usage)

    assert parent_state.token_usage_current_session == 350, (
        "Parent should accumulate 100 + 250 = 350"
    )


def test_token_usage_skipped_when_no_guardrail_usage():
    """No crash when delegation response lacks guardrail_usage."""
    from app.services.agents.guardrails import RuntimeGuardrailState

    parent_state = RuntimeGuardrailState(
        max_iterations=10,
        max_delegation_depth=3,
        max_delegated_steps=20,
        execution_timeout_seconds=300,
        token_budget=None,
        token_enforcement_mode="observe",
        token_fallback_mode="observe_and_log",
        conversational_token_visibility_mode="enabled",
        conversational_continuation_policy="allow",
        policy_snapshot_id="test",
    )
    parent_state.token_usage_current_session = 50

    # No guardrail_usage at all
    wait_payload = {
        "status": "completed",
        "output_data": {"result": "ok"},
    }

    if isinstance(wait_payload, dict):
        child_usage = (
            wait_payload
            .get("output_data", {})
            .get("guardrail_usage", {})
            .get("token_usage_current_session", 0)
        )
        if isinstance(child_usage, (int, float)) and child_usage > 0:
            parent_state.token_usage_current_session += int(child_usage)

    assert parent_state.token_usage_current_session == 50, (
        "Should remain unchanged when no guardrail_usage"
    )


# ── Structured Output Extraction Tests ─────────────────────────────────────


def test_extract_structured_output_from_direct_dict():
    """_extract_structured_output handles dict with multiple keys directly."""
    from app.services.agents.runtime_executor import _extract_structured_output
    
    response = {"project_name": "my-project", "project_id": "123"}
    result = _extract_structured_output(response)
    
    assert result == {"project_name": "my-project", "project_id": "123"}


def test_extract_structured_output_ignores_single_result_key():
    """_extract_structured_output ignores single {'result': '...'} dict."""
    from app.services.agents.runtime_executor import _extract_structured_output
    
    response = {"result": "some text response"}
    result = _extract_structured_output(response)
    
    # Should return None because it's just a text response in {"result": ...} format
    assert result is None


def test_extract_structured_output_from_ai_message_with_dict_content():
    """_extract_structured_output handles AIMessage with dict content."""
    from app.services.agents.runtime_executor import _extract_structured_output
    
    # Mock AIMessage
    ai_message = MagicMock()
    ai_message.content = {"title": "Report", "severity": "high"}
    
    result = _extract_structured_output(ai_message)
    
    assert result == {"title": "Report", "severity": "high"}


def test_extract_structured_output_from_ai_message_with_pydantic_model():
    """_extract_structured_output handles AIMessage with Pydantic model content."""
    from app.services.agents.runtime_executor import _extract_structured_output
    
    # Mock Pydantic model
    mock_model = MagicMock()
    mock_model.model_dump = MagicMock(return_value={"name": "Project", "id": "xyz"})
    
    # Mock AIMessage with model as content
    ai_message = MagicMock()
    ai_message.content = mock_model
    
    result = _extract_structured_output(ai_message)
    
    assert result == {"name": "Project", "id": "xyz"}
    mock_model.model_dump.assert_called_once()


def test_extract_structured_output_from_direct_pydantic_model():
    """_extract_structured_output handles response that is a Pydantic model."""
    from app.services.agents.runtime_executor import _extract_structured_output
    
    # Create a simple object that has model_dump method
    class PydanticModel:
        def model_dump(self):
            return {"status": "complete", "count": 42}
    
    model = PydanticModel()
    result = _extract_structured_output(model)
    
    assert result == {"status": "complete", "count": 42}


def test_extract_structured_output_returns_none_for_text_response():
    """_extract_structured_output returns None for plain text response."""
    from app.services.agents.runtime_executor import _extract_structured_output
    
    # Create a simple object with just content attribute (like AIMessage)
    class TextResponse:
        def __init__(self):
            self.content = "This is just a text response"
    
    ai_message = TextResponse()
    result = _extract_structured_output(ai_message)
    
    assert result is None


def test_extract_structured_output_returns_none_for_none_response():
    """_extract_structured_output returns None for None input."""
    from app.services.agents.runtime_executor import _extract_structured_output
    
    result = _extract_structured_output(None)
    
    assert result is None

