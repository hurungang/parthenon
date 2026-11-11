"""AR/CH activity emission & forwarding boundaries.

- AR wire status -> persisted ActivityState mapping.
- ``activity_state`` hydration message shape (idle + live).
- CH forwards each transition to CC and never writes a DB itself.
- A CC failure while forwarding must never crash the turn pipeline.
"""
import uuid
from types import SimpleNamespace

import pytest

from app.api.ws.chat import (
    _activity_state_message,
    _map_wire_status_to_activity_state,
    _persist_activity_transition,
)


class TestWireStatusMapping:
    @pytest.mark.parametrize(
        "wire,agent_type,expected",
        [
            ("thinking", None, "thinking"),
            ("using_tool", None, "using_tool"),
            ("delegating", None, "delegating"),
            ("waiting", "researcher", "delegating"),
            ("waiting", None, "thinking"),
            ("waiting_for_human", None, "waiting_for_human"),
            ("timeout_or_failed", None, "timed_out"),
            ("failed", None, "failed"),
            ("delegation_resumed", None, None),
        ],
    )
    def test_mapping(self, wire, agent_type, expected):
        assert _map_wire_status_to_activity_state(wire, agent_type) == expected


class TestActivityStateMessage:
    def test_idle_session_pushes_null_state(self):
        msg = _activity_state_message(None)
        assert msg["type"] == "activity_state"
        assert msg["state"] is None
        assert msg["pending_intervention"] is False
        assert msg["is_terminal"] is False
        assert "timestamp" in msg

    def test_waiting_state_exposes_pending_intervention(self):
        msg = _activity_state_message(
            {
                "state": "waiting_for_human",
                "is_terminal": False,
                "pending_intervene_request_id": str(uuid.uuid4()),
                "detail": {"agent_type": "assistant"},
            }
        )
        assert msg["state"] == "waiting_for_human"
        assert msg["pending_intervention"] is True
        assert msg["agent_type"] == "assistant"

    def test_terminal_state_flags_terminal(self):
        msg = _activity_state_message({"state": "finished", "is_terminal": True})
        assert msg["state"] == "finished"
        assert msg["is_terminal"] is True


class _FakeDataClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    async def upsert_conversation_activity(
        self, conv_session_id, state, *, tool_name=None, detail=None, **kwargs
    ):
        self.calls.append(
            {
                "conv_session_id": conv_session_id,
                "state": state,
                "tool_name": tool_name,
                "detail": detail,
            }
        )
        if self.fail:
            raise RuntimeError("CC unavailable")
        return {"state": state}


def _app_with(data_client) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(data_client=data_client))


class TestForwarding:
    @pytest.mark.asyncio
    async def test_using_tool_transition_carries_tool_name(self):
        client = _FakeDataClient()
        conv_id = uuid.uuid4()
        await _persist_activity_transition(
            _app_with(client), conv_id, "using_tool", None, "cc____list_agents"
        )
        assert client.calls == [
            {
                "conv_session_id": conv_id,
                "state": "using_tool",
                "tool_name": "cc____list_agents",
                "detail": None,
            }
        ]

    @pytest.mark.asyncio
    async def test_waiting_for_human_marks_pending_intervention(self):
        client = _FakeDataClient()
        await _persist_activity_transition(
            _app_with(client), uuid.uuid4(), "waiting_for_human", "assistant", None
        )
        assert client.calls[0]["state"] == "waiting_for_human"
        assert client.calls[0]["detail"] == {
            "agent_type": "assistant",
            "pending_intervention": True,
        }

    @pytest.mark.asyncio
    async def test_timeout_maps_to_timed_out(self):
        client = _FakeDataClient()
        await _persist_activity_transition(
            _app_with(client), uuid.uuid4(), "timeout_or_failed", None, None
        )
        assert client.calls[0]["state"] == "timed_out"

    @pytest.mark.asyncio
    async def test_unknown_status_is_not_forwarded(self):
        client = _FakeDataClient()
        await _persist_activity_transition(
            _app_with(client), uuid.uuid4(), "delegation_resumed", None, None
        )
        assert client.calls == []

    @pytest.mark.asyncio
    async def test_cc_failure_is_swallowed(self):
        client = _FakeDataClient(fail=True)
        # Must not raise — a CC hiccup never crashes the turn pipeline.
        await _persist_activity_transition(
            _app_with(client), uuid.uuid4(), "thinking", None, None
        )
        assert len(client.calls) == 1

    @pytest.mark.asyncio
    async def test_no_data_client_is_noop(self):
        await _persist_activity_transition(
            SimpleNamespace(state=SimpleNamespace(data_client=None)),
            uuid.uuid4(),
            "thinking",
            None,
            None,
        )
