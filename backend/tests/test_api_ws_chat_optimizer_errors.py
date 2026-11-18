"""WebSocket chat payloads for optimization conversations.

The chat contract adds three optimization-shaped payloads without changing the
existing pause/reply semantics:

* ``chat_error`` with the optimizer reason codes
  (``optimizer_model_not_configured`` / ``optimizer_model_not_enabled`` /
  ``optimization_out_of_scope`` / ``optimization_permission_denied``) mapped
  from the internal ``412``/structured ``403`` refusals — a business/assistant
  refusal keeps its generic handling;
* ``chat_blocked`` (``reason=decision_pending``) when a decision is pending,
  carrying the intervention / live-test ids and the expiry so the client can
  re-surface the card and keep the composer disabled;
* a ``live_test`` block on ``intervene_request`` (only for a live-test
  approval), and a ``live_test_result`` chunk pushed **before** the resumed
  reply.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.api.ws import chat
from app.communication_hub.intervention_router import InterventionRouter
from app.services.conversations import turn_resolution


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.query_params: dict[str, str] = {}

    async def accept(self) -> None:  # noqa: D105
        return None

    async def send_json(self, payload) -> None:  # noqa: ANN001
        self.sent.append(payload)


def _make_app(**data_client_overrides) -> SimpleNamespace:
    data_client = SimpleNamespace()
    data_client.append_conversation_turn = AsyncMock(return_value={"title": None})
    data_client.append_conversation_turn_started = AsyncMock(
        return_value={"turn": {"id": str(uuid.uuid4())}}
    )
    data_client.prepare_conversation_turn = AsyncMock(
        return_value={
            "agent_type_id": str(uuid.uuid4()),
            "messages": [{"role": "user", "content": "hi"}],
        }
    )
    for name, value in data_client_overrides.items():
        setattr(data_client, name, value)
    return SimpleNamespace(
        state=SimpleNamespace(data_client=data_client, certificate_manager=None)
    )


def _status_error(status_code: int, detail) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://cc/api/v1/internal/x")
    response = httpx.Response(status_code, json={"detail": detail}, request=request)
    return httpx.HTTPStatusError("upstream error", request=request, response=response)


# ── chat_error mapping ──────────────────────────────────────────────────────


class TestOptimizerErrorMapping:
    @pytest.mark.parametrize(
        ("reason_code", "expected_code"),
        [
            ("optimizer_model_not_configured", "optimizer_model_not_configured"),
            ("optimizer_model_not_enabled", "optimizer_model_not_enabled"),
        ],
    )
    def test_412_maps_onto_the_optimizer_model_codes(self, reason_code, expected_code):
        err = chat._optimizer_conversation_turn_error(
            412,
            {
                "error": "optimizer_model_unavailable",
                "reason_code": reason_code,
                "reason": "No usable optimizer model.",
            },
        )
        assert isinstance(err, chat.ConversationTurnError)
        assert err.code == expected_code
        assert err.message == "No usable optimizer model."

    def test_412_unknown_reason_defaults_to_not_configured(self):
        err = chat._optimizer_conversation_turn_error(
            412, {"error": "optimizer_model_unavailable"}
        )
        assert err is not None
        assert err.code == "optimizer_model_not_configured"
        assert "Optimizer Model" in err.message

    @pytest.mark.parametrize(
        ("detail", "expected_code"),
        [
            (
                {"error": "optimization_out_of_scope", "reason": "Out of scope."},
                "optimization_out_of_scope",
            ),
            (
                {
                    "error": "optimization_permission_denied",
                    "reason": "No execute grant.",
                },
                "optimization_permission_denied",
            ),
        ],
    )
    def test_403_maps_onto_the_optimization_codes(self, detail, expected_code):
        err = chat._optimizer_conversation_turn_error(403, detail)
        assert err is not None
        assert err.code == expected_code

    def test_a_business_refusal_is_not_mapped(self):
        # Generic business refusals keep their existing handling.
        assert chat._optimizer_conversation_turn_error(403, "Forbidden") is None
        assert (
            chat._optimizer_conversation_turn_error(
                403, {"error": "not_allowed", "reason": "no"}
            )
            is None
        )
        assert chat._optimizer_conversation_turn_error(412, {"detail": "x"}) is None

    def test_http_status_mapping_prefers_the_optimizer_code(self):
        exc = _status_error(
            412,
            {
                "error": "optimizer_model_unavailable",
                "reason_code": "optimizer_model_not_enabled",
                "reason": "The configured optimizer model is gone.",
            },
        )
        err = chat._conversation_turn_error_from_http_status(exc)
        assert err is not None
        assert err.code == "optimizer_model_not_enabled"

    def test_cc_error_chain_mapping(self):
        exc = RuntimeError("cc failed")
        exc.__cause__ = _status_error(
            403, {"error": "optimization_out_of_scope", "reason": "Out of scope."}
        )
        err = chat._conversation_turn_error_from_cc_error(exc)
        assert err is not None
        assert err.code == "optimization_out_of_scope"

    def test_a_plain_error_is_unmapped(self):
        assert chat._conversation_turn_error_from_cc_error(RuntimeError("x")) is None


class TestChatErrorEmission:
    @pytest.mark.asyncio
    async def test_412_emits_the_typed_chat_error_and_a_persisted_turn(self):
        conv_session_id = uuid.uuid4()

        async def _failing_prepare(*args, **kwargs):  # noqa: ANN001
            raise _status_error(
                412,
                {
                    "error": "optimizer_model_unavailable",
                    "reason_code": "optimizer_model_not_configured",
                    "reason": "No optimizer model configured.",
                },
            )

        app = _make_app()
        # The CC data client wraps the HTTP failure as its own error with a cause.
        async def _prepare_via_client(conv_id, message):  # noqa: ANN001
            wrapper = RuntimeError("prepare failed")
            try:
                await _failing_prepare()
            except httpx.HTTPStatusError as exc:
                wrapper.__cause__ = exc
            raise wrapper

        app.state.data_client.prepare_conversation_turn = _prepare_via_client
        ws = _FakeWebSocket()
        chat.ActiveSessionTracker.register(str(conv_session_id), ws)
        settings = SimpleNamespace(
            agent_runtime_url="http://localhost:8001",
            agent_question_timeout_seconds=30,
            conversation_heartbeat_interval_seconds=15,
        )
        try:
            with patch.object(chat, "get_settings", return_value=settings):
                await chat.run_conversation_turn(
                    session_id=str(conv_session_id),
                    conv_session_id=conv_session_id,
                    user_message="optimize",
                    is_first_message=True,
                    app=app,
                    websocket=ws,
                    message_count=1,
                )
        finally:
            chat.ActiveSessionTracker.unregister(str(conv_session_id), ws)

        errors = [m for m in ws.sent if m.get("type") == "chat_error"]
        assert len(errors) == 1
        assert errors[0]["code"] == "optimizer_model_not_configured"
        assert "optimizer model" in errors[0]["message"].lower()
        # The failure is persisted as one structured error turn.
        app.state.data_client.append_conversation_turn.assert_awaited_once()


# ── chat_blocked (decision pending) ────────────────────────────────────────


class TestChatBlocked:
    @pytest.mark.asyncio
    async def test_a_pending_decision_blocks_the_turn_with_the_ids(self):
        conv_session_id = uuid.uuid4()
        intervene_id = uuid.uuid4()
        live_test_id = uuid.uuid4()

        app = _make_app()
        app.state.data_client.prepare_conversation_turn = AsyncMock(
            return_value={
                "agent_type_id": str(uuid.uuid4()),
                "messages": [],
                "blocked": {
                    "reason_code": "decision_pending",
                    "message": "Waiting for your decision on the pending request.",
                    "intervene_request_id": str(intervene_id),
                    "live_test_request_id": str(live_test_id),
                    "expires_at": "2026-11-15T12:00:00+00:00",
                },
            }
        )
        ws = _FakeWebSocket()
        chat.ActiveSessionTracker.register(str(conv_session_id), ws)
        settings = SimpleNamespace(
            agent_runtime_url="http://localhost:8001",
            agent_question_timeout_seconds=30,
            conversation_heartbeat_interval_seconds=15,
        )
        try:
            with patch.object(chat, "get_settings", return_value=settings):
                await chat.run_conversation_turn(
                    session_id=str(conv_session_id),
                    conv_session_id=conv_session_id,
                    user_message="another message",
                    is_first_message=False,
                    app=app,
                    websocket=ws,
                    message_count=2,
                )
        finally:
            chat.ActiveSessionTracker.unregister(str(conv_session_id), ws)

        blocked = [m for m in ws.sent if m.get("type") == "chat_blocked"]
        assert len(blocked) == 1
        payload = blocked[0]
        assert payload["reason"] == "decision_pending"
        assert payload["intervene_request_id"] == str(intervene_id)
        assert payload["live_test_request_id"] == str(live_test_id)
        assert payload["expires_at"] == "2026-11-15T12:00:00+00:00"
        assert "Waiting for your decision" in payload["message"]
        # Nothing was dispatched and no error turn was persisted.
        app.state.data_client.append_conversation_turn.assert_not_awaited()


# ── live_test block on intervene_request ──────────────────────────────────


class TestInterveneRequestLiveTestBlock:
    def test_dispatch_content_carries_the_live_test_block(self):
        message = InterventionRouter._build_intervene_request_message(
            {
                "request_id": str(uuid.uuid4()),
                "intervention_type": "approval",
                "reason": "Live test approval",
                "conversation_session_id": str(uuid.uuid4()),
                "live_test": {
                    "live_test_request_id": str(uuid.uuid4()),
                    "status": "pending",
                    "operations": [{"tool_name": "crm____searchCustomers"}],
                    "expires_at": None,
                },
            },
            metadata=None,
        )
        assert message["type"] == "intervene_request"
        assert message["live_test"]["status"] == "pending"
        assert message["live_test"]["operations"][0]["tool_name"] == (
            "crm____searchCustomers"
        )

    def test_db_record_carries_the_live_test_block_on_reconnect(self):
        message = InterventionRouter._build_intervene_request_message_from_db(
            {
                "id": str(uuid.uuid4()),
                "intervention_type": "approval",
                "reason": "Live test approval",
                "conversation_session_id": str(uuid.uuid4()),
                "live_test": {
                    "live_test_request_id": str(uuid.uuid4()),
                    "status": "pending",
                    "operations": [
                        {"tool_name": "crm____searchCustomers", "arguments": {"q": "a"}}
                    ],
                    "executed_operations": None,
                    "target_agent_type_id": str(uuid.uuid4()),
                },
            }
        )
        assert message["live_test"]["executed_operations"] is None
        assert message["live_test"]["operations"][0]["arguments"] == {"q": "a"}

    def test_a_plain_ask_never_carries_the_block(self):
        message = InterventionRouter._build_intervene_request_message(
            {
                "request_id": str(uuid.uuid4()),
                "intervention_type": "text",
                "reason": "Which customer?",
                "conversation_session_id": str(uuid.uuid4()),
            }
        )
        assert "live_test" not in message


# ── live_test_result chunk before the resumed reply ───────────────────────


class TestLiveTestResultChunk:
    @pytest.mark.asyncio
    async def test_the_result_chunk_is_dispatched_with_every_outcome(self):
        conversation_id = uuid.uuid4()
        payload = {
            "live_test_status": "executed",
            "live_test_request_id": str(uuid.uuid4()),
            "executed_operations": [
                {"tool_name": "crm____searchCustomers", "status": "success"}
            ],
        }
        dispatch = AsyncMock()

        with patch(
            "app.services.control_center.comm_hub_client.CommunicationHubClient."
            "dispatch_message",
            dispatch,
        ):
            await turn_resolution.push_live_test_result(conversation_id, payload)

        dispatch.assert_awaited_once()
        kwargs = dispatch.await_args.kwargs
        assert kwargs["session_id"] == conversation_id
        assert kwargs["message_type"] == "live_test_result"
        content = kwargs["content"]
        assert content["type"] == "live_test_result"
        assert content["live_test_status"] == "executed"
        assert content["executed_operations"] == payload["executed_operations"]

    @pytest.mark.asyncio
    async def test_a_missing_socket_never_fails_the_answer_path(self):
        with patch(
            "app.services.control_center.comm_hub_client.CommunicationHubClient."
            "dispatch_message",
            AsyncMock(side_effect=RuntimeError("no socket")),
        ):
            # Must swallow: persistence already happened.
            await turn_resolution.push_live_test_result(uuid.uuid4(), {"live_test_status": "executed"})
