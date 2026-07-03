import uuid
from unittest.mock import AsyncMock, patch

import pytest

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.services.agents.runtime_executor import AgentRuntimeExecutor
from app.services.agents.tool_naming import build_tool_name


class _FakeDelegationModel(GenericFakeChatModel):
    """Fake LangChain chat model for delegation testing.

    Overrides ``bind_tools`` (not implemented in GenericFakeChatModel) to
    return self, making it compatible with LangGraph's create_agent.
    """

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self

    def model_copy(self, **kwargs):  # type: ignore[override]
        return self


@pytest.mark.asyncio
async def test_conversation_context_emits_delegation_status_events() -> None:
    executor = AgentRuntimeExecutor()
    conv_session_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    role_id = uuid.uuid4()
    receiver_session_id = str(uuid.uuid4())

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

    # Fake model: first call produces delegation tool call, second returns final text
    fake_model = _FakeDelegationModel(
        messages=iter([
            AIMessage(
                content='',
                tool_calls=[{
                    'id': 'call-1',
                    'name': 'agent__research_agent',
                    'args': {},
                    'type': 'tool_call',
                }],
            ),
            AIMessage(content='delegation complete'),
        ])
    )

    with patch(
        'app.services.agents.langchain_model_factory.LangChainModelFactory'
    ) as mock_factory_cls, patch(
        'app.agent_runtime.comm_hub_client.CommHubToolClient'
    ) as comm_hub_client_cls:

        mock_factory_cls.return_value.get_model_from_config_dict.return_value = fake_model

        comm_hub_client = comm_hub_client_cls.return_value
        comm_hub_client.call_a2a_request = AsyncMock(
            return_value={
                'status': 'accepted',
                'receiver_session_id': receiver_session_id,
            }
        )
        comm_hub_client.wait_for_a2a_response = AsyncMock(
            return_value={
                'status': 'completed',
                'output_data': {},
            }
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

    status_sequence = [e['status'] for e in status_events]
    assert 'using_tool' in status_sequence
    assert 'delegating' in status_sequence
    assert 'waiting' in status_sequence
    assert 'delegation_resumed' in status_sequence

    comm_hub_client.call_a2a_request.assert_awaited_once()
    call_kwargs = comm_hub_client.call_a2a_request.await_args.kwargs
    assert call_kwargs['target_agent_type_slug'] == 'research-agent'
    assert call_kwargs['session_id'] == str(conv_session_id)
    assert call_kwargs['wait_for_response'] is False

