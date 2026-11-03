"""FIX-20261031-133253 — conversational-turn human_intervene round-trip.

The assistant (a conversational agent) must be able to PAUSE on
``human_intervene`` and RESUME on the operator's ``intervene_response``:
previously the conversational turn path caught ``GraphInterrupt`` and
swallowed it ("HITL not supported for conversational turns"), which made the
mandatory confirmation-before-create/update contract unenforceable.

Covered here:
1. ``conversation_resume`` registry semantics (register/resolve/timeout).
2. AR ``POST /internal/resume`` resolves a pending conversational
   intervention instead of relaunching a job execution.
3. ``LangChainHumanInterveneTool`` returns the operator's resume value as
   the tool result after ``Command(resume=...)``.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.agent_runtime.conversation_resume import (
    is_pending,
    register,
    resolve,
    unregister,
    wait_for_resume,
)


# ── 1. registry semantics ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wait_for_resume_resolves_with_response_value() -> None:
    conv_id = uuid.uuid4()

    async def _resolver():
        await asyncio.sleep(0.01)
        assert resolve(conv_id, {"approval_value": True})
        assert not is_pending(conv_id)

    task = asyncio.create_task(_resolver())
    value = await wait_for_resume(conv_id, timeout_seconds=5)
    await task
    assert value == {"approval_value": True}
    assert not is_pending(conv_id)


@pytest.mark.asyncio
async def test_wait_for_resume_times_out_cleanly() -> None:
    conv_id = uuid.uuid4()
    value = await wait_for_resume(conv_id, timeout_seconds=0.05)
    assert value is None
    assert not is_pending(conv_id)


def test_is_pending_rejects_garbage_ids() -> None:
    assert not is_pending("not-a-uuid")
    assert resolve("not-a-uuid", {}) is False
    unregister("not-a-uuid")  # must not raise


@pytest.mark.asyncio
async def test_register_is_scoped_per_conversation() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    fut_a = register(a)
    fut_b = register(b)
    assert is_pending(a) and is_pending(b)
    assert resolve(a, {"approval_value": False})
    assert fut_a.done() and not fut_b.done()
    assert not is_pending(a) and is_pending(b)
    fut_b.cancel()
    unregister(b)


# ── 2. AR /internal/resume resolves pending conversation interventions ──────


@pytest.mark.asyncio
async def test_resume_endpoint_resolves_conversation_intervention_first() -> None:
    """A pending conversational intervention must be resolved via the
    registry — never by relaunching a job execution."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    from app.agent_runtime.api.intervene import resume_router

    conv_id = uuid.uuid4()
    future = register(conv_id)

    app = FastAPI()
    app.include_router(resume_router)
    # data_client absent: if the endpoint wrongly fell through to the job
    # path it would 503 — resolving via the registry must succeed first.
    app.state.data_client = None

    with patch(
        "app.agent_runtime.api.intervene._execute_session"
    ) as _exec:
        with TestClient(app) as client:
            resp = client.post(
                "/internal/resume",
                json={
                    "session_id": str(conv_id),
                    "response_value": {"approval_value": True},
                },
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "resumed"
        _exec.assert_not_called()

    assert future.done()
    assert future.result() == {"approval_value": True}


@pytest.mark.asyncio
async def test_resume_endpoint_falls_back_to_job_path_when_not_conversation() -> None:
    """Non-conversation sessions keep the existing relaunch behaviour."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import AsyncMock, patch

    from app.agent_runtime.api.intervene import resume_router

    job_id = uuid.uuid4()
    app = FastAPI()
    app.include_router(resume_router)
    data_client = AsyncMock()
    app.state.data_client = data_client
    app.state.execution_semaphore = None

    with patch(
        "app.agent_runtime.api.intervene._execute_session"
    ) as _exec:
        with TestClient(app) as client:
            resp = client.post(
                "/internal/resume",
                json={"session_id": str(job_id), "response_value": None},
            )
        assert resp.status_code == 200
        assert _exec.called
    # mark_session_running still called (unchanged job-path contract)
    data_client.mark_session_running.assert_awaited()


# ── 3. LangChainHumanInterveneTool returns the resume value ─────────────────


@pytest.mark.asyncio
async def test_human_intervene_tool_conversational_returns_operator_response() -> None:
    """Conversational turns (conv_session_id set) must NOT use LangGraph
    interrupt (replay re-registered duplicate requests) — the tool waits on
    the in-process registry and returns the operator's response."""
    import json
    from unittest.mock import AsyncMock

    from app.agent_runtime import conversation_resume
    from app.services.agents.langchain_system_tools import LangChainHumanInterveneTool

    conv_id = uuid.uuid4()
    comm_hub_client = AsyncMock()
    comm_hub_client.call_human_intervene = AsyncMock(
        return_value={"request_id": "req-1", "status": "pending"}
    )
    tool = LangChainHumanInterveneTool(
        comm_hub_client=comm_hub_client,
        session_id=str(uuid.uuid4()),
        agent_type_id=str(uuid.uuid4()),
        conv_session_id=str(conv_id),
    )

    async def _approve():
        await asyncio.sleep(0.01)
        assert conversation_resume.resolve(conv_id, {"approval_value": True})

    task = asyncio.create_task(_approve())
    result = await tool._arun(
        intervention_type="approval", reason="r", choices=None, prompt="p"
    )
    await task
    payload = json.loads(result)
    assert payload["status"] == "approved"
    assert payload["approval_value"] is True
    assert payload["request_id"] == "req-1"


@pytest.mark.asyncio
async def test_human_intervene_tool_conversational_timeout_marks_not_executed() -> None:
    """Registry timeout (None) → the tool reports status='timeout' with an
    explicit not-executed error, so the model must not run the write."""
    import json
    from unittest.mock import AsyncMock, patch

    from app.agent_runtime import conversation_resume as _cr
    from app.services.agents.langchain_system_tools import LangChainHumanInterveneTool

    conv_id = uuid.uuid4()
    comm_hub_client = AsyncMock()
    comm_hub_client.call_human_intervene = AsyncMock(
        return_value={"request_id": "req-2", "status": "pending"}
    )
    tool = LangChainHumanInterveneTool(
        comm_hub_client=comm_hub_client,
        session_id=str(uuid.uuid4()),
        agent_type_id=str(uuid.uuid4()),
        conv_session_id=str(conv_id),
    )

    # Pre-empt the tool's registry future with a timeout: shrink the wait by
    # resolving nothing and patching the settings timeout via registry —
    # instead, directly assert the timeout branch contract.
    with patch(
        "app.agent_runtime.conversation_resume.wait_for_resume",
        side_effect=None,
    ) as _wait:
        import asyncio as _asyncio

        async def _timeout(conv_id, timeout_seconds):
            return None

        _wait.__wrapped__ = None
        _wait.side_effect = _timeout
        result = await tool._arun(
            intervention_type="approval", reason="r", choices=None, prompt="p"
        )
    payload = json.loads(result)
    assert payload["status"] == "timeout"
    assert "NOT executed" in payload["error"]
