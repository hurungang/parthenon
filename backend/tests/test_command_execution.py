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


# ── Issue regression: the command run's final output serves the OPERATOR ─────


def test_command_mission_final_answer_is_operator_facing_status_report():
    """The reworded mission separates 'author + verify the plan via tools'
    from 'report the outcome in the final message': an optimization run is not
    a business run, so the final message is a concise operator-facing status."""
    from app.services.agents.command_prompts import (
        OPTIMIZE_AND_VERIFY_COMMAND,
        build_command_mission,
    )

    mission = build_command_mission(OPTIMIZE_AND_VERIFY_COMMAND, agent_type_id="x")
    normalized = " ".join(mission.split())
    assert "Final answer" in mission
    assert (
        "Your FINAL message must be a short status report for the operator"
        in normalized
    )
    assert "This is an optimization run, not a business run" in normalized
    assert "keep the final message concise and operator-facing" in normalized


def test_command_mission_verifies_syntax_and_tool_invocation_not_identical_output():
    """The optimization goal is correct script syntax + correct tool
    invocation — NOT reproducing the reference execution's output. Differing
    or empty tool results must not trigger re-attempts."""
    from app.services.agents.command_prompts import OPTIMIZE_AND_VERIFY_COMMAND

    normalized = " ".join(OPTIMIZE_AND_VERIFY_COMMAND.split())
    assert "correct syntax" in normalized
    assert "invokes the agent's tools CORRECTLY" in normalized
    # The identical-result framing is explicitly rejected.
    assert "A script does NOT need to reproduce the reference execution's tool" in normalized
    assert "do NOT treat it as a failure" in normalized
    assert "NEVER re-attempt a script merely to force an output match" in normalized
    assert "Do NOT re-attempt it to force an identical result" in normalized


def test_command_mission_mandates_bounded_needs_feedback_stop_with_error():
    """No dead loop: when confidence cannot be reached the run MUST stop and
    persist ``needs_feedback`` with a mandatory ``error`` reason."""
    from app.services.agents.command_prompts import OPTIMIZE_AND_VERIFY_COMMAND

    normalized = " ".join(OPTIMIZE_AND_VERIFY_COMMAND.split())
    assert "needs_feedback" in normalized
    assert "you MUST STOP" in normalized
    assert "`error` is MANDATORY" in normalized
    assert "no dead loop" in normalized
    assert "never keep retrying to avoid it" in normalized
    # Per-script retries are explicitly bounded.
    assert "Bounded 3 attempts per script" in normalized


@pytest.mark.asyncio
async def test_command_run_final_message_is_passed_through():
    """A command run completes with its final assistant message as the session
    output (the optimize mission defines that message as an operator-facing
    status report; the executor must not rewrite it)."""
    from langchain_core.messages import AIMessage

    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()
    session_id = str(uuid.uuid4())
    agent_type_id = str(uuid.uuid4())

    status_report = (
        "Optimized plan authored and verified. Script `fetch-contact` compiles "
        "and its tool calls validate. No re-authoring was needed."
    )
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
    fake_agent.ainvoke = AsyncMock(
        return_value={"messages": [AIMessage(content=status_report)]}
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

    assert output_data.get("result") == status_report
