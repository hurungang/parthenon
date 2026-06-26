"""Unit tests for LangChainToolWrapper — tool wrapping, mTLS dispatch, tool names.

Verifies:
- build_langchain_tools_from_definitions returns StructuredTool list
- Tools with no name are skipped
- Tool names are sanitized (/ and : replaced with _)
- _arun dispatches to comm_hub_client.call_tool()
- JSON serialisation of dict and list results
- Error dict returned on tool call failure
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── _sanitize_tool_name ────────────────────────────────────────────────────────


def test_sanitize_replaces_slash():
    from app.services.agents.langchain_tool_wrapper import _sanitize_tool_name
    assert _sanitize_tool_name("server/tool") == "server_tool"


def test_sanitize_replaces_colon():
    from app.services.agents.langchain_tool_wrapper import _sanitize_tool_name
    assert _sanitize_tool_name("tool:v2") == "tool_v2"


def test_sanitize_replaces_hyphen():
    from app.services.agents.langchain_tool_wrapper import _sanitize_tool_name
    assert _sanitize_tool_name("my-tool") == "my_tool"


def test_sanitize_replaces_dot():
    from app.services.agents.langchain_tool_wrapper import _sanitize_tool_name
    assert _sanitize_tool_name("my.tool") == "my_tool"


def test_sanitize_digit_prefix():
    from app.services.agents.langchain_tool_wrapper import _sanitize_tool_name
    assert _sanitize_tool_name("123tool") == "tool_123tool"


def test_sanitize_already_clean():
    from app.services.agents.langchain_tool_wrapper import _sanitize_tool_name
    assert _sanitize_tool_name("my_tool_name") == "my_tool_name"


# ── build_langchain_tools_from_definitions ────────────────────────────────────


def test_empty_definitions_returns_empty_list():
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_from_definitions

    tools = build_langchain_tools_from_definitions(
        tool_definitions=[],
        comm_hub_client=MagicMock(),
        session_id="sess-1",
        agent_type_id="at-1",
    )
    assert tools == []


def test_tool_without_name_is_skipped():
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_from_definitions

    defs = [{"type": "function", "function": {"name": "", "description": "bad"}}]
    tools = build_langchain_tools_from_definitions(
        tool_definitions=defs,
        comm_hub_client=MagicMock(),
        session_id="sess-1",
        agent_type_id="at-1",
    )
    assert tools == []


def test_single_tool_created_with_sanitized_name():
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_from_definitions
    from langchain_core.tools import StructuredTool

    defs = [
        {
            "type": "function",
            "function": {
                "name": "server/get_data",
                "description": "Get data from server",
                "parameters": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                },
            },
        }
    ]
    tools = build_langchain_tools_from_definitions(
        tool_definitions=defs,
        comm_hub_client=AsyncMock(),
        session_id="sess-1",
        agent_type_id="at-1",
    )
    assert len(tools) == 1
    tool = tools[0]
    assert isinstance(tool, StructuredTool)
    assert tool.name == "server_get_data"
    assert tool.description == "Get data from server"


def test_multiple_tools_created():
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_from_definitions

    defs = [
        {"type": "function", "function": {"name": f"tool_{i}", "description": f"Tool {i}"}}
        for i in range(3)
    ]
    tools = build_langchain_tools_from_definitions(
        tool_definitions=defs,
        comm_hub_client=AsyncMock(),
        session_id="sess-1",
        agent_type_id="at-1",
    )
    assert len(tools) == 3


# ── Tool dispatch via _arun ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_arun_calls_comm_hub_client():
    """_arun dispatches to comm_hub_client.call_tool with original (unsanitized) name."""
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_from_definitions

    mock_client = AsyncMock()
    mock_client.call_tool = AsyncMock(return_value={"result": "ok"})

    defs = [
        {
            "type": "function",
            "function": {
                "name": "server/my_tool",
                "description": "My tool",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                },
            },
        }
    ]
    tools = build_langchain_tools_from_definitions(
        tool_definitions=defs,
        comm_hub_client=mock_client,
        session_id="sess-123",
        agent_type_id="at-456",
    )
    tool = tools[0]

    # arun dispatches with original name
    result_str = await tool.arun({"value": 42})
    mock_client.call_tool.assert_called_once_with(
        tool_name="server/my_tool",
        tool_args={"value": 42},
        session_id="sess-123",
        agent_type_id="at-456",
    )
    result = json.loads(result_str)
    assert result["result"] == "ok"


@pytest.mark.asyncio
async def test_arun_returns_json_string_for_list_result():
    """_arun JSON-serialises list results."""
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_from_definitions

    mock_client = AsyncMock()
    mock_client.call_tool = AsyncMock(return_value=["item1", "item2"])

    defs = [{"type": "function", "function": {"name": "list_tool", "description": "Returns list"}}]
    tools = build_langchain_tools_from_definitions(
        tool_definitions=defs,
        comm_hub_client=mock_client,
        session_id="s",
        agent_type_id="a",
    )
    result_str = await tools[0].arun({})
    assert json.loads(result_str) == ["item1", "item2"]


@pytest.mark.asyncio
async def test_arun_returns_error_json_on_exception():
    """_arun returns error dict when call_tool raises."""
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_from_definitions

    mock_client = AsyncMock()
    mock_client.call_tool = AsyncMock(side_effect=RuntimeError("connection failed"))

    defs = [{"type": "function", "function": {"name": "fail_tool", "description": "Fails"}}]
    tools = build_langchain_tools_from_definitions(
        tool_definitions=defs,
        comm_hub_client=mock_client,
        session_id="s",
        agent_type_id="a",
    )
    result_str = await tools[0].arun({})
    result = json.loads(result_str)
    assert "error" in result
    assert "connection failed" in result["error"]


# ── _extract_delegation_target_slug ───────────────────────────────────────────


def test_extract_delegation_target_canonical():
    from app.services.agents.langchain_tool_wrapper import _extract_delegation_target_slug
    assert _extract_delegation_target_slug("agent____analyst") == "analyst"


def test_extract_delegation_target_sanitized():
    from app.services.agents.langchain_tool_wrapper import _extract_delegation_target_slug
    assert _extract_delegation_target_slug("agent__analyst") == "analyst"


def test_extract_delegation_target_returns_none_for_mcp():
    from app.services.agents.langchain_tool_wrapper import _extract_delegation_target_slug
    assert _extract_delegation_target_slug("server__my_tool") is None


def test_extract_delegation_target_returns_none_for_system():
    from app.services.agents.langchain_tool_wrapper import _extract_delegation_target_slug
    assert _extract_delegation_target_slug("system____save_result") is None


# ── Delegation tool routing (AR path) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_delegation_tool_calls_a2a_not_call_tool():
    """Agent delegation tools must route via call_a2a_request, NOT call_tool."""
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_for_ar_path

    mock_comm = AsyncMock()
    mock_comm.call_a2a_request = AsyncMock(return_value={"status": "completed"})
    mock_comm.call_tool = AsyncMock(return_value={"should": "not be called"})

    mock_data = AsyncMock()
    mock_data.log_execution_event = AsyncMock(return_value=None)

    defs = [
        {
            "type": "function",
            "function": {
                "name": "agent__analyst",
                "description": "Delegate to analyst agent",
                "parameters": {
                    "type": "object",
                    "properties": {"task": {"type": "string"}},
                },
            },
        }
    ]
    tools = build_langchain_tools_for_ar_path(
        tool_definitions=defs,
        comm_hub_client=mock_comm,
        data_client=mock_data,
        session_id="00000000-0000-0000-0000-000000000001",
        agent_type_id="at-1",
        role_id="role-1",
    )
    assert len(tools) == 1
    result_str = await tools[0].arun({"task": "analyse the data"})

    # Must use A2A, never the generic call_tool path
    mock_comm.call_a2a_request.assert_called_once()
    mock_comm.call_tool.assert_not_called()

    call_kwargs = mock_comm.call_a2a_request.call_args
    assert call_kwargs.kwargs["target_agent_type_slug"] == "analyst"
    assert call_kwargs.kwargs["requester_role_id"] == "role-1"

    result = json.loads(result_str)
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_delegation_tool_logs_started_and_resumed():
    """Delegation tool must log delegation_started and delegation_resumed events."""
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_for_ar_path

    mock_comm = AsyncMock()
    mock_comm.call_a2a_request = AsyncMock(return_value={"result": "ok"})

    logged_events: list[str] = []

    async def log_event(session_id, event_type, message, data, **_):
        logged_events.append(event_type)

    mock_data = AsyncMock()
    mock_data.log_execution_event = log_event

    defs = [
        {"type": "function", "function": {"name": "agent__researcher", "description": "Researcher"}},
    ]
    tools = build_langchain_tools_for_ar_path(
        tool_definitions=defs,
        comm_hub_client=mock_comm,
        data_client=mock_data,
        session_id="00000000-0000-0000-0000-000000000002",
        agent_type_id="at-1",
    )
    await tools[0].arun({})

    assert "delegation_started" in logged_events
    assert "delegation_resumed" in logged_events


@pytest.mark.asyncio
async def test_delegation_tool_logs_failed_on_error():
    """Delegation tool must log delegation_failed when call_a2a_request raises."""
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_for_ar_path

    mock_comm = AsyncMock()
    mock_comm.call_a2a_request = AsyncMock(side_effect=RuntimeError("timeout"))

    logged_events: list[str] = []

    async def log_event(session_id, event_type, message, data, **_):
        logged_events.append(event_type)

    mock_data = AsyncMock()
    mock_data.log_execution_event = log_event

    defs = [
        {"type": "function", "function": {"name": "agent__worker", "description": "Worker"}},
    ]
    tools = build_langchain_tools_for_ar_path(
        tool_definitions=defs,
        comm_hub_client=mock_comm,
        data_client=mock_data,
        session_id="00000000-0000-0000-0000-000000000003",
        agent_type_id="at-1",
    )
    result_str = await tools[0].arun({})

    assert "delegation_failed" in logged_events
    result = json.loads(result_str)
    assert "error" in result


@pytest.mark.asyncio
async def test_regular_tool_still_uses_call_tool():
    """Non-delegation tools must still use call_tool (not a2a)."""
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_for_ar_path

    mock_comm = AsyncMock()
    mock_comm.call_tool = AsyncMock(return_value={"data": "value"})
    mock_comm.call_a2a_request = AsyncMock()

    mock_data = AsyncMock()
    mock_data.log_execution_event = AsyncMock(return_value=None)

    defs = [
        {"type": "function", "function": {"name": "server__search", "description": "Search tool"}},
    ]
    tools = build_langchain_tools_for_ar_path(
        tool_definitions=defs,
        comm_hub_client=mock_comm,
        data_client=mock_data,
        session_id="00000000-0000-0000-0000-000000000004",
        agent_type_id="at-1",
    )
    await tools[0].arun({"query": "test"})

    mock_comm.call_tool.assert_called_once()
    mock_comm.call_a2a_request.assert_not_called()
