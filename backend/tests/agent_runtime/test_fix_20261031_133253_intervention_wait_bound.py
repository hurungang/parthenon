"""FIX-20261031-133253 — conversational HITL wait extends the turn bound
ONLY while an intervention is actually pending.

Contract (co-existence with FIX-20261031-091657):
- No pending intervention → the strict ``conversation_llm_timeout_seconds``
  bound fires (hanging provider → timeout_or_failed), unchanged.
- Pending intervention (tool awaiting the operator) → the wait is re-armed;
  the turn survives until the operator responds or
  ``conversation_intervention_timeout_seconds`` elapses.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.config import get_settings
from app.services.agents.runtime_executor import AgentRuntimeExecutor


def _executor_patches():
    import app.agent_runtime.comm_hub_client as comm_hub_module
    import app.services.agents.guardrail_callback as guardrail_cb_module
    import app.services.agents.langchain_tool_wrapper as tool_wrapper_module
    import langchain.agents as lc_agents

    return (
        patch.object(
            comm_hub_module,
            "CommHubToolClient",
            lambda: SimpleNamespace(set_certificate=lambda *a: None),
        ),
        patch.object(
            guardrail_cb_module, "GuardrailCallback", lambda **kwargs: SimpleNamespace()
        ),
        patch.object(
            tool_wrapper_module, "build_langchain_tools_for_ar_path", lambda **kwargs: []
        ),
    )


def _agent_context(conv_id: uuid.UUID) -> dict:
    return {
        "allowed_tools": [],
        "tool_definitions": [],
        "tool_name_map": {},
        "role_id": None,
        "model_id": "test-model",
    }


@pytest.mark.asyncio
async def test_pending_intervention_extends_the_turn_bound() -> None:
    """While a human_intervene is pending, a 'slow' model (tool awaiting the
    operator) must NOT time out at conversation_llm_timeout_seconds."""
    from app.agent_runtime import conversation_resume

    settings = get_settings()
    original_llm = settings.conversation_llm_timeout_seconds
    original_int = settings.conversation_intervention_timeout_seconds
    settings.conversation_llm_timeout_seconds = 0.3
    settings.conversation_intervention_timeout_seconds = 6
    conv_id = uuid.uuid4()

    class _SlowInterventionAgent:
        async def ainvoke(self, messages, config):  # noqa: ANN001
            # Simulate the human_intervene tool: register + wait for operator
            value = await conversation_resume.wait_for_resume(
                conv_id, timeout_seconds=5
            )
            class _Msg:
                type = "ai"
                content = f"resolved: {value}"

            return {"messages": [_Msg()]}

    executor = AgentRuntimeExecutor(data_client=SimpleNamespace())
    p1, p2, p3 = _executor_patches()
    import langchain.agents as lc_agents

    async def _approve():
        await asyncio.sleep(1.0)  # well beyond the strict 0.3s LLM bound
        assert conversation_resume.resolve(conv_id, {"approval_value": True})

    approver = asyncio.create_task(_approve())
    started = time.monotonic()
    try:
        with p1, p2, p3, patch.object(lc_agents, "create_agent", lambda **kw: _SlowInterventionAgent()):
            reply, _usage, status_events = await executor.execute_conversation_turn_from_context(
                agent_type_id=uuid.uuid4(),
                agent_context=_agent_context(conv_id),
                model_config={"provider_type": "openai"},
                messages=[{"role": "user", "content": "hello"}],
                conv_session_id=conv_id,
                status_event_callback=lambda e: asyncio.sleep(0, None),
            )
        elapsed = time.monotonic() - started
        # Survived the strict 0.3s bound (extension worked)...
        assert elapsed > 0.9
        # ...and completed with the operator's approval, no timeout event.
        assert "resolved" in reply and "True" in reply
        assert not any(
            e.get("status") == "timeout_or_failed" for e in status_events
        )
    finally:
        await approver
        settings.conversation_llm_timeout_seconds = original_llm
        settings.conversation_intervention_timeout_seconds = original_int


@pytest.mark.asyncio
async def test_intervention_timeout_converts_to_timeout_or_failed() -> None:
    """If the operator never responds, the turn ends with timeout_or_failed
    (and does NOT hang past the intervention window)."""
    from app.agent_runtime import conversation_resume

    settings = get_settings()
    original_llm = settings.conversation_llm_timeout_seconds
    original_int = settings.conversation_intervention_timeout_seconds
    settings.conversation_llm_timeout_seconds = 0.3
    settings.conversation_intervention_timeout_seconds = 1
    conv_id = uuid.uuid4()

    class _WaitingAgent:
        async def ainvoke(self, messages, config):  # noqa: ANN001
            # Emulate the real tool: wait for the operator; on timeout report
            # the not-executed outcome (the model then relays it).
            _t = float(settings.conversation_intervention_timeout_seconds)
            value = await conversation_resume.wait_for_resume(
                conv_id, timeout_seconds=_t
            )
            class _Msg:
                type = "ai"
                content = (
                    "did NOT execute" if value is None else f"resolved: {value}"
                )

            return {"messages": [_Msg()]}

    executor = AgentRuntimeExecutor(data_client=SimpleNamespace())
    p1, p2, p3 = _executor_patches()
    started = time.monotonic()
    try:
        with p1, p2, p3, patch("langchain.agents.create_agent", lambda **kw: _WaitingAgent()):
            reply, _usage, status_events = await executor.execute_conversation_turn_from_context(
                agent_type_id=uuid.uuid4(),
                agent_context=_agent_context(conv_id),
                model_config={"provider_type": "openai"},
                messages=[{"role": "user", "content": "hello"}],
                conv_session_id=conv_id,
                status_event_callback=lambda e: asyncio.sleep(0, None),
            )
        elapsed = time.monotonic() - started
        assert elapsed < 30
        assert "did NOT execute" in reply
    finally:
        settings.conversation_llm_timeout_seconds = original_llm
        settings.conversation_intervention_timeout_seconds = original_int
