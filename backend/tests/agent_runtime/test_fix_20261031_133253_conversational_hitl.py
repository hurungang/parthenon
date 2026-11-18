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
from typing import TypedDict

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


# ── 3. LangChainHumanInterveneTool now pauses via LangGraph interrupt() ─────
#
# The conversational in-process wait was retired: both task and conversational
# paths register the intervention with CommHub and then call LangGraph
# ``interrupt()``.  A later ``Command(resume=<operator response>)`` replays the
# interrupted task (the registration is re-sent and de-duplicated by Control
# Center) and ``interrupt()`` returns the operator's value.


class _ToolGraphState(TypedDict):
    result: str


def _compile_tool_graph(tool):
    """Wrap one human_intervene tool call in a minimal graph with an interrupt."""
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph

    async def _intervene(state: _ToolGraphState) -> dict[str, str]:
        out = await tool._arun(
            intervention_type="approval", reason="r", choices=None, prompt="p"
        )
        return {"result": out}

    builder = StateGraph(_ToolGraphState)
    builder.add_node("intervene", _intervene)
    builder.add_edge(START, "intervene")
    builder.add_edge("intervene", END)
    return builder.compile(checkpointer=MemorySaver())


def _make_tool(conv_id: uuid.UUID):
    from unittest.mock import AsyncMock

    from app.services.agents.langchain_system_tools import LangChainHumanInterveneTool

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
    return tool, comm_hub_client


@pytest.mark.asyncio
async def test_human_intervene_tool_pauses_with_interrupt_for_conversation() -> None:
    """A conversational tool call returns immediately with an interrupt — it
    never blocks awaiting an in-process future."""
    import time

    conv_id = uuid.uuid4()
    tool, comm_hub_client = _make_tool(conv_id)
    app = _compile_tool_graph(tool)
    cfg = {"configurable": {"thread_id": str(conv_id)}}

    started = time.monotonic()
    result = await app.ainvoke({"result": ""}, cfg)
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, "conversational pause must not await an in-process future"
    assert result.get("__interrupt__"), "the tool must pause via interrupt()"
    comm_hub_client.call_human_intervene.assert_awaited_once()
    interrupt_value = result["__interrupt__"][0].value
    assert interrupt_value["request_id"] == "req-1"


@pytest.mark.asyncio
async def test_human_intervene_tool_resume_returns_operator_response() -> None:
    """``Command(resume=...)`` replays the task and returns the operator value."""
    import json

    from langgraph.types import Command

    conv_id = uuid.uuid4()
    tool, comm_hub_client = _make_tool(conv_id)
    app = _compile_tool_graph(tool)
    cfg = {"configurable": {"thread_id": str(conv_id)}}

    await app.ainvoke({"result": ""}, cfg)
    resumed = await app.ainvoke(Command(resume={"approval_value": True}), cfg)

    payload = json.loads(resumed["result"])
    assert payload["status"] == "approved"
    assert payload["approval_value"] is True
    assert payload["request_id"] == "req-1"
    # Replayed registration is identical → CC's dedupe reuses the pending
    # request instead of creating a second one.
    assert comm_hub_client.call_human_intervene.await_count == 2
    first = comm_hub_client.call_human_intervene.await_args_list[0].kwargs
    second = comm_hub_client.call_human_intervene.await_args_list[1].kwargs
    assert first == second


@pytest.mark.asyncio
async def test_human_intervene_tool_rejection_returns_non_approved_result() -> None:
    """A rejected confirmation surfaces as a non-approved result and the tool
    itself dispatches no management write (the loop never reaches CC)."""
    import json

    from langgraph.types import Command

    conv_id = uuid.uuid4()
    tool, comm_hub_client = _make_tool(conv_id)
    app = _compile_tool_graph(tool)
    cfg = {"configurable": {"thread_id": str(conv_id)}}

    await app.ainvoke({"result": ""}, cfg)
    resumed = await app.ainvoke(Command(resume={"approval_value": False}), cfg)

    payload = json.loads(resumed["result"])
    assert payload["status"] == "resolved"
    assert payload["approval_value"] is False
    comm_hub_client.call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_human_intervene_registration_failure_returns_error_without_pausing() -> None:
    """A failed CommHub registration returns an error tool result and does NOT
    interrupt — the model decides how to proceed and no pause is created."""
    import json
    from unittest.mock import AsyncMock

    from langchain_core.tools import BaseTool

    from app.services.agents.langchain_system_tools import LangChainHumanInterveneTool

    comm_hub_client = AsyncMock()
    comm_hub_client.call_human_intervene = AsyncMock(
        side_effect=RuntimeError("comm hub down")
    )
    tool = LangChainHumanInterveneTool(
        comm_hub_client=comm_hub_client,
        session_id=str(uuid.uuid4()),
        agent_type_id=str(uuid.uuid4()),
        conv_session_id=str(uuid.uuid4()),
    )
    assert isinstance(tool, BaseTool)

    result = await tool._arun(
        intervention_type="approval", reason="r", choices=None, prompt="p"
    )
    payload = json.loads(result)
    assert "comm hub down" in payload["error"]
