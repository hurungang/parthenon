"""Agent Runtime signed tenant-header verification tests (Phase 9.4, CS-19/CS-20).

``ControlCenterCertificateMiddleware`` (AR) must:

- pass headerless traffic through unchanged (single-tenant)
- verify the full signed set from CC and bind the verified context
- reject tampered / stale / unsigned / partial sets with 401
- never gain the ability to SIGN (forwarding only — see
  test_tenant_signature.py::test_receiver_services_never_import_signing_helper
  and the forwarding unit tests here)
"""
from __future__ import annotations

import os
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.tenant_context import TenantContext, get_current_tenant_context  # noqa: E402
from app.core.tenant_signature import (  # noqa: E402
    TENANT_ID_HEADER,
    TENANT_SIGNATURE_HEADER,
    TENANT_SIGNATURE_HEADERS,
    TENANT_SLUG_HEADER,
    build_tenant_signature_headers,
    forward_tenant_headers,
    verify_request_tenant_context,
)

CTX = TenantContext(
    tenant_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
    slug="ar-tenant",
    name="AR Tenant",
)

_DUMMY_CA = "-----BEGIN CERTIFICATE-----\nZmFrZQ==\n-----END CERTIFICATE-----\n"


@pytest.fixture
def ar_client():
    """Minimal AR-shaped app with the cert-validation steps stubbed so the
    tests exercise exactly the tenant-header step (step 6 of middleware)."""
    from app.agent_runtime.middleware import ControlCenterCertificateMiddleware

    app = FastAPI()

    @app.get("/internal/echo")
    async def echo(request: Request):
        ctx = get_current_tenant_context()
        forwarded = forward_tenant_headers()
        return {
            "tenant_slug": ctx.slug if ctx else None,
            "state_bound": getattr(request.state, "tenant_context", None) is not None,
            "forwarded_headers": sorted(forwarded.keys()),
        }

    app.add_middleware(ControlCenterCertificateMiddleware)

    cert_result = SimpleNamespace(
        valid=True, reason="", service_name="communication-hub", serial_number="SERIAL"
    )
    with patch(
        "app.agent_runtime.middleware.validate_service_cert_locally",
        return_value=cert_result,
    ), patch(
        "app.agent_runtime.middleware._load_ca_cert_pem", return_value=_DUMMY_CA
    ), patch(
        "app.agent_runtime.middleware._get_control_center_url", return_value=""
    ):
        with TestClient(app) as client:
            yield client


def _headers(**overrides) -> dict[str, str]:
    headers = {"X-Client-Certificate": "FAKE", **build_tenant_signature_headers(CTX)}
    headers.update(overrides)
    return headers


class TestHeaderlessTraffic:
    def test_no_tenant_headers_pass_through_unchanged(self, ar_client):
        response = ar_client.get("/internal/echo", headers={"X-Client-Certificate": "FAKE"})
        assert response.status_code == 200
        body = response.json()
        assert body["tenant_slug"] is None
        assert body["state_bound"] is False
        assert body["forwarded_headers"] == []


class TestValidSignedContext:
    def test_valid_headers_bind_context_and_forward_originals(self, ar_client):
        response = ar_client.get("/internal/echo", headers=_headers())
        assert response.status_code == 200
        body = response.json()
        assert body["tenant_slug"] == "ar-tenant"
        assert body["state_bound"] is True
        # The ORIGINAL signed set is bound for downstream forwarding.
        assert sorted(body["forwarded_headers"]) == sorted(TENANT_SIGNATURE_HEADERS)


class TestInvalidHeaderSets:
    def test_tampered_slug_rejected(self, ar_client):
        response = ar_client.get(
            "/internal/echo", headers=_headers(**{TENANT_SLUG_HEADER: "widened-tenant"})
        )
        assert response.status_code == 401
        assert "Invalid tenant context" in response.json()["detail"]

    def test_tampered_signature_rejected(self, ar_client):
        response = ar_client.get(
            "/internal/echo", headers=_headers(**{TENANT_SIGNATURE_HEADER: "ab" * 32})
        )
        assert response.status_code == 401

    def test_stale_replayed_signature_rejected(self, ar_client):
        stale = build_tenant_signature_headers(CTX, timestamp=time.time() - 600)
        response = ar_client.get(
            "/internal/echo", headers={"X-Client-Certificate": "FAKE", **stale}
        )
        assert response.status_code == 401

    def test_unsigned_partial_set_rejected(self, ar_client):
        partial = {"X-Client-Certificate": "FAKE", TENANT_ID_HEADER: str(CTX.tenant_id)}
        response = ar_client.get("/internal/echo", headers=partial)
        assert response.status_code == 401

    def test_missing_signature_header_rejected(self, ar_client):
        headers = build_tenant_signature_headers(CTX)
        del headers[TENANT_SIGNATURE_HEADER]
        response = ar_client.get(
            "/internal/echo", headers={"X-Client-Certificate": "FAKE", **headers}
        )
        assert response.status_code == 401


class TestNoWidening:
    def test_receiver_cannot_fabricate_headers_for_another_tenant(self):
        """verify_request_tenant_context derives the context ONLY from
        values covered by the signature — slug/id cannot diverge."""
        headers = build_tenant_signature_headers(CTX)
        headers[TENANT_SLUG_HEADER] = "other-tenant"
        with pytest.raises(Exception):
            verify_request_tenant_context(headers)

    def test_forwarding_helper_never_signs_new_sets(self):
        """forward_tenant_headers only replays a bound set or {} — it can
        never mint a fresh valid set for a different tenant."""
        assert forward_tenant_headers() == {}
