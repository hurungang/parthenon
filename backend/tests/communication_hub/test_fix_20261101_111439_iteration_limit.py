"""FIX-20261101-111439 — guardrail iteration-limit stops surface clearly.

Defect 1: after a post-approval turn legitimately needed 11+ tool
iterations (agent-creation workflow), the guardrail stop
``GuardrailStop('iteration_limit')`` reached the user as the generic
"An error occurred" message. Now:

- Agent Runtime forwards the guardrail stop reason + details on the
  streaming error chunk.
- Control Center maps it onto a structured ``ConversationTurnError``
  and persists a clear, user-comprehensible error turn (the
  ``timeout_or_failed`` structured-error pattern).
- The seeded assistant's iteration budget is raised (24) — covered in
  ``tests/unit/test_assistant_seeder.py``.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent_runtime.api import conversation as ar_conversation
from app.api.ws import chat
from app.services.agents.guardrails import RuntimeGuardrailState
from app.services.agents.guardrail_callback import GuardrailCallback, GuardrailStop


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.query_params: dict[str, str] = {}

    async def accept(self) -> None:  # noqa: D105
        return None

    async def send_json(self, payload) -> None:  # noqa: ANN001
        self.sent.append(payload)


def _make_app() -> SimpleNamespace:
    data_client = SimpleNamespace()
    data_client.append_conversation_turn = AsyncMock(return_value={"title": None})
    return SimpleNamespace(state=SimpleNamespace(data_client=data_client, certificate_manager=None))


# ── AR forwards the guardrail stop reason on the error chunk ────────────────


@pytest.mark.asyncio
async def test_ar_streaming_error_chunk_carries_guardrail_reason() -> None:
    agent_type_id = uuid.uuid4()
    conv_session_id = uuid.uuid4()

    data_client = SimpleNamespace()
    data_client.get_agent_context = AsyncMock(
        return_value={
            "is_active": True,
            "identity_role_valid": True,
            "model_id": "m-1",
            "model_config_id": str(uuid.uuid4()),
        }
    )
    data_client.get_model_config = AsyncMock(return_value={"provider_type": "openai"})

    stop = GuardrailStop(
        reason="iteration_limit",
        details={"iteration_count": 11, "max_iterations": 10, "session_id": "s"},
    )

    async def failing_turn(**kwargs):  # noqa: ANN001
        raise stop

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                data_client=data_client,
                certificate_manager=None,
                conversation_tasks={},
            )
        ),
    )
    body = ar_conversation.ConversationTurnRequest(
        conv_session_id=conv_session_id,
        agent_type_id=agent_type_id,
        messages=[{"role": "user", "content": "create an agent"}],
        stream_status_events=True,
    )

    with patch.object(
        ar_conversation.AgentRuntimeExecutor,
        "execute_conversation_turn_from_context",
        side_effect=failing_turn,
    ):
        response = await ar_conversation.execute_conversation_turn(body, request)

        # Consume inside the patch context: the endpoint schedules a background
        # task whose executor call only runs when the stream is drained.
        chunks: list[dict] = []
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            chunks.append(json.loads(chunk))

    error_chunks = [c for c in chunks if c.get("type") == "error"]
    assert len(error_chunks) == 1
    assert error_chunks[0]["error_type"] == "iteration_limit"
    assert error_chunks[0]["error_details"]["max_iterations"] == 10


# ── CC maps the guardrail stop onto a structured, persisted error turn ──────


def test_maps_iteration_limit_stop_to_structured_error() -> None:
    err = chat._conversation_turn_error_from_guardrail_stop(
        "iteration_limit", {"max_iterations": 10}
    )
    assert isinstance(err, chat.ConversationTurnError)
    assert err.code == "iteration_limit"
    assert "limit 10" in err.message
    assert "smaller requests" in err.message


def test_maps_iteration_limit_without_details() -> None:
    err = chat._conversation_turn_error_from_guardrail_stop("iteration_limit", {})
    assert err.code == "iteration_limit"
    assert "more steps than allowed" in err.message


def test_maps_other_guardrail_stops() -> None:
    err = chat._conversation_turn_error_from_guardrail_stop("token_budget", {})
    assert err.code == "guardrail_token_budget"
    assert "safety limit" in err.message


@pytest.mark.asyncio
async def test_guardrail_stop_persists_clear_error_turn() -> None:
    conv_session_id = uuid.uuid4()
    app = _make_app()
    ws = _FakeWebSocket()
    chat.ActiveSessionTracker.register(str(conv_session_id), ws)
    settings = SimpleNamespace(
        agent_runtime_url="http://localhost:8001", agent_question_timeout_seconds=30
    )

    async def failing_process_message(**kwargs):  # noqa: ANN001
        raise chat.ConversationTurnError(
            "iteration_limit",
            chat.ITERATION_LIMIT_MESSAGE_TEMPLATE.format(limit=10),
        )

    with patch.object(chat, "get_settings", return_value=settings), \
         patch.object(chat, "_process_message", failing_process_message):
        await chat.run_conversation_turn(
            session_id=str(conv_session_id),
            conv_session_id=conv_session_id,
            user_message="create an agent",
            is_first_message=True,
            app=app,
            websocket=ws,
            message_count=1,
        )

    # Typed chat_error payload is still emitted for structured UI handling.
    chat_errors = [m for m in ws.sent if m.get("type") == "chat_error"]
    assert chat_errors and chat_errors[0]["code"] == "iteration_limit"

    # Clear, user-comprehensible message turn (NOT the generic fallback).
    error_messages = [m for m in ws.sent if m.get("sender_role") == "agent"]
    assert error_messages and "limit 10" in error_messages[-1]["content"]
    assert "An error occurred" not in error_messages[-1]["content"]

    # The error turn is persisted exactly once with the status event.
    assert app.state.data_client.append_conversation_turn.await_count == 1
    kwargs = app.state.data_client.append_conversation_turn.await_args.kwargs
    assert any(e.get("status") == "iteration_limit" for e in kwargs["status_events"])
    assert "limit 10" in kwargs["agent_reply"]


# ── The callback itself still raises with the raised budget respected ───────


@pytest.mark.asyncio
async def test_guardrail_callback_raises_iteration_limit() -> None:
    state = RuntimeGuardrailState(
        max_iterations=10,
        max_delegation_depth=3,
        max_delegated_steps=20,
        execution_timeout_seconds=300,
        token_budget=None,
        token_enforcement_mode="observe",
        token_fallback_mode="observe_and_log",
        conversational_token_visibility_mode="enabled",
        conversational_continuation_policy="allow",
        policy_snapshot_id="test",
    )
    state.cumulative_iterations = 11
    callback = GuardrailCallback(guardrail_state=state, session_id="s")
    with pytest.raises(GuardrailStop) as excinfo:
        await callback.on_llm_start({}, ["prompt"])
    assert excinfo.value.reason == "iteration_limit"
    assert excinfo.value.details["max_iterations"] == 10
