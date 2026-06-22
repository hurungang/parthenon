import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agents.runtime_executor import AgentRuntimeExecutor
from app.services.agents.tool_naming import build_tool_name


@pytest.mark.asyncio
async def test_conversation_context_emits_delegation_status_events() -> None:
    executor = AgentRuntimeExecutor()
    conv_session_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    role_id = uuid.uuid4()

    agent_context = {
        'model_id': str(uuid.uuid4()),
        'role_id': str(role_id),
        'allowed_tools': [build_tool_name('agent', 'research-agent')],
        'tool_definitions': [
            {
                'type': 'function',
                'function': {
                    'name': 'agent__research-agent',
                    'description': 'delegate',
                    'parameters': {'type': 'object', 'properties': {}},
                },
            },
        ],
        'tool_name_map': {
            'agent__research-agent': build_tool_name('agent', 'research-agent'),
        },
        'role_mcp_sessions': {},
        'guardrail_policy': {
            'max_iterations': 5,
            'max_delegation_depth': 3,
            'max_delegated_steps': 10,
            'execution_timeout_seconds': 300,
        },
        'sops': [],
        'skills': [],
    }
    model_config = {'provider_type': 'openai'}

    with patch('app.services.agents.model_binding.ModelBindingLayer') as model_binding_cls, patch(
        'app.agent_runtime.comm_hub_client.CommHubToolClient'
    ) as comm_hub_client_cls:
        binding = model_binding_cls.return_value
        binding.complete_from_context = AsyncMock(side_effect=[{'step': 1}, {'step': 2}])
        model_binding_cls.extract_text.side_effect = ['', 'delegation complete']
        model_binding_cls.extract_tool_calls.side_effect = [
            [
                {
                    'id': 'call-1',
                    'function': {
                        'name': 'agent__research-agent',
                        'arguments': '{}',
                    },
                }
            ],
            [],
        ]
        model_binding_cls.extract_usage.return_value = None

        comm_hub_client = comm_hub_client_cls.return_value
        comm_hub_client.call_a2a_request = AsyncMock(
            return_value={'status': 'accepted', 'response_payload': {'status': 'completed'}}
        )

        response, guardrail_usage, status_events = await executor.execute_conversation_turn_from_context(
            agent_type_id=agent_type_id,
            agent_context=agent_context,
            model_config=model_config,
            messages=[{'role': 'user', 'content': 'delegate'}],
            conv_session_id=conv_session_id,
        )

    assert response == 'delegation complete'
    assert guardrail_usage['delegated_steps'] == 1
    assert status_events == [
        {'status': 'using_tool', 'tool_name': 'research-agent'},
        {'status': 'delegating', 'agent_type': 'research-agent'},
        {'status': 'waiting', 'agent_type': 'research-agent'},
    ]
    comm_hub_client.call_a2a_request.assert_awaited_once_with(
        target_agent_type_slug='research-agent',
        session_id=str(conv_session_id),
        requester_role_id=str(role_id),
        request_payload={'__delegation_depth': 1},
        session_link_id=None,
        wait_for_response=False,
        wait_timeout_seconds=120.0,
        conv_session_id=str(conv_session_id),
    )
