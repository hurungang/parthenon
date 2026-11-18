"""Backend end-to-end — a paused turn survives an Agent Runtime instance swap.

Task 7.7 / test-plan §C ("a turn paused on AR instance A can be continued on a
DIGITALLY DIFFERENT instance") and PRD AC-2.1/AC-2.3, without any live service:

* instance **A** runs the conversational graph, pauses on ``interrupt()``,
  flushes the durable envelope to the CC-owned store, writes the resume index,
  and then its process state is thrown away;
* instance **B** (a brand-new ``DurableCheckpointSaver`` + transport) claims the
  turn, loads the persisted envelope, rebuilds the graph and continues it with
  ``Command(resume=...)`` — proving the pause never depended on A's memory;
* the claim arbitrates contention (B holds it, C is refused, an expired lease is
  re-acquirable without changing the lifecycle state);
* the confirmed write is applied exactly once under repeated delivery, and the
  turn is closed (outcome turn appended) exactly once.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agent_runtime.durable_checkpointer import DurableCheckpointSaver


class _State(TypedDict):
    messages: list[str]


def _graph() -> Any:
    """prepare → gate(interrupt) → finish, carrying the operator's answer."""

    def prepare(state: _State) -> dict[str, list[str]]:
        return {"messages": state["messages"] + ["prepared"]}

    def gate(state: _State) -> dict[str, list[str]]:
        answer = interrupt({"reason": "confirm the create?"})
        return {"messages": state["messages"] + [f"approved:{answer}"]}

    builder = StateGraph(_State)
    builder.add_node("prepare", prepare)
    builder.add_node("gate", gate)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "gate")
    builder.add_edge("gate", END)
    return builder


class FakeControlCenter:
    """The durable, CC-owned state shared by every simulated AR instance.

    Holds the opaque checkpoint payload, the resume index (claim + exactly-once
    fields), the applied-write markers and the single outcome turn — i.e. all the
    state that survives an Agent Runtime restart.
    """

    def __init__(self, conv_id: uuid.UUID, idempotency_key: str) -> None:
        self.conv_id = conv_id
        self.checkpoint: dict[str, Any] | None = None
        self.index: dict[str, Any] = {
            "resume_id": uuid.uuid4(),
            "conversation_session_id": conv_id,
            "resume_key": f"rk-{uuid.uuid4().hex}",
            "idempotency_key": idempotency_key,
            "state": "waiting_for_human",
            "is_terminal": False,
            "claimed_by": None,
            "claim_expires_at": None,
            "attempt_count": 0,
            "write_applied": False,
            "applied_effect_summary": None,
            "outcome": None,
            "outcome_turn_id": None,
        }
        self.applied_writes: list[dict[str, Any]] = []
        self.outcome_turns: list[str] = []

    # ── checkpoint payload (AR → CH → CC) ───────────────────────────────
    async def save_checkpoint(self, conv_id, payload, **kwargs):  # noqa: ANN001
        assert conv_id == self.conv_id
        self.checkpoint = json.loads(json.dumps(payload))
        return type("R", (), {"payload_bytes": len(json.dumps(payload))})()

    async def load_checkpoint(self) -> dict[str, Any] | None:
        return self.checkpoint

    # ── resume index + claims ───────────────────────────────────────────
    def claim(self, *, instance_id: str, lease_seconds: int = 45) -> str:
        now = datetime.now(timezone.utc)
        if self.index["is_terminal"]:
            return "terminal"
        live = self.index["claim_expires_at"]
        if (
            self.index["claimed_by"] is not None
            and live is not None
            and live > now
            and self.index["claimed_by"] != instance_id
        ):
            return "already_held"
        self.index["claimed_by"] = instance_id
        self.index["claim_expires_at"] = now + timedelta(seconds=lease_seconds)
        self.index["attempt_count"] += 1
        self.index["state"] = "resuming"
        return "acquired"

    def expire_claim(self) -> None:
        self.index["claim_expires_at"] = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )

    # ── exactly-once confirmed write ────────────────────────────────────
    def dispatch_confirmed_write(self, effect: dict[str, Any]) -> dict[str, Any]:
        if self.index["write_applied"]:
            return {
                "duplicate_dispatch": True,
                "write_applied": True,
                "applied_effect_summary": self.index["applied_effect_summary"],
            }
        if self.index["is_terminal"]:
            return {"error": "resume_terminal_no_write", "write_applied": False}
        self.index["write_applied"] = True
        self.index["applied_effect_summary"] = effect
        self.applied_writes.append(effect)
        return {"duplicate_dispatch": False, "write_applied": True}

    # ── single-transaction closer ───────────────────────────────────────
    def complete(self, *, outcome: str, outcome_turn_content: str) -> dict[str, Any]:
        self.index["state"] = "resolved"
        self.index["is_terminal"] = True
        self.index["outcome"] = outcome
        self.index["claimed_by"] = None
        self.index["claim_expires_at"] = None
        if self.index["outcome_turn_id"] is None:
            turn_id = uuid.uuid4()
            self.index["outcome_turn_id"] = turn_id
            self.outcome_turns.append(outcome_turn_content)
        return dict(self.index)


class Transport:
    """One simulated AR instance's courier to the shared CC store."""

    def __init__(self, cc: FakeControlCenter) -> None:
        self.cc = cc

    async def save_checkpoint(self, conv_id, payload, **kwargs):  # noqa: ANN001
        return await self.cc.save_checkpoint(conv_id, payload, **kwargs)

    async def load_checkpoint(self, conv_id):  # noqa: ANN001
        payload = await self.cc.load_checkpoint()
        if payload is None:
            return None
        return type(
            "CheckpointRead",
            (),
            {
                "resume_id": self.cc.index["resume_id"],
                "payload_kind": "agent_turn_state",
                "schema_version": payload.get("schema_version", 1),
                "payload_bytes": len(json.dumps(payload)),
                "payload": payload,
            },
        )()


def _instance(
    cc: FakeControlCenter, conv_id: uuid.UUID, *, payload: dict[str, Any] | None = None
) -> DurableCheckpointSaver:
    return DurableCheckpointSaver(
        Transport(cc),  # type: ignore[arg-type]
        conv_id,
        agent_type_id=uuid.uuid4(),
        turn_idempotency_key=cc.index["idempotency_key"],
        payload=payload,
    )


# ── The drill ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pause_on_instance_a_continues_on_a_fresh_instance_b() -> None:
    conv_id = uuid.uuid4()
    cc = FakeControlCenter(conv_id, idempotency_key=f"turn-{uuid.uuid4().hex}")
    config = {"configurable": {"thread_id": str(conv_id)}}

    # ── Instance A: pause + flush the durable envelope, then vanish. ──
    saver_a = _instance(cc, conv_id)
    app_a = _graph().compile(checkpointer=saver_a)
    paused = await app_a.ainvoke({"messages": ["create the skill"]}, config)
    assert paused.get("__interrupt__"), "the graph must pause on the confirmation"
    await saver_a.flush()
    assert cc.checkpoint is not None, "the pause point must be durable before 'waiting'"
    assert cc.checkpoint["turn_idempotency_key"] == cc.index["idempotency_key"]
    await saver_a.aclose()

    # Simulate the AR process going away: drop every reference to instance A's
    # memory.  Only the CC-owned payload survives.
    del saver_a, app_a, paused
    loaded = await Transport(cc).load_checkpoint(conv_id)
    assert loaded is not None

    # ── Instance B: claim, load, rebuild, continue. ──
    assert cc.claim(instance_id="ar-instance-b") == "acquired"
    saver_b = _instance(cc, conv_id, payload=loaded.payload)
    app_b = _graph().compile(checkpointer=saver_b)
    resumed = await app_b.ainvoke(Command(resume={"approval_value": True}), config)

    assert "prepared" in resumed["messages"]
    assert resumed["messages"][-1] == "approved:{'approval_value': True}"
    assert cc.index["state"] == "resuming"
    assert cc.index["claimed_by"] == "ar-instance-b"
    await saver_b.aclose()

    # The confirmed write applies once — a re-delivered dispatch replays the
    # stored summary instead of writing again.
    first = cc.dispatch_confirmed_write({"tool": "create_skill", "name": "skill-x"})
    retry = cc.dispatch_confirmed_write({"tool": "create_skill", "name": "skill-x"})
    assert first["write_applied"] is True
    assert retry["duplicate_dispatch"] is True
    assert len(cc.applied_writes) == 1

    # The closer appends exactly one outcome turn (a duplicate close adds none).
    closed = cc.complete(
        outcome="approved_applied", outcome_turn_content="Done — skill created."
    )
    again = cc.complete(
        outcome="approved_applied", outcome_turn_content="Done — skill created."
    )
    assert closed["state"] == "resolved"
    assert closed["outcome"] == "approved_applied"
    assert again["outcome_turn_id"] == closed["outcome_turn_id"]
    assert cc.outcome_turns == ["Done — skill created."]


@pytest.mark.asyncio
async def test_claim_contention_and_failover_after_instance_death() -> None:
    conv_id = uuid.uuid4()
    cc = FakeControlCenter(conv_id, idempotency_key=f"turn-{uuid.uuid4().hex}")

    # Instance A paused first.
    saver_a = _instance(cc, conv_id)
    app_a = _graph().compile(checkpointer=saver_a)
    await app_a.ainvoke({"messages": ["pause"]}, config := {"configurable": {"thread_id": str(conv_id)}})
    await saver_a.flush()
    await saver_a.aclose()

    # B acquires; C is refused while B's lease is live.
    assert cc.claim(instance_id="ar-b") == "acquired"
    state_before = cc.index["state"]
    assert cc.claim(instance_id="ar-c") == "already_held"
    assert cc.index["claimed_by"] == "ar-b"
    # A refused claim never changes the lifecycle state.
    assert cc.index["state"] == state_before

    # B "dies" mid-resume: its lease expires and C can finish the turn.
    cc.expire_claim()
    assert cc.claim(instance_id="ar-c") == "acquired"
    assert cc.index["claimed_by"] == "ar-c"
    assert cc.index["attempt_count"] == 2

    # C continues from the same durable payload.
    loaded = await Transport(cc).load_checkpoint(conv_id)
    saver_c = _instance(cc, conv_id, payload=loaded.payload)
    app_c = _graph().compile(checkpointer=saver_c)
    resumed = await app_c.ainvoke(Command(resume={"approval_value": False}), config)
    assert resumed["messages"][-1] == "approved:{'approval_value': False}"
    await saver_c.aclose()

    # A denied close never records an applied write.
    closed = cc.complete(outcome="denied", outcome_turn_content="Nothing was created.")
    assert closed["write_applied"] is False
    assert cc.applied_writes == []
    assert cc.outcome_turns == ["Nothing was created."]


@pytest.mark.asyncio
async def test_terminal_turn_cannot_be_claimed_or_re_applied() -> None:
    conv_id = uuid.uuid4()
    cc = FakeControlCenter(conv_id, idempotency_key=f"turn-{uuid.uuid4().hex}")
    cc.complete(outcome="expired", outcome_turn_content="The window elapsed.")

    assert cc.claim(instance_id="ar-late") == "terminal"
    refused = cc.dispatch_confirmed_write({"tool": "create_skill"})
    assert refused == {"error": "resume_terminal_no_write", "write_applied": False}
    assert cc.applied_writes == []
    assert len(cc.outcome_turns) == 1
