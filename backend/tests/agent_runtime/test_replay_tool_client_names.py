"""Replay verification matches canonical script names to sanitized transcripts.

Older (and LLM-path) reference executions recorded provider-sanitized tool names
(``mcp_demo__searchFlights``) while scripts call the canonical
``mcp-demo____searchFlights``. Replay must still match those entries — a miss
made optimization report "no recorded response" for a tool the reference
execution had in fact called.
"""
from __future__ import annotations

import pytest

from app.agent_runtime.api.script_tools import ReplayToolClient
from app.agent_runtime.scripts.sandbox import SandboxViolationError


@pytest.mark.asyncio
async def test_replay_matches_canonical_name_to_sanitized_transcript():
    client = ReplayToolClient(
        [
            {
                "tool": "mcp_demo__searchFlights",
                "arguments": {"origin": "MEL", "destination": "SYD"},
                "response": {"results": [{"flight_id": "FL-1"}], "count": 1},
            }
        ]
    )

    payload = await client.call_tool(
        "mcp-demo____searchFlights",
        {"origin": "MEL", "destination": "SYD"},
    )

    assert payload == {"results": [{"flight_id": "FL-1"}], "count": 1}
    assert client.calls[0]["tool_name"] == "mcp-demo____searchFlights"


@pytest.mark.asyncio
async def test_replay_matches_underscore_server_four_underscore_transcript():
    """The intermediate fallback form (``mcp_demo____tool``) must still replay.

    A run logged between the two name fixes recorded the server with ``_``
    instead of ``-`` but kept the four-underscore separator.
    """
    client = ReplayToolClient(
        [
            {
                "tool": "mcp_demo____generatePaymentLink",
                "arguments": {"order_id": "ORD-1"},
                "response": {"link": "https://pay.example/ORD-1"},
            }
        ]
    )

    payload = await client.call_tool(
        "mcp-demo____generatePaymentLink", {"order_id": "ORD-1"}
    )

    assert payload == {"link": "https://pay.example/ORD-1"}


@pytest.mark.asyncio
async def test_replay_matches_sanitized_name_to_canonical_transcript():
    client = ReplayToolClient(
        [
            {
                "tool": "mcp-demo____searchFlights",
                "arguments": {},
                "response": {"count": 0},
            }
        ]
    )

    payload = await client.call_tool("mcp_demo__searchFlights", {})

    assert payload == {"count": 0}


@pytest.mark.asyncio
async def test_replay_miss_still_fails_and_names_recorded_tools():
    client = ReplayToolClient(
        [
            {
                "tool": "mcp_demo__bookTicket",
                "arguments": {},
                "response": {},
            }
        ]
    )

    with pytest.raises(SandboxViolationError) as exc_info:
        await client.call_tool("mcp-demo____searchFlights", {})

    message = str(exc_info.value)
    assert "No recorded response for tool 'mcp-demo____searchFlights'" in message
    assert "recorded tools: mcp_demo__bookTicket" in message
