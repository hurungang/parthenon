"""Command-driven special executions (e.g. "optimize-and-verify").

Covers the executor-side contract for command executions:

- A command execution exposes the command's optimization system tools in the
  LLM toolset (they are NOT part of the agent type's permission-scoped allowed
  tools), and
- the dispatcher never intercepts a command execution (covered in
  ``test_script_first_dispatcher.py``) — here we assert the tool wiring.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agents.command_prompts import (
    OPTIMIZE_AND_VERIFY_SLUG,
    OPTIMIZE_AND_VERIFY_TOOLS,
)


# ── Pure helper ────────────────────────────────────────────────────────────────


def test_command_tool_schemas_returns_optimization_tools():
    from app.services.agents.runtime_executor import _command_tool_schemas

    schemas = _command_tool_schemas(OPTIMIZE_AND_VERIFY_SLUG)
    names = [s["function"]["name"] for s in schemas]
    assert set(names) == set(OPTIMIZE_AND_VERIFY_TOOLS)


def test_command_tool_schemas_empty_for_non_command():
    from app.services.agents.runtime_executor import _command_tool_schemas

    assert _command_tool_schemas(None) == []
    assert _command_tool_schemas("") == []
    assert _command_tool_schemas("unknown-command") == []


# ── Executor integration (mock LLM) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_command_execution_wires_optimization_tools_into_llm_toolset():
    """A command execution appends the optimization system tools to the LLM
    toolset — even though the agent type's permission-scoped allowed tools do
    not include them."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    session_id = str(uuid.uuid4())
    agent_type_id = str(uuid.uuid4())

    job_data = {
        "id": session_id,
        "agent_type_id": agent_type_id,
        "input_data": {
            "__command": OPTIMIZE_AND_VERIFY_SLUG,
            "message": "author the optimized plan",
        },
    }
    context = {
        "model_id": "gpt-4o-mini",
        "model_config_id": str(uuid.uuid4()),
        "system_instruction": "you are the agent",
        "allowed_tools": [],
        "allowed_agent_types": [],
        "tool_name_map": {},
        "tool_definitions": [],  # NOTHING permission-scoped for this role
        "role_mcp_sessions": {},
        "role_id": None,
        "identity_name": None,
        "role_name": None,
        "sops": [],
        "skills": [],
        "input_type": "typed",
    }
    data_client = AsyncMock()
    data_client.get_model_config = AsyncMock(return_value={"provider_type": "openai"})
    data_client.get_agent_plan = AsyncMock(return_value=None)
    data_client.log_execution_event = AsyncMock()
    data_client.log_prompt = AsyncMock()

    captured: dict = {}

    def _fake_build_tools(**kwargs):
        captured["tool_definitions"] = kwargs["tool_definitions"]
        return []

    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(return_value={"messages": []})

    with patch.object(
        executor, "_append_invocable_script_tools", new=AsyncMock()
    ), patch(
        "app.services.agents.langchain_tool_wrapper.build_langchain_tools_for_ar_path",
        side_effect=_fake_build_tools,
    ), patch(
        "langchain.agents.create_agent", return_value=fake_agent
    ), patch(
        "app.services.agents.langchain_model_factory.LangChainModelFactory"
        ".get_model_from_config_dict",
        return_value=MagicMock(),
    ):
        await executor._run_task_loop_ar(job_data, context, data_client)

    names = [
        td["function"]["name"] for td in captured["tool_definitions"]
    ]
    assert set(OPTIMIZE_AND_VERIFY_TOOLS) <= set(names)


@pytest.mark.asyncio
async def test_non_command_execution_does_not_add_command_tools():
    """Regression: a NON-command execution keeps only the permission-scoped
    toolset — it does not get the optimization system tools."""
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    session_id = str(uuid.uuid4())
    agent_type_id = str(uuid.uuid4())

    job_data = {
        "id": session_id,
        "agent_type_id": agent_type_id,
        "input_data": {"message": "run the workflow"},
    }
    context = {
        "model_id": "gpt-4o-mini",
        "model_config_id": str(uuid.uuid4()),
        "system_instruction": "you are the agent",
        "allowed_tools": ["save_data"],
        "allowed_agent_types": [],
        "tool_name_map": {},
        "tool_definitions": [
            {
                "type": "function",
                "function": {"name": "save_data", "parameters": {"type": "object"}},
            }
        ],
        "role_mcp_sessions": {},
        "role_id": None,
        "identity_name": None,
        "role_name": None,
        "sops": [],
        "skills": [],
        "input_type": "typed",
    }
    data_client = AsyncMock()
    data_client.get_model_config = AsyncMock(return_value={"provider_type": "openai"})
    data_client.get_agent_plan = AsyncMock(return_value=None)
    data_client.log_execution_event = AsyncMock()
    data_client.log_prompt = AsyncMock()

    captured: dict = {}

    def _fake_build_tools(**kwargs):
        captured["tool_definitions"] = kwargs["tool_definitions"]
        return []

    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(return_value={"messages": []})

    with patch.object(
        executor, "_append_invocable_script_tools", new=AsyncMock()
    ), patch(
        "app.services.agents.langchain_tool_wrapper.build_langchain_tools_for_ar_path",
        side_effect=_fake_build_tools,
    ), patch(
        "langchain.agents.create_agent", return_value=fake_agent
    ), patch(
        "app.services.agents.langchain_model_factory.LangChainModelFactory"
        ".get_model_from_config_dict",
        return_value=MagicMock(),
    ):
        await executor._run_task_loop_ar(job_data, context, data_client)

    names = [
        td["function"]["name"] for td in captured["tool_definitions"]
    ]
    assert set(OPTIMIZE_AND_VERIFY_TOOLS).isdisjoint(set(names))


# ── Bug: command runs must not die on a tight token budget ────────────────────


class TestCommandTokenBudget:
    def _executor(self):
        from app.services.agents.runtime_executor import AgentRuntimeExecutor

        return AgentRuntimeExecutor()

    def _job(self, command: bool):
        input_data = {"message": "run"} if not command else {
            "__command": OPTIMIZE_AND_VERIFY_SLUG,
            "message": "author the optimized plan",
        }
        return {"id": str(uuid.uuid4()), "input_data": input_data}

    def _context(self, token_budget):
        policy = {} if token_budget is None else {"token_budget": token_budget}
        return {
            "guardrail_policy": policy,
            "input_type": "typed",
        }

    def test_command_run_gets_generous_token_budget_over_policy(self):
        from app.services.agents.command_prompts import COMMAND_TOKEN_BUDGET

        guardrail = self._executor()._build_guardrail_state(
            self._context(50_000), self._job(command=True)
        )
        assert guardrail.token_budget == COMMAND_TOKEN_BUDGET
        assert guardrail.token_budget > 50_000

    def test_command_run_without_policy_budget_gets_command_budget(self):
        from app.services.agents.command_prompts import COMMAND_TOKEN_BUDGET

        guardrail = self._executor()._build_guardrail_state(
            self._context(None), self._job(command=True)
        )
        assert guardrail.token_budget == COMMAND_TOKEN_BUDGET

    def test_non_command_run_keeps_policy_budget(self):
        guardrail = self._executor()._build_guardrail_state(
            self._context(123_456), self._job(command=False)
        )
        assert guardrail.token_budget == 123_456


# ── Issue regression: the command run's final output serves the USER ──────────


def test_command_mission_final_answer_is_business_result_not_meta_talk():
    """The command prompt must separate 'do the task for the user' (final
    message = the user's result in the required format) from 'record
    optimization details via your tools, not in your final message'."""
    from app.services.agents.command_prompts import (
        OPTIMIZE_AND_VERIFY_COMMAND,
        build_command_mission,
    )

    mission = build_command_mission(OPTIMIZE_AND_VERIFY_COMMAND, agent_type_id="x")
    normalized = " ".join(mission.split())
    assert "Final answer" in mission
    assert "Your FINAL message must BE the user-facing result of that task" in normalized
    assert "ONLY into the optimized plan record through your tools" in normalized
    assert "never into your final message" in normalized
    # The old meta-report instruction is gone.
    assert "Respond with a concise summary of what you found" not in mission


@pytest.mark.asyncio
async def test_command_run_final_answer_is_business_result():
    """Regression: a command run with a mocked LLM whose scripted final
    response is the business result completes with THAT result as the session
    output — no optimization meta-talk leaks into the user-facing result."""
    from langchain_core.messages import AIMessage

    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    session_id = str(uuid.uuid4())
    agent_type_id = str(uuid.uuid4())

    business_result = (
        "# Q3 Sales Summary\n\nTotal revenue: $1.2M (up 8% QoQ).\n"
        "Top region: EMEA. Churn: 2.1%."
    )
    job_data = {
        "id": session_id,
        "agent_type_id": agent_type_id,
        "input_data": {
            "__command": OPTIMIZE_AND_VERIFY_SLUG,
            "message": "produce the Q3 sales summary",
        },
    }
    context = {
        "model_id": "gpt-4o-mini",
        "model_config_id": str(uuid.uuid4()),
        "system_instruction": "you are the agent",
        "allowed_tools": [],
        "allowed_agent_types": [],
        "tool_name_map": {},
        "tool_definitions": [],
        "role_mcp_sessions": {},
        "role_id": None,
        "identity_name": None,
        "role_name": None,
        "sops": [],
        "skills": [],
        "input_type": "typed",
    }
    data_client = AsyncMock()
    data_client.get_model_config = AsyncMock(return_value={"provider_type": "openai"})
    data_client.get_agent_plan = AsyncMock(return_value=None)
    data_client.log_execution_event = AsyncMock()
    data_client.log_prompt = AsyncMock()

    fake_agent = MagicMock()
    # The scripted final response IS the business result.
    fake_agent.ainvoke = AsyncMock(
        return_value={"messages": [AIMessage(content=business_result)]}
    )

    with patch.object(
        executor, "_append_invocable_script_tools", new=AsyncMock()
    ), patch(
        "app.services.agents.langchain_tool_wrapper.build_langchain_tools_for_ar_path",
        return_value=[],
    ), patch(
        "langchain.agents.create_agent", return_value=fake_agent
    ), patch(
        "app.services.agents.langchain_model_factory.LangChainModelFactory"
        ".get_model_from_config_dict",
        return_value=MagicMock(),
    ):
        output_data = await executor._run_task_loop_ar(job_data, context, data_client)

    result = output_data.get("result")
    assert result == business_result
    # No optimization meta-talk in the user-facing result.
    lowered = str(result).lower()
    for meta_marker in ("optimized plan", "generate_script", "verification",
                        "tool-name", "authored"):
        assert meta_marker not in lowered
