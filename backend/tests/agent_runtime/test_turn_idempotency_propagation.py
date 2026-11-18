"""Paused-turn idempotency key propagation (AR → CH → CC).

The key is generated once per paused turn (opaque, never derived from user
input), stored on the Control Center resume record, and carried on every tool
call made while the turn is being continued.  CH forwards it to CC as a request
header; calls outside a paused turn carry no key at all.
"""
from __future__ import annotations

import inspect
import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.agent_runtime.checkpoint_transport import TURN_IDEMPOTENCY_HEADER
from app.agent_runtime.comm_hub_client import CommHubToolClient


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/tools/call"):
            return httpx.Response(200, json={"result": {"ok": True}})
        return httpx.Response(200, json={})

    @property
    def bodies(self) -> list[dict]:
        return [json.loads(r.content or b"{}") for r in self.requests]

    @property
    def headers(self) -> list[httpx.Headers]:
        return [r.headers for r in self.requests]


def _patched_client(recorder: _Recorder):
    """Patch the CommHub client's egress factory with a fake socket."""

    def _factory(**kwargs):  # noqa: ANN003
        return httpx.AsyncClient(transport=httpx.MockTransport(recorder.handler))

    return patch("app.agent_runtime.comm_hub_client.internal_httpx_client", _factory)


# ── AR → CH ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_call_tool_sends_the_same_key_on_retries() -> None:
    recorder = _Recorder()
    client = CommHubToolClient()
    client.set_turn_idempotency_key("turn-key-1")

    with _patched_client(recorder):
        await client.call_tool(
            "system____invoke_management_tool",
            {"tool_name": "create_skill"},
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )
        # A retried / duplicated dispatch of the same tool call.
        await client.call_tool(
            "system____invoke_management_tool",
            {"tool_name": "create_skill"},
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )

    assert len(recorder.requests) == 2
    for headers, body in zip(recorder.headers, recorder.bodies):
        assert headers[TURN_IDEMPOTENCY_HEADER] == "turn-key-1"
        assert body["idempotency_key"] == "turn-key-1"


@pytest.mark.asyncio
async def test_call_tool_sends_no_key_outside_a_paused_turn() -> None:
    recorder = _Recorder()
    client = CommHubToolClient()

    with _patched_client(recorder):
        await client.call_tool(
            "system____save_data",
            {"data_name": "x", "data_value": {}},
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )

    assert TURN_IDEMPOTENCY_HEADER not in recorder.headers[0]
    assert "idempotency_key" not in recorder.bodies[0]


@pytest.mark.asyncio
async def test_call_tool_explicit_key_overrides_the_bound_key() -> None:
    recorder = _Recorder()
    client = CommHubToolClient()
    client.set_turn_idempotency_key("bound-key")

    with _patched_client(recorder):
        await client.call_tool(
            "system____save_data",
            {},
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
            idempotency_key="explicit-key",
        )

    assert recorder.headers[0][TURN_IDEMPOTENCY_HEADER] == "explicit-key"


@pytest.mark.asyncio
async def test_human_intervene_registration_carries_the_turn_key() -> None:
    recorder = _Recorder()
    client = CommHubToolClient()
    client.set_turn_idempotency_key("turn-key-2")

    with _patched_client(recorder):
        await client.call_human_intervene(
            session_id=str(uuid.uuid4()),
            intervention_type="approval",
            reason="confirm?",
            conv_session_id=str(uuid.uuid4()),
        )

    body = recorder.bodies[0]
    assert body["tool_args"]["turn_idempotency_key"] == "turn-key-2"
    assert recorder.headers[0][TURN_IDEMPOTENCY_HEADER] == "turn-key-2"


# ── CH → CC ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ch_tool_route_forwards_the_key_as_a_header_to_cc() -> None:
    from app.communication_hub.api.internal import tool_routing

    captured: dict[str, httpx.Request] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"result": {"ok": True}})

    def _factory(**kwargs):  # noqa: ANN003
        return httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(certificate_manager=None)),
        headers={"X-Turn-Idempotency-Key": "turn-key-3"},
    )
    body = tool_routing.ToolCallRequest(
        tool_name="system____invoke_management_tool",
        tool_args={"tool_name": "create_skill"},
        session_id=str(uuid.uuid4()),
        agent_type_id=str(uuid.uuid4()),
        conv_session_id=str(uuid.uuid4()),
        idempotency_key="turn-key-3",
    )

    async def _user_sub(_jwt):  # noqa: ANN001
        return "user-1"

    with patch.object(
        tool_routing,
        "_build_control_center_auth",
        return_value=({}, {}),
    ), patch.object(
        tool_routing, "_extract_user_sub", _user_sub
    ), patch.object(tool_routing, "internal_httpx_client", _factory):
        result = await tool_routing._route_to_system_tool(body, request)  # noqa: SLF001

    assert result.result == {"result": {"ok": True}}
    forwarded = captured["request"]
    assert forwarded.headers[TURN_IDEMPOTENCY_HEADER] == "turn-key-3"
    assert forwarded.url.path.endswith("/internal/management-tools/invoke_management_tool")


@pytest.mark.asyncio
async def test_ch_tool_route_forwards_no_key_outside_a_paused_turn() -> None:
    from app.communication_hub.api.internal import tool_routing

    captured: dict[str, httpx.Request] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"result": {"ok": True}})

    def _factory(**kwargs):  # noqa: ANN003
        return httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(certificate_manager=None)),
        headers={},
    )
    body = tool_routing.ToolCallRequest(
        tool_name="system____save_data",
        tool_args={},
        session_id=str(uuid.uuid4()),
        agent_type_id=str(uuid.uuid4()),
    )

    with patch.object(
        tool_routing,
        "_build_control_center_auth",
        return_value=({}, {}),
    ), patch.object(tool_routing, "internal_httpx_client", _factory):
        await tool_routing._route_to_system_tool(body, request)  # noqa: SLF001

    assert TURN_IDEMPOTENCY_HEADER not in captured["request"].headers


def test_cc_management_endpoints_accept_the_header() -> None:
    """Both the per-tool and meta dispatch chokepoints accept the paused-turn
    key (Phase 5 commits the applied marker with the write under it)."""
    from app.api.v1.internal import management_tools

    for func in (
        management_tools.execute_management_tool,
        management_tools.invoke_management_tool_meta,
    ):
        params = inspect.signature(func).parameters
        assert "turn_idempotency_key" in params
        default = params["turn_idempotency_key"].default
        assert getattr(default, "alias", None) == TURN_IDEMPOTENCY_HEADER


@pytest.mark.asyncio
async def test_human_intervene_persists_the_key_on_the_resume_record(
    db_session,
) -> None:
    """The key supplied on the human_intervene call lands on the durable resume
    record, where the resumed turn reads it back."""
    from app.db.models.agents import AgentInputType, AgentType
    from app.db.models.conversations import ConversationSession, ConversationStatus
    from app.db.models.intervene import InterventionType
    from app.services.agents.intervene_service import InterveneRequestStore
    from app.services.conversations.turn_resume_store import (
        ConversationTurnResumeStore,
    )

    agent_type = AgentType(
        name=f"agent-{uuid.uuid4().hex[:8]}", input_type=AgentInputType.conversation
    )
    db_session.add(agent_type)
    await db_session.flush()
    conv = ConversationSession(
        agent_type_id=agent_type.id,
        status=ConversationStatus.active,
    )
    db_session.add(conv)
    await db_session.flush()

    request = await InterveneRequestStore().create_request(
        db=db_session,
        agent_session_id=None,
        agent_type_id=agent_type.id,
        intervention_type=InterventionType.approval,
        reason="confirm?",
        conversation_session_id=conv.id,
        idempotency_key="turn-key-4",
    )
    await db_session.flush()

    record = await ConversationTurnResumeStore().get_live_for_session(conv.id, db_session)
    assert record is not None
    assert record.intervene_request_id == request.id
    assert record.idempotency_key == "turn-key-4"
