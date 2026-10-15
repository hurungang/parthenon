"""Signed tenant context on the conversational dispatch chain.

Live failure (multi-tenancy ON, chat with a conversational agent):

    user WS message → CH (WS auth OK, loopback OK)
      → CH → AR ``POST /internal/conversation/turn``   ← headers were DROPPED
      → AR → CC ``PATCH /internal/data/sessions/{id}/status``
      ← 401 "Signed tenant context headers are required on internal
         data-plane endpoints" → AR 502 → CH retry ×3 → message fails.

AR and CH are receivers — they never sign; they forward the verified set.
The WS chat is the origin: it mints a FRESH signed set per call from the
tenant context bound at connect time (``_signed_tenant_forwarding``).  The
loopback data calls already carried it, but the delegate hop to AR did not,
so AR's middleware never bound a forwarded set and AR's data client went
out headerless — CC rejected the status PATCH fail-closed.

These tests pin the whole chain hop by hop:

1. CH → AR delegate (``_delegate_conversation_turn_to_agent_runtime``)
   carries the signed set on the wire (and stays headerless in
   single-tenant mode).
2. CH → AR execution trigger (``POST /internal/agent/execute``) forwards
   the bound set.
3. AR's CC data client forwards the bound set verbatim on EVERY AR→CC
   call — ``_get``, ``_post``, ``_patch`` (status PATCH) and
   ``_internal_post`` (typed outputs).
4. Missing headers at a hop fail CLEAR: CC's verifier semantics are
   asserted through the real ``verify_tenant_signature_headers``.
"""
from __future__ import annotations

import inspect
import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.api.ws import chat  # noqa: E402
from app.core.tenant_context import (  # noqa: E402
    TenantContext,
    reset_current_tenant_context,
    set_current_tenant_context,
)
from app.core.tenant_signature import (  # noqa: E402
    TENANT_SIGNATURE_HEADERS,
    bind_forwarded_tenant_headers,
    forward_tenant_headers,
    reset_forwarded_tenant_headers,
    verify_tenant_signature_headers,
)

CTX = TenantContext(
    tenant_id=uuid.UUID("66666666-6666-6666-6666-666666666666"),
    slug="dispatch-tenant",
    name="Dispatch Tenant",
)


@pytest.fixture
def bound_tenant():
    """Bind the WS-equivalent tenant context (as websocket_chat does)."""
    token = set_current_tenant_context(CTX)
    yield CTX
    reset_current_tenant_context(token)


@pytest.fixture
def bound_forwarded_headers():
    """Bind a signed header set as if a middleware had verified it."""
    from app.core.tenant_signature import build_tenant_signature_headers

    headers = build_tenant_signature_headers(CTX)
    token = bind_forwarded_tenant_headers(headers)
    yield headers
    reset_forwarded_tenant_headers(token)


def _wire_headers(request: httpx.Request) -> dict[str, str]:
    """Case-insensitive extraction of the signature headers from a
    captured httpx request (the wire lowercases header names)."""
    lowered = {k.lower(): v for k, v in request.headers.items()}
    result: dict[str, str] = {}
    for h in TENANT_SIGNATURE_HEADERS:
        if h.lower() in lowered:
            result[h] = lowered[h.lower()]
    return result


def _client_factory(captured: list[httpx.Request], responder=None):
    """Patch target for ``mod.httpx.AsyncClient`` — uses the REAL class
    captured before patching (the httpx module object is shared)."""
    real_client = httpx.AsyncClient
    transport = _capturing_transport(captured, responder)

    def factory(**kw):
        # Keep the internal_http egress hook so tenant-header forwarding
        # (now a client-level event hook) actually runs on the wire.
        return real_client(transport=transport, event_hooks=kw.get("event_hooks"))

    return factory


def _capturing_transport(captured: list[httpx.Request], responder=None):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if responder is not None:
            return responder(request)
        return httpx.Response(200, json={})

    return httpx.MockTransport(handler)


# ── Hop 1: CH WS chat → AR /internal/conversation/turn ──────────────────────


class TestChatDelegateToAgentRuntime:
    @pytest.fixture
    def chat_settings(self, monkeypatch):
        monkeypatch.setattr(
            chat,
            "get_settings",
            lambda: SimpleNamespace(
                agent_runtime_url="http://ar-test:8001",
                agent_question_timeout_seconds=60,
            ),
        )

    @pytest.mark.asyncio
    async def test_delegate_carries_signed_tenant_context(
        self, bound_tenant, chat_settings
    ):
        """The delegate hop to AR forwards the freshly minted signed set —
        AR can only bind what it receives; without it AR's first CC data
        call fails closed with 401."""
        captured: list[httpx.Request] = []
        factory = _client_factory(captured)

        app = SimpleNamespace(state=SimpleNamespace(certificate_manager=None))

        with patch.object(chat.httpx, "AsyncClient", factory):
            with chat._signed_tenant_forwarding():
                await chat._delegate_conversation_turn_to_agent_runtime(
                    app=app,
                    conv_session_id=uuid.uuid4(),
                    agent_type_id=uuid.uuid4(),
                    messages=[{"role": "user", "content": "hello"}],
                )

        assert len(captured) == 1
        forwarded = _wire_headers(captured[0])
        assert len(forwarded) == len(TENANT_SIGNATURE_HEADERS)
        verified = verify_tenant_signature_headers(forwarded)  # AR-side check
        assert str(verified.tenant_id) == str(CTX.tenant_id)
        assert verified.slug == CTX.slug

    @pytest.mark.asyncio
    async def test_signature_is_minted_at_delegate_time(self, bound_tenant, chat_settings):
        """The set reaching the delegate hop is minted for the dispatch call
        itself — ``_process_message`` wraps the ``_call_llm`` (→ delegate)
        step in ``_signed_tenant_forwarding``, so a long turn never sends a
        stale connect-time signature to AR."""
        captured_in_llm: list[dict[str, str]] = []

        async def fake_call_llm(**kwargs):
            captured_in_llm.append(dict(forward_tenant_headers()))
            return "llm reply", None, []

        captured: list[httpx.Request] = []
        factory = _client_factory(captured)
        client = SimpleNamespace(
            prepare_conversation_turn=lambda *a, **k: _async_return(
                {
                    "agent_type_id": str(uuid.uuid4()),
                    "messages": [],
                    "no_agent_message": None,
                }
            ),
            append_conversation_turn=_async_append,
        )
        app = SimpleNamespace(state=SimpleNamespace(data_client=client))

        with patch.object(chat, "_call_llm", fake_call_llm):
            with patch.object(chat.httpx, "AsyncClient", factory):
                await chat._process_message(
                    conv_session_id=uuid.uuid4(),
                    user_message="hi",
                    is_first_message=False,
                    app=app,
                )

        # The LLM/delegate step saw a freshly minted, verifiable set.
        assert len(captured_in_llm) == 1
        verified = verify_tenant_signature_headers(captured_in_llm[0])
        assert verified.slug == CTX.slug
        # And nothing leaks after the turn.
        assert forward_tenant_headers() == {}

    @pytest.mark.asyncio
    async def test_delegate_single_tenant_mode_stays_headerless(
        self, chat_settings
    ):
        """No tenant context bound → headerless traffic, byte-for-byte
        unchanged; AR middleware binds nothing and AR's data calls stay
        headerless as before."""
        captured: list[httpx.Request] = []
        factory = _client_factory(captured)
        app = SimpleNamespace(state=SimpleNamespace(certificate_manager=None))

        with patch.object(chat.httpx, "AsyncClient", factory):
            await chat._delegate_conversation_turn_to_agent_runtime(
                app=app,
                conv_session_id=uuid.uuid4(),
                agent_type_id=uuid.uuid4(),
                messages=[{"role": "user", "content": "hi"}],
            )

        headers = _wire_headers(captured[0])
        for h in TENANT_SIGNATURE_HEADERS:
            assert h not in headers


# ── Hop 2: CH /internal/agent/execute → AR /execute ─────────────────────────


class TestAgentExecuteTriggerForwarding:
    @pytest.mark.asyncio
    async def test_trigger_forwards_bound_signed_set(self, bound_forwarded_headers):
        """The CC→CH execution trigger forwards the verified set to AR
        (CH middleware bound it; the forward must be verbatim)."""
        from app.communication_hub.api.internal import agent_execute

        captured: list[httpx.Request] = []

        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "session_id": str(uuid.uuid4()),
                    "status": "running",
                },
            )

        factory = _client_factory(captured, responder)

        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(certificate_manager=None))
        )

        with patch("app.communication_hub.main._load_certificate", _async_noop()):
            with patch.object(agent_execute.httpx, "AsyncClient", factory):
                resp = await agent_execute.trigger_agent_execution(
                    agent_execute.AgentExecuteRequest(
                        session_id=uuid.uuid4(),
                        agent_type_id=uuid.uuid4(),
                        input_data=None,
                    ),
                    request,
                )

        assert resp.status == "running"
        assert len(captured) == 1
        forwarded = _wire_headers(captured[0])
        assert forwarded == bound_forwarded_headers, (
            "trigger must forward the received signed set verbatim"
        )

    @pytest.mark.asyncio
    async def test_trigger_single_tenant_mode_stays_headerless(self):
        from app.communication_hub.api.internal import agent_execute

        captured: list[httpx.Request] = []
        factory = _client_factory(
            captured,
            lambda req: httpx.Response(
                200,
                json={"session_id": str(uuid.uuid4()), "status": "running"},
            ),
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(certificate_manager=None))
        )

        with patch("app.communication_hub.main._load_certificate", _async_noop()):
            with patch.object(agent_execute.httpx, "AsyncClient", factory):
                await agent_execute.trigger_agent_execution(
                    agent_execute.AgentExecuteRequest(
                        session_id=uuid.uuid4(),
                        agent_type_id=uuid.uuid4(),
                        input_data=None,
                    ),
                    request,
                )

        headers = _wire_headers(captured[0])
        for h in TENANT_SIGNATURE_HEADERS:
            assert h not in headers


def _async_return(value):
    async def _inner(*a, **k):
        return value

    return _inner()


async def _async_append(**kwargs):
    return {"title": "T"}


def _async_noop():
    async def _noop():
        return None

    return _noop


# ── Hop 3: AR data client → CC internal data plane ──────────────────────────


class FakeCertManager:
    """Supplies mTLS client kwargs (no cert in test); the transport is
    injected into the factory by ``_client``."""

    def mtls_client_kwargs(self) -> dict:
        return {}


class TestARDataClientForwarding:
    def _client(self, captured, responder=None, monkeypatch=None):
        from app.agent_runtime import data_client as dc_module
        from app.agent_runtime.data_client import ControlCenterDataClient

        transport = _capturing_transport(captured, responder)

        # Route the factory-built client through the capturing transport so
        # the egress hook's wire output is observable.
        real_factory = dc_module.internal_httpx_client
        monkeypatch.setattr(
            dc_module,
            "internal_httpx_client",
            lambda **kwargs: real_factory(transport=transport, **kwargs),
        )

        return ControlCenterDataClient(
            cert_manager=FakeCertManager(),
            control_center_url="http://cc-test:8000",
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "invoke,expected_path",
        [
            (
                lambda c, sid: c.mark_session_running(sid),
                "/api/v1/internal/data/sessions/{sid}/status",
            ),
            (
                lambda c, sid: c.get_session(sid),
                "/api/v1/internal/data/sessions/{sid}",
            ),
            (
                lambda c, sid: c.save_output(sid, {"answer": 1}),
                "/api/v1/internal/data/sessions/{sid}/result",
            ),
            (
                lambda c, sid: c.log_execution_event(
                    sid, "status_event", "running", {}
                ),
                "/api/v1/internal/data/sessions/{sid}/log",
            ),
            (
                lambda c, sid: c.validate_typed_output(uuid.uuid4(), {"a": 1}),
                "/api/v1/internal/validate-output",
            ),
            (
                lambda c, sid: c.persist_typed_output(
                    uuid.uuid4(), uuid.uuid4(), sid, None, "valid"
                ),
                "/api/v1/internal/agent-outputs",
            ),
        ],
    )
    async def test_every_ar_cc_call_forwards_signed_set(
        self, bound_forwarded_headers, monkeypatch, invoke, expected_path
    ):
        """PATCH status (the live failure), GET session, result submission,
        execution logs and typed-output calls all carry the bound signed
        set verbatim."""
        captured: list[httpx.Request] = []
        client = self._client(captured, monkeypatch=monkeypatch)
        sid = uuid.uuid4()

        await invoke(client, sid)

        assert len(captured) == 1
        assert captured[0].url.path == expected_path.format(sid=sid)
        forwarded = _wire_headers(captured[0])
        assert forwarded == bound_forwarded_headers, (
            f"AR→CC call {expected_path} must forward the signed set verbatim"
        )
        # CC-side acceptance through the real verifier.
        verify_tenant_signature_headers(forwarded)

    @pytest.mark.asyncio
    async def test_missing_headers_fail_clear_not_silent(self, monkeypatch):
        """Nothing bound (multi-tenancy misconfiguration at an earlier hop)
        → the call goes out headerless and CC's 401 is raised loudly as
        ControlCenterDataError — never swallowed into a fake success."""

        def cc_rejects(request: httpx.Request) -> httpx.Response:
            # Assert the client really sent NO tenant headers — CC would
            # reject exactly this wire shape.
            assert _wire_headers(request) == {}
            return httpx.Response(
                401,
                json={
                    "detail": "Signed tenant context headers are required "
                    "on internal data-plane endpoints"
                },
            )

        captured: list[httpx.Request] = []
        client = self._client(captured, cc_rejects, monkeypatch=monkeypatch)

        from app.agent_runtime.data_client import ControlCenterDataError

        with pytest.raises(ControlCenterDataError) as excinfo:
            await client.mark_session_running(uuid.uuid4())

        assert "401" in str(excinfo.value)
        assert "Signed tenant context headers" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_status_patch_retry_after_cert_recovery_keeps_headers(
        self, bound_forwarded_headers, monkeypatch
    ):
        """401 with a certificate message triggers re-bootstrap and one
        retry — the retry must still carry the forwarded signed set."""

        calls: list[httpx.Request] = []

        def responder(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(401, text="certificate has expired")
            return httpx.Response(200, json={})

        captured: list[httpx.Request] = []
        client = self._client(captured, responder, monkeypatch=monkeypatch)

        async def fake_recover() -> None:
            return None

        client._auto_recover_certificate = fake_recover  # type: ignore[method-assign]

        await client.mark_session_running(uuid.uuid4())

        assert len(captured) == 2
        for request in captured:
            forwarded = _wire_headers(request)
            assert forwarded == bound_forwarded_headers


class TestReceiverPurityStillHolds:
    def test_chat_delegate_only_forwards_never_signs(self):
        """The delegate hop must obtain headers via the forwarding helper —
        minting stays inside ``_signed_tenant_forwarding`` (the WS-chat
        origin), not ad-hoc signing in the delegate."""
        from app.api.ws import chat as chat_module

        source = inspect.getsource(
            chat_module._delegate_conversation_turn_to_agent_runtime
        )
        assert "forward_tenant_headers()" in source
        assert "build_tenant_signature_headers" not in source

    def test_ar_data_client_uses_egress_hook_forward_only(self):
        """Tenant forwarding now lives in the internal_httpx_client egress
        hook — the manual per-call merge is gone, and AR still never signs."""
        from app.agent_runtime import data_client

        source = inspect.getsource(data_client)
        assert "internal_httpx_client(" in source
        assert "forward_tenant_headers()" not in source
        assert "build_tenant_signature_headers" not in source
        assert "sign_context_for_authenticated_session" not in source
