import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agents.runtime_executor import AgentRuntimeExecutor


@pytest.mark.asyncio
async def test_conversation_turn_propagates_cert_to_comm_hub_client() -> None:
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
    executor._permission_manager.calculate_allowed_agent_types = AsyncMock(return_value=set())
    executor._load_tool_definitions = AsyncMock(return_value=([], {}))
    executor._load_role_mcp_session_map = AsyncMock(return_value={})

    with patch("app.services.agents.model_binding.ModelBindingLayer") as model_binding_cls, patch(
        "app.agent_runtime.comm_hub_client.CommHubToolClient"
    ) as comm_hub_client_cls:
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
            cert_path="C:/tmp/ar-cert.pem",
            key_path="C:/tmp/ar-key.pem",
        )

    assert result == "ok"
    comm_hub_client_cls.return_value.set_certificate.assert_called_once_with(
        "C:/tmp/ar-cert.pem",
        "C:/tmp/ar-key.pem",
    )
