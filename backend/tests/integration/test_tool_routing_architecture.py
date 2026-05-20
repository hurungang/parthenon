"""Integration tests for tool routing architecture.

Tests that ALL tool calls (external MCP + system tools) route through
Communication Hub with proper authentication and permission validation.
"""
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient

from app.agent_runtime.comm_hub_client import CommHubToolClient, CommHubToolClientError


@pytest.mark.asyncio
class TestToolRoutingArchitecture:
    """Test tool routing through Communication Hub."""

    async def test_comm_hub_client_basic_call(self):
        """Test basic tool call through Communication Hub client."""
        client = CommHubToolClient()

        # Mock the httpx client — use MagicMock for response because httpx response
        # methods (json, raise_for_status) are synchronous, not coroutines.
        with patch("app.agent_runtime.comm_hub_client.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "result": {"status": "success", "data": "test"},
                "error": None,
            }
            mock_client.post.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = await client.call_tool(
                tool_name="hello-world/helloWorld",
                tool_args={"name": "test"},
                session_id=str(uuid.uuid4()),
                agent_type_id=str(uuid.uuid4()),
            )

            assert result["status"] == "success"
            assert result["data"] == "test"
            mock_client.post.assert_called_once()

    async def test_comm_hub_client_error_handling(self):
        """Test error handling in Communication Hub client."""
        client = CommHubToolClient()

        # Mock HTTP error — raise httpx.HTTPStatusError so the client's
        # HTTPStatusError handler fires and produces the expected error message.
        with patch("app.agent_runtime.comm_hub_client.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 502
            mock_response.text = "Bad Gateway"
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "502 Bad Gateway",
                request=MagicMock(),
                response=mock_response,
            )
            mock_client.post.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            with pytest.raises(CommHubToolClientError, match="Communication Hub tool call failed"):
                await client.call_tool(
                    tool_name="test/tool",
                    tool_args={},
                    session_id=str(uuid.uuid4()),
                    agent_type_id=str(uuid.uuid4()),
                )

    async def test_comm_hub_client_tool_execution_error(self):
        """Test tool execution error returned from Communication Hub."""
        client = CommHubToolClient()

        # Mock successful HTTP but tool error
        with patch("app.agent_runtime.comm_hub_client.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "result": {},
                "error": "Tool not found",
            }
            mock_client.post.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            with pytest.raises(CommHubToolClientError, match="Tool not found"):
                await client.call_tool(
                    tool_name="invalid/tool",
                    tool_args={},
                    session_id=str(uuid.uuid4()),
                    agent_type_id=str(uuid.uuid4()),
                )

    async def test_system_tool_routing(self):
        """Test system tool routing to Control Center endpoints."""
        # This test would require a running Communication Hub and Control Center
        # For now, we test the client call pattern
        client = CommHubToolClient()

        with patch("app.agent_runtime.comm_hub_client.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "result": {"status": "saved", "session_id": str(uuid.uuid4())},
                "error": None,
            }
            mock_client.post.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = await client.call_tool(
                tool_name="save_result",
                tool_args={"content": "test result", "title": "Test"},
                session_id=str(uuid.uuid4()),
                agent_type_id=str(uuid.uuid4()),
            )

            assert result["status"] == "saved"
            mock_client.post.assert_called_once()

    async def test_mcp_tool_routing(self):
        """Test external MCP tool routing through Communication Hub."""
        client = CommHubToolClient()

        with patch("app.agent_runtime.comm_hub_client.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "result": {"message": "Hello, World!"},
                "error": None,
            }
            mock_client.post.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client_class.return_value = mock_client

            result = await client.call_tool(
                tool_name="hello-world/helloWorld",
                tool_args={},
                session_id=str(uuid.uuid4()),
                agent_type_id=str(uuid.uuid4()),
            )

            assert result["message"] == "Hello, World!"
            mock_client.post.assert_called_once()

    async def test_runtime_executor_uses_comm_hub_client(self):
        """Test that runtime_executor uses CommHubToolClient instead of direct MCP calls."""
        from app.services.agents.runtime_executor import AgentRuntimeExecutor

        executor = AgentRuntimeExecutor()

        # Mock context data
        context = {
            "model_id": "gpt-4",
            "system_instruction": "Test agent",
            "tool_definitions": [],
            "role_mcp_sessions": {},
        }

        job_data = {
            "id": str(uuid.uuid4()),
            "agent_type_id": str(uuid.uuid4()),
            "input_data": {"message": "test"},
        }

        # Mock the data client
        mock_data_client = AsyncMock()
        mock_data_client.log_execution_event = AsyncMock()
        mock_data_client.log_prompt = AsyncMock()
        mock_data_client.get_model_config = AsyncMock(return_value={})
        mock_data_client.get_agent_plan = AsyncMock(return_value=None)

        # Verify the method signature includes comm_hub_client
        import inspect
        sig = inspect.signature(executor._execute_mcp_tool_ar)
        params = list(sig.parameters.keys())

        assert "comm_hub_client" in params, "Method must accept comm_hub_client parameter"
        assert "session_id" in params, "Method must accept session_id parameter"


@pytest.mark.integration
class TestToolRoutingIntegration:
    """Integration tests requiring running services.

    These tests require:
    - Control Center running on port 8000
    - Communication Hub running on port 8003
    - Agent Runtime with valid certificate
    """

    @pytest.mark.skip(reason="Requires running services")
    async def test_end_to_end_hello_world_tool(self):
        """Test calling hello-world/helloWorld through full stack."""
        # TODO: Implement when services are running
        pass

    @pytest.mark.skip(reason="Requires running services")
    async def test_end_to_end_save_result_tool(self):
        """Test calling save_result through full stack."""
        # TODO: Implement when services are running
        pass

    @pytest.mark.skip(reason="Requires running services")
    async def test_certificate_authentication(self):
        """Test mTLS certificate authentication for tool calls."""
        # TODO: Implement when services are running
        pass

    @pytest.mark.skip(reason="Requires running services")
    async def test_permission_validation(self):
        """Test permission denied scenarios."""
        # TODO: Implement when services are running
        pass
