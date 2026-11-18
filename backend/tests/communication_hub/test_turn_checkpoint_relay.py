"""Communication Hub — AR-facing checkpoint / resume-index relay (Phase 4.1).

Agent Runtime reaches the Control Center–owned paused-turn state only through
this relay.  The tests pin the transport contract:

* the checkpoint payload is relayed **byte-for-byte** and the upstream status
  and body are replayed unchanged;
* the signed tenant header set is **forwarded** on the wire by the single
  shared egress hook (Communication Hub never mints or merges headers);
* an upstream 4xx/5xx is surfaced as a typed relay error — never a silent
  empty payload (and 404 keeps meaning "no record" for Agent Runtime);
* the configured byte-size guard rejects an oversized payload before it ever
  reaches Control Center.
"""
from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.communication_hub.api.internal.turn_checkpoint import router  # noqa: E402
from app.communication_hub.data_client import ControlCenterDataClient  # noqa: E402
from app.core.tenant_context import TenantContext  # noqa: E402
from app.core.tenant_signature import (  # noqa: E402
    TENANT_SIGNATURE_HEADERS,
    bind_forwarded_tenant_headers,
    build_tenant_signature_headers,
    reset_forwarded_tenant_headers,
    verify_tenant_signature_headers,
)

CTX = TenantContext(
    tenant_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
    slug="relay-tenant",
    name="Relay Tenant",
)
CONV_ID = uuid.uuid4()


class _Wire:
    """Captured upstream requests from the httpx MockTransport."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.bodies: list[bytes] = []


def _app(wire: _Wire, responder) -> FastAPI:
    """CH app whose data client talks to a fake Control Center."""

    def handler(request: httpx.Request) -> httpx.Response:
        wire.requests.append(request)
        wire.bodies.append(request.content)
        return responder(request)

    transport = httpx.MockTransport(handler)
    cert_manager = SimpleNamespace(
        mtls_client_kwargs=lambda: {"transport": transport},
    )
    app = FastAPI()
    app.include_router(router)
    app.state.data_client = ControlCenterDataClient(
        cert_manager=cert_manager, control_center_url="http://cc.test"
    )
    return app


@pytest.fixture(autouse=True)
def _clean_bound_headers():
    from app.core.tenant_signature import forward_tenant_headers

    token = bind_forwarded_tenant_headers(forward_tenant_headers())
    yield
    reset_forwarded_tenant_headers(token)


def test_checkpoint_payload_is_relayed_byte_for_byte() -> None:
    """The opaque payload leaves CH exactly as AR produced it."""
    upstream_body = (
        b'{"resume_id": "r-1", "payload_kind": "agent_turn_state", '
        b'"schema_version": 1, "payload_bytes": 9}'
    )
    wire = _Wire()

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=upstream_body, headers={"content-type": "application/json"}
        )

    app = _app(wire, responder)
    payload_text = '{"payload": {"weird": "  spacing\\n kept  ", "n": 1.5}}'
    with TestClient(app) as client:
        response = client.put(
            f"/internal/checkpoint/{CONV_ID}",
            content=payload_text.encode(),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 200
    # Byte-for-byte in BOTH directions.
    assert wire.bodies == [payload_text.encode()]
    assert response.content == upstream_body
    # And the relay targeted Control Center's resume/checkpoint route.
    assert wire.requests[0].method == "PUT"
    assert wire.requests[0].url.path == (
        f"/api/v1/internal/data/conversations/{CONV_ID}/resume/checkpoint"
    )


def test_tenant_header_set_is_forwarded_never_minted() -> None:
    """The verified CC-signed set travels verbatim; CH adds nothing of its own."""
    signed = build_tenant_signature_headers(CTX)
    token = bind_forwarded_tenant_headers(signed)
    wire = _Wire()

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"resume_id": str(uuid.uuid4()), "state": "waiting_for_human"})

    app = _app(wire, responder)
    try:
        with TestClient(app) as client:
            response = client.get(f"/internal/turn-resume/{CONV_ID}")
    finally:
        reset_forwarded_tenant_headers(token)

    assert response.status_code == 200
    forwarded = {
        name: wire.requests[0].headers[name]
        for name in TENANT_SIGNATURE_HEADERS
        if name in wire.requests[0].headers
    }
    assert forwarded == signed
    verified = verify_tenant_signature_headers(forwarded)  # Control Center's check
    assert str(verified.tenant_id) == str(CTX.tenant_id)
    assert verified.slug == CTX.slug


def test_claim_and_complete_routes_match_ar_transport_paths() -> None:
    """Every relay path is the CC twin of the AR transport's CH path."""
    seen: list[tuple[str, str]] = []

    def responder(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"status": "acquired", "resume": None})

    wire = _Wire()
    app = _app(wire, responder)
    with TestClient(app) as client:
        client.post(
            f"/internal/turn-resume/{CONV_ID}/claim",
            json={"instance_id": "ar-1", "lease_seconds": 45},
        )
        client.post(f"/internal/turn-resume/{CONV_ID}/release", json={})
        client.post(f"/internal/turn-resume/{CONV_ID}/complete", json={"outcome": "denied"})
        client.put(f"/internal/turn-resume/{CONV_ID}", json={})
        client.get(f"/internal/checkpoint/{CONV_ID}")

    base = f"/api/v1/internal/data/conversations/{CONV_ID}/resume"
    assert seen == [
        ("POST", f"{base}/claim"),
        ("POST", f"{base}/release"),
        ("POST", f"{base}/complete"),
        ("PUT", base),
        ("GET", f"{base}/checkpoint"),
    ]
    # Claim bodies are relayed unchanged too.
    assert json.loads(wire.bodies[0]) == {"instance_id": "ar-1", "lease_seconds": 45}


def test_upstream_4xx_is_a_typed_relay_error_not_an_empty_payload() -> None:
    """A CC rejection keeps its status and detail (AR maps 404/409 itself)."""

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "Resume already terminal"})

    app = _app(_Wire(), responder)
    with TestClient(app) as client:
        response = client.post(
            f"/internal/turn-resume/{CONV_ID}/complete", json={"outcome": "denied"}
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "relay_error"
    assert detail["upstream_status"] == 409
    assert "terminal" in detail["detail"]
    assert response.content  # never an empty payload


def test_upstream_404_is_relayed_so_ar_sees_no_record() -> None:
    """404 must survive the relay: AR maps it to 'no live resume record'."""

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"detail": "No live resume record for conversation"}
        )

    app = _app(_Wire(), responder)
    with TestClient(app) as client:
        response = client.get(f"/internal/checkpoint/{CONV_ID}")

    assert response.status_code == 404
    assert response.json()["detail"]["upstream_status"] == 404


def test_upstream_5xx_maps_to_relay_unavailable() -> None:
    """A broken Control Center is 'relay unavailable', never a silent success."""

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    app = _app(_Wire(), responder)
    with TestClient(app) as client:
        response = client.put(f"/internal/checkpoint/{CONV_ID}", content=b"{}")

    assert response.status_code == 503
    assert response.json()["detail"]["upstream_status"] == 500


def test_unreachable_control_center_maps_to_503() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    app = _app(_Wire(), responder)
    with TestClient(app) as client:
        response = client.get(f"/internal/turn-resume/{CONV_ID}")

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "relay_unavailable"


def test_oversized_payload_is_rejected_by_the_size_guard(monkeypatch) -> None:
    """The guard rejects before relaying — CH never forwards a huge payload."""
    wire = _Wire()

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    app = _app(wire, responder)
    from app.core.config import get_settings

    monkeypatch.setattr(
        get_settings(), "conversation_turn_checkpoint_max_bytes", 32, raising=False
    )
    with TestClient(app) as client:
        response = client.put(
            f"/internal/checkpoint/{CONV_ID}", content=b"x" * 64
        )

    assert response.status_code == 413
    detail = response.json()["detail"]
    assert detail["error"] == "checkpoint_payload_too_large"
    assert detail["guard_bytes"] == 32
    assert wire.requests == []  # rejected locally


def test_checkpoint_load_null_is_relayed_unchanged() -> None:
    """CC's explicit ``null`` (absent/consumed payload) reaches AR unchanged."""

    def responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"null")

    app = _app(_Wire(), responder)
    with TestClient(app) as client:
        response = client.get(f"/internal/checkpoint/{CONV_ID}")

    assert response.status_code == 200
    assert response.content == b"null"
