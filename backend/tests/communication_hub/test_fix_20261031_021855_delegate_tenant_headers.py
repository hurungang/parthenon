"""FIX-20261031-021855 reproduction — conversation callback 401 under multi-tenancy.

Live failure (multi-tenancy ON, first chat message):

    browser → WS chat → delegate hop CH/CC → AR ``POST /internal/conversation/turn``
      → AR → CC ``PATCH /internal/data/sessions/{id}/status``
      ← 401 "Signed tenant context headers are required on internal
         data-plane endpoints"
    ControlCenterDataError: CC data API PATCH .../status returned 401

The delegate hop to Agent Runtime must carry the CC-signed
``X-Internal-Tenant-*`` header set (minted by ``_signed_tenant_forwarding``
from the tenant context bound at WS connect time); AR verifies it, binds it,
and forwards it VERBATIM on every AR→CC data call.  If the delegate hop goes
out headerless, AR has nothing to bind/forward and CC rejects the first
status PATCH fail-closed.

Two layers:

1. CC-side delegation contract (``_delegate_conversation_turn_to_agent_runtime``):
   the request CH/CC puts on the wire for AR carries the full signed set.
2. AR-side callback contract (``ControlCenterDataClient.mark_session_running``):
   with a verified set bound (exactly what AR's middleware does after the hop
   above succeeds), the status PATCH forwards it verbatim and CC's real
   verifier accepts — and headerless traffic fails CLEAR with the live 401.
"""
from __future__ import annotations

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
    reset_forwarded_tenant_headers,
    verify_tenant_signature_headers,
)

CTX = TenantContext(
    tenant_id=uuid.UUID("77777777-7777-7777-7777-777777777777"),
    slug="fix-021855-tenant",
    name="FIX-20261031-021855 Tenant",
)


@pytest.fixture
def bound_tenant():
    """Bind the WS-equivalent tenant context (as websocket_chat does)."""
    token = set_current_tenant_context(CTX)
    yield CTX
    reset_current_tenant_context(token)


@pytest.fixture
def bound_forwarded_headers():
    """Bind a signed header set as AR's middleware would after verifying
    the delegate hop's inbound request."""
    from app.core.tenant_signature import build_tenant_signature_headers

    headers = build_tenant_signature_headers(CTX)
    token = bind_forwarded_tenant_headers(headers)
    yield headers
    reset_forwarded_tenant_headers(token)


def _wire_headers(request: httpx.Request) -> dict[str, str]:
    lowered = {k.lower(): v for k, v in request.headers.items()}
    return {
        h: lowered[h.lower()]
        for h in TENANT_SIGNATURE_HEADERS
        if h.lower() in lowered
    }


def _client_factory(captured: list[httpx.Request], responder=None):
    """Patch target for ``chat.httpx.AsyncClient`` — real class, capturing
    transport, and the caller's event hooks preserved (the forwarding hook
    must run on the wire)."""
    real_client = httpx.AsyncClient
    transport = _capturing_transport(captured, responder)

    def factory(**kw):
        return real_client(
            transport=transport, event_hooks=kw.get("event_hooks")
        )

    return factory


def _capturing_transport(captured: list[httpx.Request], responder=None):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if responder is not None:
            return responder(request)
        return httpx.Response(200, json={})

    return httpx.MockTransport(handler)


# ── Layer 1: CC/CH → AR delegate hop carries the signed set ─────────────────


class TestDelegateHopCarriesSignedTenantContext:
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
    async def test_delegate_hop_to_ar_carries_signed_tenant_set(
        self, bound_tenant, chat_settings
    ):
        """REPRODUCTION of the live 401 chain, hop 1: the delegation request
        to AR MUST carry the CC-signed X-Internal-Tenant-* header set minted
        by ``_signed_tenant_forwarding`` — without it AR binds nothing and
        its first PATCH of the session status fails closed with 401."""
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

        assert len(captured) == 1, "delegate hop must issue exactly one request"
        forwarded = _wire_headers(captured[0])
        missing = [h for h in TENANT_SIGNATURE_HEADERS if h not in forwarded]
        assert not missing, (
            "delegate hop to AR went out WITHOUT the signed tenant header "
            f"set (missing: {missing}) — AR will fail closed on its first "
            "CC data call with 401 under multi-tenancy"
        )
        # AR-side acceptance through the REAL verifier.
        verified = verify_tenant_signature_headers(forwarded)
        assert str(verified.tenant_id) == str(CTX.tenant_id)
        assert verified.slug == CTX.slug

    @pytest.mark.asyncio
    async def test_streaming_delegate_hop_carries_signed_tenant_set(
        self, bound_tenant, chat_settings
    ):
        """The STREAMING variant (the path actually used by the chat UI)
        must attach the signed set on the streamed POST too."""

        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"type": "final", "response": "ok"},
            )

        captured: list[httpx.Request] = []
        factory = _client_factory(captured, responder)
        app = SimpleNamespace(state=SimpleNamespace(certificate_manager=None))

        async def on_status_event(event: dict[str, str]) -> None:
            return None

        with patch.object(chat.httpx, "AsyncClient", factory):
            with chat._signed_tenant_forwarding():
                await chat._delegate_conversation_turn_to_agent_runtime(
                    app=app,
                    conv_session_id=uuid.uuid4(),
                    agent_type_id=uuid.uuid4(),
                    messages=[{"role": "user", "content": "hello"}],
                    on_status_event=on_status_event,
                )

        assert len(captured) == 1
        forwarded = _wire_headers(captured[0])
        missing = [h for h in TENANT_SIGNATURE_HEADERS if h not in forwarded]
        assert not missing, (
            "streaming delegate hop to AR went out WITHOUT the signed tenant "
            f"header set (missing: {missing})"
        )
        verify_tenant_signature_headers(forwarded)

    @pytest.mark.asyncio
    async def test_delegate_hop_single_tenant_mode_stays_headerless(
        self, chat_settings
    ):
        """Single-tenant mode (no bound context) → headerless, unchanged."""
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

        assert _wire_headers(captured[0]) == {}


# ── Layer 2: AR → CC status PATCH succeeds with a bound verified set ────────


class FakeCertManager:
    def mtls_client_kwargs(self) -> dict:
        return {}


class TestARStatusPatchCallbackSucceeds:
    def _client(self, captured, responder, monkeypatch):
        from app.agent_runtime import data_client as dc_module
        from app.agent_runtime.data_client import ControlCenterDataClient

        transport = _capturing_transport(captured, responder)
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
    async def test_status_patch_succeeds_with_bound_forwarded_set(
        self, bound_forwarded_headers, monkeypatch
    ):
        """AR-side contract (passes when hop 1 is correct): with the verified
        set bound — exactly what AR's middleware does — the live-failing
        PATCH /internal/data/sessions/{id}/status forwards the set verbatim
        and CC's real verifier accepts it."""

        def cc_accepts(request: httpx.Request) -> httpx.Response:
            forwarded = _wire_headers(request)
            verify_tenant_signature_headers(forwarded)  # raises on any gap
            assert str(verify_tenant_signature_headers(forwarded).tenant_id) == str(
                CTX.tenant_id
            )
            return httpx.Response(200, json={})

        captured: list[httpx.Request] = []
        client = self._client(captured, cc_accepts, monkeypatch)
        sid = uuid.uuid4()

        await client.mark_session_running(sid)  # must not raise

        assert len(captured) == 1
        assert captured[0].url.path == f"/api/v1/internal/data/sessions/{sid}/status"
        assert _wire_headers(captured[0]) == bound_forwarded_headers

    @pytest.mark.asyncio
    async def test_headerless_status_patch_fails_clear_with_live_401(
        self, monkeypatch
    ):
        """Nothing bound (the live misconfiguration when hop 1 drops the
        set) → CC rejects fail-closed and the error surfaces loudly as
        ControlCenterDataError with the exact live message."""

        def cc_rejects(request: httpx.Request) -> httpx.Response:
            assert _wire_headers(request) == {}
            return httpx.Response(
                401,
                json={
                    "detail": "Signed tenant context headers are required "
                    "on internal data-plane endpoints"
                },
            )

        captured: list[httpx.Request] = []
        client = self._client(captured, cc_rejects, monkeypatch)

        from app.agent_runtime.data_client import ControlCenterDataError

        with pytest.raises(ControlCenterDataError) as excinfo:
            await client.mark_session_running(uuid.uuid4())

        assert "401" in str(excinfo.value)
        assert "Signed tenant context headers" in str(excinfo.value)
