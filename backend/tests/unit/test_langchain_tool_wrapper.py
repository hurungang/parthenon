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
    assert _extract_delegation_target_slug("system____save_data") is None


# ── Delegation tool routing (AR path) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_delegation_tool_calls_a2a_not_call_tool():
    """Agent delegation tools must route via call_a2a_request, NOT call_tool."""
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_for_ar_path

    mock_comm = AsyncMock()
    mock_comm.call_a2a_request = AsyncMock(
        return_value={"status": "accepted", "receiver_session_id": "rcv-analyst-1"}
    )
    mock_comm.wait_for_a2a_response = AsyncMock(
        return_value={"status": "completed", "output_data": {"status": "completed", "result": "analysis done"}}
    )
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


# ── Delegation depth guard (AR path) ─────────────────────────────────────────

_DEPTH_SESSION_ID = "00000000-0000-0000-0000-0000000000d1"


def _make_depth_guardrail_state(
    *,
    tree_depth: int = 0,
    delegation_depth: int = 0,
    max_depth: int = 3,
):
    """Build a real RuntimeGuardrailState with the given depth configuration."""
    from app.services.agents.guardrails import RuntimeGuardrailState

    return RuntimeGuardrailState(
        max_iterations=10,
        max_delegation_depth=max_depth,
        max_delegated_steps=20,
        execution_timeout_seconds=300,
        token_budget=None,
        token_enforcement_mode="observe",
        token_fallback_mode="observe_and_log",
        conversational_token_visibility_mode="enabled",
        conversational_continuation_policy="allow",
        policy_snapshot_id="agent_type:test",
        delegation_depth=delegation_depth,
        tree_depth=tree_depth,
    )


def _depth_guard_tools(guardrail_state, captured_events: list[dict], captured_status: list[dict]):
    """Build one delegation tool plus its mocked CommHub/data clients."""
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_for_ar_path

    mock_comm = AsyncMock()
    mock_comm.call_a2a_request = AsyncMock(
        return_value={"status": "accepted", "receiver_session_id": "rcv-depth-1"}
    )
    mock_comm.wait_for_a2a_response = AsyncMock(
        return_value={"status": "completed", "output_data": {"result": "done"}}
    )
    mock_comm.call_tool = AsyncMock(return_value={"should": "not be called"})

    async def log_event(session_id, event_type, message, data, **_):
        captured_events.append({"event_type": event_type, "message": message, "data": data})

    async def status_event(event: dict) -> None:
        captured_status.append(event)

    mock_data = AsyncMock()
    mock_data.log_execution_event = log_event

    tools = build_langchain_tools_for_ar_path(
        tool_definitions=[
            {
                "type": "function",
                "function": {
                    "name": "agent____analyst",
                    "description": "Delegate to analyst agent",
                    "parameters": {
                        "type": "object",
                        "properties": {"task": {"type": "string"}},
                    },
                },
            }
        ],
        comm_hub_client=mock_comm,
        data_client=mock_data,
        session_id=_DEPTH_SESSION_ID,
        agent_type_id="at-1",
        role_id="role-1",
        guardrail_state=guardrail_state,
        status_event_callback=status_event,
    )
    assert len(tools) == 1
    return tools[0], mock_comm, mock_data


@pytest.mark.asyncio
async def test_delegation_blocked_when_at_configured_maximum():
    """A run already at its configured maximum must not dispatch an over-depth hop."""
    captured_events: list[dict] = []
    captured_status: list[dict] = []
    state = _make_depth_guardrail_state(tree_depth=3, delegation_depth=3, max_depth=3)
    tool, mock_comm, _ = _depth_guard_tools(state, captured_events, captured_status)

    result = json.loads(await tool.arun({"task": "analyse"}))

    assert result["blocked"] is True
    assert "delegating from depth 3" in result["reason"]
    assert "configured maximum delegation depth of 3" in result["reason"]

    # Nothing is dispatched.
    mock_comm.call_a2a_request.assert_not_called()
    mock_comm.wait_for_a2a_response.assert_not_called()
    mock_comm.call_tool.assert_not_called()

    # Policy block is recorded with the configured maximum and the hop depth.
    blocked = [e for e in captured_events if e["event_type"] == "delegation_depth_blocked"]
    assert len(blocked) == 1
    assert blocked[0]["data"] == {
        "delegation_target": "analyst",
        "current_depth": 3,
        "next_depth": 4,
        "max_depth": 3,
    }
    # The hop is blocked BEFORE delegation_started / waiting are logged.
    event_types = [e["event_type"] for e in captured_events]
    assert "delegation_started" not in event_types
    assert "delegation_waiting" not in event_types
    assert captured_status == []

    # Counters do not move.
    assert state.delegated_steps == 0
    assert state.delegation_depth == 3
    assert state.tree_depth == 3


@pytest.mark.asyncio
async def test_delegation_allowed_below_configured_maximum():
    """A hop that stays within the configured maximum keeps existing behaviour."""
    captured_events: list[dict] = []
    captured_status: list[dict] = []
    state = _make_depth_guardrail_state(tree_depth=2, delegation_depth=2, max_depth=3)
    tool, mock_comm, _ = _depth_guard_tools(state, captured_events, captured_status)

    result = json.loads(await tool.arun({"task": "analyse"}))

    assert result == {"result": "done"}
    mock_comm.call_a2a_request.assert_called_once()
    call_kwargs = mock_comm.call_a2a_request.call_args.kwargs
    assert call_kwargs["target_agent_type_slug"] == "analyst"
    assert call_kwargs["wait_for_response"] is False

    event_types = [e["event_type"] for e in captured_events]
    assert "delegation_depth_blocked" not in event_types
    assert "delegation_started" in event_types
    assert "delegation_waiting" in event_types
    assert "delegation_resumed" in event_types

    status_kinds = [e["status"] for e in captured_status]
    assert status_kinds == ["using_tool", "delegating", "waiting", "waiting", "delegation_resumed"]

    # Hop counters advance as before (next hop reaches the last permitted level).
    assert state.delegated_steps == 1
    assert state.delegation_depth == 3
    assert state.tree_depth == 2


@pytest.mark.asyncio
async def test_delegation_blocked_at_root_with_configured_max_zero():
    """Configured maximum 0 blocks the first hop from the root."""
    captured_events: list[dict] = []
    captured_status: list[dict] = []
    state = _make_depth_guardrail_state(tree_depth=0, delegation_depth=0, max_depth=0)
    tool, mock_comm, _ = _depth_guard_tools(state, captured_events, captured_status)

    result = json.loads(await tool.arun({"task": "analyse"}))

    assert result["blocked"] is True
    assert "delegating from depth 0" in result["reason"]
    assert "configured maximum delegation depth of 0" in result["reason"]
    mock_comm.call_a2a_request.assert_not_called()

    blocked = [e for e in captured_events if e["event_type"] == "delegation_depth_blocked"]
    assert len(blocked) == 1
    assert blocked[0]["data"]["current_depth"] == 0
    assert blocked[0]["data"]["next_depth"] == 1
    assert blocked[0]["data"]["max_depth"] == 0
    assert state.delegated_steps == 0
    assert state.delegation_depth == 0


@pytest.mark.asyncio
async def test_delegation_without_guardrail_state_is_unchanged():
    """No guardrail state → no depth guard (legacy behaviour preserved)."""
    captured_events: list[dict] = []
    captured_status: list[dict] = []
    tool, mock_comm, _ = _depth_guard_tools(None, captured_events, captured_status)

    await tool.arun({"task": "analyse"})

    mock_comm.call_a2a_request.assert_called_once()
    assert "delegation_depth_blocked" not in [e["event_type"] for e in captured_events]


# ── build_langchain_tools_for_ar_path: other tools ────────────────────────────


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


@pytest.mark.asyncio
async def test_arun_accepts_normalised_key_for_hyphenated_schema_property():
    """LLMs normalise hyphenated keys (project-id → project_id); both forms must
    dispatch with the schema's ORIGINAL key so receivers validating typed input
    (e.g. A2A enqueue requiring ``project-id``) accept the payload."""
    from app.services.agents.langchain_tool_wrapper import build_langchain_tools_for_ar_path

    mock_client = AsyncMock()
    mock_client.call_a2a_request = AsyncMock(return_value={"receiver_session_id": "rx-1"})
    mock_client.wait_for_a2a_response = AsyncMock(
        return_value={"status": "completed", "output_data": {"result": "done"}}
    )
    mock_data_client = MagicMock()

    defs = [
        {
            "type": "function",
            "function": {
                "name": "agent____target-agent",
                "description": "Delegate to target agent",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project-id": {"type": "string", "description": "The project id"},
                        "session_link_id": {
                            "type": "string",
                            "description": "Optional existing A2A session link",
                        },
                    },
                    "required": ["project-id"],
                },
            },
        }
    ]
    tools = build_langchain_tools_for_ar_path(
        tool_definitions=defs,
        comm_hub_client=mock_client,
        data_client=mock_data_client,
        session_id="sess-1",
        agent_type_id="at-1",
        role_id=None,
    )
    assert len(tools) == 1
    tool = tools[0]

    # The LLM sends the normalised (snake_case) key — must still validate and
    # dispatch with the schema's original hyphenated key.
    result_str = await tool.arun({"project_id": "abc123"})
    payload = mock_client.call_a2a_request.call_args.kwargs["request_payload"]
    assert payload == {"project-id": "abc123"}
    assert "error" not in json.loads(result_str)

    mock_client.call_a2a_request.reset_mock()
    # The exact hyphenated key also keeps working.
    await tool.arun({"project-id": "xyz789"})
    payload = mock_client.call_a2a_request.call_args.kwargs["request_payload"]
    assert payload == {"project-id": "xyz789"}
