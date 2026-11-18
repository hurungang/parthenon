"""Resume a paused conversational turn from its durable checkpoint.

Covers the Agent Runtime half of the resumability promise:

* a pause persists the checkpoint + resume index BEFORE reporting waiting;
* a checkpoint/index write failure fails the pause closed (no fake waiting);
* the resume service claims, loads, rebuilds and continues on a *second*
  simulated instance, using only the persisted payload;
* contention → 409-style contention error, missing/unusable checkpoint →
  terminal ``unresumable``, re-pause → ``paused`` outcome;
* a claim lost mid-run aborts without completing (no double-apply).
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from app.agent_runtime.checkpoint_transport import (
    CheckpointRead,
    CheckpointTransportError,
    CheckpointTransportUnavailableError,
    ResumeClaimContentionError,
    ResumeClaimRead,
    ResumeIndexRead,
)
from app.agent_runtime.turn_resume_service import ConversationTurnResumeService
from app.services.agents.runtime_executor import (
    AgentRuntimeExecutor,
    ConversationTurnPause,
)


# ── Fakes ────────────────────────────────────────────────────────────────────

class _FakeTransport:
    def __init__(
        self,
        *,
        claim_status: str = "acquired",
        payload: dict[str, Any] | None = None,
        terminal_state: str | None = None,
        renew_status: str = "acquired",
    ) -> None:
        self.conv_id: uuid.UUID | None = None
        self.claim_status = claim_status
        self.renew_status = renew_status
        self.payload = payload
        self.terminal_state = terminal_state
        self.saved_checkpoints: list[dict[str, Any]] = []
        self.saved_indexes: list[dict[str, Any]] = []
        self.completions: list[dict[str, Any]] = []
        self.releases = 0
        self.claims = 0

    def _record(self, conv_id: uuid.UUID) -> ResumeIndexRead:
        self.conv_id = conv_id
        return ResumeIndexRead(
            resume_id=uuid.uuid4(),
            conversation_session_id=conv_id,
            resume_key="rk",
            idempotency_key="idem-from-record",
            state="waiting_for_human",
            is_terminal=self.terminal_state is not None,
        )

    async def save_checkpoint(self, conv_id, payload, **kwargs):  # noqa: ANN001
        self.saved_checkpoints.append(payload)
        return SimpleNamespace(payload_bytes=len(str(payload)))

    async def save_resume_index(self, conv_id, **kwargs):  # noqa: ANN001
        self.saved_indexes.append(kwargs)
        return self._record(conv_id)

    async def get_resume_index(self, conv_id):  # noqa: ANN001
        return self._record(conv_id)

    async def claim(self, conv_id, *, instance_id, lease_seconds=None):  # noqa: ANN001
        self.claims += 1
        record = self._record(conv_id)
        if self.claims > 1:
            status = self.renew_status
        else:
            status = self.claim_status
        if status == "terminal":
            record.state = self.terminal_state or "resolved"
            record.resume_outcome = (
                "approved_applied"
                if record.state == "resolved"
                else "resume_failed"
            )
            return ResumeClaimRead(status="terminal", resume=record)
        if status == "not_found":
            return ResumeClaimRead(status="not_found")
        if status == "already_held":
            return ResumeClaimRead(
                status="already_held",
                resume=record,
                holder_instance_id="ar-other",
            )
        return ResumeClaimRead(status="acquired", resume=record)

    async def load_checkpoint(self, conv_id):  # noqa: ANN001
        if self.payload is None:
            return None
        return CheckpointRead(
            resume_id=uuid.uuid4(),
            payload_kind="agent_turn_state",
            schema_version=1,
            payload_bytes=len(str(self.payload)),
            payload=self.payload,
        )

    async def release(self, conv_id, *, instance_id=None):  # noqa: ANN001
        self.releases += 1
        return True

    async def complete_resume(self, conv_id, **kwargs):  # noqa: ANN001
        self.completions.append(kwargs)
        return self._record(conv_id)


class _FakeDataClient:
    def __init__(self) -> None:
        self.agent_type_ids: list[uuid.UUID] = []
        self.conv_session_ids: list[uuid.UUID | None] = []

    async def get_agent_context(self, agent_type_id, conv_session_id=None):  # noqa: ANN001
        self.agent_type_ids.append(agent_type_id)
        self.conv_session_ids.append(conv_session_id)
        return {
            "is_active": True,
            "identity_role_valid": True,
            "model_id": "m",
            "model_config_id": str(uuid.uuid4()),
            "system_instruction": "system",
            "tool_definitions": [],
            "tool_name_map": {},
            "allowed_tools": [],
        }

    async def get_model_config(self, model_config_id):  # noqa: ANN001
        return {"provider_type": "openai", "api_key": "sk-test"}


class _FakeExecutor:
    """Stand-in for AgentRuntimeExecutor at the resume boundary."""

    last_kwargs: dict[str, Any] = {}
    pause: ConversationTurnPause | None = None
    delay_seconds: float = 0.0

    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs

    async def resume_conversation_turn_from_context(self, **kwargs):  # noqa: ANN003
        type(self).last_kwargs = dict(kwargs)
        if type(self).delay_seconds:
            await asyncio.sleep(type(self).delay_seconds)
        return ("resumed reply", {"tokens": 1}, [{"status": "thinking"}])

    def pop_conversation_pause(self):  # noqa: ANN201
        return type(self).pause


def _service(transport: _FakeTransport, **kwargs: Any) -> ConversationTurnResumeService:
    return ConversationTurnResumeService(
        transport=transport,  # type: ignore[arg-type]
        data_client=_FakeDataClient(),
        instance_id="ar-test",
        lease_seconds=30,
        renew_interval_seconds=3600,
        executor_factory=_FakeExecutor,
        **kwargs,
    )


async def _payload(conv_id: uuid.UUID) -> dict[str, Any]:
    """Build a genuine persisted checkpoint envelope (via a real pause)."""
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    from app.agent_runtime.durable_checkpointer import DurableCheckpointSaver

    class _S(TypedDict):
        value: str

    def _gate(state: _S) -> dict[str, str]:
        value = interrupt({"request_id": "req-1", "reason": "confirm?"})
        return {"value": str(value)}

    builder = StateGraph(_S)
    builder.add_node("gate", _gate)
    builder.add_edge(START, "gate")
    builder.add_edge("gate", END)

    captured: list[dict[str, Any]] = []

    class _CaptureTransport:
        async def save_checkpoint(self, conv_id_, payload, **kwargs):  # noqa: ANN001
            captured.append(payload)
            return SimpleNamespace(payload_bytes=1)

    saver = DurableCheckpointSaver(
        _CaptureTransport(),  # type: ignore[arg-type]
        conv_id,
        agent_type_id=uuid.uuid4(),
        turn_idempotency_key="idem-turn",
    )
    app = builder.compile(checkpointer=saver)
    await app.ainvoke({"value": ""}, {"configurable": {"thread_id": str(conv_id)}})
    await saver.flush()
    await saver.aclose()
    return captured[-1]


# ── Service-level behaviour ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resume_loads_checkpoint_and_continues_on_another_instance() -> None:
    conv_id = uuid.uuid4()
    payload = await _payload(conv_id)
    transport = _FakeTransport(payload=payload)
    _FakeExecutor.pause = None
    events: list[dict[str, str]] = []

    async def _on_event(event: dict[str, str]) -> None:
        events.append(event)

    outcome = await _service(transport).resume(
        conv_id, {"approval_value": True}, status_event_callback=_on_event
    )

    assert outcome.status == "resumed"
    assert outcome.response == "resumed reply"
    assert outcome.pause is None
    assert transport.claims == 1
    assert transport.releases == 1
    assert transport.completions == []
    # The first streamed status is ``thinking`` (the turn is being continued).
    assert events and events[0]["status"] == "thinking"
    # The executor received the persisted payload + the record's stable key.
    kwargs = _FakeExecutor.last_kwargs
    assert kwargs["checkpoint_payload"] == payload
    assert kwargs["turn_idempotency_key"] == "idem-from-record"
    assert kwargs["response_value"] == {"approval_value": True}


@pytest.mark.asyncio
async def test_claim_contention_is_distinct_error() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeTransport(claim_status="already_held")
    with pytest.raises(ResumeClaimContentionError) as exc_info:
        await _service(transport).resume(conv_id, {"approval_value": True})
    assert exc_info.value.holder_instance_id == "ar-other"
    assert transport.completions == []


@pytest.mark.asyncio
async def test_missing_checkpoint_resolves_unresumable_and_completes_failed() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeTransport(payload=None)
    outcome = await _service(transport).resume(conv_id, {"approval_value": True})

    assert outcome.status == "unresumable"
    assert outcome.reason == "checkpoint_unavailable"
    assert len(transport.completions) == 1
    assert transport.completions[0]["outcome"] == "resume_failed"
    assert transport.releases == 0


@pytest.mark.asyncio
async def test_unsupported_checkpoint_schema_is_unresumable() -> None:
    conv_id = uuid.uuid4()
    payload = await _payload(conv_id)
    payload["schema_version"] = 99
    transport = _FakeTransport(payload=payload)
    outcome = await _service(transport).resume(conv_id, {"approval_value": True})

    assert outcome.status == "unresumable"
    assert outcome.reason == "resume_failed"
    assert transport.completions[-1]["outcome"] == "resume_failed"


@pytest.mark.asyncio
async def test_re_pause_during_resume_returns_paused_outcome() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeTransport(payload=await _payload(conv_id))
    _FakeExecutor.pause = ConversationTurnPause(
        resume_id=str(uuid.uuid4()),
        resume_key="rk-2",
        intervene_request_id=str(uuid.uuid4()),
        idempotency_key="idem-2",
    )
    try:
        outcome = await _service(transport).resume(conv_id, {"approval_value": True})
    finally:
        _FakeExecutor.pause = None

    assert outcome.status == "resumed"
    assert outcome.pause is not None
    assert outcome.pause.idempotency_key == "idem-2"
    assert transport.releases == 1
    # The executor persists the new pause; the service must not close it.
    assert transport.completions == []


@pytest.mark.asyncio
async def test_terminal_record_maps_to_already_resolved() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeTransport(claim_status="terminal", terminal_state="resolved")
    outcome = await _service(transport).resume(conv_id, {"approval_value": True})
    assert outcome.status == "already_resolved"
    assert outcome.reason == "approved_applied"


@pytest.mark.asyncio
async def test_terminal_unresumable_record_maps_to_unresumable() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeTransport(claim_status="terminal", terminal_state="unresumable")
    outcome = await _service(transport).resume(conv_id, {"approval_value": True})
    assert outcome.status == "unresumable"


@pytest.mark.asyncio
async def test_not_found_maps_to_not_awaiting() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeTransport(claim_status="not_found")
    outcome = await _service(transport).resume(conv_id, {"approval_value": True})
    assert outcome.status == "not_awaiting"


@pytest.mark.asyncio
async def test_claim_lost_mid_run_aborts_without_completing() -> None:
    """If a renewal finds another holder, abort — never write a terminal
    outcome for a turn this instance no longer owns (no double-apply)."""
    conv_id = uuid.uuid4()
    transport = _FakeTransport(
        payload=await _payload(conv_id), renew_status="already_held"
    )
    _FakeExecutor.pause = None
    _FakeExecutor.delay_seconds = 1.0
    service = ConversationTurnResumeService(
        transport=transport,  # type: ignore[arg-type]
        data_client=_FakeDataClient(),
        instance_id="ar-test",
        lease_seconds=3,
        renew_interval_seconds=0.05,
        executor_factory=_FakeExecutor,
    )
    try:
        outcome = await service.resume(conv_id, {"approval_value": True})
    finally:
        _FakeExecutor.delay_seconds = 0.0

    assert outcome.status == "unresumable"
    assert outcome.reason == "resume_failed"
    assert transport.claims >= 2
    assert transport.completions == [], "a lost claim must never complete the turn"


@pytest.mark.asyncio
async def test_agent_context_rebuild_failure_is_unresumable() -> None:
    conv_id = uuid.uuid4()
    transport = _FakeTransport(payload=await _payload(conv_id))

    class _BrokenDataClient(_FakeDataClient):
        async def get_agent_context(self, agent_type_id, conv_session_id=None):  # noqa: ANN001
            raise RuntimeError("agent type deleted")

    service = ConversationTurnResumeService(
        transport=transport,  # type: ignore[arg-type]
        data_client=_BrokenDataClient(),
        instance_id="ar-test",
        renew_interval_seconds=3600,
        executor_factory=_FakeExecutor,
    )
    outcome = await service.resume(conv_id, {"approval_value": True})
    assert outcome.status == "unresumable"
    assert transport.completions[-1]["outcome"] == "resume_failed"


# ── Executor pause persistence ──────────────────────────────────────────────

from langgraph.types import Interrupt as _LangGraphInterrupt


def _interrupt(value: dict[str, Any]) -> _LangGraphInterrupt:
    return _LangGraphInterrupt(value=value, id=uuid.uuid4().hex)


def _executor_patches():
    import app.agent_runtime.comm_hub_client as comm_hub_module
    import app.services.agents.guardrail_callback as guardrail_cb_module
    import app.services.agents.langchain_tool_wrapper as tool_wrapper_module
    import langchain.agents as lc_agents

    return (
        patch.object(
            comm_hub_module,
            "CommHubToolClient",
            lambda: SimpleNamespace(
                set_certificate=lambda *a: None,
                set_turn_idempotency_key=lambda *a: None,
            ),
        ),
        patch.object(
            guardrail_cb_module, "GuardrailCallback", lambda **kwargs: SimpleNamespace()
        ),
        patch.object(
            tool_wrapper_module, "build_langchain_tools_for_ar_path", lambda **kwargs: []
        ),
    )


def _agent_context() -> dict[str, Any]:
    return {
        "allowed_tools": [],
        "tool_definitions": [],
        "tool_name_map": {},
        "role_id": None,
        "model_id": "test-model",
    }


class _PausedAgent:
    """Emulates LangGraph: writes the pause checkpoint + interrupt write, then
    returns the interrupt in the result."""

    def __init__(self, interrupt_value: dict[str, Any], saver: Any) -> None:
        self._value = interrupt_value
        self._saver = saver

    async def ainvoke(self, messages, config):  # noqa: ANN001
        if self._saver is not None:
            new_config = await self._saver.aput(
                config,
                {
                    "id": str(uuid.uuid4()),
                    "v": 1,
                    "ts": "2026-01-01T00:00:00+00:00",
                    "channel_values": {"messages": []},
                    "channel_versions": {"messages": "1"},
                    "versions_seen": {},
                    "updated_channels": ["messages"],
                },
                {"source": "loop", "step": 0},
                {"messages": "1"},
            )
            await self._saver.aput_writes(
                new_config,
                [("__interrupt__", [_interrupt(self._value)])],
                task_id=str(uuid.uuid4()),
            )
        return {"messages": [], "__interrupt__": [_interrupt(self._value)]}


@pytest.mark.asyncio
async def test_pause_persists_checkpoint_and_index_before_waiting() -> None:
    sequence: list[str] = []
    request_id = uuid.uuid4()
    conv_id = uuid.uuid4()

    class _OrderedTransport(_FakeTransport):
        async def save_checkpoint(self, conv_id_, payload, **kwargs):  # noqa: ANN001
            sequence.append("checkpoint")
            return await super().save_checkpoint(conv_id_, payload, **kwargs)

        async def save_resume_index(self, conv_id_, **kwargs):  # noqa: ANN001
            sequence.append("index")
            return await super().save_resume_index(conv_id_, **kwargs)

    transport = _OrderedTransport()
    events: list[dict[str, str]] = []

    async def _on_event(event: dict[str, str]) -> None:
        events.append(event)
        if event.get("status") == "waiting_for_human":
            sequence.append("waiting")

    executor = AgentRuntimeExecutor(
        data_client=SimpleNamespace(), checkpoint_transport=transport
    )
    p1, p2, p3 = _executor_patches()
    import langchain.agents as lc_agents

    try:
        with p1, p2, p3, patch.object(
            lc_agents,
            "create_agent",
            lambda **kw: _PausedAgent(
                {
                    "request_id": str(request_id),
                    "intervention_type": "approval",
                    "reason": "confirm?",
                },
                kw.get("checkpointer"),
            ),
        ):
            reply, _usage, _events = await executor.execute_conversation_turn_from_context(
                agent_type_id=uuid.uuid4(),
                agent_context=_agent_context(),
                model_config={"provider_type": "openai"},
                messages=[{"role": "user", "content": "hello"}],
                conv_session_id=conv_id,
                status_event_callback=_on_event,
                turn_idempotency_key="idem-turn",
            )
    finally:
        pass

    pause = executor.pop_conversation_pause()
    assert reply == ""
    assert pause is not None and pause.durable
    assert pause.intervene_request_id == str(request_id)
    assert pause.resume_key == "rk"
    assert pause.idempotency_key == "idem-from-record"
    assert sequence == ["checkpoint", "index", "waiting"]
    assert transport.saved_indexes[0]["intervene_request_id"] == request_id


@pytest.mark.asyncio
async def test_pause_write_refusal_fails_closed_without_waiting() -> None:
    conv_id = uuid.uuid4()

    class _RefusingTransport(_FakeTransport):
        async def save_checkpoint(self, conv_id_, payload, **kwargs):  # noqa: ANN001
            raise CheckpointTransportError("payload rejected (413)")

    transport = _RefusingTransport()
    events: list[dict[str, str]] = []

    async def _on_event(event: dict[str, str]) -> None:
        events.append(event)

    executor = AgentRuntimeExecutor(
        data_client=SimpleNamespace(), checkpoint_transport=transport
    )
    p1, p2, p3 = _executor_patches()
    import langchain.agents as lc_agents

    with p1, p2, p3, patch.object(
        lc_agents,
        "create_agent",
        lambda **kw: _PausedAgent(
            {"request_id": str(uuid.uuid4()), "reason": "r"}, kw.get("checkpointer")
        ),
    ):
        reply, _usage, _events = await executor.execute_conversation_turn_from_context(
            agent_type_id=uuid.uuid4(),
            agent_context=_agent_context(),
            model_config={"provider_type": "openai"},
            messages=[{"role": "user", "content": "hello"}],
            conv_session_id=conv_id,
            status_event_callback=_on_event,
        )

    assert "NOT execute" in reply
    assert executor.pop_conversation_pause() is None
    statuses = [e.get("status") for e in events]
    assert "waiting_for_human" not in statuses
    assert statuses[-1] == "timeout_or_failed"
    assert events[-1].get("reason") == "pause_not_persisted"


@pytest.mark.asyncio
async def test_relay_unavailable_degrades_to_legacy_pause() -> None:
    """A CH without the checkpoint relay (rollout window) keeps the previous
    in-process conversational UX instead of failing the turn."""
    conv_id = uuid.uuid4()

    class _UnavailableTransport(_FakeTransport):
        async def save_checkpoint(self, conv_id_, payload, **kwargs):  # noqa: ANN001
            raise CheckpointTransportUnavailableError("relay not deployed")

    transport = _UnavailableTransport()
    events: list[dict[str, str]] = []

    async def _on_event(event: dict[str, str]) -> None:
        events.append(event)

    executor = AgentRuntimeExecutor(
        data_client=SimpleNamespace(), checkpoint_transport=transport
    )
    p1, p2, p3 = _executor_patches()
    import langchain.agents as lc_agents

    async def _no_response(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    with p1, p2, p3, patch.object(
        lc_agents,
        "create_agent",
        lambda **kw: _PausedAgent(
            {"request_id": str(uuid.uuid4()), "reason": "r"}, kw.get("checkpointer")
        ),
    ), patch(
        "app.agent_runtime.conversation_resume.wait_for_resume", side_effect=_no_response
    ):
        reply, _usage, _events = await executor.execute_conversation_turn_from_context(
            agent_type_id=uuid.uuid4(),
            agent_context=_agent_context(),
            model_config={"provider_type": "openai"},
            messages=[{"role": "user", "content": "hello"}],
            conv_session_id=conv_id,
            status_event_callback=_on_event,
        )

    statuses = [e.get("status") for e in events]
    assert statuses[0] == "waiting_for_human"
    assert executor.pop_conversation_pause() is None
    assert "NOT execute" in reply


@pytest.mark.asyncio
async def test_resume_endpoint_maps_contention_to_http_409() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.agent_runtime.api import conversation as conversation_module

    conv_id = uuid.uuid4()

    class _ContendingService:
        async def claim(self, conv_session_id):  # noqa: ANN001
            raise ResumeClaimContentionError(
                "held elsewhere", holder_instance_id="ar-other"
            )

    app = FastAPI()
    app.include_router(conversation_module.conversation_router)
    app.state.data_client = SimpleNamespace()

    with patch.object(
        conversation_module, "build_resume_service", return_value=_ContendingService()
    ):
        with TestClient(app) as client:
            resp = client.post(
                "/internal/conversation/resume",
                json={
                    "conv_session_id": str(conv_id),
                    "response_value": {"approval_value": True},
                },
            )

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["status"] == "claim_held"
    assert detail["holder_instance_id"] == "ar-other"


@pytest.mark.asyncio
async def test_resume_endpoint_streams_final_and_paused_chunks() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.agent_runtime.api import conversation as conversation_module
    from app.agent_runtime.turn_resume_service import ConversationResumeOutcome

    conv_id = uuid.uuid4()

    class _Service:
        def __init__(self, outcome: ConversationResumeOutcome) -> None:
            self._outcome = outcome

        async def claim(self, conv_session_id):  # noqa: ANN001
            return ResumeClaimRead(
                status="acquired",
                resume=ResumeIndexRead(
                    resume_id=uuid.uuid4(),
                    conversation_session_id=conv_session_id,
                    resume_key="rk",
                    state="waiting_for_human",
                ),
            )

        def outcome_for_claim(self, claim):  # noqa: ANN001
            return None

        async def resume_claimed(self, conv_session_id, claim, response_value, *, status_event_callback=None):  # noqa: ANN001, ANN003
            if status_event_callback is not None:
                await status_event_callback({"status": "thinking"})
            return self._outcome

    def _run(outcome: ConversationResumeOutcome) -> list[dict[str, Any]]:
        app = FastAPI()
        app.include_router(conversation_module.conversation_router)
        app.state.data_client = SimpleNamespace()
        with patch.object(
            conversation_module, "build_resume_service", return_value=_Service(outcome)
        ):
            with TestClient(app) as client:
                with client.stream(
                    "POST",
                    "/internal/conversation/resume",
                    json={
                        "conv_session_id": str(conv_id),
                        "response_value": {"approval_value": True},
                        "stream_status_events": True,
                    },
                ) as resp:
                    assert resp.status_code == 200
                    return [
                        __import__("json").loads(line)
                        for line in resp.iter_lines()
                        if line
                    ]

    final_chunks = _run(
        ConversationResumeOutcome(status="resumed", response="done")
    )
    assert [c["type"] for c in final_chunks] == ["status_event", "final"]
    assert final_chunks[-1]["response"] == "done"

    paused_chunks = _run(
        ConversationResumeOutcome(
            status="resumed",
            pause=ConversationTurnPause(resume_id="r2", resume_key="rk2"),
        )
    )
    assert [c["type"] for c in paused_chunks] == ["status_event", "paused"]
