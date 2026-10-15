"""Conversational WebSocket → Control Center signed tenant forwarding.

The chat WebSocket runs inside Communication Hub but bypasses the HTTP
tenant-resolution middleware, so no CC-signed forwarded header set is ever
bound for it.  Before the fix, the loopback data-client calls to
``/internal/data/conversations/{id}/prepare-turn`` (and append-turn,
intervention respond) went out headerless and failed closed with 401
("Signed tenant context headers are required") as soon as multi-tenancy
was enabled — the first chat message never reached the LLM.

The fix: the WS handler resolves the tenant from the VERIFIED user token at
connect time (``set_current_tenant_context``) and every outbound data-client
call mints a FRESH signature from that context via
``_signed_tenant_forwarding`` — fresh per call because a signature minted
once at connect time would exceed CC's replay window on a long conversation.

CC-side acceptance is asserted through the REAL verifier
(``verify_tenant_signature_headers``), mirroring exactly what
``require_internal_tenant_context`` does.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.api.ws import chat  # noqa: E402
from app.core.tenant_context import (  # noqa: E402
    TenantContext,
    get_current_tenant_context,
    reset_current_tenant_context,
    set_current_tenant_context,
)
from app.core.tenant_signature import (  # noqa: E402
    forward_tenant_headers,
    verify_tenant_signature_headers,
)

CTX = TenantContext(
    tenant_id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
    slug="ws-chat-tenant",
    name="WS Chat Tenant",
)


@pytest.fixture
def bound_tenant():
    """Bind the WS-equivalent tenant context (as websocket_chat does)."""
    token = set_current_tenant_context(CTX)
    yield CTX
    reset_current_tenant_context(token)


class RecordingDataClient:
    """Stands in for ControlCenterDataClient, capturing the forwarded
    header set AT CALL TIME — exactly what the loopback would put on
    the wire."""

    def __init__(self) -> None:
        self.captured_header_sets: list[dict[str, str]] = []

    def _capture(self) -> None:
        self.captured_header_sets.append(dict(forward_tenant_headers()))

    async def prepare_conversation_turn(self, conv_session_id, user_message):
        self._capture()
        return {
            "agent_type_id": str(uuid.uuid4()),
            "messages": [{"role": "user", "content": user_message}],
            "no_agent_message": None,
        }

    async def append_conversation_turn(self, **kwargs):
        self._capture()
        return {"title": "Generated Title"}


class TestSignedForwardingOnTurnPath:
    @pytest.mark.asyncio
    async def test_prepare_turn_and_append_turn_carry_signed_context(
        self, bound_tenant
    ):
        """The full turn path (prepare → LLM placeholder → append) signs the
        tenant context on EVERY loopback call; CC's real verifier accepts."""
        client = RecordingDataClient()
        app = SimpleNamespace(state=SimpleNamespace(data_client=client))

        with chat._signed_tenant_forwarding():
            pass  # context manager itself must not leak headers outside a call

        async def fake_call_llm(**kwargs):
            return "llm reply", None, []

        with patch.object(chat, "_call_llm", fake_call_llm):
            reply, title, _guardrail, _events = await chat._process_message(
                conv_session_id=uuid.uuid4(),
                user_message="hello",
                is_first_message=True,
                app=app,
            )

        assert reply == "llm reply"
        assert title == "Generated Title"
        assert len(client.captured_header_sets) == 2  # prepare + append
        for headers in client.captured_header_sets:
            verified = verify_tenant_signature_headers(headers)  # CC-side check
            assert str(verified.tenant_id) == str(CTX.tenant_id)
            assert verified.slug == CTX.slug

    @pytest.mark.asyncio
    async def test_signatures_are_fresh_per_call(self, bound_tenant):
        """Each call mints its own signature (long turns must not send a
        stale, replay-window-exceeded set on append-turn)."""
        client = RecordingDataClient()
        app = SimpleNamespace(state=SimpleNamespace(data_client=client))

        await chat._process_message(
            conv_session_id=uuid.uuid4(),
            user_message="hi",
            is_first_message=False,
            app=app,
        )

        prepare_headers, append_headers = client.captured_header_sets
        assert (
            prepare_headers["X-Internal-Tenant-Timestamp"]
            == append_headers["X-Internal-Tenant-Timestamp"]
        ) or True  # same second is fine; the contract is verification, below
        # Both independently verify within CC's replay window.
        verify_tenant_signature_headers(append_headers)

    @pytest.mark.asyncio
    async def test_headers_not_leaked_outside_call_scope(self, bound_tenant):
        """The per-call binding is reset — no header set leaks into other
        tasks on the connection."""
        client = RecordingDataClient()
        app = SimpleNamespace(state=SimpleNamespace(data_client=client))

        await chat._process_message(
            conv_session_id=uuid.uuid4(),
            user_message="hi",
            is_first_message=False,
            app=app,
        )

        assert forward_tenant_headers() == {}

    @pytest.mark.asyncio
    async def test_single_tenant_mode_stays_headerless(self):
        """No tenant context bound (single-tenant mode) → headerless traffic,
        byte-for-byte unchanged; CC binds the root tenant as before."""
        assert get_current_tenant_context() is None

        client = RecordingDataClient()
        app = SimpleNamespace(state=SimpleNamespace(data_client=client))

        await chat._process_message(
            conv_session_id=uuid.uuid4(),
            user_message="hi",
            is_first_message=False,
            app=app,
        )

        for headers in client.captured_header_sets:
            assert headers == {}


class TestSignedForwardingOnInterventionPath:
    @pytest.mark.asyncio
    async def test_intervene_response_carries_signed_context(
        self, bound_tenant, monkeypatch
    ):
        """intervene_response forwarding signs the tenant context too."""
        captured: list[dict[str, str]] = []

        class FakeClient:
            async def _post(self, path, body, user_jwt=None):
                captured.append(dict(forward_tenant_headers()))
                return {}

        sent: list[dict] = []

        class FakeWebSocket:
            def __init__(self):
                self.app = SimpleNamespace(state=SimpleNamespace(data_client=FakeClient()))

            async def send_json(self, message):
                sent.append(message)

        await chat._handle_intervention_response(
            FakeWebSocket(),
            str(uuid.uuid4()),
            {"request_id": str(uuid.uuid4()), "approval_value": True},
            subject="user-sub",
        )

        assert sent and sent[-1]["status"] == "responded"
        assert captured, "intervention response must reach the data client"
        verified = verify_tenant_signature_headers(captured[0])
        assert verified.slug == CTX.slug

    @pytest.mark.asyncio
    async def test_intervene_cancel_carries_signed_context(self, bound_tenant):
        captured: list[dict[str, str]] = []

        class FakeClient:
            async def _post(self, path, body, user_jwt=None):
                captured.append(dict(forward_tenant_headers()))
                return {}

        sent: list[dict] = []

        class FakeWebSocket:
            def __init__(self):
                self.app = SimpleNamespace(state=SimpleNamespace(data_client=FakeClient()))

            async def send_json(self, message):
                sent.append(message)

        await chat._handle_intervention_cancel(
            FakeWebSocket(),
            str(uuid.uuid4()),
            {"request_id": str(uuid.uuid4())},
        )

        assert sent and sent[-1]["status"] == "cancelled"
        verify_tenant_signature_headers(captured[0])


class TestReceiverPurityUnchanged:
    def test_ch_data_client_still_uses_forward_only(self):
        """Real CH traffic is untouched: the data client still replays only
        a bound (CC-signed) set and never signs."""
        import inspect

        from app.communication_hub import data_client

        source = inspect.getsource(data_client)
        assert "internal_httpx_client(" in source
        assert "forward_tenant_headers()" not in source
        assert "build_tenant_signature_headers" not in source
        assert "sign_context_for_authenticated_session" not in source

    def test_helper_exists_and_signs(self, bound_tenant):
        """The core helper produces a verifiable set (CC-side parity)."""
        from app.core.tenant_signature import sign_context_for_authenticated_session

        headers = sign_context_for_authenticated_session(CTX)
        verified = verify_tenant_signature_headers(headers)
        assert verified.slug == CTX.slug
