"""Signed tenant context forwarding on CH → CC tool-call hops.

Live failure (multi-tenancy ON, agent tool call ``decision____severity-decision``):

    AR → CH ``POST /internal/tools/call``   (AR forwards its signed set; CH
          ControlPlaneMiddleware verifies + binds it)
      → CH → CC ``/internal/mcp/proxy-tool``   ← headers were DROPPED
        (also ``/internal/system-tools/*`` via the same module)
      ← CC 401 "Signed tenant context headers are required on internal
         data-plane endpoints" → CH 502 → AR tool failure ×N.

CH is a receiver — it never signs; it FORWARDS the bound verified set.
The MCP protocol-server bridge (``tool_registry_bridge._post_cc``) already
forwarded; ``tool_routing`` (the AR tool-call route) did not. These tests
pin every CH → CC POST hop at the HTTP layer:

1. ``tool_routing`` system-tool and MCP-proxy routes carry the bound
   signed set verbatim on the wire (and stay headerless when nothing is
   bound — single-tenant mode).
2. The bridge's ``_call_decision_tool`` (decision list + execute) and
   sibling CC calls (skills resolve, system tools, MCP proxy) carry the
   bound signed set verbatim.
3. The AR → CH ``/internal/tools/call`` route is covered by the
   ``ControlPlaneMiddleware`` binding (verify-only, fail-closed when
   present-but-invalid).
"""
from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.tenant_signature import (  # noqa: E402
    TENANT_SIGNATURE_HEADERS,
    TenantSignatureError,
    bind_forwarded_tenant_headers,
    build_tenant_signature_headers,
    forward_tenant_headers,
    reset_forwarded_tenant_headers,
    verify_tenant_signature_headers,
)

CTX_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
SIGNED = build_tenant_signature_headers(
    SimpleNamespace(tenant_id=CTX_ID, slug="tool-routing-tenant")  # type: ignore[arg-type]
)


@pytest.fixture(autouse=True)
def _insecure_fallback(monkeypatch):
    """Allow the no-certificate development path so the tests reach the
    HTTP layer without a CH service certificate."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "1")


@pytest.fixture
def bound():
    """Bind a signed header set as if ControlPlaneMiddleware verified it."""
    token = bind_forwarded_tenant_headers(SIGNED)
    yield SIGNED
    reset_forwarded_tenant_headers(token)


def _wire_headers(request: httpx.Request) -> dict[str, str]:
    lowered = {k.lower(): v for k, v in request.headers.items()}
    return {
        h: lowered[h.lower()]
        for h in TENANT_SIGNATURE_HEADERS
        if h.lower() in lowered
    }


def _client_factory(captured: list[httpx.Request], responder=None):
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if responder is not None:
            return responder(request)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)

    def factory(**kw):
        # Keep the internal_http egress hook so tenant-header forwarding
        # (now a client-level event hook) actually runs on the wire.
        return real_client(transport=transport, event_hooks=kw.get("event_hooks"))

    return factory


def _fake_request() -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(certificate_manager=None))
    )


# ── 1. tool_routing (AR tool-call route) ─────────────────────────────────────


class TestToolRoutingForwarding:
    @pytest.fixture
    def routing_settings(self, monkeypatch):
        from app.communication_hub.api.internal import tool_routing

        monkeypatch.setattr(
            tool_routing.settings,
            "control_center_url",
            "http://cc-test:8000",
        )
        return tool_routing

    @pytest.mark.asyncio
    async def test_decision_tool_route_forwards_bound_signed_set(
        self, bound, routing_settings
    ):
        """The live-failure hop: decision____<name> tools route to the CC
        decision execute endpoint (NOT the MCP proxy, where they 502'd
        with "MCP tool not found") with the tenant's signed set attached."""
        captured: list[httpx.Request] = []

        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"result": {"outcome": "approve", "tool_name": "severity-decision"}},
            )

        factory = _client_factory(captured, responder)
        body = routing_settings.ToolCallRequest(
            tool_name="decision____severity-decision",
            tool_args={"state": {"severity": "high"}},
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )

        with patch.object(routing_settings.httpx, "AsyncClient", factory):
            response = await routing_settings.route_tool_call(body, _fake_request())

        assert captured[0].url.path == "/api/v1/internal/system-tools/decision/execute"
        assert _wire_headers(captured[0]) == bound
        # CC-side acceptance through the real verifier.
        verify_tenant_signature_headers(_wire_headers(captured[0]))
        # Payload matches the CC DecisionToolExecuteRequest schema.
        payload = json.loads(captured[0].content)
        assert payload["tool_name"] == "severity-decision"
        assert payload["input_state"] == {"severity": "high"}
        # Result relayed back in the call_tool contract.
        assert response.result == {"outcome": "approve", "tool_name": "severity-decision"}

    @pytest.mark.asyncio
    async def test_decision_tool_route_single_tenant_stays_headerless(
        self, routing_settings
    ):
        captured: list[httpx.Request] = []
        factory = _client_factory(captured)
        body = routing_settings.ToolCallRequest(
            tool_name="decision____severity-decision",
            tool_args={"severity": "high"},  # bare args, no state wrapper
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )

        with patch.object(routing_settings.httpx, "AsyncClient", factory):
            await routing_settings.route_tool_call(body, _fake_request())

        assert captured[0].url.path == "/api/v1/internal/system-tools/decision/execute"
        assert _wire_headers(captured[0]) == {}
        payload = json.loads(captured[0].content)
        assert payload["input_state"] == {"severity": "high"}

    def test_decision_prefix_checked_before_system_and_mcp(self, routing_settings):
        """Routing order: the decision prefix must win over the system and
        MCP fallbacks (parse_tool_name would classify it as MCP server
        slug 'decision')."""
        assert routing_settings.DECISION_TOOL_PREFIX == "decision____"
        assert not routing_settings._is_system_tool("decision____severity-decision")
        assert "decision____severity-decision".startswith(
            routing_settings.DECISION_TOOL_PREFIX
        )

    @pytest.mark.asyncio
    async def test_mcp_proxy_route_forwards_bound_signed_set(
        self, bound, routing_settings
    ):
        """Genuine MCP tools still route through the MCP proxy with the
        tenant's signed set attached."""
        captured: list[httpx.Request] = []
        factory = _client_factory(captured)
        body = routing_settings.ToolCallRequest(
            tool_name="github____list_prs",
            tool_args={},
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )

        with patch.object(routing_settings.httpx, "AsyncClient", factory):
            await routing_settings._route_to_mcp_tool(body, _fake_request())

        assert captured[0].url.path == "/api/v1/internal/mcp/proxy-tool"
        assert _wire_headers(captured[0]) == bound
        # CC-side acceptance through the real verifier.
        verify_tenant_signature_headers(_wire_headers(captured[0]))

    @pytest.mark.asyncio
    async def test_mcp_proxy_route_single_tenant_stays_headerless(
        self, routing_settings
    ):
        captured: list[httpx.Request] = []
        factory = _client_factory(captured)
        body = routing_settings.ToolCallRequest(
            tool_name="github____list_prs",
            tool_args={},
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )

        with patch.object(routing_settings.httpx, "AsyncClient", factory):
            await routing_settings._route_to_mcp_tool(body, _fake_request())

        assert _wire_headers(captured[0]) == {}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool_name,tool_args",
        [
            ("system____save_data", {"data_name": "x", "data_value": {}}),
            ("save_data", {"data_name": "x", "data_value": {}}),  # legacy bare
        ],
    )
    async def test_system_tool_route_forwards_bound_signed_set(
        self, bound, routing_settings, tool_name, tool_args
    ):
        captured: list[httpx.Request] = []
        factory = _client_factory(captured)
        body = routing_settings.ToolCallRequest(
            tool_name=tool_name,
            tool_args=tool_args,
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )

        with patch.object(routing_settings.httpx, "AsyncClient", factory):
            await routing_settings._route_to_system_tool(body, _fake_request())

        assert "/api/v1/internal/system-tools/" in captured[0].url.path
        assert _wire_headers(captured[0]) == bound

    @pytest.mark.asyncio
    async def test_system_tool_route_single_tenant_stays_headerless(
        self, routing_settings
    ):
        captured: list[httpx.Request] = []
        factory = _client_factory(captured)
        body = routing_settings.ToolCallRequest(
            tool_name="system____save_data",
            tool_args={"data_name": "x", "data_value": {}},
            session_id=str(uuid.uuid4()),
            agent_type_id=str(uuid.uuid4()),
        )

        with patch.object(routing_settings.httpx, "AsyncClient", factory):
            await routing_settings._route_to_system_tool(body, _fake_request())

        assert _wire_headers(captured[0]) == {}

    def test_routing_module_forwards_never_signs(self):
        """CH is a receiver: tenant forwarding happens via the global
        internal_http egress hook only — never mint signatures."""
        import inspect

        source = inspect.getsource(routing_settings_module())
        assert "internal_httpx_client(" in source
        assert "build_tenant_signature_headers" not in source
        assert "sign_context_for_authenticated_session" not in source
        # The manual per-call merge is gone — the hook is the single mechanism.
        assert "forward_tenant_headers()" not in source


def routing_settings_module():
    from app.communication_hub.api.internal import tool_routing

    return tool_routing


# ── 2. MCP protocol-server bridge ────────────────────────────────────────────


class TestBridgeForwarding:
    @pytest.fixture
    def bridge_env(self, monkeypatch):
        monkeypatch.setenv("CONTROL_CENTER_URL", "http://cc-test:8000")
        from app.communication_hub.mcp.tool_registry_bridge import ToolRegistryBridge

        return ToolRegistryBridge()

    def _session(self):
        from app.communication_hub.mcp.session_manager import McpSession

        return McpSession(
            session_id="session-1",
            agent_role_id="role-1",
            agent_identity_id="identity-1",
            permissions=[],
            skills=[],
        )

    @pytest.mark.asyncio
    async def test_decision_execute_forwards_bound_signed_set(
        self, bound, bridge_env
    ):
        """_call_decision_tool: both the containment list call and the
        execute call carry the bound signed set (stubbed HTTP layer)."""
        captured: list[httpx.Request] = []

        def responder(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/decision/list"):
                return httpx.Response(
                    200, json={"tools": [{"name": "severity-decision"}]}
                )
            return httpx.Response(200, json={"result": {"outcome": "approve"}})

        factory = _client_factory(captured, responder)

        with patch(
            "app.communication_hub.mcp.tool_registry_bridge.httpx.AsyncClient",
            factory,
        ):
            await bridge_env._call_decision_tool(
                _fake_request(),
                self._session(),
                "decision____severity-decision",
                {"state": {"severity": "high"}},
            )

        assert len(captured) == 2
        assert captured[0].url.path.endswith("/decision/list")
        assert captured[1].url.path.endswith("/decision/execute")
        for request in captured:
            assert _wire_headers(request) == bound
        # CC-side acceptance through the real verifier.
        verify_tenant_signature_headers(_wire_headers(captured[1]))

    @pytest.mark.asyncio
    async def test_decision_execute_single_tenant_stays_headerless(
        self, bridge_env
    ):
        captured: list[httpx.Request] = []

        def responder(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/decision/list"):
                return httpx.Response(
                    200, json={"tools": [{"name": "severity-decision"}]}
                )
            return httpx.Response(200, json={"result": {}})

        factory = _client_factory(captured, responder)

        with patch(
            "app.communication_hub.mcp.tool_registry_bridge.httpx.AsyncClient",
            factory,
        ):
            await bridge_env._call_decision_tool(
                _fake_request(),
                self._session(),
                "decision____severity-decision",
                {"state": {}},
            )

        for request in captured:
            assert _wire_headers(request) == {}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "invoke,expected_suffix",
        [
            (
                lambda b, s: b._call_load_skills(_fake_request(), s, {}),
                "/api/v1/internal/system-tools/skills/resolve",
            ),
            (
                lambda b, s: b._call_system_tool(
                    _fake_request(), s, "system____save_data", {}
                ),
                "/api/v1/internal/system-tools/save-data",
            ),
            (
                lambda b, s: b._call_mcp_tool(
                    _fake_request(), s, "github____list_prs", {}
                ),
                "/api/v1/internal/mcp/proxy-tool",
            ),
        ],
    )
    async def test_every_bridge_cc_call_forwards_bound_signed_set(
        self, bound, bridge_env, invoke, expected_suffix
    ):
        captured: list[httpx.Request] = []
        factory = _client_factory(captured)

        with patch(
            "app.communication_hub.mcp.tool_registry_bridge.httpx.AsyncClient",
            factory,
        ):
            await invoke(bridge_env, self._session())

        assert captured[0].url.path == expected_suffix
        assert _wire_headers(captured[0]) == bound


# ── 3. AR → CH route binding (ControlPlaneMiddleware) ────────────────────────


class TestToolCallRouteBinding:
    @pytest.fixture
    def ch_client(self, monkeypatch):
        from app.communication_hub.middleware import control_plane
        from app.communication_hub.middleware.control_plane import (
            ControlPlaneMiddleware,
        )
        from app.core.tenant_context import get_current_tenant_context

        # /internal/tools/call is NOT cert-exempt — accept a synthetic
        # valid agent-runtime service cert for the binding test.
        monkeypatch.setattr(
            control_plane,
            "_load_ca_cert_pem",
            lambda: "FAKE-CA",
        )
        monkeypatch.setattr(
            control_plane,
            "validate_service_cert_locally",
            lambda **kw: SimpleNamespace(
                valid=True, service_name="agent-runtime", serial_number="42", reason=None
            ),
        )
        monkeypatch.setattr(
            control_plane._revocation_service,
            "check_remote",
            _async_false,
        )

        app = FastAPI()

        @app.post("/internal/tools/call")
        async def call(request: Request):
            ctx = get_current_tenant_context()
            return {
                "tenant_slug": ctx.slug if ctx else None,
                "forwarded": forward_tenant_headers(),
            }

        app.add_middleware(ControlPlaneMiddleware)
        with TestClient(app) as client:
            yield client

    def test_signed_headers_bound_on_tools_call_route(self, ch_client):
        """AR forwards its signed set; the middleware binds it for the
        handler (and every downstream CH → CC forward)."""
        response = ch_client.post(
            "/internal/tools/call",
            json={},
            headers={"X-Client-Certificate": "FAKE-CERT", **dict(SIGNED)},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["tenant_slug"] == "tool-routing-tenant"
        assert payload["forwarded"] == SIGNED

    def test_headerless_tools_call_passes_through(self, ch_client):
        response = ch_client.post(
            "/internal/tools/call",
            json={},
            headers={"X-Client-Certificate": "FAKE-CERT"},
        )
        assert response.status_code == 200
        assert response.json()["forwarded"] == {}

    def test_present_but_invalid_set_fails_closed(self, ch_client):
        """Verify-only semantics: a partial/tampered set is rejected, never
        silently treated as single-tenant traffic."""
        tampered = dict(SIGNED)
        tampered[TENANT_SIGNATURE_HEADERS[1]] = "other-tenant"
        response = ch_client.post(
            "/internal/tools/call",
            json={},
            headers={"X-Client-Certificate": "FAKE-CERT", **tampered},
        )
        assert response.status_code == 401


async def _async_false(**kwargs) -> bool:
    return False
