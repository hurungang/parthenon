"""FIX-20260518-153000: Conversational agents must route MCP tool calls through CommHubToolClient.

FAILING TESTS — these reproduce the architecture violation described in:
  docs/changes/service-decomposition/fix-log.md  (FIX-20260518-153000)

Bug summary:
  - Task agents (non-conversational):  tool calls → _execute_mcp_tool_ar → CommHubToolClient  ✓ CORRECT
  - Conversational agents:             tool calls → _execute_mcp_tool    → McpProxyEngine      ✗ WRONG

Both agent types must route ALL tool calls through CommHubToolClient and Communication Hub.

These tests CURRENTLY FAIL and will PASS when the bug is fixed.
"""
from __future__ import annotations

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

def _make_mcp_tool_response(call_id: str = "call_mcp001") -> dict:
    """Return an OpenAI-format LLM response that requests one MCP tool call."""
    return {
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        # Sanitized MCP name: "hello-world/helloWorld" → "hello_world__helloWorld"
                        "name": "hello_world__helloWorld",
                        "arguments": '{"name": "integration-test"}',
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }]
    }


def _make_final_response(text: str = "Tool executed.") -> dict:
    """Return an OpenAI-format LLM response with no further tool calls."""
    return {
        "choices": [{
            "message": {
                "content": text,
                "tool_calls": [],
            },
            "finish_reason": "stop",
        }]
    }


def _build_executor_with_mocks() -> tuple:
    """
    Build an AgentRuntimeExecutor with all DB-dependent helpers pre-mocked.

    Returns (executor, mock_model_config, call_id) so callers can stage
    further assertions.
    """
    from app.services.agents.runtime_executor import AgentRuntimeExecutor

    executor = AgentRuntimeExecutor()

    # Mock all helpers that hit the database — we only care about which
    # tool-dispatch method is ultimately called.
    tool_def = {
        "type": "function",
        "function": {
            "name": "hello_world__helloWorld",
            "description": "Calls hello-world MCP tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    tool_name_map = {"hello_world__helloWorld": "hello-world/helloWorld"}

    executor._load_tool_definitions = AsyncMock(return_value=([tool_def], tool_name_map))
    executor._load_role_mcp_session_map = AsyncMock(return_value={})
    executor._permission_manager.calculate_allowed_tools = AsyncMock(
        return_value={"hello-world/helloWorld"}
    )
    # check_tool_allowed is sync — MagicMock default (does not raise)
    executor._permission_manager.check_tool_allowed = MagicMock()

    mock_model_config = MagicMock()
    mock_model_config.provider_type = "openai"

    return executor, mock_model_config


# ---------------------------------------------------------------------------
# Test 1 (PRIMARY): conversational agents MUST call _execute_mcp_tool_ar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conversation_turn_routes_tool_calls_through_comm_hub_client():
    """
    BUG REPRODUCTION (FIX-20260518-153000):

    execute_conversation_turn MUST route external MCP tool calls through
    _execute_mcp_tool_ar (CommHubToolClient / Communication Hub), matching
    the path used by task agents.

    CURRENTLY FAILS because execute_conversation_turn calls the old
    _execute_mcp_tool() method (McpProxyEngine + direct DB) and never
    calls _execute_mcp_tool_ar at all.

    WILL PASS when execute_conversation_turn is fixed to use CommHubToolClient.
    """
    executor, mock_model_config = _build_executor_with_mocks()

    agent_type = MagicMock()
    agent_type.id = uuid.uuid4()
    agent_type.role_id = uuid.uuid4()
    agent_type.model_id = "gpt-4o"

    db = AsyncMock()
    conv_session_id = uuid.uuid4()
    messages = [{"role": "user", "content": "Call the hello-world tool for me"}]

    mock_binding_instance = MagicMock()
    mock_binding_instance.resolve_model_config = AsyncMock(return_value=mock_model_config)
    # First LLM call: tool call requested; second: final text answer
    mock_binding_instance.complete = AsyncMock(
        side_effect=[_make_mcp_tool_response(), _make_final_response()]
    )

    # Replace BOTH dispatch methods with AsyncMocks so we can spy on which one fires.
    executor._execute_mcp_tool_ar = AsyncMock(return_value={"result": "Hello from CommHub!"})
    executor._execute_mcp_tool = AsyncMock(return_value={"result": "Hello from McpProxy (WRONG)!"})

    # Import the real static methods so the extract_* calls in execute_conversation_turn work.
    from app.services.agents.model_binding import ModelBindingLayer as _RealMBL

    with patch("app.services.agents.model_binding.ModelBindingLayer") as MockMBL:
        MockMBL.return_value = mock_binding_instance
        MockMBL.extract_text = staticmethod(_RealMBL.extract_text)
        MockMBL.extract_tool_calls = staticmethod(_RealMBL.extract_tool_calls)

        await executor.execute_conversation_turn(
            agent_type=agent_type,
            messages=messages,
            conv_session_id=conv_session_id,
            db=db,
        )

    # ── ASSERTION: the CommHubToolClient dispatch path MUST have been used ──
    # CURRENTLY FAILS:
    #   execute_conversation_turn never calls _execute_mcp_tool_ar.
    #   It calls _execute_mcp_tool (old path) instead.
    # WILL PASS when the fix routes conversational tool calls through CommHubToolClient.
    executor._execute_mcp_tool_ar.assert_called_once()


# ---------------------------------------------------------------------------
# Test 2 (SECONDARY): conversational agents MUST NOT use McpProxyEngine directly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conversation_turn_does_not_use_mcp_proxy_engine_directly():
    """
    BUG REPRODUCTION (FIX-20260518-153000):

    execute_conversation_turn must NOT dispatch external MCP tool calls through
    _execute_mcp_tool (which uses McpProxyEngine with direct database access).

    CURRENTLY FAILS because _execute_mcp_tool IS called when a conversational
    agent makes an MCP tool call (the wrong architecture).

    WILL PASS when the bug is fixed and _execute_mcp_tool is no longer called.
    """
    executor, mock_model_config = _build_executor_with_mocks()

    agent_type = MagicMock()
    agent_type.id = uuid.uuid4()
    agent_type.role_id = uuid.uuid4()
    agent_type.model_id = "gpt-4o"

    db = AsyncMock()
    conv_session_id = uuid.uuid4()
    messages = [{"role": "user", "content": "Call the hello-world tool for me"}]

    mock_binding_instance = MagicMock()
    mock_binding_instance.resolve_model_config = AsyncMock(return_value=mock_model_config)
    mock_binding_instance.complete = AsyncMock(
        side_effect=[_make_mcp_tool_response(), _make_final_response()]
    )

    # Replace BOTH dispatch methods with AsyncMocks so we can spy on which one fires.
    executor._execute_mcp_tool_ar = AsyncMock(return_value={"result": "Hello from CommHub!"})
    executor._execute_mcp_tool = AsyncMock(return_value={"result": "Hello from McpProxy (WRONG)!"})

    from app.services.agents.model_binding import ModelBindingLayer as _RealMBL

    with patch("app.services.agents.model_binding.ModelBindingLayer") as MockMBL:
        MockMBL.return_value = mock_binding_instance
        MockMBL.extract_text = staticmethod(_RealMBL.extract_text)
        MockMBL.extract_tool_calls = staticmethod(_RealMBL.extract_tool_calls)

        await executor.execute_conversation_turn(
            agent_type=agent_type,
            messages=messages,
            conv_session_id=conv_session_id,
            db=db,
        )

    # ── ASSERTION: the old McpProxyEngine path must NOT have been used ──────
    # CURRENTLY FAILS:
    #   execute_conversation_turn calls _execute_mcp_tool for external MCP tools,
    #   meaning McpProxyEngine was invoked with direct database access.
    # WILL PASS when the fix removes _execute_mcp_tool from the conversation path.
    executor._execute_mcp_tool.assert_not_called()
