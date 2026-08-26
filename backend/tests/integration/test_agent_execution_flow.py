"""Integration tests — Agent execution flow (UI → CC → AR → CC → CH).

Reproduces the user-reported issue where agent execution triggered from the UI
fails to reach Agent Runtime because Control Center's ``AgentRuntimeClient``
does not send the ``X-Client-Certificate`` header that AR's middleware requires.

**Bug summary:**
  - ``AgentRuntimeClient._make_client()`` builds either an SSL mTLS client or a
    plain-HTTP client.  Neither path adds the ``X-Client-Certificate`` header.
  - ``ControlCenterCertificateMiddleware`` (AR) reads ONLY the
    ``X-Client-Certificate`` header.  It never inspects the TLS handshake cert.
  - Result: AR rejects every CC trigger with 401, falls back to 30-second
    polling, and the session appears stuck in "queued" from the UI's perspective.
  - Compare with ``comm_hub_client.py`` which correctly sends the cert as a
    header for HTTP and uses ``cert=(path, key)`` for HTTPS.

**What these tests prove (all expected to FAIL currently):**
  1. AR enforces the ``X-Client-Certificate`` header — requests without it get 401.
  2. AR rejects certificates whose CN is not ``service:control-center`` — even a
     valid test-service cert is rejected.
  3. ``AgentRuntimeClient._make_client()`` does NOT send ``X-Client-Certificate`` —
     confirming the bug in CC's outbound client.
  4. A live CC → AR trigger (using ``AgentRuntimeClient`` as CC does) returns 401
     (not 200), proving the execution trigger is broken end-to-end.

Tests that are expected to PASS (verifying pre-conditions and correct rejections):
  - AR health endpoint is accessible without cert (exemption list).
  - AR correctly bootstrapped its own cert from CC.
  - Test-service cert is correctly rejected by AR (security boundary).

All HTTP calls are real requests to live services.  Tests skip automatically
when a required service is unreachable (via ``test_cert_manager`` fixture).

Services required:
  - Control Center  (CONTROL_CENTER_URL, default http://localhost:8000)
  - Agent Runtime   (AGENT_RUNTIME_URL,   default http://localhost:8001)
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest

pytest_plugins = ["tests.fixtures.authenticated_clients"]

_DEFAULT_CC_URL = "http://localhost:8000"
_DEFAULT_AR_URL = "http://localhost:8001"


# ── Helpers ────────────────────────────────────────────────────────────────────


def _cc_url() -> str:
    return os.environ.get("CONTROL_CENTER_URL", _DEFAULT_CC_URL).rstrip("/")


def _ar_url() -> str:
    return os.environ.get("AGENT_RUNTIME_URL", _DEFAULT_AR_URL).rstrip("/")


async def _skip_if_unreachable(url: str, label: str) -> None:
    """Skip current test if the service at *url* is not reachable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{url}/health")
        if r.status_code != 200:
            pytest.skip(f"{label} not healthy (HTTP {r.status_code})")
    except httpx.RequestError as exc:
        pytest.skip(f"{label} unreachable: {exc}")


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-condition: Service health and bootstrapping
# ═══════════════════════════════════════════════════════════════════════════════


class TestServicePreConditions:
    """Verify services are running and AR bootstrapped its cert from CC.

    These tests must PASS before the execution-flow tests are meaningful.
    """

    @pytest.mark.asyncio
    async def test_control_center_healthy(self):
        """Control Center /health returns status ok."""
        await _skip_if_unreachable(_cc_url(), "Control Center")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{_cc_url()}/health")

        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("service") == "control-center"

    @pytest.mark.asyncio
    async def test_agent_runtime_healthy(self):
        """Agent Runtime /health returns status ok."""
        await _skip_if_unreachable(_ar_url(), "Agent Runtime")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{_ar_url()}/health")

        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("service") == "agent-runtime"

    @pytest.mark.asyncio
    async def test_ar_bootstrapped_cert_from_cc(self):
        """Agent Runtime health shows cert_expires_at, confirming it bootstrapped from CC.

        AR bootstraps its certificate from CC on startup.  ``cert_expires_at``
        in the health response confirms bootstrapping succeeded.  This is a
        pre-condition for the execution flow tests.
        """
        await _skip_if_unreachable(_ar_url(), "Agent Runtime")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{_ar_url()}/health")

        assert response.status_code == 200
        data = response.json()
        assert data.get("cert_expires_at") is not None, (
            "Agent Runtime has no cert_expires_at — "
            "AR failed to bootstrap its certificate from Control Center on startup. "
            "Check AR logs for bootstrap errors."
        )

    @pytest.mark.asyncio
    async def test_ar_health_exempt_no_cert_required(self):
        """AR /health is on the exempt list and does not require a certificate.

        Confirms the exempt-path logic so we know /execute is NOT exempt.
        """
        await _skip_if_unreachable(_ar_url(), "Agent Runtime")

        # Client with no certificate and no X-Client-Certificate header
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{_ar_url()}/health")

        assert response.status_code == 200, (
            f"/health should be exempt from cert auth, got {response.status_code}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AR certificate enforcement — verifying the middleware behaviour
# ═══════════════════════════════════════════════════════════════════════════════


class TestARCertificateEnforcement:
    """Confirm AR's ControlCenterCertificateMiddleware works as documented.

    These tests establish the security baseline that the CC → AR trigger must
    satisfy: AR's /execute requires an ``X-Client-Certificate`` header whose
    CN is exactly ``service:control-center``.
    """

    @pytest.mark.asyncio
    async def test_ar_execute_rejects_request_with_no_cert_header(self):
        """AR /execute returns 401 when no X-Client-Certificate header is present.

        This is the direct reproduction of the bug: ``AgentRuntimeClient``
        (in its current form) does not send this header.  AR therefore rejects
        every CC trigger with 401.

        EXPECTED TO PASS (not the bug itself — this confirms AR's defence is
        working.  The bug is that CC doesn't send the header, not that AR
        accepts the wrong certs).
        """
        await _skip_if_unreachable(_ar_url(), "Agent Runtime")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{_ar_url()}/execute",
                json={
                    "session_id": str(uuid.uuid4()),
                    "agent_type_id": str(uuid.uuid4()),
                },
            )

        assert response.status_code == 401, (
            f"Expected 401 (no cert header), got {response.status_code}: {response.text[:200]}"
        )
        detail = response.json().get("detail", "")
        assert "certificate" in detail.lower(), (
            f"401 detail should mention certificate, got: {detail!r}"
        )

    @pytest.mark.asyncio
    async def test_ar_execute_rejects_test_service_cert(self, ar_client):
        """AR /execute returns 401 when the cert CN is not service:control-center.

        ``ar_client`` carries a valid ``service:test-service`` cert (signed by
        the Parthenon CA).  AR should reject it because only
        ``service:control-center`` is permitted on /execute.

        EXPECTED TO PASS — this is correct security behaviour.
        """
        await _skip_if_unreachable(_ar_url(), "Agent Runtime")

        response = await ar_client.post(
            "/execute",
            json={
                "session_id": str(uuid.uuid4()),
                "agent_type_id": str(uuid.uuid4()),
            },
        )

        assert response.status_code == 401, (
            f"Expected 401 (test-service cert rejected by AR), got {response.status_code}: "
            f"{response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_ar_execute_rejects_arbitrary_cert_header_value(self):
        """AR /execute returns 401 for a malformed or unsigned X-Client-Certificate header.

        Confirms AR validates the cert CA signature — not just presence of the
        header.
        """
        await _skip_if_unreachable(_ar_url(), "Agent Runtime")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{_ar_url()}/execute",
                headers={"X-Client-Certificate": "not-a-real-cert"},
                json={
                    "session_id": str(uuid.uuid4()),
                    "agent_type_id": str(uuid.uuid4()),
                },
            )

        # Should be 401 — either cert parsing fails or CA validation fails
        assert response.status_code in (401, 503), (
            f"Expected 401 (invalid cert), got {response.status_code}: {response.text[:200]}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Bug confirmation: AgentRuntimeClient does NOT send X-Client-Certificate
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentRuntimeClientMissingCertHeader:
    """Verify AgentRuntimeClient behaviour after the CC → CH → AR architecture fix.

    After the fix:
    - AgentRuntimeClient._make_client() DOES send X-Client-Certificate (header added).
    - AR's /execute endpoint only accepts the communication-hub cert; control-center
      certs are rejected with 401.  CC must go through CH — not call AR directly.
    - test_full_execution_flow.py covers the correct CC → CH → AR end-to-end path.
    """

    @pytest.mark.asyncio
    async def test_agent_runtime_client_make_client_has_cert_header(self, tmp_path):
        """AgentRuntimeClient._make_client() now includes the X-Client-Certificate header.

        Verifies that the fix added the control-center's PEM cert as the
        X-Client-Certificate header for HTTP connections, matching the pattern
        in comm_hub_client.py.
        """
        from app.services.control_center.agent_runtime_client import AgentRuntimeClient

        cert = tmp_path / "cert.pem"
        cert.write_text("-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----\n")
        key = tmp_path / "key.pem"
        key.write_text("-----BEGIN PRIVATE KEY-----\nTEST\n-----END PRIVATE KEY-----\n")

        client = AgentRuntimeClient(
            agent_runtime_url=_ar_url(),
            cert_path=str(cert),
            key_path=str(key),
        )
        http_client = client._make_client()

        try:
            default_headers = dict(http_client.headers)
            assert "x-client-certificate" in {k.lower() for k in default_headers}, (
                "AgentRuntimeClient._make_client() is missing the X-Client-Certificate header. "
                "The fix in _make_client() should detect HTTP vs HTTPS and include the "
                "PEM cert as a header for HTTP (dev) mode."
            )
        finally:
            await http_client.aclose()

    @pytest.mark.asyncio
    async def test_cc_direct_ar_call_rejected_by_design(self):
        """CC calling AR directly is correctly rejected with 401.

        After the architecture fix, AR's /execute endpoint only accepts the
        communication-hub certificate.  The control-center must route through
        CH (not call AR directly), so a 401 here is the EXPECTED, correct
        behaviour — not a defect.

        The full CC → CH → AR path is validated in
        test_full_execution_flow.py::TestFullFlowEndToEnd.
        """
        await _skip_if_unreachable(_ar_url(), "Agent Runtime")

        from app.services.control_center.agent_runtime_client import (
            AgentRuntimeClient,
            AgentRuntimeClientError,
        )

        session_id = uuid.uuid4()
        agent_type_id = uuid.uuid4()

        client = AgentRuntimeClient(agent_runtime_url=_ar_url())

        with pytest.raises(AgentRuntimeClientError) as exc_info:
            await client.trigger_execution(
                session_id=session_id,
                agent_type_id=agent_type_id,
                input_data={"test": "execution_flow_integration_test"},
            )

        # AR rejects control-center cert because only communication-hub is allowed
        assert "401" in str(exc_info.value) or "communication-hub" in str(exc_info.value), (
            f"Expected 401/communication-hub rejection, got: {exc_info.value}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Full execution flow validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullExecutionFlow:
    """Validates the complete CC → AR → CC → CH execution flow.

    These tests confirm the end-to-end flow works:
      1. CC triggers AR: POST /execute with service:control-center cert
      2. AR enqueues the session and returns 200 {"status": "accepted"}
      3. AR's SessionDispatcher picks up the session and contacts CC data API
      4. CC's data API confirms the session moves out of "queued" status

    Tests that require a real control-center cert are the authoritative proof
    of the full pipeline.  The test-service cert simulates a limited view.
    """

    @pytest.mark.asyncio
    async def test_ar_accepts_execute_with_control_center_cert_from_header(
        self, test_cert_manager
    ):
        """AR /execute returns 200 when X-Client-Certificate has service:control-center CN.

        To prove AR accepts the correct cert, we need a ``service:control-center``
        certificate.  We obtain one by bootstrapping from CC using the bootstrap
        endpoint with a service_name override.

        NOTE: This test will FAIL until the AR accepts the actual CC cert — either
        because CC does not issue service:control-center certs to the test service,
        or because AR's middleware is misconfigured.

        EXPECTED TO FAIL if CC blocks issuing service:control-center to test clients.
        This test documents what the full fix requires.
        """
        await _skip_if_unreachable(_cc_url(), "Control Center")
        await _skip_if_unreachable(_ar_url(), "Agent Runtime")

        # Attempt to get a CC-like cert by inspecting CC's own cert path.
        # In dev mode, CC's cert is on disk at CC_CERT_PATH.
        cc_cert_path = os.environ.get("CC_CERT_PATH")
        if not cc_cert_path:
            pytest.skip(
                "CC_CERT_PATH not configured — cannot obtain a service:control-center cert "
                "to test AR acceptance.  Set CC_CERT_PATH to Control Center's PEM cert file."
            )

        import pathlib
        cert_path = pathlib.Path(cc_cert_path)
        if not cert_path.exists():
            pytest.skip(
                f"CC_CERT_PATH={cc_cert_path} does not exist on disk — "
                "cannot read CC service certificate for this test."
            )

        cc_cert_pem = cert_path.read_text()
        # Send the cert exactly as other services do: escaped newlines in the header
        cert_header_value = cc_cert_pem.replace("\n", "\\n")

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{_ar_url()}/execute",
                headers={"X-Client-Certificate": cert_header_value},
                json={
                    "session_id": str(uuid.uuid4()),
                    "agent_type_id": str(uuid.uuid4()),
                    "input_data": {},
                },
            )

        assert response.status_code == 200, (
            f"DEFECT: AR should accept service:control-center cert but returned "
            f"{response.status_code}: {response.text[:300]}\n"
            f"This means the CC cert either has wrong CN or AR middleware is "
            f"misconfigured."
        )
        data = response.json()
        assert data.get("status") == "accepted", (
            f"AR returned 200 but status was not 'accepted': {data}"
        )

    @pytest.mark.asyncio
    async def test_cc_internal_data_api_accessible_from_ar_perspective(self, cc_client):
        """CC's internal data API is accessible with a service cert (AR's perspective).

        AR calls CC's data API to claim queued sessions and post results.
        This confirms the AR → CC data path is open, completing one leg of
        the full bidirectional flow.

        EXPECTED TO PASS — this leg already works (test-service cert is accepted
        by CC's require_service_certificate dependency).
        """
        await _skip_if_unreachable(_cc_url(), "Control Center")

        response = await cc_client.post(
            "/api/v1/internal/data/sessions/claim-queued",
            json={"limit": 1},
        )
        assert response.status_code == 200, (
            f"CC data API (claim-queued) returned {response.status_code}: {response.text[:200]}"
        )
        data = response.json()
        assert "session_ids" in data, f"Unexpected response: {data}"

    @pytest.mark.asyncio
    async def test_session_status_endpoint_confirms_data_path(self, cc_client):
        """CC's session status update endpoint reachable from AR (via service cert).

        AR calls PATCH /internal/data/sessions/{id}/status to update session
        state.  A 404 (not 401) proves the auth succeeds — AR can push status
        updates back to CC.

        EXPECTED TO PASS — this leg already works.
        """
        await _skip_if_unreachable(_cc_url(), "Control Center")

        fake_session_id = "00000000-0000-0000-0000-000000000099"
        response = await cc_client.patch(
            f"/api/v1/internal/data/sessions/{fake_session_id}/status",
            json={"status": "running"},
        )
        # 404 = auth passed, session not found (expected — proves data path open)
        assert response.status_code == 404, (
            f"Expected 404 (auth ok, session not found), got {response.status_code}: "
            f"{response.text[:200]}"
        )
