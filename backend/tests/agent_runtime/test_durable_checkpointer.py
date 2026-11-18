"""DurableCheckpointSaver — LangGraph checkpointer backed by the CC payload.

Covers the resumability promise end to end at the framework boundary:

* a pause-point snapshot round-trips through a fake transport and a *fresh*
  saver resumes the graph with ``Command(resume=...)``;
* intermediate super-steps coalesce — only the latest checkpoint id reaches
  the payload;
* ``flush()`` waits for an outstanding (background) write to finish;
* a corrupt payload or a schema mismatch raises the typed
  ``CheckpointUnavailableError`` instead of half-restoring a graph;
* a resumed turn that pauses again persists the *new* pause checkpoint.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agent_runtime.durable_checkpointer import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointUnavailableError,
    DurableCheckpointSaver,
)


class _GraphState(TypedDict):
    messages: list[str]
    other: str


def _graph(gate_calls: list[int] | None = None):
    """Two-node graph whose second node pauses on interrupt()."""

    def prepare(state: _GraphState) -> dict[str, Any]:
        return {"messages": state["messages"] + ["prepared"], "other": "x"}

    def gate(state: _GraphState) -> dict[str, Any]:
        if gate_calls is not None:
            gate_calls.append(1)
        value = interrupt({"request_id": "req-1", "reason": "confirm?"})
        if isinstance(value, dict) and value.get("pause_again"):
            second = interrupt({"request_id": "req-2", "reason": "confirm again?"})
            return {"messages": state["messages"] + [f"second:{second}"]}
        return {"messages": state["messages"] + [f"first:{value}"]}

    builder = StateGraph(_GraphState)
    builder.add_node("prepare", prepare)
    builder.add_node("gate", gate)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "gate")
    builder.add_edge("gate", END)
    return builder


class _FakeCheckpointTransport:
    """Records saved payloads; can gate the next save on a future."""

    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []
        self.gate: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def save_checkpoint(
        self,
        conv_session_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        schema_version: int = 1,
        payload_kind: str = "agent_turn_state",
        expires_at: Any = None,
    ) -> Any:
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        # Simulate the JSON round-trip through CC.
        self.saved.append(json.loads(json.dumps(payload)))
        return object()


async def _pause(
    conv_id: uuid.UUID,
    transport: _FakeCheckpointTransport,
    *,
    agent_type_id: uuid.UUID | None = None,
    gate_calls: list[int] | None = None,
):
    saver = DurableCheckpointSaver(
        transport,  # type: ignore[arg-type]
        conv_id,
        agent_type_id=agent_type_id,
        turn_idempotency_key="idem-1",
    )
    app = _graph(gate_calls).compile(checkpointer=saver)
    config = {"configurable": {"thread_id": str(conv_id)}}
    result = await app.ainvoke({"messages": ["u"], "other": ""}, config)
    assert result.get("__interrupt__")
    await saver.flush()
    return saver, app, config, result


@pytest.mark.asyncio
async def test_pause_payload_round_trips_and_resumes_on_a_fresh_saver() -> None:
    conv_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    transport = _FakeCheckpointTransport()
    saver, _app, _config, _result = await _pause(
        conv_id, transport, agent_type_id=agent_type_id
    )
    payload = transport.saved[-1]

    assert payload["schema_version"] == CHECKPOINT_SCHEMA_VERSION
    assert payload["format"] == "langgraph-jsonplus-v1"
    assert payload["agent_type_id"] == str(agent_type_id)
    assert payload["turn_idempotency_key"] == "idem-1"
    assert payload["thread_id"] == str(conv_id)
    assert payload["checkpoint_id"] == saver.checkpoint_id
    assert payload["pending_writes"], "the interrupt write must be persisted"
    await saver.aclose()

    # A DIFFERENT saver (fresh instance) resumes from the persisted envelope.
    fresh_transport = _FakeCheckpointTransport()
    resumed_saver = DurableCheckpointSaver(
        fresh_transport,  # type: ignore[arg-type]
        conv_id,
        payload=json.loads(json.dumps(payload)),
    )
    assert resumed_saver.agent_type_id == agent_type_id
    app = _graph().compile(checkpointer=resumed_saver)
    config = {"configurable": {"thread_id": str(conv_id)}}
    resumed = await app.ainvoke(Command(resume={"approval_value": True}), config)

    assert resumed["messages"][-1] == "first:{'approval_value': True}"
    # A completed resume persisted nothing (only pause points are durable).
    assert fresh_transport.saved == []
    await resumed_saver.aclose()


@pytest.mark.asyncio
async def test_only_latest_checkpoint_is_authoritative() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeCheckpointTransport()
    saver, _app, _config, _result = await _pause(conv_id, transport)
    payload = transport.saved[-1]

    # The pause graph produced several super-steps; only one is stored.
    assert payload["checkpoint_id"] == saver.checkpoint_id
    assert "checkpoints" not in payload
    await saver.aclose()


@pytest.mark.asyncio
async def test_flush_waits_for_an_outstanding_background_write() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeCheckpointTransport()
    transport.gate = asyncio.Event()

    saver = DurableCheckpointSaver(
        transport,  # type: ignore[arg-type]
        conv_id,
        autosave=True,
    )
    app = _graph().compile(checkpointer=saver)
    config = {"configurable": {"thread_id": str(conv_id)}}

    invoke = asyncio.create_task(app.ainvoke({"messages": ["u"], "other": ""}, config))
    await asyncio.wait_for(transport.entered.wait(), timeout=2.0)

    flushed = asyncio.Event()

    async def _flush() -> None:
        await saver.flush()
        flushed.set()

    flush_task = asyncio.create_task(_flush())
    await asyncio.sleep(0.05)
    assert not flushed.is_set(), "flush must wait for the outstanding write"

    transport.gate.set()
    await asyncio.wait_for(flush_task, timeout=3.0)
    assert flushed.is_set()
    await asyncio.wait_for(invoke, timeout=3.0)
    await saver.aclose()


@pytest.mark.asyncio
async def test_schema_mismatch_raises_checkpoint_unavailable() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeCheckpointTransport()
    saver, _app, _config, _result = await _pause(conv_id, transport)
    payload = transport.saved[-1]
    await saver.aclose()

    bad = dict(payload)
    bad["schema_version"] = CHECKPOINT_SCHEMA_VERSION + 1
    with pytest.raises(CheckpointUnavailableError, match="schema version"):
        DurableCheckpointSaver(transport, conv_id, payload=bad)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_corrupt_payload_raises_checkpoint_unavailable() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeCheckpointTransport()
    saver, _app, _config, _result = await _pause(conv_id, transport)
    payload = transport.saved[-1]
    await saver.aclose()

    corrupt = json.loads(json.dumps(payload))
    corrupt["checkpoint"]["d"] = "!!!not-base64!!!"
    with pytest.raises(CheckpointUnavailableError):
        DurableCheckpointSaver(transport, conv_id, payload=corrupt)  # type: ignore[arg-type]

    missing = json.loads(json.dumps(payload))
    missing.pop("metadata")
    with pytest.raises(CheckpointUnavailableError, match="missing required keys"):
        DurableCheckpointSaver(transport, conv_id, payload=missing)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_payload_for_another_thread_is_rejected() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeCheckpointTransport()
    saver, _app, _config, _result = await _pause(conv_id, transport)
    payload = transport.saved[-1]
    await saver.aclose()

    with pytest.raises(CheckpointUnavailableError, match="thread"):
        DurableCheckpointSaver(transport, uuid.uuid4(), payload=payload)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_re_pause_during_resume_persists_the_new_pause_point() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeCheckpointTransport()
    saver, _app, _config, _result = await _pause(conv_id, transport)
    first_pause = transport.saved[-1]
    saves_before = len(transport.saved)
    await saver.aclose()

    resumed_saver = DurableCheckpointSaver(
        transport,  # type: ignore[arg-type]
        conv_id,
        payload=json.loads(json.dumps(first_pause)),
    )
    app = _graph().compile(checkpointer=resumed_saver)
    config = {"configurable": {"thread_id": str(conv_id)}}
    second_pause = await app.ainvoke(
        Command(resume={"pause_again": True}), config
    )

    assert second_pause.get("__interrupt__")
    await resumed_saver.flush()
    assert len(transport.saved) == saves_before + 1, (
        "the re-pause must be persisted as a new payload"
    )
    latest = transport.saved[-1]
    assert latest["checkpoint_id"] == resumed_saver.checkpoint_id
    # The persisted pending writes now carry the SECOND interrupt (the pause
    # happened in the same super-step, so the checkpoint id may be unchanged).
    interrupt_writes = [
        w for w in latest["pending_writes"] if w["channel"] == "__interrupt__"
    ]
    assert interrupt_writes, "the new pause point must be persisted"
    await resumed_saver.aclose()

    # And the second pause point is itself resumable.
    third_saver = DurableCheckpointSaver(
        transport,  # type: ignore[arg-type]
        conv_id,
        payload=json.loads(json.dumps(latest)),
    )
    app3 = _graph().compile(checkpointer=third_saver)
    final = await app3.ainvoke(Command(resume="second-answer"), config)
    assert final["messages"][-1] == "second:second-answer"
    await third_saver.aclose()


@pytest.mark.asyncio
async def test_alist_yields_only_the_latest_checkpoint() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeCheckpointTransport()
    saver, _app, config, _result = await _pause(conv_id, transport)

    listed = [item async for item in saver.alist(config)]
    assert len(listed) == 1
    assert listed[0].checkpoint["id"] == saver.checkpoint_id
    # A different thread yields nothing.
    other = {"configurable": {"thread_id": str(uuid.uuid4())}}
    assert [item async for item in saver.alist(other)] == []
    await saver.aclose()


@pytest.mark.asyncio
async def test_adelete_thread_clears_local_state() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeCheckpointTransport()
    saver, _app, config, _result = await _pause(conv_id, transport)

    await saver.adelete_thread(str(conv_id))
    assert not saver.has_checkpoint
    assert await saver.aget_tuple(config) is None
    await saver.aclose()


@pytest.mark.asyncio
async def test_new_turn_starts_empty_and_does_not_load_old_state() -> None:
    """A fresh conversational turn must NOT restore the previous turn's
    channels (each turn passes the full history as input)."""
    conv_id = uuid.uuid4()
    transport = _FakeCheckpointTransport()
    saver = DurableCheckpointSaver(transport, conv_id)  # type: ignore[arg-type]
    config = {"configurable": {"thread_id": str(conv_id)}}
    assert await saver.aget_tuple(config) is None
    await saver.aclose()


class _RefusingCheckpointTransport:
    """Relay that refuses the write (e.g. missing signed tenant headers)."""

    def __init__(self) -> None:
        self.attempts = 0

    async def save_checkpoint(
        self,
        conv_session_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        schema_version: int = 1,
        payload_kind: str = "agent_turn_state",
        expires_at: Any = None,
    ) -> Any:
        from app.agent_runtime.checkpoint_transport import CheckpointTransportError

        self.attempts += 1
        raise CheckpointTransportError(
            "Checkpoint relay rejected the write: HTTP 401 — signed tenant "
            "context headers are required"
        )


@pytest.mark.asyncio
async def test_flush_is_fail_closed_when_the_cc_write_is_rejected(caplog) -> None:
    """``flush()`` must raise — and must NOT log success — on a refused write.

    A refused checkpoint save means nothing durable was stored, so a pause that
    returns "flushed" would masquerade as resumable (the 401 relay bug).  The
    executor relies on this raise to fail the turn closed
    (``pause_not_persisted``) instead of reporting ``waiting_for_human``.
    """
    from app.agent_runtime.checkpoint_transport import CheckpointTransportError

    conv_id = uuid.uuid4()
    transport = _RefusingCheckpointTransport()
    saver = DurableCheckpointSaver(transport, conv_id)  # type: ignore[arg-type]
    app = _graph().compile(checkpointer=saver)
    config = {"configurable": {"thread_id": str(conv_id)}}
    result = await app.ainvoke({"messages": ["u"], "other": ""}, config)
    assert result.get("__interrupt__")

    caplog.clear()
    with caplog.at_level("INFO"):
        with pytest.raises(CheckpointTransportError):
            await saver.flush()
    assert transport.attempts == 1
    assert not any(
        "Durable checkpoint flushed" in record.getMessage()
        for record in caplog.records
    ), "a refused write must never log a successful flush"
    await saver.aclose()
