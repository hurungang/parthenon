"""Unit tests for ExecutionLoggingCallback — LLM/tool event emission.

Verifies:
- ExecutionLoggingCallback can be instantiated
- on_llm_start emits llm_request event via data_client.log_execution_event
- on_chat_model_start emits llm_request event
- on_llm_end emits llm_response event with token usage
- on_tool_start emits tool_call event
- on_tool_end emits tool_response event
- on_tool_error emits tool_error event
- on_llm_error emits llm_error event
- raise_error is False (logging failures must not stop execution)
- Logging failures are silently swallowed
- iteration_ref updates are reflected in log messages
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── Instantiation ─────────────────────────────────────────────────────────────


def test_execution_logging_callback_can_be_instantiated():
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    data_client = AsyncMock()
    cb = ExecutionLoggingCallback(session_id="sess-1", data_client=data_client)
    assert cb is not None


def test_raise_error_is_false():
    """raise_error=False so logging failures don't abort execution."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    cb = ExecutionLoggingCallback(session_id="sess-1", data_client=AsyncMock())
    assert cb.raise_error is False


def test_iteration_ref_defaults_to_zero_list():
    """iteration_ref defaults to [0] when not provided."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    cb = ExecutionLoggingCallback(session_id="sess-1", data_client=AsyncMock())
    assert cb.iteration_ref == [0]


def test_iteration_ref_can_be_shared():
    """iteration_ref can be passed as a shared mutable list."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    ref = [5]
    cb = ExecutionLoggingCallback(session_id="sess-1", data_client=AsyncMock(), iteration_ref=ref)
    assert cb.iteration_ref is ref
    assert cb.iteration_ref[0] == 5


# ── llm_request event ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_llm_start_calls_log_execution_event():
    """on_llm_start emits llm_request event via data_client."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    cb = ExecutionLoggingCallback(session_id="sess-1", data_client=data_client)

    await cb.on_llm_start(serialized={"kwargs": {"model_name": "gpt-4o"}}, prompts=["hello"])

    data_client.log_execution_event.assert_awaited()
    call_kwargs = data_client.log_execution_event.call_args[1]
    assert call_kwargs["event_type"] == "llm_request"
    assert "sess-1" in str(call_kwargs["session_id"])


@pytest.mark.asyncio
async def test_on_chat_model_start_calls_log_execution_event():
    """on_chat_model_start emits llm_request event."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    cb = ExecutionLoggingCallback(session_id="sess-2", data_client=data_client)

    await cb.on_chat_model_start(
        serialized={"name": "ChatOpenAI"},
        messages=[[MagicMock()]],
    )

    data_client.log_execution_event.assert_awaited()
    call_kwargs = data_client.log_execution_event.call_args[1]
    assert call_kwargs["event_type"] == "llm_request"


# ── llm_response event ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_llm_end_calls_log_execution_event():
    """on_llm_end emits llm_response event via data_client."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback
    from langchain_core.outputs import LLMResult

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    cb = ExecutionLoggingCallback(session_id="sess-3", data_client=data_client)

    result = LLMResult(generations=[], llm_output={"token_usage": {"total_tokens": 150}})
    await cb.on_llm_end(result)

    data_client.log_execution_event.assert_awaited()
    call_kwargs = data_client.log_execution_event.call_args[1]
    assert call_kwargs["event_type"] == "llm_response"


# ── tool_call event ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_tool_start_calls_log_execution_event():
    """on_tool_start emits tool_call event."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    cb = ExecutionLoggingCallback(session_id="sess-4", data_client=data_client)

    await cb.on_tool_start(serialized={"name": "my_tool"}, input_str='{"key": "val"}')

    data_client.log_execution_event.assert_awaited()
    call_kwargs = data_client.log_execution_event.call_args[1]
    assert call_kwargs["event_type"] == "tool_call"


@pytest.mark.asyncio
async def test_on_tool_start_logs_canonical_tool_name_for_replay():
    """Tool events must log the canonical name, not the sanitized model name.

    Replay matches a script's ``server____tool`` call against the transcript;
    logging ``server__tool`` made the reference look like it never called it.
    """
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    # Real shape: the CC map key keeps the hyphen, LangChain's serialized name
    # does not (``mcp-demo__generatePaymentLink`` vs ``mcp_demo__...``).
    cb = ExecutionLoggingCallback(
        session_id="sess-canon",
        data_client=data_client,
        tool_name_map={
            "mcp-demo__generatePaymentLink": "mcp-demo____generatePaymentLink"
        },
    )

    await cb.on_tool_start(
        serialized={"name": "mcp_demo__generatePaymentLink"},
        input_str='{"order_id": "ORD-1"}',
        inputs={"order_id": "ORD-1"},
    )

    call_kwargs = data_client.log_execution_event.call_args[1]
    assert call_kwargs["data"]["tool"] == "mcp-demo____generatePaymentLink"
    assert call_kwargs["data"]["tool_raw"] == "mcp_demo__generatePaymentLink"
    assert call_kwargs["data"]["arguments"] == {"order_id": "ORD-1"}


@pytest.mark.asyncio
async def test_on_tool_start_canonicalizes_without_map():
    """Even without the map, a sanitized ``server__tool`` becomes canonical."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    cb = ExecutionLoggingCallback(session_id="sess-canon-2", data_client=data_client)

    await cb.on_tool_start(
        serialized={"name": "mcp_demo__searchFlights"},
        input_str="{}",
    )

    call_kwargs = data_client.log_execution_event.call_args[1]
    assert call_kwargs["data"]["tool"] == "mcp_demo____searchFlights"


@pytest.mark.asyncio
async def test_on_tool_end_calls_log_execution_event():
    """on_tool_end emits tool_response event."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    cb = ExecutionLoggingCallback(session_id="sess-5", data_client=data_client)

    await cb.on_tool_end(output="some result")

    data_client.log_execution_event.assert_awaited()
    call_kwargs = data_client.log_execution_event.call_args[1]
    assert call_kwargs["event_type"] == "tool_response"


@pytest.mark.asyncio
async def test_on_tool_error_calls_log_execution_event():
    """on_tool_error emits tool_error event."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    cb = ExecutionLoggingCallback(session_id="sess-6", data_client=data_client)

    await cb.on_tool_error(error=RuntimeError("tool failed"))

    data_client.log_execution_event.assert_awaited()
    call_kwargs = data_client.log_execution_event.call_args[1]
    assert call_kwargs["event_type"] == "tool_error"


@pytest.mark.asyncio
async def test_on_llm_error_calls_log_execution_event():
    """on_llm_error emits llm_error event."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    cb = ExecutionLoggingCallback(session_id="sess-7", data_client=data_client)

    await cb.on_llm_error(error=RuntimeError("llm failed"))

    data_client.log_execution_event.assert_awaited()
    call_kwargs = data_client.log_execution_event.call_args[1]
    assert call_kwargs["event_type"] == "llm_error"


# ── Logging failures swallowed ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logging_failure_does_not_raise():
    """Logging failures are silently swallowed — execution must continue."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock(side_effect=RuntimeError("DB down"))
    cb = ExecutionLoggingCallback(session_id="sess-8", data_client=data_client)

    # Should not raise despite data_client failure
    await cb.on_llm_start(serialized={}, prompts=["test"])


@pytest.mark.asyncio
async def test_no_data_client_does_not_raise():
    """Callback with data_client=None does not raise on any event."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback
    from langchain_core.outputs import LLMResult

    cb = ExecutionLoggingCallback(session_id="sess-9", data_client=None)

    # None of these should raise
    await cb.on_llm_start(serialized={}, prompts=["hi"])
    await cb.on_llm_end(LLMResult(generations=[], llm_output={}))
    await cb.on_tool_start(serialized={"name": "tool"}, input_str="{}")
    await cb.on_tool_end(output="result")
    await cb.on_tool_error(error=RuntimeError("err"))


# ── Drafted-script visibility (execute_script full source) ───────────────────


@pytest.mark.asyncio
async def test_on_tool_start_keeps_full_source_for_execute_script():
    """The FULL python_source passed to execute_script appears in the
    execution log — it is the reviewable in-context artifact, never truncated."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    cb = ExecutionLoggingCallback(session_id="sess-11", data_client=data_client)

    long_source = "def run(context, tools):\n    return {'pad': '" + ("x" * 2000) + "'}\n"
    import json as _json
    input_str = _json.dumps({"python_source": long_source, "input": {}})
    assert len(input_str) > 500

    await cb.on_tool_start(serialized={"name": "execute_script"}, input_str=input_str)

    call_kwargs = data_client.log_execution_event.call_args[1]
    assert call_kwargs["data"]["input"] == input_str
    assert ("x" * 500) in call_kwargs["data"]["input"]  # untruncated


@pytest.mark.asyncio
async def test_on_tool_start_truncates_other_tools():
    """Non-execute_script tool inputs are still truncated (10,000 chars).

    The cap is generous because the recorded ``arguments``/``input`` are the
    REPLAY source for optimization verification, not just a log line.
    """
    from app.services.agents.execution_logging_callback import (
        MAX_INPUT_CHARS,
        ExecutionLoggingCallback,
    )

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    cb = ExecutionLoggingCallback(session_id="sess-12", data_client=data_client)

    big = "y" * (MAX_INPUT_CHARS + 500)
    await cb.on_tool_start(serialized={"name": "other_tool"}, input_str=big)

    call_kwargs = data_client.log_execution_event.call_args[1]
    assert len(call_kwargs["data"]["input"]) == MAX_INPUT_CHARS
    assert call_kwargs["data"]["input_truncated"] is True


@pytest.mark.asyncio
async def test_on_tool_start_records_structured_arguments_for_replay():
    """Structured ``inputs`` become ``arguments`` — the replay matching key."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    cb = ExecutionLoggingCallback(session_id="sess-13", data_client=data_client)

    await cb.on_tool_start(
        serialized={"name": "crm____getContact"},
        input_str='{"id": "c-1"}',
        run_id="run-1",
        inputs={"id": "c-1"},
    )

    data = data_client.log_execution_event.call_args[1]["data"]
    assert data["tool"] == "crm____getContact"
    assert data["arguments"] == {"id": "c-1"}
    assert data["run_id"] == "run-1"
    assert data["input_truncated"] is False


@pytest.mark.asyncio
async def test_on_tool_end_records_run_id_and_truncation_flag():
    """``tool_response`` carries the pairing ``run_id`` + a truncation flag."""
    from app.services.agents.execution_logging_callback import (
        MAX_OUTPUT_CHARS,
        ExecutionLoggingCallback,
    )

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()
    cb = ExecutionLoggingCallback(session_id="sess-14", data_client=data_client)

    await cb.on_tool_end(output="x" * (MAX_OUTPUT_CHARS + 10), run_id="run-42")

    data = data_client.log_execution_event.call_args[1]["data"]
    assert data["run_id"] == "run-42"
    assert data["output_truncated"] is True
    assert len(data["output"]) == MAX_OUTPUT_CHARS


# ── iteration_ref tracking ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_iteration_ref_reflected_in_log():
    """Changes to iteration_ref are reflected in log messages."""
    from app.services.agents.execution_logging_callback import ExecutionLoggingCallback

    data_client = AsyncMock()
    data_client.log_execution_event = AsyncMock()

    ref = [3]
    cb = ExecutionLoggingCallback(session_id="sess-10", data_client=data_client, iteration_ref=ref)
    await cb.on_llm_start(serialized={}, prompts=["test"])

    call_kwargs = data_client.log_execution_event.call_args[1]
    message = call_kwargs.get("message", "")
    assert "3" in message  # iteration 3 should appear in the message
