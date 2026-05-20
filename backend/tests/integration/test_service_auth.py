"""Integration tests — Test Service authentication (Tasks 9.5 and 9.6).

**Task 9.5**: Bootstrap flow
  - Test service bootstraps from a live CC; issued cert has 30d validity.
  - Cert CN is ``service:test-service``.
  - Wrong bootstrap key returns 401.

**Task 9.6**: Authenticated data API calls
  - ``cc_client`` (test service cert) reaches all CC internal data API endpoints.
  - Auth is validated by checking that the response code is NOT 401/403.
  - No mocking of any HTTP calls.

These tests require live Control Center, Agent Runtime, and Communication Hub
services.  They are skipped automatically (via the ``test_cert_manager`` fixture)
when CC is unreachable or ``TEST_SERVICE_BOOTSTRAP_KEY`` is not set.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio

from tests.fixtures.test_service_certificate import (
    TestServiceBootstrapError,
    TestServiceCertificateManager,
)

pytest_plugins = ["tests.fixtures.authenticated_clients"]

_DEFAULT_CC_URL = "http://localhost:8000"


# ═══════════════════════════════════════════════════════════════════════════════
# Task 9.5 — Test service bootstrap flow
# ═══════════════════════════════════════════════════════════════════════════════


class TestBootstrapFlow:
    """Validates that the test service can bootstrap from a live Control Center."""

    @pytest.mark.asyncio
    async def test_bootstrap_issues_30d_cert(self):
        """Bootstrap returns a 30-day service cert with CN service:test-service."""
        from cryptography.x509.oid import NameOID

        manager = TestServiceCertificateManager()
        try:
            await manager.bootstrap()
        except TestServiceBootstrapError as exc:
            pytest.skip(f"CC unreachable or bootstrap key not set: {exc}")
        finally:
            manager.cleanup()

        assert manager.is_bootstrapped
        assert manager.cert_pem is not None
        assert manager.ca_cert_pem is not None

        # Verify CN
        cert = manager.get_parsed_cert()
        attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        assert attrs, "Certificate has no CN"
        cn = attrs[0].value
        assert cn == "service:test-service", f"Unexpected CN: {cn}"

        # Verify ~30d validity (allow ±1 day for clock drift)
        validity_seconds = (
            cert.not_valid_after_utc - cert.not_valid_before_utc
        ).total_seconds()
        days = validity_seconds / 86400
        assert 29 <= days <= 31, f"Expected ~30d validity, got {days:.1f}d"

        # Cert must not already be expired
        assert cert.not_valid_after_utc > datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_wrong_bootstrap_key_returns_401(self):
        """Wrong bootstrap key is rejected by CC with HTTP 401."""
        cc_url = os.environ.get("CONTROL_CENTER_URL", _DEFAULT_CC_URL)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{cc_url}/health")
        except httpx.RequestError as exc:
            pytest.skip(f"CC unreachable: {exc}")

        if resp.status_code != 200:
            pytest.skip(f"CC not healthy (HTTP {resp.status_code})")

        # Now test with wrong key — manager is not expected to raise until bootstrap()
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048, backend=default_backend()
        )
        public_key_pem = (
            private_key.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{cc_url}/api/v1/internal/bootstrap",
                json={
                    "service_name": "test-service",
                    "service_type": "test_service",
                    "public_key": public_key_pem,
                },
                headers={"Authorization": "Bearer definitely-wrong-key"},
            )

        assert response.status_code == 401, (
            f"Expected 401 for wrong key, got {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_bootstrap_idempotent(self):
        """Bootstrapping twice returns two valid certs (each call generates new key pair)."""
        manager1 = TestServiceCertificateManager()
        manager2 = TestServiceCertificateManager()
        try:
            await manager1.bootstrap()
            await manager2.bootstrap()
        except TestServiceBootstrapError as exc:
            pytest.skip(f"CC unreachable or bootstrap key not set: {exc}")
        finally:
            manager1.cleanup()
            manager2.cleanup()

        # Both should have valid certs
        assert manager1.serial_number is not None
        assert manager2.serial_number is not None
        # Serials should differ (each bootstrap generates a new cert)
        assert manager1.serial_number != manager2.serial_number


# ═══════════════════════════════════════════════════════════════════════════════
# Task 9.6 — Authenticated data API calls via cc_client
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthenticatedDataAPICalls:
    """Validates that the test service cert is accepted at CC's internal data API endpoints.

    The test service cert has CN ``service:test-service``, which satisfies
    ``require_service_certificate`` (blocks agent-instance certs, accepts any
    service cert).  A 404 response (not 401/403) proves auth succeeded but the
    resource was not found — expected since we use non-existent UUIDs.
    """

    _FAKE_UUID = "00000000-0000-0000-0000-000000000001"

    @pytest.mark.asyncio
    async def test_cc_health_accessible(self, cc_client):
        """Control Center health endpoint is reachable with or without cert."""
        response = await cc_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("service") == "control-center"

    @pytest.mark.asyncio
    async def test_session_data_api_requires_valid_service_cert(self, cc_client):
        """GET /internal/data/sessions/{id} returns 404 (not 401/403) for test service cert.

        A 404 proves the cert was accepted and the request reached the handler.
        A 401 or 403 would indicate auth failure.
        """
        response = await cc_client.get(
            f"/api/v1/internal/data/sessions/{self._FAKE_UUID}"
        )
        assert response.status_code == 404, (
            f"Expected 404 (not found), got {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_claim_queued_sessions_api(self, cc_client):
        """POST /internal/data/sessions/claim-queued returns 200 with session_ids list.

        Empty list is expected when no sessions are queued; validates the full
        auth+data path without requiring pre-existing test data.
        """
        response = await cc_client.post(
            "/api/v1/internal/data/sessions/claim-queued",
            json={"limit": 4},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:200]}"
        )
        data = response.json()
        assert "session_ids" in data
        assert isinstance(data["session_ids"], list)

    @pytest.mark.asyncio
    async def test_agent_type_plan_api(self, cc_client):
        """GET /internal/data/agent-types/{id}/plan returns 404 for nonexistent agent type.

        404 proves auth succeeded; 401/403 indicates a cert validation problem.
        """
        response = await cc_client.get(
            f"/api/v1/internal/data/agent-types/{self._FAKE_UUID}/plan"
        )
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_agent_type_context_api(self, cc_client):
        """GET /internal/data/agent-types/{id}/context returns 404 for nonexistent type."""
        response = await cc_client.get(
            f"/api/v1/internal/data/agent-types/{self._FAKE_UUID}/context"
        )
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_model_config_api(self, cc_client):
        """GET /internal/data/model-configs/{id} returns 404 for nonexistent config."""
        response = await cc_client.get(
            f"/api/v1/internal/data/model-configs/{self._FAKE_UUID}"
        )
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_user_permissions_api(self, cc_client):
        """GET /internal/data/users/{id}/permissions returns 404 for nonexistent user."""
        response = await cc_client.get(
            f"/api/v1/internal/data/users/{self._FAKE_UUID}/permissions"
        )
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_no_cert_returns_401(self):
        """Calling a CC internal endpoint without a certificate returns 401."""
        cc_url = os.environ.get("CONTROL_CENTER_URL", _DEFAULT_CC_URL)
        fake_id = self._FAKE_UUID
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{cc_url}/api/v1/internal/data/sessions/{fake_id}"
                )
        except httpx.RequestError as exc:
            pytest.skip(f"CC unreachable: {exc}")

        assert response.status_code == 401, (
            f"Expected 401 without cert, got {response.status_code}"
        )
