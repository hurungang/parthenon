"""Unit tests for the Communication Hub agent-execute forwarding endpoint.

Covers retry behaviour and error mapping for the three failure modes the
endpoint can observe when calling ``Agent Runtime``:

- 4xx from Agent Runtime → non-retriable, surface as 502 to caller
- 5xx from Agent Runtime → retriable, surface as 502 after exhaustion
- ``httpx.TimeoutException`` (Read/Connect/Write/Pool) → retriable,
  surface as **503** to caller (transient availability issue)
- ``httpx.ConnectError`` → retriable, surface as 503 to caller
- Other unexpected errors → 502 to caller

The endpoint is invoked via a minimal FastAPI app that mounts the router
in isolation. The ``httpx.AsyncClient`` used for the upstream call is
mocked so the tests never open a real socket.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Make sure ``app.*`` resolves to the backend, not mcp-demo-app's app
BACKEND_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault(
    "CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault(
    "OIDC_PROVIDER_URL", "http://localhost:8080/realms/parthenon"
)

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.communication_hub.api.internal.agent_execute import (
    AgentExecuteRequest,
    router as agent_execute_router,
)


def _build_test_app() -> FastAPI:
    """Mount the agent-execute router on a bare FastAPI app.

    No certificate manager is set on ``app.state``; the endpoint is
    expected to log a warning and proceed without a client cert (HTTP
    dev path).
    """
    app = FastAPI()
    app.include_router(agent_execute_router)
    return app


def _payload() -> dict:
    return {
        "session_id": str(uuid.uuid4()),
        "agent_type_id": str(uuid.uuid4()),
        "input_data": {"prompt": "hello"},
    }


def _mock_response(json_body: dict, status_code: int = 200) -> MagicMock:
    """Build a mock httpx.Response."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    response.raise_for_status = MagicMock()
    response.text = json_body.__repr__()
    return response


class _AsyncClientContext:
    """Async context manager that yields a supplied mock client."""

    def __init__(self, client: MagicMock) -> None:
        self._client = client

    async def __aenter__(self) -> MagicMock:
        return self._client

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401
        return None


@pytest.mark.asyncio
async def test_happy_path_forwards_and_returns_accepted():
    """When Agent Runtime returns 200, the endpoint returns its payload."""
    app = _build_test_app()
    body = _payload()
    # Endpoint echoes back the session_id from Agent Runtime's response,
    # so the mock must use the same session_id as the request body.
    upstream = MagicMock()
    upstream.post = AsyncMock(
        return_value=_mock_response(
            {"session_id": body["session_id"], "status": "queued"},
        )
    )

    with patch(
        "app.communication_hub.api.internal.agent_execute.asyncio.sleep",
        new=AsyncMock(),
    ), patch(
        "app.communication_hub.api.internal.agent_execute.httpx.AsyncClient",
        return_value=_AsyncClientContext(upstream),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/internal/agent/execute", json=body
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == body["session_id"]
    assert payload["status"] == "queued"
    assert upstream.post.await_count == 1


@pytest.mark.asyncio
async def test_read_timeout_retries_then_returns_503():
    """Regression: ``httpx.ReadTimeout`` must be retried (3 attempts) and
    surface as **503** to the caller when retries are exhausted — Agent
    Runtime is reachable but slow, which is a transient availability
    issue distinct from a hard 5xx rejection.
    """
    app = _build_test_app()
    body = _payload()

    upstream = MagicMock()
    upstream.post = AsyncMock(
        side_effect=httpx.ReadTimeout("read timed out")
    )

    with patch(
        "app.communication_hub.api.internal.agent_execute.asyncio.sleep",
        new=AsyncMock(),
    ), patch(
        "app.communication_hub.api.internal.agent_execute.httpx.AsyncClient",
        return_value=_AsyncClientContext(upstream),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/internal/agent/execute", json=body
            )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "unavailable" in detail.lower()
    assert "timed out" in detail.lower() or "timeout" in detail.lower()
    # 3 attempts, 2 retries between them
    assert upstream.post.await_count == 3


@pytest.mark.asyncio
async def test_connect_timeout_retries_then_returns_503():
    """``httpx.ConnectTimeout`` is a subclass of ``TimeoutException`` and
    must follow the same retry + 503 contract as ``ReadTimeout``.
    """
    app = _build_test_app()
    body = _payload()

    upstream = MagicMock()
    upstream.post = AsyncMock(
        side_effect=httpx.ConnectTimeout("connect timed out")
    )

    with patch(
        "app.communication_hub.api.internal.agent_execute.asyncio.sleep",
        new=AsyncMock(),
    ), patch(
        "app.communication_hub.api.internal.agent_execute.httpx.AsyncClient",
        return_value=_AsyncClientContext(upstream),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/internal/agent/execute", json=body
            )

    assert response.status_code == 503
    assert upstream.post.await_count == 3


@pytest.mark.asyncio
async def test_connect_error_retries_then_returns_503():
    """``httpx.ConnectError`` (connection refused) must surface as 503
    after retries — this was the original behaviour and must stay.
    """
    app = _build_test_app()
    body = _payload()

    upstream = MagicMock()
    upstream.post = AsyncMock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with patch(
        "app.communication_hub.api.internal.agent_execute.asyncio.sleep",
        new=AsyncMock(),
    ), patch(
        "app.communication_hub.api.internal.agent_execute.httpx.AsyncClient",
        return_value=_AsyncClientContext(upstream),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/internal/agent/execute", json=body
            )

    assert response.status_code == 503
    assert upstream.post.await_count == 3


@pytest.mark.asyncio
async def test_4xx_response_does_not_retry_and_returns_502():
    """A 4xx from Agent Runtime is non-retriable — fail fast with 502
    so the caller can surface the validation problem immediately.
    """
    app = _build_test_app()
    body = _payload()

    response_mock = MagicMock()
    response_mock.status_code = 422
    response_mock.text = '{"detail":"bad input"}'
    response_mock.raise_for_status.side_effect = httpx.HTTPStatusError(
        "422 Unprocessable Entity",
        request=MagicMock(),
        response=response_mock,
    )

    upstream = MagicMock()
    upstream.post = AsyncMock(return_value=response_mock)

    with patch(
        "app.communication_hub.api.internal.agent_execute.asyncio.sleep",
        new=AsyncMock(),
    ), patch(
        "app.communication_hub.api.internal.agent_execute.httpx.AsyncClient",
        return_value=_AsyncClientContext(upstream),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/internal/agent/execute", json=body
            )

    assert response.status_code == 502
    assert "HTTP 422" in response.json()["detail"]
    # 4xx is non-retriable — single attempt
    assert upstream.post.await_count == 1


@pytest.mark.asyncio
async def test_5xx_response_retries_then_returns_502():
    """A 5xx from Agent Runtime is retriable, but the final response to
    the caller is 502 (Agent Runtime is reachable but rejected the
    request after the retry budget is exhausted).
    """
    app = _build_test_app()
    body = _payload()

    response_mock = MagicMock()
    response_mock.status_code = 503
    response_mock.text = '{"detail":"upstream overloaded"}'
    response_mock.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503 Service Unavailable",
        request=MagicMock(),
        response=response_mock,
    )

    upstream = MagicMock()
    upstream.post = AsyncMock(return_value=response_mock)

    with patch(
        "app.communication_hub.api.internal.agent_execute.asyncio.sleep",
        new=AsyncMock(),
    ), patch(
        "app.communication_hub.api.internal.agent_execute.httpx.AsyncClient",
        return_value=_AsyncClientContext(upstream),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/internal/agent/execute", json=body
            )

    assert response.status_code == 502
    # 5xx is retriable — 3 attempts
    assert upstream.post.await_count == 3


@pytest.mark.asyncio
async def test_transient_timeout_then_success_recovers():
    """If the first attempt times out but a later attempt succeeds, the
    endpoint returns 200 and the caller's contract is preserved.
    """
    app = _build_test_app()
    body = _payload()

    success_response = _mock_response(
        {"session_id": body["session_id"], "status": "queued"},
    )

    upstream = MagicMock()
    upstream.post = AsyncMock(
        side_effect=[
            httpx.ReadTimeout("first try timed out"),
            success_response,
        ]
    )

    with patch(
        "app.communication_hub.api.internal.agent_execute.asyncio.sleep",
        new=AsyncMock(),
    ), patch(
        "app.communication_hub.api.internal.agent_execute.httpx.AsyncClient",
        return_value=_AsyncClientContext(upstream),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/internal/agent/execute", json=body
            )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert upstream.post.await_count == 2
