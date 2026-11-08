"""Delegation reliability: a pre-execution failure (token preflight BLOCKED)
must fail the parent's A2A wait immediately instead of letting it poll the
full delegation cap (30 min) without ever learning the real reason.

Covers:
- agent_execute: ``AgentPreflightBlocked`` fails the A2A wait before the 422.
- a2a waiter: a sticky session-failure record returns
  ``{"status": "failed", "error": ...}`` immediately.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import uuid
from unittest.mock import AsyncMock, patch

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]
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

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.communication_hub.api.a2a import _wait_for_receiver_result
from app.communication_hub.api.internal.agent_execute import (
    AgentExecuteRequest,
    router as agent_execute_router,
)
from app.services.gateway.preflight_gate import (
    AgentPreflightBlocked,
    AgentPreflightUnavailable,
)


class _StubBroker:
    """Minimal broker stub: no pub/sub messages, sticky failure record only."""

    def __init__(self, failure: dict | None = None) -> None:
        self.failure = failure

    async def get_session_failure(self, session_id: str) -> dict | None:
        return self.failure

    async def subscribe(self, session_id: str):  # pragma: no cover - never yields
        await asyncio.Event().wait()
        yield None  # unreachable; keeps this an async generator

    async def close(self) -> None:
        return None


# ── agent_execute: preflight BLOCKED fails the wait ──────────────────────────


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(agent_execute_router)
    return app


@pytest.mark.asyncio
async def test_preflight_blocked_fails_a2a_wait_before_422():
    """When the token preflight gate BLOCKs, the A2A wait for the receiver
    session is marked FAILED before the HTTP 422 is raised."""
    app = _build_test_app()
    body = {
        "session_id": str(uuid.uuid4()),
        "agent_type_id": str(uuid.uuid4()),
        "input_data": {"prompt": "book a flight"},
    }
    blocked = AgentPreflightBlocked(
        "Execution blocked: agent_identity 'test_agent' token auto-refresh failed "
        "(invalid_grant) — re-authenticate this identity"
    )
    fail_wait = AsyncMock()

    with patch(
        "app.services.gateway.preflight_gate.enforce_execution_preflight",
        new=AsyncMock(side_effect=blocked),
    ), patch(
        "app.communication_hub.api.internal.agent_execute._fail_a2a_wait",
        new=fail_wait,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/internal/agent/execute", json=body)

    assert response.status_code == 422
    assert "auto-refresh failed" in response.json()["detail"]
    fail_wait.assert_awaited_once()
    assert str(fail_wait.await_args.args[0]) == body["session_id"]
    assert "auto-refresh failed" in fail_wait.await_args.args[1]


@pytest.mark.asyncio
async def test_preflight_unavailable_fails_a2a_wait_before_503():
    """Preflight unreachable (fail closed) also fails the A2A wait."""
    app = _build_test_app()
    body = {
        "session_id": str(uuid.uuid4()),
        "agent_type_id": str(uuid.uuid4()),
        "input_data": {},
    }
    fail_wait = AsyncMock()
    with patch(
        "app.services.gateway.preflight_gate.enforce_execution_preflight",
        new=AsyncMock(side_effect=AgentPreflightUnavailable("Token preflight endpoint unreachable")),
    ), patch(
        "app.communication_hub.api.internal.agent_execute._fail_a2a_wait",
        new=fail_wait,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/internal/agent/execute", json=body)

    assert response.status_code == 503
    fail_wait.assert_awaited_once()


# ── a2a waiter: sticky failure record → immediate failed result ──────────────


@pytest.mark.asyncio
async def test_waiter_returns_failed_immediately_from_sticky_record():
    """The waiter returns status=failed with the real error right away."""
    session_id = str(uuid.uuid4())
    broker = _StubBroker(
        failure={"status": "failed", "error": "token auto-refresh failed (invalid_grant)"}
    )
    result = await _wait_for_receiver_result(
        uuid.UUID(session_id), timeout_seconds=5.0, broker=broker
    )
    assert result["status"] == "failed"
    assert "auto-refresh failed" in result["error"]


@pytest.mark.asyncio
async def test_waiter_without_failure_record_times_out_normally():
    """Without a failure record the waiter keeps waiting (regression guard)."""
    session_id = str(uuid.uuid4())
    broker = _StubBroker(failure=None)
    result = await _wait_for_receiver_result(
        uuid.UUID(session_id), timeout_seconds=0.5, broker=broker
    )
    assert result["status"] == "timeout"
