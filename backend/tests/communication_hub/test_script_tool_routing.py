"""Unit tests for the ``script____<name>`` virtual-tool routing (Communication Hub).

The scripts-as-tools surface: a compiled script that is NOT ``fully_scripted``
is exposed to the agent LLM as an invocable ``script____<name>`` tool. When the
LLM invokes one, Communication Hub must route the call to **Agent Runtime** —
sandboxed scripts execute ONLY there (top-priority rule) — never to Control
Center or the MCP proxy (the ``script`` slug has no ``mcp_tools`` row and no
system-tool entry, so both would fail). The forwarded payload carries the
session's agent identity (``session_id`` + ``agent_type_id``) so AR runs the
sandbox with the same identity as the agent's own tool calls (SEC1 parity).

Mirrors the ``decision____`` / ``semantic____`` virtual-tool routing tests in
``test_tool_routing_tenant_forwarding.py``.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.communication_hub.api.internal import tool_routing


class _FakeCertManager:
    """CH service-certificate double (the script route requires cert+key)."""

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
        # Keep the internal_http egress hook so the request flows through the
        # real client construction path (tenant forwarding is a no-op here).
        return real_client(transport=transport, event_hooks=kw.get("event_hooks"))

    return factory


class TestScriptToolRouting:
    @pytest.fixture
    def routing_settings(self, monkeypatch):
        # Route to a distinct AR host so the destination is unambiguous.
        monkeypatch.setattr(
            tool_routing.settings, "agent_runtime_url", "https://ar-test:8001"
        )
        return tool_routing

    @pytest.mark.asyncio
    async def test_script_tool_routes_to_agent_runtime(self, routing_settings):
        """``script____<name>`` forwards to AR ``/internal/script-tools/execute``
        (NOT CC / system-tools / MCP proxy) with the session's agent identity."""
        captured: list[httpx.Request] = []
        session_id = str(uuid.uuid4())
        agent_type_id = str(uuid.uuid4())
        factory = _client_factory(captured)
        body = routing_settings.ToolCallRequest(
            tool_name="script____auto-aaaaaaaa",
            tool_args={"id": "c-1"},
            session_id=session_id,
            agent_type_id=agent_type_id,
        )

        with patch.object(routing_settings.httpx, "AsyncClient", factory):
            response = await routing_settings.route_tool_call(body, _fake_request())

        # Routed to Agent Runtime (ar-test), not Control Center (cc) or MCP.
        assert captured[0].url.host == "ar-test"
        assert captured[0].url.path == "/internal/script-tools/execute"
        payload = json.loads(captured[0].content)
        assert payload["tool_name"] == "script____auto-aaaaaaaa"
        assert payload["tool_args"] == {"id": "c-1"}
        # Session-bound identity: AR executes the sandbox as this session's agent.
        assert payload["session_id"] == session_id
        assert payload["agent_type_id"] == agent_type_id
        # The LLM is the invoker of a script tool (provenance audit).
        assert payload["provenance"] == "llm"
        assert response.result == {}

    @pytest.mark.asyncio
    async def test_script_tool_returns_script_result(self, routing_settings):
        """The AR script result is unwrapped from ``{"result": ...}`` and
        returned in the ``call_tool`` contract shape."""
        captured: list[httpx.Request] = []

        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"result": {"name": "Ada", "tier": "gold"}}
            )

        factory = _client_factory(captured, responder)
        body = routing_settings.ToolCallRequest(
            tool_name="script____report",
            tool_args={},
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )

        with patch.object(routing_settings.httpx, "AsyncClient", factory):
            response = await routing_settings.route_tool_call(body, _fake_request())

        assert response.result == {"name": "Ada", "tier": "gold"}
        assert response.error is None

    @pytest.mark.asyncio
    async def test_script_tool_ar_error_surfaces_as_tool_error(self, routing_settings):
        """A failed AR script execution surfaces as a tool error, not a 502."""
        captured: list[httpx.Request] = []

        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "sandbox violation: os import"})

        factory = _client_factory(captured, responder)
        body = routing_settings.ToolCallRequest(
            tool_name="script____report",
            tool_args={},
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )

        with patch.object(routing_settings.httpx, "AsyncClient", factory):
            response = await routing_settings.route_tool_call(body, _fake_request())

        assert response.result == {}
        assert "sandbox violation" in (response.error or "")

    @pytest.mark.asyncio
    async def test_inline_python_source_forwarded_to_ar(self, routing_settings):
        """CC verification runs: ``python_source`` on the request is forwarded
        verbatim in the AR payload (inline execution, no registry lookup)."""
        captured: list[httpx.Request] = []
        source = "def run(context, tools):\n    return {'ok': True}\n"
        factory = _client_factory(captured)
        body = routing_settings.ToolCallRequest(
            tool_name="script____inline",
            tool_args={"input": {"x": 1}},
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
            python_source=source,
        )

        with patch.object(routing_settings.httpx, "AsyncClient", factory):
            await routing_settings.route_tool_call(body, _fake_request())

        payload = json.loads(captured[0].content)
        assert payload["python_source"] == source
        assert payload["tool_name"] == "script____inline"

    @pytest.mark.asyncio
    async def test_no_python_source_omits_field(self, routing_settings):
        """Without inline source the field is omitted (registry path)."""
        captured: list[httpx.Request] = []
        factory = _client_factory(captured)
        body = routing_settings.ToolCallRequest(
            tool_name="script____report",
            tool_args={},
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )

        with patch.object(routing_settings.httpx, "AsyncClient", factory):
            await routing_settings.route_tool_call(body, _fake_request())

        payload = json.loads(captured[0].content)
        assert "python_source" not in payload

    def test_script_prefix_checked_before_system_and_mcp(self, routing_settings):
        """Routing order: the script prefix must win over the system and MCP
        fallbacks (``script`` would otherwise parse as an MCP server slug)."""
        assert routing_settings.SCRIPT_TOOL_PREFIX == "script____"
        assert "script____report".startswith(routing_settings.SCRIPT_TOOL_PREFIX)
        # Distinct from the other virtual-tool prefixes.
        assert routing_settings.SCRIPT_TOOL_PREFIX != routing_settings.DECISION_TOOL_PREFIX
        assert routing_settings.SCRIPT_TOOL_PREFIX != routing_settings.SEMANTIC_TOOL_PREFIX
        # Not classified as a system tool.
        assert not routing_settings._is_system_tool("script____report")

    @pytest.mark.asyncio
    async def test_script_tool_requires_ch_service_certificate(self, routing_settings):
        """Without a CH service certificate the script route fails closed (503)
        — it never silently forwards to AR."""
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(certificate_manager=None))
        )
        body = routing_settings.ToolCallRequest(
            tool_name="script____report",
            tool_args={},
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )

        with pytest.raises(Exception) as excinfo:
            await routing_settings.route_tool_call(body, request)

        assert getattr(excinfo.value, "status_code", None) == 503
        assert "service certificate" in str(excinfo.value.detail).lower()
