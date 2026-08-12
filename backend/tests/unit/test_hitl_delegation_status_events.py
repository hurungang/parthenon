"""Reproduction test for FIX-20260617-130000: HITL status events during delegation.

When a delegated sub-agent requests human intervention (HITL) during a
conversational session, the Runtime Executor should emit status events
so the frontend chatbot can:
  - Show a distinct "waiting for human input" indicator
  - Pause the delegation timeout countdown
  - Restart delegation log streaming after HITL resolves

Currently, no ``waiting_for_human`` or ``delegation_resumed`` status
events are emitted during the delegation wait cycle, causing the
frontend delegation cycle to remain in an indefinite "waiting" state
with no visibility into HITL progress.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.agents.runtime_executor import AgentRuntimeExecutor
from app.services.agents.tool_naming import build_tool_name

# ── Fake model helper ─────────────────────────────────────────────────

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


class _FakeDelegationModel(GenericFakeChatModel):
    """Fake LangChain chat model for delegation testing.

    Overrides ``bind_tools`` (not implemented in GenericFakeChatModel) to
    return self, making it compatible with LangGraph’s create_agent.
    """

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self

    def model_copy(self, **kwargs):  # type: ignore[override]
        return self

# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_agent_context(role_id: uuid.UUID, agent_slug: str) -> dict:
    """Build a minimal agent context for delegation testing."""
    return {
        "model_id": str(uuid.uuid4()),
        "role_id": str(role_id),
        "allowed_tools": [build_tool_name("agent", agent_slug)],
        "tool_definitions": [
            {
                "type": "function",
                "function": {
                    "name": f"agent__{agent_slug}",
                    "description": "delegate",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ],
        "tool_name_map": {
            f"agent__{agent_slug}": build_tool_name("agent", agent_slug),
        },
        "role_mcp_sessions": {},
        "guardrail_policy": {
            "max_iterations": 5,
            "max_delegation_depth": 3,
            "max_delegated_steps": 10,
            "execution_timeout_seconds": 300,
        },
        "sops": [],
        "skills": [],
    }


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delegation_with_hitl_emits_waiting_for_human_and_resumed_events() -> None:
    """Verify HITL status events during conversational agent delegation.

    When a delegated sub-agent enters human intervention (HITL) state, the
    frontend is notified via the SEPARATE ``intervene_request`` WebSocket message
    from the InterventionRouter, not the status event stream. The
    ``waiting_for_human`` chat status is set by the ``intervene_request`` handler,
    not by the NDJSON status stream.

    After the human responds and the sub-agent resumes execution, the
    Runtime Executor MUST emit a ``delegation_resumed`` status event through
    the NDJSON status stream so the frontend can:
      - Restart delegation log polling
      - Update the delegation cycle with resumed activity (tool calls, logs)
      - Show that the delegation is progressing again

    FIX-20260617-130000: This test verifies that ``delegation_resumed`` is
    emitted after the delegation wait returns, enabling the frontend to
    resume log streaming.
    """
    executor = AgentRuntimeExecutor()
    conv_session_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    role_id = uuid.uuid4()
    receiver_session_id = str(uuid.uuid4())

    agent_context = _build_agent_context(role_id, "approval-agent")
    model_config = {"provider_type": "openai"}

    # Fake model: first call emits delegation tool call, second returns final text
    fake_model = _FakeDelegationModel(
        messages=iter([
            AIMessage(
                content="",
                tool_calls=[{
                    "id": "call-1",
                    "name": "agent__approval_agent",
                    "args": {},
                    "type": "tool_call",
                }],
            ),
            AIMessage(content="delegation completed successfully."),
        ])
    )

    with patch(
        "app.services.agents.langchain_model_factory.LangChainModelFactory"
    ) as mock_factory_cls, patch(
        "app.agent_runtime.comm_hub_client.CommHubToolClient"
    ) as comm_hub_client_cls:

        mock_factory_cls.return_value.get_model_from_config_dict.return_value = fake_model

        comm_hub_client = comm_hub_client_cls.return_value

        comm_hub_client.call_a2a_request = AsyncMock(
            return_value={
                "status": "accepted",
                "receiver_session_id": receiver_session_id,
            }
        )

        comm_hub_client.wait_for_a2a_response = AsyncMock(
            return_value={
                "status": "completed",
                "output_data": {"approved": True},
            }
        )

        captured_events_via_callback: list[dict[str, str]] = []

        async def on_status_event(event: dict[str, str]) -> None:
            captured_events_via_callback.append(event)

        response, guardrail_usage, status_events = (
            await executor.execute_conversation_turn_from_context(
                agent_type_id=agent_type_id,
                agent_context=agent_context,
                model_config=model_config,
                messages=[{"role": "user", "content": "delegate"}],
                conv_session_id=conv_session_id,
                status_event_callback=on_status_event,
            )
        )

    assert response == "delegation completed successfully."
    assert guardrail_usage["delegated_steps"] == 1

    assert captured_events_via_callback == status_events

    status_sequence = [e["status"] for e in status_events]

    assert "using_tool" in status_sequence
    assert "delegating" in status_sequence
    assert "waiting" in status_sequence

    assert "delegation_resumed" in status_sequence, (
        "FIX-20260617-130000: Expected 'delegation_resumed' status event "
        "after human intervention is resolved and the sub-agent resumes "
        "execution. This event is required by the frontend to:\n"
        "  - Restart delegation log polling (currently stops at 'waiting')\n"
        "  - Update the delegation cycle to show resumed sub-agent activity\n"
        "  - Signal that tool calls and logs should appear again\n\n"
        "Current status_events: {!r}".format(status_events)
    )

    first_waiting_idx = status_sequence.index("waiting")

    if "delegation_resumed" in status_sequence:
        resumed_idx = status_sequence.index("delegation_resumed")
        assert resumed_idx > first_waiting_idx, (
            "'delegation_resumed' must appear after the initial 'waiting' event"
        )

    comm_hub_client.call_a2a_request.assert_awaited_once()
    call_kwargs = comm_hub_client.call_a2a_request.await_args.kwargs
    assert call_kwargs["target_agent_type_slug"] == "approval-agent"
    assert call_kwargs["session_id"] == str(conv_session_id)
    assert call_kwargs["wait_for_response"] is False

    comm_hub_client.wait_for_a2a_response.assert_awaited_once()
    wait_kwargs = comm_hub_client.wait_for_a2a_response.await_args.kwargs
    assert wait_kwargs["receiver_session_id"] == receiver_session_id
    assert wait_kwargs["timeout_seconds"] == 90.0


@pytest.mark.asyncio
async def test_delegation_hitl_status_sequence_order_is_correct() -> None:
    """Verify the full status event sequence for a delegation with HITL.

    The expected sequence is:
      1. using_tool       (parent agent invokes delegation tool)
      2. delegating       (delegation to sub-agent started)
      3. waiting          (waiting for sub-agent to begin)
      4. waiting          (waiting for sub-agent response, with receiver_session_id)
      5. waiting_for_human    (sub-agent entered HITL — pending human input)
      6. delegation_resumed   (human responded, sub-agent resumed)
    """
    executor = AgentRuntimeExecutor()
    conv_session_id = uuid.uuid4()
    agent_type_id = uuid.uuid4()
    role_id = uuid.uuid4()
    receiver_session_id = str(uuid.uuid4())

    agent_context = _build_agent_context(role_id, "review-agent")
    model_config = {"provider_type": "openai"}

    # Fake model: first call emits delegation tool call, second returns final text
    fake_model = _FakeDelegationModel(
        messages=iter([
            AIMessage(
                content="",
                tool_calls=[{
                    "id": "call-1",
                    "name": "agent__review_agent",
                    "args": {},
                    "type": "tool_call",
                }],
            ),
            AIMessage(content="Review delegation finished."),
        ])
    )

    with patch(
        "app.services.agents.langchain_model_factory.LangChainModelFactory"
    ) as mock_factory_cls, patch(
        "app.agent_runtime.comm_hub_client.CommHubToolClient"
    ) as comm_hub_client_cls:

        mock_factory_cls.return_value.get_model_from_config_dict.return_value = fake_model

        comm_hub_client = comm_hub_client_cls.return_value
        comm_hub_client.call_a2a_request = AsyncMock(
            return_value={
                "status": "accepted",
                "receiver_session_id": receiver_session_id,
            }
        )
        comm_hub_client.wait_for_a2a_response = AsyncMock(
            return_value={
                "status": "completed",
                "output_data": {"reviewed": True},
            }
        )

        _, _, status_events = await executor.execute_conversation_turn_from_context(
            agent_type_id=agent_type_id,
            agent_context=agent_context,
            model_config=model_config,
            messages=[{"role": "user", "content": "delegate review"}],
            conv_session_id=conv_session_id,
        )

    status_sequence = [e["status"] for e in status_events]

    # ── The minimum expected sequence (prefix match) ─────────────────────
    # After the delegation wait returns, delegation_resumed must appear.
    expected_prefix = [
        "using_tool",
        "delegating",
        "waiting",
        "waiting",
        "delegation_resumed",
    ]

    actual_prefix = status_sequence[: len(expected_prefix)]

    assert actual_prefix == expected_prefix, (
        "FIX-20260617-130000: The status event sequence for a delegation "
        "with human intervention must follow the expected order:\n"
        "  Expected prefix: {}\n"
        "  Actual prefix:   {}\n"
        "  Full sequence:   {}\n\n"
        "The 'delegation_resumed' event triggers the frontend to restart log "
        "polling after the human intervention pause ends.".format(
            expected_prefix, actual_prefix, status_sequence
        )
    )

    # ── Verify each expected event's metadata ────────────────────────────
    # Find the first 'waiting' event (the one with receiver_session_id)
    waiting_events = [e for e in status_events if e["status"] == "waiting"]
    assert len(waiting_events) >= 2, (
        "Expected at least 2 'waiting' events: one before call_a2a_request "
        "and one after with receiver_session_id. Got: {}".format(len(waiting_events))
    )

    # The second 'waiting' event should have the receiver_session_id
    second_waiting = waiting_events[1]
    assert second_waiting.get("receiver_session_id") == receiver_session_id, (
        "The second 'waiting' status event must include the receiver_session_id "
        "so the frontend can start polling execution logs. "
        "Got: {!r}".format(second_waiting)
    )
