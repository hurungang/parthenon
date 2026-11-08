"""Thinking-mode model / forced tool_choice fix (2026-11-08).

DeepSeek thinking-mode models (e.g. ``deepseek-v4-flash``) reject forced
``tool_choice`` with HTTP 400 ("Thinking mode does not support this
tool_choice"). LangChain's ToolStrategy (structured output) internally forces
tool_choice on a hidden response tool, so it must be skipped for thinking-mode
models — both via static detection (widened) and via a runtime fallback that
retries once without structured output when the provider still rejects it.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agents.runtime_executor import (
    AgentRuntimeExecutor,
    _is_thinking_mode_model,
)


# ── Static detection helper ──────────────────────────────────────────────────


class TestIsThinkingModeModel:
    def test_deepseek_reasoner_is_thinking(self) -> None:
        assert _is_thinking_mode_model("deepseek", "deepseek-reasoner") is True

    def test_deepseek_v4_flash_is_thinking(self) -> None:
        assert _is_thinking_mode_model("deepseek", "deepseek-v4-flash") is True

    def test_deepseek_chat_is_not_thinking(self) -> None:
        assert _is_thinking_mode_model("deepseek", "deepseek-chat") is False

    def test_any_provider_thinking_in_id_is_thinking(self) -> None:
        assert _is_thinking_mode_model("openai", "gpt-4o-thinking") is True

    def test_openai_plain_model_is_not_thinking(self) -> None:
        assert _is_thinking_mode_model("openai", "gpt-4o") is False

    def test_empty_inputs(self) -> None:
        assert _is_thinking_mode_model("", "") is False


# ── Executor-level runtime fallback ──────────────────────────────────────────


class _FakeBadRequest(Exception):
    """Mimics openai.BadRequestError generically (status_code attribute)."""

    status_code = 400


class _RetryThenSuccessAgent:
    """First invoke raises the provider 400; retry invoke succeeds."""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages, config):  # noqa: ANN001
        self.calls += 1
        if self.calls == 1:
            raise _FakeBadRequest(
                "Error code: 400 - {'error': {'message': "
                "'Thinking mode does not support this tool_choice', "
                "'type': 'invalid_request_error'}}"
            )

        class _Msg:
            type = "ai"
            content = "done after retry"

        return {"messages": [_Msg()]}


class TestRuntimeToolChoiceFallback:
    @pytest.mark.asyncio
    async def test_session_completes_after_retry_without_structured_output(self) -> None:
        executor = AgentRuntimeExecutor()
        executor._permission_manager = SimpleNamespace(
            get_allowed_tools_from_context=lambda x: []
        )
        data_client = AsyncMock()
        data_client.log_execution_event = AsyncMock()
        data_client.log_prompt = AsyncMock()
        data_client.get_agent_plan = AsyncMock(return_value=None)
        data_client.get_model_config = AsyncMock(return_value={"provider_type": "deepseek"})

        agent = _RetryThenSuccessAgent()
        captured_response_formats: list[object] = []

        def _fake_create_agent(**kwargs):  # noqa: ANN001
            captured_response_formats.append(kwargs.get("response_format"))
            return agent

        import app.agent_runtime.comm_hub_client as comm_hub_module
        import app.services.agents.guardrail_callback as guardrail_cb_module
        import app.services.agents.execution_logging_callback as exec_log_module
        import app.services.agents.langchain_model_factory as factory_module
        import app.services.agents.langchain_tool_wrapper as tool_wrapper_module
        import langchain.agents as lc_agents

        schema = {
            "title": "AgentOutput",
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        }
        # NOTE: "deepseek-chat" is NOT classified as thinking mode by static
        # detection — this simulates the catch-all: the provider still rejects
        # forced tool_choice, and the runtime fallback must recover.
        context = {
            "model_id": "deepseek-chat",
            "model_config_id": str(uuid.uuid4()),
            "input_type": "typed",
            "guardrail_policy": {},
            "system_instruction": "You are a booking agent.",
            "allowed_tools": [],
            "tool_definitions": [{"name": "noop", "description": "noop",
                                  "parameters": {"type": "object", "properties": {}}}],
            "tool_name_map": {},
            "output_json_schema": schema,
            "output_schema_prompt": "Respond with JSON matching the schema.",
            "role_id": None,
        }
        job_data = {
            "id": str(uuid.uuid4()),
            "agent_type_id": str(uuid.uuid4()),
            "input_data": {"message": "book a flight"},
        }

        from langchain.agents.structured_output import ToolStrategy

        with patch.object(comm_hub_module, "CommHubToolClient", lambda: SimpleNamespace(set_certificate=lambda *a: None)), \
        patch.object(guardrail_cb_module, "GuardrailCallback", lambda **kwargs: SimpleNamespace()), \
        patch.object(exec_log_module, "ExecutionLoggingCallback", lambda **kwargs: SimpleNamespace()), \
        patch.object(factory_module.LangChainModelFactory, "get_model_from_config_dict", lambda self, **kw: SimpleNamespace()), \
        patch.object(tool_wrapper_module, "build_langchain_tools_for_ar_path", lambda **kwargs: []), \
        patch.object(lc_agents, "create_agent", _fake_create_agent):
            output = await executor._run_task_loop_ar(job_data, context, data_client)

        assert output.get("result") == "done after retry"
        assert agent.calls == 2
        # First build used ToolStrategy; retry rebuilt without structured output.
        assert isinstance(captured_response_formats[0], ToolStrategy)
        assert captured_response_formats[1] is None


class TestRuntimeNonToolChoiceErrorNotRetried:
    @pytest.mark.asyncio
    async def test_unrelated_400_is_raised(self) -> None:
        """A 400 unrelated to tool_choice/thinking must propagate (no retry)."""

        class _OtherAgent:
            calls = 0

            async def ainvoke(self, messages, config):  # noqa: ANN001
                type(self).calls += 1
                exc = _FakeBadRequest("invalid api key")
                raise exc

        executor = AgentRuntimeExecutor()
        executor._permission_manager = SimpleNamespace(
            get_allowed_tools_from_context=lambda x: []
        )
        data_client = AsyncMock()
        data_client.log_execution_event = AsyncMock()
        data_client.log_prompt = AsyncMock()
        data_client.get_agent_plan = AsyncMock(return_value=None)
        data_client.get_model_config = AsyncMock(return_value={"provider_type": "deepseek"})

        agent = _OtherAgent()

        def _fake_create_agent(**kwargs):  # noqa: ANN001
            return agent

        import app.agent_runtime.comm_hub_client as comm_hub_module
        import app.services.agents.guardrail_callback as guardrail_cb_module
        import app.services.agents.execution_logging_callback as exec_log_module
        import app.services.agents.langchain_model_factory as factory_module
        import app.services.agents.langchain_tool_wrapper as tool_wrapper_module
        import langchain.agents as lc_agents

        context = {
            "model_id": "deepseek-v4-flash",
            "model_config_id": str(uuid.uuid4()),
            "input_type": "typed",
            "guardrail_policy": {},
            "system_instruction": "You are a booking agent.",
            "allowed_tools": [],
            "tool_definitions": [{"name": "noop", "description": "noop",
                                  "parameters": {"type": "object", "properties": {}}}],
            "tool_name_map": {},
            "output_json_schema": {"type": "object", "properties": {}},
            "role_id": None,
        }
        job_data = {
            "id": str(uuid.uuid4()),
            "agent_type_id": str(uuid.uuid4()),
            "input_data": {"message": "hello"},
        }

        with patch.object(comm_hub_module, "CommHubToolClient", lambda: SimpleNamespace(set_certificate=lambda *a: None)), \
        patch.object(guardrail_cb_module, "GuardrailCallback", lambda **kwargs: SimpleNamespace()), \
        patch.object(exec_log_module, "ExecutionLoggingCallback", lambda **kwargs: SimpleNamespace()), \
        patch.object(factory_module.LangChainModelFactory, "get_model_from_config_dict", lambda self, **kw: SimpleNamespace()), \
        patch.object(tool_wrapper_module, "build_langchain_tools_for_ar_path", lambda **kwargs: []), \
        patch.object(lc_agents, "create_agent", _fake_create_agent):
            with pytest.raises(_FakeBadRequest):
                await executor._run_task_loop_ar(job_data, context, data_client)

        assert agent.calls == 1
