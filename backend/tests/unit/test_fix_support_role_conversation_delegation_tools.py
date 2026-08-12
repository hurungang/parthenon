import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agents.runtime_executor import AgentRuntimeExecutor
from app.services.agents.tool_naming import build_tool_name


@pytest.mark.asyncio
async def test_conversation_turn_includes_delegated_agent_tools_from_role_permissions() -> None:
    executor = AgentRuntimeExecutor()

    agent_type = SimpleNamespace(
        id=uuid.uuid4(),
        role_id=uuid.uuid4(),
        model_id=uuid.uuid4(),
    )
    conv_session_id = uuid.uuid4()
    db = AsyncMock()
    _db_result = MagicMock()
    _db_result.fetchall.return_value = []
    db.execute.return_value = _db_result

    executor._permission_manager.calculate_allowed_tools = AsyncMock(return_value=set())
    executor._permission_manager.calculate_allowed_agent_types = AsyncMock(
        return_value={"supabase-agent"}
    )
    executor._load_tool_definitions = AsyncMock(return_value=([], {}))
    executor._load_role_mcp_session_map = AsyncMock(return_value={})

    with patch("app.services.agents.model_binding.ModelBindingLayer") as model_binding_cls, patch(
        "app.agent_runtime.comm_hub_client.CommHubToolClient"
    ):
        binding = model_binding_cls.return_value
        binding.resolve_model_config = AsyncMock(
            return_value=SimpleNamespace(provider_type="openai")
        )
        binding.complete = AsyncMock(return_value={})
        model_binding_cls.extract_text.return_value = "ok"
        model_binding_cls.extract_tool_calls.return_value = []

        result = await executor.execute_conversation_turn(
            agent_type=agent_type,
            messages=[{"role": "user", "content": "hello"}],
            conv_session_id=conv_session_id,
            db=db,
        )

    assert result == "ok"

    allowed_tools = executor._load_tool_definitions.await_args.args[0]
    assert build_tool_name("agent", "supabase-agent") in allowed_tools
    executor._permission_manager.calculate_allowed_agent_types.assert_awaited_once_with(
        agent_type.role_id,
        db,
        override_sop_ids=None,
    )


@pytest.mark.asyncio
async def test_conversation_turn_delegation_waits_for_receiver_response() -> None:
    executor = AgentRuntimeExecutor()

    agent_type = SimpleNamespace(
        id=uuid.uuid4(),
        role_id=uuid.uuid4(),
        model_id=uuid.uuid4(),
    )
    conv_session_id = uuid.uuid4()
    db = AsyncMock()
    _db_result = MagicMock()
    _db_result.fetchall.return_value = []
    db.execute.return_value = _db_result

    executor._permission_manager.calculate_allowed_tools = AsyncMock(return_value=set())
    executor._permission_manager.calculate_allowed_agent_types = AsyncMock(
        return_value={"supabase-agent"}
    )
    executor._load_tool_definitions = AsyncMock(
        return_value=(
            [
                {
                    "type": "function",
                    "function": {
                        "name": build_tool_name("agent", "supabase-agent"),
                        "description": "delegate",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            {"agent__supabase-agent": build_tool_name("agent", "supabase-agent")},
        )
    )
    executor._load_role_mcp_session_map = AsyncMock(return_value={})

    with patch("app.services.agents.model_binding.ModelBindingLayer") as model_binding_cls, patch(
        "app.agent_runtime.comm_hub_client.CommHubToolClient"
    ) as comm_hub_client_cls:
        binding = model_binding_cls.return_value
        binding.resolve_model_config = AsyncMock(
            return_value=SimpleNamespace(provider_type="openai")
        )
        binding.complete = AsyncMock(side_effect=[{"step": 1}, {"step": 2}])
        model_binding_cls.extract_text.side_effect = ["", "done"]
        model_binding_cls.extract_tool_calls.side_effect = [
            [
                {
                    "id": "call-1",
                    "function": {
                        "name": "agent__supabase-agent",
                        "arguments": "{}",
                    },
                }
            ],
            [],
        ]

        comm_hub_client = comm_hub_client_cls.return_value
        comm_hub_client.call_a2a_request = AsyncMock(
            return_value={"status": "accepted", "response_payload": {"status": "completed"}}
        )

        result = await executor.execute_conversation_turn(
            agent_type=agent_type,
            messages=[{"role": "user", "content": "delegate"}],
            conv_session_id=conv_session_id,
            db=db,
        )

    assert result == "done"
    comm_hub_client.call_a2a_request.assert_awaited_once_with(
        target_agent_type_slug="supabase-agent",
        session_id=str(conv_session_id),
        requester_role_id=str(agent_type.role_id),
        request_payload={},
        session_link_id=None,
        wait_for_response=True,
        wait_timeout_seconds=45.0,
        conv_session_id=str(conv_session_id),
    )
