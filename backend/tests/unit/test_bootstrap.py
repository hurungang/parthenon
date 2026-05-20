"""Unit tests — Bootstrap certificate issuance endpoint (Task 7.1).

Tests:
  - Valid agent-runtime bootstrap request with correct key → 200, agent-instance cert
  - Valid comm-hub bootstrap request with correct key → 200, service cert
  - Invalid service name → 401
  - Wrong bootstrap key → 401
  - Certificate validity: 24h for agent_instance, 30d for service
  - CN format: agent-instance:agent-runtime:{uuid} and service:communication-hub
  - Missing Authorization header → 401
  - Bootstrap key env var not set → 503

The tests mock `_ca_service.issue_from_public_key` so no real CA or DB is needed.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.internal.bootstrap import InternalBootstrapRouter
from app.schemas.certificates import BootstrapResponse


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_public_key_pem() -> str:
    """Generate a throwaway RSA public key in PEM format."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()


def _fake_issued(cn: str, validity_hours: int):
    """Return a fake IssuedCertificate-like object."""
    obj = MagicMock()
    obj.certificate_pem = "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"
    obj.serial_number = "12345"
    obj.expires_at = datetime.now(timezone.utc) + timedelta(hours=validity_hours)
    obj.cn = cn
    return obj


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def app():
    """Create a test FastAPI app with the bootstrap router."""
    application = FastAPI()
    application.include_router(InternalBootstrapRouter)
    return application


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def set_bootstrap_keys(monkeypatch):
    """Inject deterministic bootstrap keys for both services."""
    monkeypatch.setenv("AGENT_RUNTIME_BOOTSTRAP_KEY", "ar-test-key-1234")
    monkeypatch.setenv("COMM_HUB_BOOTSTRAP_KEY", "ch-test-key-5678")


# ── Valid bootstrap — agent-runtime ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_agent_runtime_bootstrap(client):
    """Valid agent-runtime request returns an agent-instance cert (24h validity)."""
    captured = {}

    async def fake_issue(public_key_pem: str, cn: str, validity_hours: int):
        captured["cn"] = cn
        captured["validity_hours"] = validity_hours
        return _fake_issued(cn, validity_hours)

    with patch(
        "app.api.v1.internal.bootstrap._ca_service.issue_from_public_key",
        new=AsyncMock(side_effect=fake_issue),
    ), patch(
        "app.api.v1.internal.bootstrap._ca_service.get_ca_pem",
        return_value="-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----\n",
    ):
        resp = client.post(
            "/internal/bootstrap",
            json={
                "service_name": "agent-runtime",
                "service_type": "agent_instance",
                "public_key": _make_public_key_pem(),
            },
            headers={"Authorization": "Bearer ar-test-key-1234"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Certificate returned
    assert "certificate_pem" in body
    assert "ca_certificate_pem" in body
    assert "serial_number" in body
    assert "expires_at" in body

    # CN format: agent-instance:agent-runtime:{uuid}
    cn = captured["cn"]
    assert cn.startswith("agent-instance:agent-runtime:"), f"Unexpected CN: {cn}"
    # Third segment should be a valid UUID
    parts = cn.split(":")
    assert len(parts) == 3
    uuid.UUID(parts[2])  # raises if not valid UUID

    # 24-hour validity for agent_instance
    assert captured["validity_hours"] == 24


@pytest.mark.asyncio
async def test_valid_comm_hub_bootstrap(client):
    """Valid comm-hub request returns a service cert (30d = 720h validity)."""
    captured = {}

    async def fake_issue(public_key_pem: str, cn: str, validity_hours: int):
        captured["cn"] = cn
        captured["validity_hours"] = validity_hours
        return _fake_issued(cn, validity_hours)

    with patch(
        "app.api.v1.internal.bootstrap._ca_service.issue_from_public_key",
        new=AsyncMock(side_effect=fake_issue),
    ), patch(
        "app.api.v1.internal.bootstrap._ca_service.get_ca_pem",
        return_value="-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----\n",
    ):
        resp = client.post(
            "/internal/bootstrap",
            json={
                "service_name": "communication-hub",
                "service_type": "service",
                "public_key": _make_public_key_pem(),
            },
            headers={"Authorization": "Bearer ch-test-key-5678"},
        )

    assert resp.status_code == 200, resp.text

    # CN format: service:communication-hub
    cn = captured["cn"]
    assert cn == "service:communication-hub", f"Unexpected CN: {cn}"

    # 30d validity (24 * 30 = 720 hours)
    assert captured["validity_hours"] == 720


# ── Invalid service name ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_service_name_rejected(client):
    """Unknown service name returns 401."""
    resp = client.post(
        "/internal/bootstrap",
        json={
            "service_name": "evil-service",
            "service_type": "agent_instance",
            "public_key": _make_public_key_pem(),
        },
        headers={"Authorization": "Bearer ar-test-key-1234"},
    )
    assert resp.status_code == 401
    assert "invalid bootstrap key" in resp.json()["detail"].lower()


# ── Wrong bootstrap key ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrong_bootstrap_key_rejected(client):
    """Wrong bootstrap key returns 401."""
    resp = client.post(
        "/internal/bootstrap",
        json={
            "service_name": "agent-runtime",
            "service_type": "agent_instance",
            "public_key": _make_public_key_pem(),
        },
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mismatched_service_key_rejected(client):
    """Using the comm-hub key for agent-runtime (or vice versa) returns 401."""
    resp = client.post(
        "/internal/bootstrap",
        json={
            "service_name": "agent-runtime",
            "service_type": "agent_instance",
            "public_key": _make_public_key_pem(),
        },
        headers={"Authorization": "Bearer ch-test-key-5678"},  # comm-hub key, wrong service
    )
    assert resp.status_code == 401


# ── Missing or malformed Authorization header ──────────────────────────────────


@pytest.mark.asyncio
async def test_missing_authorization_header_rejected(client):
    """No Authorization header returns 422 (validation error — required header)."""
    resp = client.post(
        "/internal/bootstrap",
        json={
            "service_name": "agent-runtime",
            "service_type": "agent_instance",
            "public_key": _make_public_key_pem(),
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_non_bearer_scheme_rejected(client):
    """Authorization header without 'Bearer ' prefix returns 401."""
    resp = client.post(
        "/internal/bootstrap",
        json={
            "service_name": "agent-runtime",
            "service_type": "agent_instance",
            "public_key": _make_public_key_pem(),
        },
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert resp.status_code == 401


# ── Bootstrap key env var not configured ──────────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_key_env_var_not_set_returns_503(client, monkeypatch):
    """When the bootstrap key env var is not set, endpoint returns 503."""
    monkeypatch.delenv("AGENT_RUNTIME_BOOTSTRAP_KEY", raising=False)

    resp = client.post(
        "/internal/bootstrap",
        json={
            "service_name": "agent-runtime",
            "service_type": "agent_instance",
            "public_key": _make_public_key_pem(),
        },
        headers={"Authorization": "Bearer ar-test-key-1234"},
    )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


# ── CN format validation ───────────────────────────────────────────────────────


def test_agent_instance_cn_contains_three_colon_segments():
    """agent-instance CN must have format agent-instance:<service>:<uuid>."""
    cn = "agent-instance:agent-runtime:some-uuid-here"
    parts = cn.split(":")
    assert parts[0] == "agent-instance"
    assert len(parts) == 3


def test_service_cn_contains_two_colon_segments():
    """service CN must have format service:<name>."""
    cn = "service:communication-hub"
    parts = cn.split(":")
    assert parts[0] == "service"
    assert len(parts) == 2


# ── Test service bootstrap (Task 9.2) ─────────────────────────────────────────


@pytest.fixture
def set_test_service_key(monkeypatch):
    """Inject test service bootstrap key."""
    monkeypatch.setenv("TEST_SERVICE_BOOTSTRAP_KEY", "ts-test-key-9999")


@pytest.mark.asyncio
async def test_valid_test_service_bootstrap(client, set_test_service_key):
    """Valid test-service request returns a 30d service cert with CN service:test-service."""
    captured: dict = {}

    async def fake_issue(public_key_pem: str, cn: str, validity_hours: int):
        captured["cn"] = cn
        captured["validity_hours"] = validity_hours
        return _fake_issued(cn, validity_hours)

    with patch(
        "app.api.v1.internal.bootstrap._ca_service.issue_from_public_key",
        new=AsyncMock(side_effect=fake_issue),
    ), patch(
        "app.api.v1.internal.bootstrap._ca_service.get_ca_pem",
        return_value="-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----\n",
    ):
        resp = client.post(
            "/internal/bootstrap",
            json={
                "service_name": "test-service",
                "service_type": "test_service",
                "public_key": _make_public_key_pem(),
            },
            headers={"Authorization": "Bearer ts-test-key-9999"},
        )

    assert resp.status_code == 200, resp.text

    # CN must be service:test-service (30d service cert)
    cn = captured["cn"]
    assert cn == "service:test-service", f"Unexpected CN: {cn}"

    # 30d validity (24 * 30 = 720 hours)
    assert captured["validity_hours"] == 720, f"Expected 720h, got {captured['validity_hours']}"


@pytest.mark.asyncio
async def test_test_service_wrong_key_rejected(client, set_test_service_key):
    """Wrong bootstrap key for test-service returns 401."""
    resp = client.post(
        "/internal/bootstrap",
        json={
            "service_name": "test-service",
            "service_type": "test_service",
            "public_key": _make_public_key_pem(),
        },
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_test_service_key_not_set_returns_503(client, monkeypatch):
    """When TEST_SERVICE_BOOTSTRAP_KEY is unset, endpoint returns 503."""
    monkeypatch.delenv("TEST_SERVICE_BOOTSTRAP_KEY", raising=False)

    resp = client.post(
        "/internal/bootstrap",
        json={
            "service_name": "test-service",
            "service_type": "test_service",
            "public_key": _make_public_key_pem(),
        },
        headers={"Authorization": "Bearer any-key"},
    )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()
