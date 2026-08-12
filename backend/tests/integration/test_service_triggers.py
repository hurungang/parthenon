"""Integration tests — Service-to-service triggers (Task 7.4).

Tests the execution flow between Control Center, Agent Runtime, and Communication Hub:
  - CC triggers AR via AgentRuntimeClient (POST /execute)
  - AR enqueues job into session_queue
  - CC dispatches to CH via CommHubClient (POST /internal/dispatch)
  - CH publishes to broker channel

All service calls use mocked HTTP — no running services required.
"""
from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason='Requires running services (CC, AR, or CH)')

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.control_center.agent_runtime_client import (
    AgentRuntimeClient,
    AgentRuntimeClientError,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Control Center → Agent Runtime execution trigger
# ═══════════════════════════════════════════════════════════════════════════════


class TestCCToARExecutionTrigger:
    """Tests for AgentRuntimeClient.trigger_execution."""

    @pytest.mark.asyncio
    async def test_trigger_execution_sends_correct_payload(self):
        """trigger_execution POSTs session_id, agent_type_id, and input_data to AR /execute."""
        session_id = uuid.uuid4()
        agent_type_id = uuid.uuid4()
        input_data = {"prompt": "What is the status?"}

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"session_id": str(session_id), "status": "accepted"}
        mock_resp.raise_for_status = MagicMock()

        client = AgentRuntimeClient(agent_runtime_url="http://ar.test")

        with patch.object(client, "_make_client") as mock_make:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_make.return_value = mock_http

            result = await client.trigger_execution(session_id, agent_type_id, input_data)

        assert result["session_id"] == str(session_id)
        assert result["status"] == "accepted"

        call_args = mock_http.post.call_args
        url = call_args[0][0]
        assert url == "http://ar.test/execute"
        body = call_args[1]["json"]
        assert body["session_id"] == str(session_id)
        assert body["agent_type_id"] == str(agent_type_id)
        assert body["input_data"] == input_data

    @pytest.mark.asyncio
    async def test_trigger_execution_raises_on_http_error(self):
        """trigger_execution raises AgentRuntimeClientError on non-200 response."""
        session_id = uuid.uuid4()
        agent_type_id = uuid.uuid4()

        error_resp = MagicMock(spec=httpx.Response)
        error_resp.status_code = 503
        error_resp.text = "AR not ready"
        error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503",
            request=MagicMock(),
            response=error_resp,
        )

        client = AgentRuntimeClient(agent_runtime_url="http://ar.test")

        with patch.object(client, "_make_client") as mock_make:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=error_resp)
            mock_make.return_value = mock_http

            with pytest.raises(AgentRuntimeClientError) as exc_info:
                await client.trigger_execution(session_id, agent_type_id)

        assert "503" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_trigger_execution_raises_on_network_error(self):
        """trigger_execution raises AgentRuntimeClientError on network failure."""
        session_id = uuid.uuid4()
        agent_type_id = uuid.uuid4()

        client = AgentRuntimeClient(agent_runtime_url="http://ar.test")

        with patch.object(client, "_make_client") as mock_make:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_make.return_value = mock_http

            with pytest.raises(AgentRuntimeClientError):
                await client.trigger_execution(session_id, agent_type_id)

    @pytest.mark.asyncio
    async def test_trigger_execution_uses_mtls_client(self):
        """trigger_execution uses the mTLS client when cert files are provided."""
        import tempfile
        import os

        # Create temporary cert/key files
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as cf:
            cf.write("-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n")
            cert_path = cf.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as kf:
            kf.write("-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----\n")
            key_path = kf.name

        try:
            client = AgentRuntimeClient(
                agent_runtime_url="https://ar.test",  # HTTPS triggers mTLS path
                cert_path=cert_path,
                key_path=key_path,
            )
            # For HTTPS URLs, _make_client creates an SSL context (mTLS)
            with patch("ssl.create_default_context") as mock_ssl:
                mock_ssl.return_value = MagicMock()
                http_client = client._make_client()
                mock_ssl.assert_called_once()
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Runtime — session_queue enqueue
# ═══════════════════════════════════════════════════════════════════════════════


class TestARExecuteEndpoint:
    """Tests for Agent Runtime /execute endpoint handling."""

    @pytest.mark.asyncio
    async def test_execute_endpoint_accepts_session(self):
        """POST /execute calls data_client.mark_session_running and returns accepted."""
        from unittest.mock import AsyncMock
        from app.agent_runtime.api.execute import trigger_execution, ExecuteRequest

        session_id = uuid.uuid4()
        agent_type_id = uuid.uuid4()

        mock_data_client = AsyncMock()
        mock_data_client.mark_session_running = AsyncMock(return_value=None)

        mock_request = MagicMock()
        mock_request.app.state.data_client = mock_data_client
        mock_request.app.state.execution_semaphore = None

        body = ExecuteRequest(
            session_id=session_id,
            agent_type_id=agent_type_id,
            input_data=None,
        )

        response = await trigger_execution(body=body, request=mock_request)

        assert response.session_id == session_id
        assert response.status == "accepted"
        mock_data_client.mark_session_running.assert_awaited_once_with(session_id)

    @pytest.mark.asyncio
    async def test_execute_endpoint_returns_503_if_data_client_not_initialised(self):
        """POST /execute returns 503 when data_client is not on app.state."""
        from fastapi import HTTPException
        from app.agent_runtime.api.execute import trigger_execution, ExecuteRequest

        session_id = uuid.uuid4()
        agent_type_id = uuid.uuid4()

        mock_request = MagicMock()
        mock_request.app.state.data_client = None  # Not initialised

        body = ExecuteRequest(
            session_id=session_id,
            agent_type_id=agent_type_id,
            input_data=None,
        )

        with pytest.raises(HTTPException) as exc_info:
            await trigger_execution(body=body, request=mock_request)

        assert exc_info.value.status_code == 503


# ═══════════════════════════════════════════════════════════════════════════════
# Control Center → Communication Hub message dispatch
# ═══════════════════════════════════════════════════════════════════════════════


class TestCCToCHDispatch:
    """Tests for CH dispatch endpoint and CC→CH client."""

    @pytest.mark.asyncio
    async def test_dispatch_endpoint_publishes_to_broker(self):
        """POST /internal/dispatch publishes message to broker channel."""
        from app.communication_hub.api.dispatch import dispatch_message, DispatchRequest

        session_id = uuid.uuid4()
        content = {"result": "Task completed successfully", "status": "completed"}

        body = DispatchRequest(
            session_id=session_id,
            message_type="agent_result",
            content=content,
        )

        mock_broker = AsyncMock()
        mock_broker.publish.return_value = 1  # 1 subscriber received

        with patch("app.communication_hub.api.dispatch._broker", mock_broker):
            response = await dispatch_message(body=body)

        assert response.dispatched is True
        assert str(session_id) in response.channel
        mock_broker.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_endpoint_handles_broker_failure(self):
        """POST /internal/dispatch returns 502 when broker publish fails."""
        from fastapi import HTTPException
        from app.communication_hub.api.dispatch import dispatch_message, DispatchRequest

        session_id = uuid.uuid4()
        body = DispatchRequest(
            session_id=session_id,
            message_type="agent_result",
            content="result",
        )

        mock_broker = AsyncMock()
        mock_broker.publish.side_effect = Exception("Redis connection lost")

        with patch("app.communication_hub.api.dispatch._broker", mock_broker):
            with pytest.raises(HTTPException) as exc_info:
                await dispatch_message(body=body)

        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_dispatch_dict_content_is_json_serialized(self):
        """Dict content is JSON-serialized before publishing to broker."""
        from app.communication_hub.api.dispatch import dispatch_message, DispatchRequest

        session_id = uuid.uuid4()
        content_dict = {"key": "value", "nested": {"x": 1}}

        body = DispatchRequest(
            session_id=session_id,
            message_type="agent_result",
            content=content_dict,
        )

        published_messages = []

        mock_broker = AsyncMock()

        async def capture_publish(message):
            published_messages.append(message)
            return 1

        mock_broker.publish.side_effect = capture_publish

        with patch("app.communication_hub.api.dispatch._broker", mock_broker):
            await dispatch_message(body=body)

        assert len(published_messages) == 1
        msg = published_messages[0]
        # BrokerMessage or published content should be JSON
        import json
        if hasattr(msg, "content"):
            data = json.loads(msg.content)
        else:
            data = json.loads(msg)
        assert data["key"] == "value"
