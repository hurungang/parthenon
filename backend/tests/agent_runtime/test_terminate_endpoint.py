"""Tests for the Agent Runtime session-termination endpoint.

Phase 3.11: the Control Center's termination orchestrator calls
``POST /terminate/{session_id}`` on Agent Runtime to cancel the
in-flight ``asyncio.Task`` for the session.  These tests verify
the endpoint's behaviour in isolation.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


def _build_app_with_task_registry() -> tuple:
    """Build a minimal FastAPI app with just the terminate router and
    a manually-populated ``session_tasks`` registry.  Returns
    ``(app, request)`` so tests can drive the endpoint directly.
    """
    from fastapi import FastAPI, Request

    from app.agent_runtime.api.terminate import terminate_router

    app = FastAPI()
    app.include_router(terminate_router)
    return app


@pytest.mark.asyncio
async def test_terminate_cancels_running_task():
    """A registered in-flight task must be cancelled by the
    terminate endpoint.
    """
    app = _build_app_with_task_registry()
    session_id = uuid.uuid4()

    # Create a long-running asyncio task that we can cancel
    async def _long_running():
        await asyncio.sleep(60)

    task = asyncio.create_task(_long_running(), name=f"execute-{session_id}")
    app.state.session_tasks = {session_id: task}

    with TestClient(app) as client:
        # Manually inject the state since TestClient resets state.
        # The endpoint reads ``request.app.state.session_tasks`` directly.
        response = client.post(f"/terminate/{session_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == str(session_id)
    assert body["cancelled"] is True

    # Confirm the task is in fact cancelled (or about to be)
    # Give the event loop a chance to deliver the cancellation
    try:
        await asyncio.wait_for(task, timeout=0.5)
    except asyncio.CancelledError:
        pass
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_terminate_returns_404_for_unknown_session():
    app = _build_app_with_task_registry()
    app.state.session_tasks = {}

    with TestClient(app) as client:
        response = client.post(f"/terminate/{uuid.uuid4()}")

    assert response.status_code == 404
    assert "No in-flight task" in response.json()["detail"]


@pytest.mark.asyncio
async def test_terminate_returns_404_when_registry_not_initialised():
    """If the app was never started (no ``_init_execution_engine`` ran),
    ``session_tasks`` is missing entirely.  The endpoint should 404
    rather than 500.
    """
    app = _build_app_with_task_registry()
    # Deliberately do NOT set session_tasks on app.state

    with TestClient(app) as client:
        response = client.post(f"/terminate/{uuid.uuid4()}")

    assert response.status_code == 404
