"""Tests for the CC → CH → AR termination routing in ``AgentRuntimeClient``.

Phase 3.11 v2: ``AgentRuntimeClient.terminate_session`` must call
Communication Hub (not Agent Runtime directly) because AR's certificate
middleware only accepts ``CN=service:communication-hub`` certs.  These
tests verify the URL and the request shape, without spinning up a real
HTTP server.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import httpx
import pytest

from app.services.control_center.agent_runtime_client import (
    AgentRuntimeClient,
    AgentRuntimeClientError,
)


def _make_client(comm_hub_url: str = "http://localhost:8002") -> AgentRuntimeClient:
    return AgentRuntimeClient(
        agent_runtime_url="http://localhost:8001",
        communication_hub_url=comm_hub_url,
    )


@pytest.mark.asyncio
async def test_terminate_session_targets_communication_hub_not_agent_runtime():
    """The URL the client posts to must be CH's
    ``/internal/agent/terminate/{session_id}`` — NOT AR's
    ``/terminate/{session_id}``.  Otherwise AR's cert middleware
    would reject the request with 401 (it only accepts the
    communication-hub service cert).
    """
    client = _make_client()
    session_id = uuid.uuid4()

    captured_url: dict[str, str] = {}

    class _StubAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            captured_url["url"] = url
            resp = AsyncMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json = lambda: {"session_id": str(session_id), "cancelled": True}
            resp.raise_for_status = lambda: None
            return resp

    with patch.object(client, "_make_client", return_value=_StubAsyncClient()):
        result = await client.terminate_session(session_id=session_id, reason="test")

    # URL must be the CH endpoint, NOT the AR endpoint
    assert captured_url["url"] == (
        f"http://localhost:8002/internal/agent/terminate/{session_id}"
    )
    assert "/8001" not in captured_url["url"], (
        "terminate_session must NOT target Agent Runtime directly"
    )
    # Response was forwarded
    assert result == {"session_id": str(session_id), "cancelled": True}


@pytest.mark.asyncio
async def test_terminate_session_sends_reason_in_body():
    client = _make_client()
    session_id = uuid.uuid4()

    captured_kwargs: dict = {}

    class _StubAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            captured_kwargs.update(kwargs)
            resp = AsyncMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json = lambda: {"session_id": str(session_id), "cancelled": True}
            resp.raise_for_status = lambda: None
            return resp

    with patch.object(client, "_make_client", return_value=_StubAsyncClient()):
        await client.terminate_session(
            session_id=session_id, reason="operator hit Terminate"
        )

    body = captured_kwargs.get("json") or {}
    assert body.get("reason") == "operator hit Terminate"


@pytest.mark.asyncio
async def test_terminate_session_treats_404_as_success():
    """CH returns 404 when the session is already terminal; that
    should be treated as success (intent satisfied) and return None.
    """
    client = _make_client()
    session_id = uuid.uuid4()

    class _StubAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            resp = AsyncMock(spec=httpx.Response)
            resp.status_code = 404
            resp.text = "Session already terminal"
            raise httpx.HTTPStatusError(
                "404 Not Found", request=AsyncMock(), response=resp
            )

    with patch.object(client, "_make_client", return_value=_StubAsyncClient()):
        result = await client.terminate_session(session_id=session_id)

    # 404 → None (success: intent already satisfied)
    assert result is None


@pytest.mark.asyncio
async def test_terminate_session_raises_on_5xx_after_retries():
    """5xx errors should be retried by httpx's loop in the client;
    the client surfaces them as AgentRuntimeClientError.
    """
    client = _make_client()
    session_id = uuid.uuid4()

    class _StubAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            resp = AsyncMock(spec=httpx.Response)
            resp.status_code = 502
            resp.text = "Bad Gateway"
            raise httpx.HTTPStatusError(
                "502 Bad Gateway", request=AsyncMock(), response=resp
            )

    with patch.object(client, "_make_client", return_value=_StubAsyncClient()):
        with pytest.raises(AgentRuntimeClientError) as exc_info:
            await client.terminate_session(session_id=session_id)

    assert "502" in str(exc_info.value)
