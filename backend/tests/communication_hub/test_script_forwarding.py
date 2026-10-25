"""Routing tests: CC ``execute_script`` verification reaches AR via CH's
cert-authorized forwarding hop — NOT via CH ``/internal/tools/call``.

Background (architectural fix): CH's ControlPlaneMiddleware only accepts
AGENT-RUNTIME certificates on ``/internal/tools/`` — CC's service certificate
is rejected there, so the historical ``execute_sandboxed_script`` CC→CH
``/internal/tools/call`` hop was architecturally broken. The fix adds CH
``POST /internal/script-tools/forward`` (CC-cert hop, enforced by
ControlPlaneMiddleware) which forwards to AR ``/internal/script-tools/execute``
using CH's OWN certificate — the exact same CH→AR hop ``script____<name>``
tools take. The sandbox executes in AR with the session-bound tool client.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.communication_hub.api.internal import script_forwarding, tool_routing
from app.services.control_center import comm_hub_client


class _FakeCertManager:
    """CH service-certificate double (the AR hop requires cert+key)."""

    cert_path = "/tmp/ch-cert.pem"
    key_path = "/tmp/ch-key.pem"


def _fake_request() -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(certificate_manager=_FakeCertManager())
        )
    )


def _client_factory(captured: list[httpx.Request], responder=None):
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if responder is not None:
            return responder(request)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)

    def factory(**kw):
        return real_client(transport=transport, event_hooks=kw.get("event_hooks"))

    return factory


SOURCE = "def run(context, tools):\n    return {'ok': True}\n"


class TestChForwardEndpoint:
    """CH ``POST /internal/script-tools/forward`` → AR ``/internal/script-tools/execute``."""

    @pytest.fixture
    def fwd(self, monkeypatch):
        monkeypatch.setattr(
            script_forwarding, "_ar_base", lambda: "https://ar-test:8001"
        )
        return script_forwarding

    @pytest.mark.asyncio
    async def test_forward_targets_ar_script_tools_execute(self, fwd):
        """The CH→AR hop hits AR's script-tools endpoint (mirrors the
        ``script____<name>`` route), tagged as inline + script provenance."""
        captured: list[httpx.Request] = []
        session_id = str(uuid.uuid4())
        agent_type_id = str(uuid.uuid4())
        body = fwd.ScriptForwardRequest(
            session_id=session_id,
            agent_type_id=agent_type_id,
            tool_args={"input": {"x": 1}},
            python_source=SOURCE,
        )

        with patch.object(
            tool_routing.httpx, "AsyncClient", _client_factory(captured)
        ):
            result = await fwd.forward_script_execution(body, _fake_request())

        assert captured[0].url.host == "ar-test"
        assert captured[0].url.path == "/internal/script-tools/execute"
        payload = json.loads(captured[0].content)
        assert payload["tool_name"] == "script____inline"
        assert payload["python_source"] == SOURCE
        assert payload["tool_args"] == {"input": {"x": 1}}
        assert payload["session_id"] == session_id
        assert payload["agent_type_id"] == agent_type_id
        assert payload["provenance"] == "script"
        assert result == {}

    @pytest.mark.asyncio
    async def test_forward_passes_ar_result_through(self, fwd):
        """AR's ``{"result": ...}`` contract is returned verbatim."""
        captured: list[httpx.Request] = []

        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": {"ok": True}, "error": None})

        body = fwd.ScriptForwardRequest(
            session_id=str(uuid.uuid4()),
            python_source=SOURCE,
        )
        with patch.object(
            tool_routing.httpx, "AsyncClient", _client_factory(captured, responder)
        ):
            result = await fwd.forward_script_execution(body, _fake_request())

        assert result == {"result": {"ok": True}, "error": None}

    @pytest.mark.asyncio
    async def test_forward_passes_ar_structured_error_through(self, fwd):
        """A sandbox failure is surfaced as AR's ``error`` — never a 5xx."""
        captured: list[httpx.Request] = []

        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"result": None, "error": "SandboxCompileError: import os"}
            )

        body = fwd.ScriptForwardRequest(
            session_id=str(uuid.uuid4()), python_source=SOURCE
        )
        with patch.object(
            tool_routing.httpx, "AsyncClient", _client_factory(captured, responder)
        ):
            result = await fwd.forward_script_execution(body, _fake_request())

        assert result["error"] == "SandboxCompileError: import os"

    @pytest.mark.asyncio
    async def test_forward_requires_ch_certificate(self, fwd):
        """Without the CH certificate the hop fails closed (503)."""
        empty_request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(certificate_manager=None))
        )
        body = fwd.ScriptForwardRequest(
            session_id=str(uuid.uuid4()), python_source=SOURCE
        )
        with patch.object(tool_routing.httpx, "AsyncClient", _client_factory([])):
            with pytest.raises(Exception) as exc_info:
                await fwd.forward_script_execution(body, empty_request)
        assert "503" in str(exc_info.value.status_code) or exc_info.value.status_code == 503


class TestCcClientDestination:
    """CC ``forward_sandboxed_script`` targets the CH forward endpoint."""

    @pytest.mark.asyncio
    async def test_cc_client_posts_to_script_tools_forward(self, monkeypatch):
        """CC must NOT use ``/internal/tools/call`` (agent-runtime certs only)
        — the verification hop goes to ``/internal/script-tools/forward``."""
        captured: list[httpx.Request] = []

        def responder(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json={"result": {"ok": 1}, "error": None})

        client = comm_hub_client.CommunicationHubClient(
            comm_hub_url="https://ch-test:8002",
            cert_path="/tmp/cc-cert.pem",
            key_path="/tmp/cc-key.pem",
        )
        # Bypass the filesystem cert read: inject a plain client factory.
        real_client = httpx.AsyncClient
        transport = httpx.MockTransport(responder)

        def factory(**kw):
            captured_factory_kw.update(kw)
            return real_client(transport=transport, event_hooks=kw.get("event_hooks"))

        captured_factory_kw: dict = {}
        monkeypatch.setattr(client, "_make_client", factory)

        resp = await client.forward_sandboxed_script(
            python_source=SOURCE,
            session_id="sess-1",
            agent_type_id="at-1",
            input_context={"x": 1},
        )

        assert captured[0].url.host == "ch-test"
        assert captured[0].url.path == "/internal/script-tools/forward"
        assert "/internal/tools/call" != captured[0].url.path
        payload = json.loads(captured[0].content)
        assert payload["python_source"] == SOURCE
        assert payload["session_id"] == "sess-1"
        assert payload["agent_type_id"] == "at-1"
        assert payload["tool_args"] == {"input": {"x": 1}}
        assert resp == {"result": {"ok": 1}, "error": None}

    def test_execute_sandboxed_script_removed_from_client(self):
        """The broken CC-cert ``/internal/tools/call`` path is gone."""
        assert not hasattr(comm_hub_client.CommunicationHubClient,
                           "execute_sandboxed_script")
