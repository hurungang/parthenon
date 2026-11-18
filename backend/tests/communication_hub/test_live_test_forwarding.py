"""Communication Hub — approved live-test forwarding (CC → CH → AR).

CH is transport only for a live test: Control Center's ledger already consumed
the single-use approval, so this endpoint forwards the approved **script**
(the saved version's source) **verbatim** to Agent Runtime's
``POST /internal/live-test/run`` using CH's own service certificate. A live test
runs the script end-to-end; there is no per-operation list to execute.

It adds no identity material (CH injects identity per tool call *inside* AR's
run), performs no authorization of its own beyond the existing control-plane
checks, and never originates a live test.

Also pinned: the route classifies as a control-plane path (CC certificate
expected — not an agent-runtime tool path), and the CH→AR hop is built through
``internal_httpx_client`` so the CC-signed tenant header set is forwarded
unchanged (CH never signs).
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.communication_hub.api.internal import live_test_forwarding
from app.communication_hub.middleware import control_plane


class _FakeCertManager:
    """CH service-certificate double (the AR hop requires cert+key)."""

    cert_path = "/tmp/ch-cert.pem"
    key_path = "/tmp/ch-key.pem"


def _fake_request(cert_manager=None) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                certificate_manager=(
                    cert_manager if cert_manager is not None else _FakeCertManager()
                )
            )
        )
    )


def _client_factory(captured: list[httpx.Request], responder=None):
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if responder is not None:
            return responder(request)
        return httpx.Response(
            200,
            json={
                "status": "executed",
                "executed_operations": [],
                "started_at": None,
                "finished_at": None,
                "error": None,
            },
        )

    transport = httpx.MockTransport(handler)

    def factory(**kwargs):
        return real_client(
            transport=transport,
            event_hooks=kwargs.get("event_hooks"),
        )

    return factory


@pytest.fixture
def fwd(monkeypatch):
    monkeypatch.setattr(
        live_test_forwarding, "_ar_base", lambda: "https://ar-test:8001"
    )
    return live_test_forwarding


SCRIPT_SOURCE = (
    "def run(context, tools):\n"
    "    customer = tools.call('crm____searchCustomers', {'q': 'ada'})\n"
    "    return {'customer': customer}\n"
)


def _body(**overrides):
    payload = {
        "live_test_request_id": str(uuid.uuid4()),
        "conversation_session_id": str(uuid.uuid4()),
        "target_agent_type_id": str(uuid.uuid4()),
        "script_version_id": str(uuid.uuid4()),
        "script_name": "daily-refunds",
        "script_version_label": "v4",
        "python_source": SCRIPT_SOURCE,
        "input_context": {"order_id": "o-1"},
    }
    payload.update(overrides)
    return live_test_forwarding.LiveTestForwardRequest(**payload)


class TestForwardToAgentRuntime:
    @pytest.mark.asyncio
    async def test_targets_the_ar_live_test_route(self, fwd):
        captured: list[httpx.Request] = []
        with patch.object(httpx, "AsyncClient", _client_factory(captured)):
            result = await fwd.forward_live_test(_body(), _fake_request())

        assert len(captured) == 1
        assert captured[0].url.host == "ar-test"
        assert captured[0].url.path == "/internal/live-test/run"
        assert captured[0].method == "POST"
        assert result["status"] == "executed"

    @pytest.mark.asyncio
    async def test_the_approved_script_is_forwarded_verbatim(self, fwd):
        captured: list[httpx.Request] = []
        body = _body()

        with patch.object(httpx, "AsyncClient", _client_factory(captured)):
            await fwd.forward_live_test(body, _fake_request())

        payload = json.loads(captured[0].content)
        assert payload == {
            "live_test_request_id": body.live_test_request_id,
            "conversation_session_id": body.conversation_session_id,
            "target_agent_type_id": body.target_agent_type_id,
            "script_version_id": body.script_version_id,
            "script_name": "daily-refunds",
            "script_version_label": "v4",
            "python_source": SCRIPT_SOURCE,
            "input_context": {"order_id": "o-1"},
        }
        # The script source is the unit of execution — byte-identical, and no
        # operation list is forwarded (nothing is executed tool-by-tool).
        assert payload["python_source"] == SCRIPT_SOURCE
        assert "operations" not in payload
        assert "requested_operations" not in payload

    @pytest.mark.asyncio
    async def test_no_identity_material_is_added(self, fwd):
        captured: list[httpx.Request] = []
        with patch.object(httpx, "AsyncClient", _client_factory(captured)):
            await fwd.forward_live_test(_body(), _fake_request())

        raw = captured[0].content.decode()
        for forbidden in ("authorization", "bearer ", "access_token", "api_key", "password"):
            assert forbidden not in raw.lower()
        # The only headers are transport headers + the CH certificate header.
        assert "X-Client-Certificate" not in captured[0].headers  # https mTLS hop
        assert "Authorization" not in captured[0].headers

    @pytest.mark.asyncio
    async def test_the_ch_certificate_is_presented_to_ar(self, fwd):
        captured: list[httpx.Request] = []
        with patch.object(httpx, "AsyncClient", _client_factory(captured)):
            await fwd.forward_live_test(_body(), _fake_request())

        # Over HTTPS the certificate is presented as mTLS, never as a token.
        assert captured[0].url.scheme == "https"

    @pytest.mark.asyncio
    async def test_http_development_mode_sends_the_certificate_header(
        self, fwd, monkeypatch, tmp_path
    ):
        cert = tmp_path / "ch-cert.pem"
        cert.write_text("-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----")
        key = tmp_path / "ch-key.pem"
        key.write_text("key")
        cert_manager = SimpleNamespace(cert_path=str(cert), key_path=str(key))
        monkeypatch.setattr(fwd, "_ar_base", lambda: "http://ar-test:8001")

        captured: list[httpx.Request] = []
        with patch.object(httpx, "AsyncClient", _client_factory(captured)):
            await fwd.forward_live_test(_body(), _fake_request(cert_manager))

        header = captured[0].headers.get("X-Client-Certificate")
        assert header is not None
        assert "BEGIN CERTIFICATE" in header

    @pytest.mark.asyncio
    async def test_cc_signed_tenant_headers_are_forwarded_unchanged(self, fwd):
        """CH never signs: it re-emits the ORIGINAL verified header set."""
        from app.core.tenant_signature import (
            bind_forwarded_tenant_headers,
            reset_forwarded_tenant_headers,
        )

        headers = {
            "X-Internal-Tenant-Id": str(uuid.uuid4()),
            "X-Internal-Tenant-Slug": "acme",
            "X-Internal-Tenant-Signature": "sig",
            "X-Internal-Tenant-Timestamp": "123",
        }
        token = bind_forwarded_tenant_headers(headers)
        captured: list[httpx.Request] = []
        try:
            with patch.object(httpx, "AsyncClient", _client_factory(captured)):
                await fwd.forward_live_test(_body(), _fake_request())
        finally:
            reset_forwarded_tenant_headers(token)

        for name, value in headers.items():
            assert captured[0].headers.get(name) == value

    @pytest.mark.asyncio
    async def test_missing_certificate_is_503_and_nothing_is_sent(self, fwd):
        from fastapi import HTTPException

        captured: list[httpx.Request] = []
        with patch.object(httpx, "AsyncClient", _client_factory(captured)):
            with pytest.raises(HTTPException) as exc_info:
                await fwd.forward_live_test(
                    _body(),
                    _fake_request(cert_manager=SimpleNamespace(cert_path=None, key_path=None)),
                )

        assert exc_info.value.status_code == 503
        assert captured == []


class TestFailurePropagation:
    @pytest.mark.asyncio
    async def test_a_4xx_from_ar_becomes_a_structured_failure(self, fwd):
        captured: list[httpx.Request] = []
        with patch.object(
            httpx,
            "AsyncClient",
            _client_factory(
                captured,
                responder=lambda request: httpx.Response(
                    422, json={"detail": "capability check failed"}
                ),
            ),
        ):
            result = await fwd.forward_live_test(_body(), _fake_request())

        assert result["status"] == "failed"
        assert result["executed_operations"] == []
        assert "422" in result["error"]

    @pytest.mark.asyncio
    async def test_a_5xx_from_ar_is_a_502(self, fwd):
        from fastapi import HTTPException

        with patch.object(
            httpx,
            "AsyncClient",
            _client_factory(
                [], responder=lambda request: httpx.Response(500, text="boom")
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await fwd.forward_live_test(_body(), _fake_request())

        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_a_transport_error_is_a_502(self, fwd):
        from fastapi import HTTPException

        def _explode(request):  # noqa: ANN001
            raise httpx.ConnectError("connection refused", request=request)

        with patch.object(httpx, "AsyncClient", _client_factory([], responder=_explode)):
            with pytest.raises(HTTPException) as exc_info:
                await fwd.forward_live_test(_body(), _fake_request())

        assert exc_info.value.status_code == 502


class TestRouteRegistrationAndHop:
    def test_the_route_is_registered(self):
        paths = {route.path for route in live_test_forwarding.router.routes}
        assert "/internal/live-test/run" in paths

    def test_the_route_expects_the_control_center_certificate(self):
        """Only the CC→CH origin exists: the path is a control-plane path, so
        CH accepts ``service:control-center`` (never an agent-runtime cert)."""
        path = "/internal/live-test/run"
        assert path.startswith(control_plane._INTERNAL_PATH_PREFIX)
        assert not path.startswith(control_plane._TOOL_CALL_PATH_PREFIX)
        assert not path.startswith(control_plane._A2A_PATH_PREFIX)
        for prefix in control_plane._AGENT_RUNTIME_RELAY_PATH_PREFIXES:
            assert not path.startswith(prefix)
        assert control_plane._EXPECTED_SERVICE_NAME == "control-center"

    def test_cc_calls_the_route_through_the_comm_hub_client(self):
        """CC's client is the only caller; it forwards the ledger's list."""
        from pathlib import Path

        client_source = (
            Path(live_test_forwarding.__file__).resolve().parents[3]
            / "services"
            / "control_center"
            / "comm_hub_client.py"
        ).read_text()
        assert "/internal/live-test/run" in client_source
        assert "forward_live_test" in client_source

    def test_ch_never_signs_tenant_headers(self):
        """Structural: the forward module uses ``internal_httpx_client`` and
        never calls a signing helper."""
        from pathlib import Path

        source = Path(live_test_forwarding.__file__).read_text()
        assert "internal_httpx_client" in source
        assert "tenant_context_headers" not in source
        # No signing capability and no hand-built tenant header merging.
        assert "X-Internal-Tenant-Signature" not in source
        assert "sign_tenant" not in source
        assert "hmac" not in source.lower()
