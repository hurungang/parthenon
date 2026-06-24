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
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── Helper: build simple guardrail state ──────────────────────────────────────


def _make_state(**kwargs):
    """Build a simple namespace object with guardrail state attributes."""
    state = MagicMock()
    state.iteration_count = kwargs.get("iteration_count", 0)
    state.max_iterations = kwargs.get("max_iterations", None)
    state.tokens_used = kwargs.get("tokens_used", 0)
    state.max_tokens_total = kwargs.get("max_tokens_total", None)
    state.started_at = kwargs.get("started_at", None)
    state.timeout_seconds = kwargs.get("timeout_seconds", None)
    state.delegation_depth = kwargs.get("delegation_depth", 0)
    state.max_delegation_depth = kwargs.get("max_delegation_depth", None)
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
    """GuardrailStop raised from on_llm_start when iteration_count >= max_iterations."""
    from app.services.agents.guardrail_callback import GuardrailCallback, GuardrailStop

    state = _make_state(iteration_count=10, max_iterations=10)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    with pytest.raises(GuardrailStop) as exc_info:
        await cb.on_llm_start(serialized={}, prompts=["hello"])

    assert exc_info.value.reason == "iteration_limit"


@pytest.mark.asyncio
async def test_on_llm_start_no_raise_when_within_limit():
    """No exception when iteration_count < max_iterations."""
    from app.services.agents.guardrail_callback import GuardrailCallback

    state = _make_state(iteration_count=5, max_iterations=10)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    # Should not raise
    await cb.on_llm_start(serialized={}, prompts=["hello"])


@pytest.mark.asyncio
async def test_on_chat_model_start_raises_when_iteration_limit_exceeded():
    """GuardrailStop raised from on_chat_model_start when iteration limit hit."""
    from app.services.agents.guardrail_callback import GuardrailCallback, GuardrailStop

    state = _make_state(iteration_count=3, max_iterations=3)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    with pytest.raises(GuardrailStop):
        await cb.on_chat_model_start(serialized={}, messages=[[]])


@pytest.mark.asyncio
async def test_no_iteration_check_when_max_iterations_is_none():
    """No iteration check performed when max_iterations is None."""
    from app.services.agents.guardrail_callback import GuardrailCallback

    state = _make_state(iteration_count=9999, max_iterations=None)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    # Should not raise
    await cb.on_llm_start(serialized={}, prompts=["hi"])


# ── Token budget ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_llm_end_raises_when_token_budget_exceeded():
    """GuardrailStop raised from on_llm_end when token budget is exceeded."""
    from app.services.agents.guardrail_callback import GuardrailCallback, GuardrailStop
    from langchain_core.outputs import LLMResult

    state = _make_state(tokens_used=10000, max_tokens_total=10000)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    result = LLMResult(generations=[], llm_output={})
    with pytest.raises(GuardrailStop) as exc_info:
        await cb.on_llm_end(result)

    assert exc_info.value.reason == "token_budget"


@pytest.mark.asyncio
async def test_on_llm_end_no_raise_when_within_budget():
    """No exception when tokens_used < max_tokens_total."""
    from app.services.agents.guardrail_callback import GuardrailCallback
    from langchain_core.outputs import LLMResult

    state = _make_state(tokens_used=500, max_tokens_total=10000)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    result = LLMResult(generations=[], llm_output={})
    # Should not raise
    await cb.on_llm_end(result)


@pytest.mark.asyncio
async def test_no_token_check_when_max_tokens_is_none():
    """No token check performed when max_tokens_total is None."""
    from app.services.agents.guardrail_callback import GuardrailCallback
    from langchain_core.outputs import LLMResult

    state = _make_state(tokens_used=9999999, max_tokens_total=None)
    cb = GuardrailCallback(guardrail_state=state, session_id="sess-1")

    result = LLMResult(generations=[], llm_output={})
    # Should not raise
    await cb.on_llm_end(result)


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
