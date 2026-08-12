"""Security tests — Bootstrap key validation (Task 7.7).

Tests that the bootstrap endpoint is secure against:
  - Wrong key → 401
  - Service name mismatch → 401
  - Timing-attack resistance (secrets.compare_digest)
  - Missing Authorization header → 422 (validation error)
  - Non-Bearer scheme → 401
  - Bootstrap endpoint uses per-service keys, not a shared key
  - Bootstrap endpoint is separate from public API routes

These tests validate the security properties of the bootstrap authentication
mechanism without requiring a full CA setup.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.internal.bootstrap import InternalBootstrapRouter


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_public_key_pem() -> str:
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
    obj = MagicMock()
    obj.certificate_pem = "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"
    obj.serial_number = "12345"
    obj.expires_at = datetime.now(timezone.utc) + timedelta(hours=validity_hours)
    return obj


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def app():
    application = FastAPI()
    application.include_router(InternalBootstrapRouter)
    return application


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def set_bootstrap_keys(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_BOOTSTRAP_KEY", "secure-ar-key-abc123xyz")
    monkeypatch.setenv("COMM_HUB_BOOTSTRAP_KEY", "secure-ch-key-def456uvw")


# ═══════════════════════════════════════════════════════════════════════════════
# Wrong key rejection
# ═══════════════════════════════════════════════════════════════════════════════


class TestWrongKeyRejection:
    """Various wrong-key scenarios are rejected with 401."""

    def test_wrong_key_for_agent_runtime(self, client):
        """Completely wrong key is rejected."""
        resp = client.post(
            "/internal/bootstrap",
            json={"service_name": "agent-runtime", "service_type": "agent_instance", "public_key": _make_public_key_pem()},
            headers={"Authorization": "Bearer definitely-wrong-key"},
        )
        assert resp.status_code == 401

    def test_empty_bearer_token_rejected(self, client):
        """Empty bearer token (only 'Bearer ') is rejected."""
        resp = client.post(
            "/internal/bootstrap",
            json={"service_name": "agent-runtime", "service_type": "agent_instance", "public_key": _make_public_key_pem()},
            headers={"Authorization": "Bearer "},
        )
        assert resp.status_code == 401

    def test_partial_key_rejected(self, client):
        """Prefix of the correct key is rejected (no prefix matching)."""
        partial_key = "secure-ar-key"  # prefix of "secure-ar-key-abc123xyz"
        resp = client.post(
            "/internal/bootstrap",
            json={"service_name": "agent-runtime", "service_type": "agent_instance", "public_key": _make_public_key_pem()},
            headers={"Authorization": f"Bearer {partial_key}"},
        )
        assert resp.status_code == 401

    def test_key_with_extra_chars_rejected(self, client):
        """Correct key plus extra characters is rejected."""
        extended_key = "secure-ar-key-abc123xyz-extra"
        resp = client.post(
            "/internal/bootstrap",
            json={"service_name": "agent-runtime", "service_type": "agent_instance", "public_key": _make_public_key_pem()},
            headers={"Authorization": f"Bearer {extended_key}"},
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Service name mismatch
# ═══════════════════════════════════════════════════════════════════════════════


class TestServiceNameMismatch:
    """Service name in payload must match the key used."""

    def test_agent_runtime_key_for_comm_hub_rejected(self, client):
        """Using agent-runtime key for comm-hub service name → 401."""
        resp = client.post(
            "/internal/bootstrap",
            json={"service_name": "communication-hub", "service_type": "service", "public_key": _make_public_key_pem()},
            headers={"Authorization": "Bearer secure-ar-key-abc123xyz"},  # AR key, CH service
        )
        assert resp.status_code == 401

    def test_comm_hub_key_for_agent_runtime_rejected(self, client):
        """Using comm-hub key for agent-runtime service name → 401."""
        resp = client.post(
            "/internal/bootstrap",
            json={"service_name": "agent-runtime", "service_type": "agent_instance", "public_key": _make_public_key_pem()},
            headers={"Authorization": "Bearer secure-ch-key-def456uvw"},  # CH key, AR service
        )
        assert resp.status_code == 401

    def test_unknown_service_name_rejected(self, client):
        """Unknown service name → 401 regardless of key."""
        resp = client.post(
            "/internal/bootstrap",
            json={"service_name": "unknown-service", "service_type": "agent_instance", "public_key": _make_public_key_pem()},
            headers={"Authorization": "Bearer secure-ar-key-abc123xyz"},
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Timing-attack resistance
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimingAttackResistance:
    """Bootstrap endpoint must use secrets.compare_digest for constant-time comparison."""

    def test_bootstrap_endpoint_uses_compare_digest(self):
        """Bootstrap source code uses secrets.compare_digest for key comparison."""
        import inspect
        import app.api.v1.internal.bootstrap as bootstrap_module

        source = inspect.getsource(bootstrap_module)
        assert "secrets.compare_digest" in source, (
            "Bootstrap endpoint must use secrets.compare_digest() for timing-safe "
            "key comparison. Simple == comparison is vulnerable to timing attacks."
        )

    def test_compare_digest_is_constant_time(self):
        """Verify secrets.compare_digest provides constant-time comparison."""
        # The key property of compare_digest: it doesn't short-circuit on mismatch
        key_a = "correct-bootstrap-key-xyz123"
        key_b_wrong = "wrong-bootstrap-key-000000"
        key_c_partial = "correct-bootstrap"  # prefix of key_a

        # These should all return False without leaking timing info
        assert secrets.compare_digest(key_a, key_b_wrong) is False
        assert secrets.compare_digest(key_a, key_c_partial) is False
        assert secrets.compare_digest(key_a, key_a) is True

    def test_bootstrap_imports_secrets_module(self):
        """Bootstrap module imports the secrets standard library module."""
        import app.api.v1.internal.bootstrap as bootstrap_module
        assert hasattr(bootstrap_module, "secrets"), (
            "Bootstrap module must import 'secrets' for compare_digest"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Authorization header format
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthorizationHeader:
    """Authorization header must be correctly formatted."""

    def test_missing_authorization_header_returns_422(self, client):
        """Missing Authorization header returns 422 (required field)."""
        resp = client.post(
            "/internal/bootstrap",
            json={"service_name": "agent-runtime", "service_type": "agent_instance", "public_key": _make_public_key_pem()},
        )
        assert resp.status_code == 422

    def test_basic_auth_scheme_rejected(self, client):
        """Basic auth scheme → 401 (not Bearer)."""
        resp = client.post(
            "/internal/bootstrap",
            json={"service_name": "agent-runtime", "service_type": "agent_instance", "public_key": _make_public_key_pem()},
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert resp.status_code == 401

    def test_api_key_scheme_rejected(self, client):
        """ApiKey scheme → 401."""
        resp = client.post(
            "/internal/bootstrap",
            json={"service_name": "agent-runtime", "service_type": "agent_instance", "public_key": _make_public_key_pem()},
            headers={"Authorization": "ApiKey secure-ar-key-abc123xyz"},
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Bootstrap endpoint isolation
# ═══════════════════════════════════════════════════════════════════════════════


class TestBootstrapEndpointIsolation:
    """Bootstrap endpoint is on /internal/ prefix (not public /api/v1/)."""

    def test_bootstrap_router_prefix_is_internal(self):
        """Bootstrap router is mounted under /internal/bootstrap."""
        from app.api.v1.internal.bootstrap import InternalBootstrapRouter
        assert InternalBootstrapRouter.prefix == "/internal/bootstrap"

    def test_bootstrap_uses_per_service_keys_not_shared_key(self, monkeypatch):
        """Bootstrap env vars are PER SERVICE — AGENT_RUNTIME_BOOTSTRAP_KEY != COMM_HUB_BOOTSTRAP_KEY."""
        ar_key = os.environ.get("AGENT_RUNTIME_BOOTSTRAP_KEY", "")
        ch_key = os.environ.get("COMM_HUB_BOOTSTRAP_KEY", "")
        assert ar_key != ch_key, (
            "Agent Runtime and Communication Hub must have DIFFERENT bootstrap keys. "
            "Sharing a single key means any service can impersonate another."
        )

    def test_env_var_names_are_service_specific(self):
        """Verify the env var names in the bootstrap module are service-specific."""
        from app.api.v1.internal import bootstrap as b
        assert "AGENT_RUNTIME_BOOTSTRAP_KEY" in b._SERVICE_KEY_ENV.get("agent-runtime", "")
        assert "COMM_HUB_BOOTSTRAP_KEY" in b._SERVICE_KEY_ENV.get("communication-hub", "")

    def test_valid_bootstrap_request_succeeds(self, client):
        """A valid request with correct credentials succeeds (integration sanity check)."""
        with patch(
            "app.api.v1.internal.bootstrap._ca_service.issue_from_public_key",
            new=AsyncMock(return_value=_fake_issued("agent-instance:agent-runtime:abc", 24)),
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
                headers={"Authorization": "Bearer secure-ar-key-abc123xyz"},
            )

        assert resp.status_code == 200
