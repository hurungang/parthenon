"""Unit tests for GuardrailCallback — iteration limit, token budget, timeout enforcement.

Verifies:
- GuardrailStop raised when iteration limit is exceeded
- GuardrailStop raised when token budget is exceeded
- GuardrailStop raised when timeout exceeded
- No exception when limits are not reached
- GuardrailStop.reason attribute set correctly
- on_llm_start triggers iteration and timeout checks
- on_chat_model_start triggers iteration and timeout checks
- on_llm_end triggers token budget check
- guardrail.runtime.snapshot emitted at each iteration start
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── Helper: build simple guardrail state ──────────────────────────────────────


def _make_state(**kwargs):
    """Build a simple namespace object with guardrail state attributes."""
    state = MagicMock()
    # cumulative_iterations is the primary counter used by GuardrailCallback
    state.cumulative_iterations = kwargs.get("cumulative_iterations", kwargs.get("iteration_count", 0))
    state.iteration_count = kwargs.get("iteration_count", 0)  # legacy fallback
    state.max_iterations = kwargs.get("max_iterations", None)
    state.tokens_used = kwargs.get("tokens_used", 0)
    state.max_tokens_total = kwargs.get("max_tokens_total", None)
    state.started_at = kwargs.get("started_at", None)
    state.timeout_seconds = kwargs.get("timeout_seconds", None)
    state.delegation_depth = kwargs.get("delegation_depth", 0)
    state.max_delegation_depth = kwargs.get("max_delegation_depth", None)
    state.delegated_steps = kwargs.get("delegated_steps", 0)
    state.max_delegated_steps = kwargs.get("max_delegated_steps", None)
    state.token_budget = kwargs.get("token_budget", None)
    state.execution_timeout_seconds = kwargs.get("execution_timeout_seconds", 300)
    state.token_usage_current_session = kwargs.get("token_usage_current_session", 0)
    state.policy_snapshot_id = kwargs.get("policy_snapshot_id", "test-snapshot-id")
    state.elapsed_seconds = MagicMock(return_value=kwargs.get("elapsed_seconds", 0.0))
    return state


# ── Instantiation ─────────────────────────────────────────────────────────────


def test_guardrail_callback_can_be_instantiated():
    from app.services.agents.guardrail_callback import GuardrailCallback

    state = _make_state()
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")
    assert cb is not None


def test_guardrail_callback_raise_error_is_true():
    """raise_error=True so exceptions propagate from LangChain callbacks."""
    from app.services.agents.guardrail_callback import GuardrailCallback

    state = _make_state()
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")
    assert cb.raise_error is True


# ── Iteration limit ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_llm_start_raises_when_iteration_limit_exceeded():
    """GuardrailStop raised from on_llm_start when cumulative_iterations > max_iterations."""
    from app.services.agents.guardrail_callback import GuardrailCallback, GuardrailStop

    state = _make_state(cumulative_iterations=10, max_iterations=10)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    with pytest.raises(GuardrailStop) as exc_info:
        await cb.on_llm_start(serialized={}, prompts=["hello"])

    assert exc_info.value.reason == "iteration_limit"


@pytest.mark.asyncio
async def test_on_llm_start_no_raise_when_within_limit():
    """No exception when cumulative_iterations <= max_iterations."""
    from app.services.agents.guardrail_callback import GuardrailCallback

    state = _make_state(cumulative_iterations=5, max_iterations=10)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    # Should not raise
    await cb.on_llm_start(serialized={}, prompts=["hello"])


@pytest.mark.asyncio
async def test_on_chat_model_start_raises_when_iteration_limit_exceeded():
    """GuardrailStop raised from on_chat_model_start when iteration limit hit."""
    from app.services.agents.guardrail_callback import GuardrailCallback, GuardrailStop

    state = _make_state(cumulative_iterations=3, max_iterations=3)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    with pytest.raises(GuardrailStop):
        await cb.on_chat_model_start(serialized={}, messages=[[]])


@pytest.mark.asyncio
async def test_no_iteration_check_when_max_iterations_is_none():
    """No iteration check performed when max_iterations is None."""
    from app.services.agents.guardrail_callback import GuardrailCallback

    state = _make_state(cumulative_iterations=9999, max_iterations=None)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    # Should not raise
    await cb.on_llm_start(serialized={}, prompts=["hi"])


# ── Token budget ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_llm_end_raises_when_token_budget_exceeded():
    """GuardrailStop raised from on_llm_end when token_usage_current_session > token_budget."""
    from app.services.agents.guardrail_callback import GuardrailCallback, GuardrailStop
    from langchain_core.outputs import LLMResult

    # token_usage_current_session starts at 9900, response adds 200 -> 10100 > 10000
    state = _make_state(token_usage_current_session=9900, token_budget=10000)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    result = LLMResult(generations=[], llm_output={"token_usage": {"total_tokens": 200}})
    with pytest.raises(GuardrailStop) as exc_info:
        await cb.on_llm_end(result)

    assert exc_info.value.reason == "token_budget"


@pytest.mark.asyncio
async def test_on_llm_end_no_raise_when_within_budget():
    """No exception when token_usage_current_session < token_budget."""
    from app.services.agents.guardrail_callback import GuardrailCallback
    from langchain_core.outputs import LLMResult

    state = _make_state(token_usage_current_session=500, token_budget=10000)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    result = LLMResult(generations=[], llm_output={})
    # Should not raise
    await cb.on_llm_end(result)


@pytest.mark.asyncio
async def test_on_llm_end_no_raise_at_exact_token_budget():
    """No exception when token_usage_current_session == token_budget (100% is not a breach)."""
    from app.services.agents.guardrail_callback import GuardrailCallback
    from langchain_core.outputs import LLMResult

    # After accumulation: 9800 + 200 = 10000 exactly == budget — must NOT raise
    state = _make_state(token_usage_current_session=9800, token_budget=10000)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    result = LLMResult(generations=[], llm_output={"token_usage": {"total_tokens": 200}})
    # Should not raise at exactly 100%
    await cb.on_llm_end(result)


@pytest.mark.asyncio
async def test_no_token_check_when_max_tokens_is_none():
    """No token check performed when token_budget is None."""
    from app.services.agents.guardrail_callback import GuardrailCallback
    from langchain_core.outputs import LLMResult

    state = _make_state(token_usage_current_session=9999999, token_budget=None)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    result = LLMResult(generations=[], llm_output={})
    # Should not raise
    await cb.on_llm_end(result)


@pytest.mark.asyncio
async def test_on_llm_end_updates_token_usage_current_session():
    """on_llm_end accumulates total_tokens into token_usage_current_session."""
    from app.services.agents.guardrail_callback import GuardrailCallback
    from langchain_core.outputs import LLMResult

    state = _make_state(token_usage_current_session=100, token_budget=None)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-tok")

    result = LLMResult(generations=[], llm_output={"token_usage": {"total_tokens": 350}})
    await cb.on_llm_end(result)

    assert state.token_usage_current_session == 450


# ── Timeout ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_llm_start_raises_when_timeout_exceeded():
    """GuardrailStop raised from on_llm_start when wall-clock timeout exceeded."""
    from app.services.agents.guardrail_callback import GuardrailCallback, GuardrailStop

    # started_at 5 minutes ago, timeout is 1 second
    state = _make_state(
        started_at=time.monotonic() - 300.0,
        timeout_seconds=1.0,
    )
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    with pytest.raises(GuardrailStop) as exc_info:
        await cb.on_llm_start(serialized={}, prompts=["test"])

    assert exc_info.value.reason == "timeout"


@pytest.mark.asyncio
async def test_on_llm_start_no_raise_when_within_timeout():
    """No timeout exception when elapsed time < timeout_seconds."""
    from app.services.agents.guardrail_callback import GuardrailCallback

    state = _make_state(
        started_at=time.monotonic(),
        timeout_seconds=3600.0,  # 1 hour
    )
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    # Should not raise
    await cb.on_llm_start(serialized={}, prompts=["test"])


@pytest.mark.asyncio
async def test_no_timeout_check_when_started_at_is_none():
    """No timeout check when started_at is None."""
    from app.services.agents.guardrail_callback import GuardrailCallback

    state = _make_state(started_at=None, timeout_seconds=1.0)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    # Should not raise
    await cb.on_llm_start(serialized={}, prompts=["test"])


# ── GuardrailStop details ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_tool_start_no_raise_at_exact_delegation_depth():
    """No exception when delegation_depth == max_delegation_depth (100% is not a breach)."""
    from app.services.agents.guardrail_callback import GuardrailCallback

    # delegation_depth exactly equals max — must NOT raise
    state = _make_state(delegation_depth=1, max_delegation_depth=1)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    # Should not raise at exactly 100%
    await cb.on_tool_start(serialized={}, input_str="test")


@pytest.mark.asyncio
async def test_on_tool_start_raises_when_delegation_depth_exceeded():
    """GuardrailStop raised when delegation_depth > max_delegation_depth."""
    from app.services.agents.guardrail_callback import GuardrailCallback, GuardrailStop

    state = _make_state(delegation_depth=2, max_delegation_depth=1)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    with pytest.raises(GuardrailStop) as exc_info:
        await cb.on_tool_start(serialized={}, input_str="test")

    assert exc_info.value.reason == "delegation_depth"


def test_guardrail_stop_has_reason_and_details():
    """GuardrailStop carries reason string and details dict."""
    from app.services.agents.guardrail_callback import GuardrailStop

    exc = GuardrailStop(reason="test_reason", details={"key": "value"})
    assert exc.reason == "test_reason"
    assert exc.details == {"key": "value"}
    assert str(exc) == "test_reason"


def test_guardrail_stop_defaults_empty_details():
    """GuardrailStop details defaults to empty dict when not provided."""
    from app.services.agents.guardrail_callback import GuardrailStop

    exc = GuardrailStop(reason="my_reason")
    assert exc.details == {}


# ── guardrail.runtime.snapshot emission ──────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_emitted_on_chat_model_start():
    """guardrail.runtime.snapshot is emitted with current_value and threshold_value on each iteration."""
    from app.services.agents.guardrail_callback import GuardrailCallback

    state = _make_state(
        cumulative_iterations=1,
        max_iterations=10,
        max_delegation_depth=3,
        max_delegated_steps=20,
        token_budget=50000,
        execution_timeout_seconds=300,
        delegated_steps=2,
        delegation_depth=1,
        token_usage_current_session=1234,
        policy_snapshot_id="snap-abc",
        elapsed_seconds=5.0,
    )
    mock_client = AsyncMock()
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-snap", data_client=mock_client)

    await cb.on_chat_model_start(serialized={}, messages=[[]])

    mock_client.log_execution_event.assert_called_once()
    call_kwargs = mock_client.log_execution_event.call_args.kwargs
    assert call_kwargs["event_type"] == "guardrail.runtime.snapshot"
    assert call_kwargs["session_id"] == "sess-snap"
    data = call_kwargs["data"]
    assert data["policy_snapshot_id"] == "snap-abc"
    assert data["current_value"]["cumulative_iterations"] == 2  # incremented before snapshot
    assert data["current_value"]["delegated_steps"] == 2
    assert data["current_value"]["delegation_depth"] == 1
    assert data["threshold_value"]["max_iterations"] == 10
    assert data["threshold_value"]["max_delegation_depth"] == 3
    assert data["threshold_value"]["max_delegated_steps"] == 20
    assert data["threshold_value"]["token_budget"] == 50000
    assert data["threshold_value"]["execution_timeout_seconds"] == 300


@pytest.mark.asyncio
async def test_snapshot_emitted_on_llm_start():
    """guardrail.runtime.snapshot also emitted from on_llm_start path."""
    from app.services.agents.guardrail_callback import GuardrailCallback

    state = _make_state(cumulative_iterations=0, max_iterations=5, policy_snapshot_id="snap-xyz")
    mock_client = AsyncMock()
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-llm", data_client=mock_client)

    await cb.on_llm_start(serialized={}, prompts=["test"])

    mock_client.log_execution_event.assert_called_once()
    call_kwargs = mock_client.log_execution_event.call_args.kwargs
    assert call_kwargs["event_type"] == "guardrail.runtime.snapshot"
    assert call_kwargs["data"]["policy_snapshot_id"] == "snap-xyz"
    assert call_kwargs["data"]["threshold_value"]["max_iterations"] == 5


@pytest.mark.asyncio
async def test_snapshot_not_emitted_when_no_data_client():
    """No snapshot call when data_client is None (no error raised)."""
    from app.services.agents.guardrail_callback import GuardrailCallback

    state = _make_state(cumulative_iterations=0, max_iterations=5)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-noop", data_client=None)

    # Should not raise even without data_client
    await cb.on_chat_model_start(serialized={}, messages=[[]])


@pytest.mark.asyncio
async def test_snapshot_failure_does_not_block_execution():
    """If snapshot emission fails, execution continues without error."""
    from app.services.agents.guardrail_callback import GuardrailCallback

    state = _make_state(cumulative_iterations=0, max_iterations=5)
    mock_client = AsyncMock()
    mock_client.log_execution_event.side_effect = RuntimeError("network error")
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-err", data_client=mock_client)

    # Should not raise despite the client error
    await cb.on_chat_model_start(serialized={}, messages=[[]])

