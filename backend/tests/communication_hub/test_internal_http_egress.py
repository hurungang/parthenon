"""Egress enforcement for internal service-to-service HTTP (single mechanism).

Historically every internal egress call site in AR/CH hand-merged
``forward_tenant_headers()`` into its request headers (~29 sites across ~18
files) — four separate production bugs came from sites that forgot.  The
mechanism is now ONE global request event hook wired by
``app.core.internal_http.internal_httpx_client``.

This module pins three layers:

1. Unit — the hook merges the bound signed set, is a no-op when nothing is
   bound (single-tenant), and never clobbers pre-existing headers (cert /
   mTLS headers coexist with forwarded tenant headers).
2. Structural — NO direct ``httpx.AsyncClient(...)`` / ``httpx.post(...)``
   / ``httpx.get(...)`` client construction anywhere in
   ``app/communication_hub`` or ``app/agent_runtime`` outside the explicit
   allowlist.  Any new egress call site MUST use ``internal_httpx_client``.
3. Behavioral — a client built by the factory sends the bound signed set
   verbatim on the wire (via ``httpx.MockTransport``), and stays
   headerless when nothing is bound.
"""
from __future__ import annotations

import os
import pathlib
import re
import uuid
from types import SimpleNamespace

import httpx
import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.internal_http import (  # noqa: E402
    attach_forwarded_tenant_headers,
    internal_httpx_client,
)
from app.core.tenant_signature import (  # noqa: E402
    TENANT_SIGNATURE_HEADERS,
    bind_forwarded_tenant_headers,
    build_tenant_signature_headers,
    forward_tenant_headers,
    reset_forwarded_tenant_headers,
    verify_tenant_signature_headers,
)

CTX_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
BOUND = build_tenant_signature_headers(
    SimpleNamespace(tenant_id=CTX_ID, slug="egress-tenant")  # type: ignore[arg-type]
)


@pytest.fixture
def bound():
    token = bind_forwarded_tenant_headers(BOUND)
    yield BOUND
    reset_forwarded_tenant_headers(token)


# ── 1. Unit: the request event hook ──────────────────────────────────────────


class TestAttachForwardedTenantHeaders:
    def test_merges_bound_signed_set(self, bound):
        request = httpx.Request("POST", "http://cc.test/api/v1/internal/data/x")
        attach_forwarded_tenant_headers(request)
        wire = {h: request.headers[h] for h in TENANT_SIGNATURE_HEADERS}
        assert wire == bound
        # Verbatim: the CC-side verifier accepts the set unchanged.
        verify_tenant_signature_headers(wire)

    def test_noop_when_nothing_bound(self):
        assert forward_tenant_headers() == {}
        request = httpx.Request("GET", "http://cc.test/health")
        before = dict(request.headers)
        attach_forwarded_tenant_headers(request)
        assert dict(request.headers) == before
        for h in TENANT_SIGNATURE_HEADERS:
            assert h not in request.headers

    def test_does_not_clobber_existing_headers(self, bound):
        """Cert/mTLS and Authorization headers coexist — forwarding is
        additive (set-add), never destructive."""
        request = httpx.Request(
            "POST",
            "http://cc.test/api/v1/internal/data/x",
            headers={
                "X-Client-Certificate": "-----CERT-----",
                "Authorization": "Bearer user-jwt",
                "Content-Type": "application/json",
            },
        )
        attach_forwarded_tenant_headers(request)
        assert request.headers["X-Client-Certificate"] == "-----CERT-----"
        assert request.headers["Authorization"] == "Bearer user-jwt"
        assert request.headers["Content-Type"] == "application/json"
        assert {h: request.headers[h] for h in TENANT_SIGNATURE_HEADERS} == bound

    def test_receiver_pure_module_never_imports_signing(self):
        """CS-20: internal_http reads the verified set only — no signing
        capability may ever be imported into the egress path."""
        import inspect

        import app.core.internal_http as module

        source = inspect.getsource(module)
        for symbol in (
            "build_tenant_signature_headers",
            "sign_context_for_authenticated_session",
            "tenant_context_headers(",
        ):
            assert symbol not in source, (
                f"internal_http must stay receiver-pure ({symbol})"
            )


class TestInternalHttpxClientFactory:
    def test_wires_hook_and_passes_kwargs_through(self):
        seen: list[httpx.Request] = []
        transport = httpx.MockTransport(
            lambda request: (seen.append(request), httpx.Response(200, json={}))[1]
        )
        token = bind_forwarded_tenant_headers(BOUND)
        try:
            client = internal_httpx_client(
                transport=transport,
                base_url="http://cc.test",
                timeout=5.0,
            )
            import asyncio

            asyncio.run(client.get("/api/v1/internal/data/ping"))
        finally:
            reset_forwarded_tenant_headers(token)
        assert {h: seen[0].headers[h] for h in TENANT_SIGNATURE_HEADERS} == BOUND
        assert str(seen[0].url).startswith("http://cc.test/api/v1")

    def test_caller_request_hooks_still_run(self):
        order: list[str] = []

        async def caller_hook(request: httpx.Request) -> None:
            order.append("caller")

        client = internal_httpx_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
            event_hooks={"request": [caller_hook]},
        )
        import asyncio

        asyncio.run(client.get("http://x.test/"))
        assert order == ["caller"]


# ── 2. Structural: no direct client construction outside the allowlist ───────

#: Files allowed to construct httpx clients directly (documented exemptions).
EGRESS_ALLOWLIST = {
    # Pre-tenancy certificate bootstrap/renewal — headerless by design
    # (no tenant context exists during bootstrap).  See the exemption
    # comments in both files.
    "app/communication_hub/certificate_manager.py",
    "app/agent_runtime/certificate_manager.py",
    # Startup health probes — no tenant exists at startup.
    "app/communication_hub/main.py",
    "app/agent_runtime/main.py",
}

_PATTERN = re.compile(r"httpx\.AsyncClient\(|httpx\.post\(|httpx\.get\(")


class TestEgressStructuralScan:
    @pytest.mark.parametrize(
        "tree", ["app/communication_hub", "app/agent_runtime"]
    )
    def test_no_direct_httpx_client_construction(self, tree):
        backend = pathlib.Path(__file__).resolve().parents[2]
        violations: list[str] = []
        for py in sorted((backend / tree).rglob("*.py")):
            rel = str(py.relative_to(backend)).replace("\\", "/")
            if rel in EGRESS_ALLOWLIST:
                continue
            source = py.read_text(encoding="utf-8")
            match = _PATTERN.search(source)
            if match:
                violations.append(f"{rel}: {match.group(0)}")
        assert violations == [], (
            "Internal egress must use internal_httpx_client (app/core/"
            "internal_http.py) so tenant headers are forwarded by the ONE "
            f"global hook; direct construction found in: {violations}. "
            f"Allowlist: {sorted(EGRESS_ALLOWLIST)}"
        )


# ── 3. Behavioral: the factory's client on the wire ──────────────────────────


class TestFactoryWireBehavior:
    @staticmethod
    def _client(captured: list[httpx.Request], responder=None) -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            if responder is not None:
                return responder(request)
            return httpx.Response(200, json={})

        return internal_httpx_client(transport=httpx.MockTransport(handler))

    @pytest.mark.asyncio
    async def test_bound_set_sent_verbatim(self, bound):
        import asyncio

        captured: list[httpx.Request] = []
        client = self._client(captured)
        await client.post("http://cc.test/api/v1/internal/data/x", json={})
        wire = {h: captured[0].headers[h] for h in TENANT_SIGNATURE_HEADERS}
        assert wire == bound, "factory client must forward the signed set verbatim"
        verify_tenant_signature_headers(wire)

    @pytest.mark.asyncio
    async def test_headerless_when_nothing_bound(self):
        import asyncio

        captured: list[httpx.Request] = []
        client = self._client(captured)
        await client.get("http://cc.test/api/v1/internal/data/x")
        for h in TENANT_SIGNATURE_HEADERS:
            assert h not in captured[0].headers

    @pytest.mark.asyncio
    async def test_per_call_headers_coexist_with_forwarded_set(self, bound):
        """Existing per-call headers (e.g. Authorization) survive the hook."""
        import asyncio

        captured: list[httpx.Request] = []
        client = self._client(captured)
        await client.post(
            "http://cc.test/api/v1/internal/data/x",
            json={},
            headers={"Authorization": "Bearer jwt"},
        )
        assert captured[0].headers["Authorization"] == "Bearer jwt"
        assert {h: captured[0].headers[h] for h in TENANT_SIGNATURE_HEADERS} == bound

    @pytest.mark.asyncio
    async def test_data_client_sends_bound_set_through_factory(
        self, bound, monkeypatch
    ):
        """End-to-end through a migrated client: AR data client's GET
        carries the bound signed set — no per-call merging involved."""
        from app.agent_runtime.data_client import ControlCenterDataClient

        captured: list[httpx.Request] = []

        class _CertManager:
            def mtls_client_kwargs(self) -> dict:
                return {"headers": {"X-Client-Certificate": "-----CERT-----"}}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json={})

        import app.agent_runtime.data_client as dc

        real_factory = dc.internal_httpx_client
        monkeypatch.setattr(
            dc,
            "internal_httpx_client",
            lambda **kw: real_factory(transport=httpx.MockTransport(handler), **kw),
        )

        client = ControlCenterDataClient(
            cert_manager=_CertManager(), control_center_url="http://cc.test"
        )
        await client.get_session(uuid.uuid4())

        request = captured[0]
        # Cert header (transport auth) and tenant headers coexist.
        assert request.headers["X-Client-Certificate"] == "-----CERT-----"
        assert {h: request.headers[h] for h in TENANT_SIGNATURE_HEADERS} == bound
