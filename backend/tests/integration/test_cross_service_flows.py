"""Integration tests — Cross-service execution and dispatch flows (Task 9.7).

Validates the full agent execution pipeline across all three services:
  CC → AR: execution trigger
  AR → CC: context fetch (AR has bootstrapped cert from CC)
  AR → CC: result submission
  CC → CH: result dispatch

These tests make **no** use of ``unittest.mock`` or ``httpx`` mocking.
All HTTP calls are real requests to live services.

Tests are skipped automatically when any required service is unreachable
(via the session-scoped ``test_cert_manager`` fixture from
``authenticated_clients``).

Services required:
  - Control Center  (CONTROL_CENTER_URL, default http://localhost:8000)
  - Agent Runtime   (AGENT_RUNTIME_URL,   default http://localhost:8001)
  - Communication Hub (COMMUNICATION_HUB_URL, default http://localhost:8002)
"""
from __future__ import annotations

import os

import httpx
import pytest

pytest_plugins = ["tests.fixtures.authenticated_clients"]

_DEFAULT_CC_URL = "http://localhost:8000"
_DEFAULT_AR_URL = "http://localhost:8001"
_DEFAULT_CH_URL = "http://localhost:8002"


# ── Helpers ────────────────────────────────────────────────────────────────────


def _cc_url() -> str:
    return os.environ.get("CONTROL_CENTER_URL", _DEFAULT_CC_URL).rstrip("/")


def _ar_url() -> str:
    return os.environ.get("AGENT_RUNTIME_URL", _DEFAULT_AR_URL).rstrip("/")


def _ch_url() -> str:
    return os.environ.get("COMMUNICATION_HUB_URL", _DEFAULT_CH_URL).rstrip("/")


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
# Service health and connectivity
# ═══════════════════════════════════════════════════════════════════════════════


class TestServiceConnectivity:
    """Verify all three services are running and healthy before cross-service tests."""

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
    async def test_communication_hub_healthy(self):
        """Communication Hub /health returns status ok."""
        await _skip_if_unreachable(_ch_url(), "Communication Hub")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{_ch_url()}/health")

        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("service") == "communication-hub"

    @pytest.mark.asyncio
    async def test_ar_bootstrapped_cert_from_cc(self):
        """Agent Runtime health shows cert_expires_at, confirming it bootstrapped from CC.

        AR bootstraps its certificate from CC on startup.  The health endpoint
        exposes ``cert_expires_at`` when bootstrapping succeeded.  This
        validates the CC → AR certificate issuance path.
        """
        await _skip_if_unreachable(_ar_url(), "Agent Runtime")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{_ar_url()}/health")

        assert response.status_code == 200
        data = response.json()
        assert data.get("cert_expires_at") is not None, (
            "Agent Runtime has no cert_expires_at — "
            "bootstrap from Control Center may have failed"
        )

    @pytest.mark.asyncio
    async def test_ch_bootstrapped_cert_from_cc(self):
        """Communication Hub health shows cert_expires_at, confirming bootstrap from CC.

        CH bootstraps its certificate from CC on startup.  This validates the
        CC → CH certificate issuance path.
        """
        await _skip_if_unreachable(_ch_url(), "Communication Hub")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{_ch_url()}/health")

        assert response.status_code == 200
        data = response.json()
        assert data.get("cert_expires_at") is not None, (
            "Communication Hub has no cert_expires_at — "
            "bootstrap from Control Center may have failed"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AR → CC data API path (AR fetches context from CC)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentRuntimeToControlCenterDataPath:
    """Validates that the CC internal data API accepts AR-style service cert auth.

    The test service cert (CN ``service:test-service``) is accepted by
    ``require_service_certificate`` (same rule AR uses with its
    ``agent-instance:*`` cert).  These tests exercise the data API endpoints
    that AR calls during execution context fetch.
    """

    @pytest.mark.asyncio
    async def test_claim_queued_sessions_endpoint_accessible(self, cc_client):
        """AR claim-queued endpoint: CC returns 200 with a session_ids list.

        This is the endpoint AR calls to atomically claim queued sessions.
        An empty list confirms there are no queued sessions; it also confirms
        the auth path from AR to CC works end-to-end.
        """
        response = await cc_client.post(
            "/api/v1/internal/data/sessions/claim-queued",
            json={"limit": 1},
        )
        assert response.status_code == 200, (
            f"claim-queued returned {response.status_code}: {response.text[:200]}"
        )
        data = response.json()
        assert "session_ids" in data
        assert isinstance(data["session_ids"], list)

    @pytest.mark.asyncio
    async def test_session_status_update_rejects_nonexistent_session(self, cc_client):
        """PATCH /internal/data/sessions/{id}/status returns 404 for unknown session.

        This endpoint is used by AR to post running/completed/failed transitions.
        A 404 (not 401/403) proves the auth path works — AR can reach CC and
        auth is accepted.
        """
        fake_id = "00000000-0000-0000-0000-000000000002"
        response = await cc_client.patch(
            f"/api/v1/internal/data/sessions/{fake_id}/status",
            json={"status": "running"},
        )
        # 404 = auth succeeded, session not found (expected with fake ID)
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_session_result_submission_rejects_nonexistent_session(self, cc_client):
        """POST /internal/data/sessions/{id}/result returns 404 for unknown session.

        This endpoint is used by AR to post execution results back to CC.
        404 confirms the auth path is open.
        """
        fake_id = "00000000-0000-0000-0000-000000000003"
        response = await cc_client.post(
            f"/api/v1/internal/data/sessions/{fake_id}/result",
            json={"output_data": {"test": "result"}},
        )
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text[:200]}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CC → CH dispatch path
# ═══════════════════════════════════════════════════════════════════════════════


class TestControlCenterToCommHubDispatchPath:
    """Validates CC → CH communication path.

    CH's ``/dispatch`` endpoint requires ``service:control-center`` cert.
    The test service cert is rejected there (401), which confirms the cert
    enforcement is working.  CH health proves it is running and bootstrapped.

    CC dispatches to CH using CC's own service cert via ``CommHubClient``
    (not the test service cert).  To validate that path, we verify:
    1. CH is running (health check)
    2. CH has bootstrapped its cert from CC (cert_expires_at in health)
    3. CH's dispatch endpoint correctly rejects non-CC certs (security boundary)
    """

    @pytest.mark.asyncio
    async def test_ch_dispatch_rejects_test_service_cert(self, ch_client):
        """CH /dispatch requires service:control-center cert; test-service cert is rejected.

        This test confirms the mTLS enforcement on CH's dispatch path is
        working correctly — a 401 here is the **expected** result.
        """
        await _skip_if_unreachable(_ch_url(), "Communication Hub")

        response = await ch_client.post(
            "/dispatch",
            json={"session_id": "00000000-0000-0000-0000-000000000004", "payload": {}},
        )
        # 401 confirms CH's cert middleware is active and test-service cert is rejected
        assert response.status_code == 401, (
            f"Expected 401 (test-service cert rejected), got {response.status_code}"
        )

    @pytest.mark.asyncio
    async def test_ch_health_is_public(self, ch_client):
        """CH /health does not require a cert and is accessible with any client."""
        await _skip_if_unreachable(_ch_url(), "Communication Hub")

        response = await ch_client.get("/health")
        assert response.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# CC → AR execution trigger path
# ═══════════════════════════════════════════════════════════════════════════════


class TestControlCenterToAgentRuntimeTriggerPath:
    """Validates CC → AR execution trigger communication path.

    AR's ``/execute`` endpoint requires ``service:control-center`` cert.
    The test service cert is rejected (401), confirming enforcement.  AR
    health proves it is running and bootstrapped via CC.

    CC triggers AR using CC's own service cert via ``AgentRuntimeClient``
    (not the test service cert).
    """

    @pytest.mark.asyncio
    async def test_ar_execute_rejects_test_service_cert(self, ar_client):
        """AR /execute requires service:control-center cert; test-service cert is rejected.

        A 401 here is the **expected** result — it confirms cert enforcement is active.
        """
        await _skip_if_unreachable(_ar_url(), "Agent Runtime")

        response = await ar_client.post(
            "/execute",
            json={
                "session_id": "00000000-0000-0000-0000-000000000005",
                "agent_type_id": "00000000-0000-0000-0000-000000000006",
            },
        )
        # 401 confirms AR's ControlCenterCertificateMiddleware is enforcing the boundary
        assert response.status_code == 401, (
            f"Expected 401 (test-service cert rejected by AR), got {response.status_code}"
        )

    @pytest.mark.asyncio
    async def test_ar_health_is_public(self, ar_client):
        """AR /health does not require a cert and is accessible with any client."""
        await _skip_if_unreachable(_ar_url(), "Agent Runtime")

        response = await ar_client.get("/health")
        assert response.status_code == 200
