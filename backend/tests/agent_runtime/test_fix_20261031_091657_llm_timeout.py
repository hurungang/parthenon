"""FIX-20261031-091657 (Defect A) — bounded LLM calls in the conversational executor.

A hanging post-tool LLM completion previously left the conversational turn
awaiting forever (no timeout anywhere on the chain). The executor must bound
every conversational turn with ``conversation_llm_timeout_seconds`` and
convert a timeout into the EXISTING ``timeout_or_failed`` status event plus a
clear, persisted error message.
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


class _HangingAgent:
    """Stand-in for the LangGraph agent whose post-tool LLM call never returns."""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages, config):  # noqa: ANN001
        self.calls += 1
        await asyncio.sleep(120)


@pytest.mark.asyncio
async def test_conversation_turn_times_out_with_timeout_or_failed_event() -> None:
    settings = get_settings()
    original = settings.conversation_llm_timeout_seconds
    settings.conversation_llm_timeout_seconds = 0.3
    try:
        executor = AgentRuntimeExecutor(data_client=SimpleNamespace())
        hanging = _HangingAgent()

        captured_events: list[dict[str, str]] = []

        async def on_status_event(event: dict[str, str]) -> None:
            captured_events.append(event)

        def _fake_create_agent(**kwargs):  # noqa: ANN001
            return hanging

        import app.agent_runtime.comm_hub_client as comm_hub_module
        import app.services.agents.guardrail_callback as guardrail_cb_module
        import app.services.agents.langchain_tool_wrapper as tool_wrapper_module
        import langchain.agents as lc_agents

        started = time.monotonic()
        with patch.object(comm_hub_module, "CommHubToolClient", lambda: SimpleNamespace(set_certificate=lambda *a: None)), \
             patch.object(guardrail_cb_module, "GuardrailCallback", lambda **kwargs: SimpleNamespace()), \
             patch.object(tool_wrapper_module, "build_langchain_tools_for_ar_path", lambda **kwargs: []), \
             patch.object(lc_agents, "create_agent", _fake_create_agent):
            reply, _guardrail_usage, status_events = await executor.execute_conversation_turn_from_context(
                agent_type_id=uuid.uuid4(),
                agent_context={
                    "allowed_tools": [],
                    "tool_definitions": [],
                    "tool_name_map": {},
                    "role_id": None,
                    "model_id": "test-model",
                },
                model_config={"provider_type": "openai"},
                messages=[{"role": "user", "content": "hello"}],
                conv_session_id=uuid.uuid4(),
                status_event_callback=on_status_event,
            )
        elapsed = time.monotonic() - started

        # Bounded well under the 120s hang.
        assert elapsed < 30
        assert hanging.calls == 1
        assert "timed out" in reply.lower() or "too long" in reply.lower()
        all_events = captured_events + status_events
        assert any(e.get("status") == "timeout_or_failed" for e in all_events)
    finally:
        settings.conversation_llm_timeout_seconds = original


@pytest.mark.asyncio
async def test_conversation_turn_success_path_unaffected_by_timeout_bound() -> None:
    """A fast turn still completes normally and emits no timeout event."""
    settings = get_settings()
    original = settings.conversation_llm_timeout_seconds
    settings.conversation_llm_timeout_seconds = 30
    try:
        executor = AgentRuntimeExecutor(data_client=SimpleNamespace())

        class _FastAgent:
            async def ainvoke(self, messages, config):  # noqa: ANN001
                class _Msg:
                    type = "ai"
                    content = "all done"

                return {"messages": [_Msg()]}

        def _fake_create_agent(**kwargs):  # noqa: ANN001
            return _FastAgent()

        import app.agent_runtime.comm_hub_client as comm_hub_module
        import app.services.agents.guardrail_callback as guardrail_cb_module
        import app.services.agents.langchain_tool_wrapper as tool_wrapper_module
        import langchain.agents as lc_agents

        with patch.object(comm_hub_module, "CommHubToolClient", lambda: SimpleNamespace(set_certificate=lambda *a: None)), \
             patch.object(guardrail_cb_module, "GuardrailCallback", lambda **kwargs: SimpleNamespace()), \
             patch.object(tool_wrapper_module, "build_langchain_tools_for_ar_path", lambda **kwargs: []), \
             patch.object(lc_agents, "create_agent", _fake_create_agent):
            reply, _usage, status_events = await executor.execute_conversation_turn_from_context(
                agent_type_id=uuid.uuid4(),
                agent_context={
                    "allowed_tools": [],
                    "tool_definitions": [],
                    "tool_name_map": {},
                    "role_id": None,
                    "model_id": "test-model",
                },
                model_config={"provider_type": "openai"},
                messages=[{"role": "user", "content": "hello"}],
                conv_session_id=uuid.uuid4(),
            )

        assert reply == "all done"
        assert status_events == []
    finally:
        settings.conversation_llm_timeout_seconds = original
