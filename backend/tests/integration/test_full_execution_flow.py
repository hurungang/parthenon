"""Integration tests — Full Execution Flow Architecture (CC → CH → AR).

Enforces the correct execution flow:

    UI → Control Center → Communication Hub → Agent Runtime

**Current bugs this test suite exposes:**

1. **CC bypasses CH** — ``GatewayLifecycleHandler._trigger_execution_via_comm_hub()``
   imports and calls ``AgentRuntimeClient`` (POST AR ``/execute``) instead of
   ``CommunicationHubClient`` (POST CH ``/internal/agent/execute``).

2. **AR accepts wrong caller** — ``ControlCenterCertificateMiddleware`` in Agent
   Runtime is configured with ``_EXPECTED_SERVICE_NAME = "control-center"``.  Only
   ``service:communication-hub`` should be permitted on ``/execute``; Control Center
   must never reach AR directly.

3. **CH exempts /internal/agent/execute from cert check** — ``ControlPlaneMiddleware``
   in Communication Hub has an explicit bypass for the agent-execute path, allowing any
   caller (not just Control Center) to trigger agent execution.

**Test class summary:**

+-------------------------------------------+---------------+---------------------------------------+
| Class                                     | Expected      | Reason                                |
+===========================================+===============+=======================================+
| TestCommunicationHubForwardingEndpoint    | Mostly PASS   | CH endpoint registered; CH has cert   |
|                                           | (1 FAIL)      | loaded; test_ch_rejects_non_cc_certs  |
|                                           |               | FAILS because CH exempts path         |
+-------------------------------------------+---------------+---------------------------------------+
| TestControlCenterCallsCommunicationHub    | FAIL          | CC calls AR directly via              |
|                                           |               | AgentRuntimeClient                    |
+-------------------------------------------+---------------+---------------------------------------+
| TestAgentRuntimeOnlyAcceptsCommunicationHub| FAIL         | AR accepts service:control-center     |
|                                           |               | (should only accept                   |
|                                           |               | service:communication-hub)            |
+-------------------------------------------+---------------+---------------------------------------+
| TestFullFlowEndToEnd                      | FAIL          | Bypass exists; full CC→CH→AR flow     |
|                                           |               | cannot succeed                        |
+-------------------------------------------+---------------+---------------------------------------+

**Run with:**

    cd backend
    ../.venv/Scripts/python.exe -m pytest tests/integration/test_full_execution_flow.py -v --tb=short

**Requirements:**

    Control Center  → http://localhost:8000 (CONTROL_CENTER_URL)
    Agent Runtime   → http://localhost:8001 (AGENT_RUNTIME_URL)
    Comm Hub        → http://localhost:8002 (COMMUNICATION_HUB_URL)
    TEST_SERVICE_BOOTSTRAP_KEY env var (for certificate fixtures)

Tests are automatically skipped when required services are unreachable.
"""
from __future__ import annotations

import inspect
import os
import uuid

import httpx
import pytest

pytest_plugins = ["tests.fixtures.authenticated_clients"]

_DEFAULT_CC_URL = "http://localhost:8000"
_DEFAULT_AR_URL = "http://localhost:8001"
_DEFAULT_CH_URL = "http://localhost:8002"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cc_url() -> str:
    return os.environ.get("CONTROL_CENTER_URL", _DEFAULT_CC_URL).rstrip("/")


def _ar_url() -> str:
    return os.environ.get("AGENT_RUNTIME_URL", _DEFAULT_AR_URL).rstrip("/")


def _ch_url() -> str:
    return os.environ.get("COMMUNICATION_HUB_URL", _DEFAULT_CH_URL).rstrip("/")


async def _skip_if_unreachable(url: str, label: str) -> None:
    """Skip the calling test if *url/health* is not reachable or returns non-200."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{url}/health")
        if r.status_code != 200:
            pytest.skip(f"{label} not healthy (HTTP {r.status_code})")
    except httpx.RequestError as exc:
        pytest.skip(f"{label} unreachable: {exc}")


# ═══════════════════════════════════════════════════════════════════════════════
# Class 1: Communication Hub Forwarding Endpoint
# ═══════════════════════════════════════════════════════════════════════════════


class TestCommunicationHubForwardingEndpoint:
    """Verify Communication Hub has POST /internal/agent/execute and handles forwarding.

    Most tests in this class PASS — the CH endpoint is registered and the CH service
    certificate is loaded.

    ``test_ch_rejects_non_cc_certs`` **FAILS** because
    ``ControlPlaneMiddleware`` in Communication Hub currently exempts
    ``/internal/agent/execute`` from cert validation (any caller can trigger
    agent execution without proving they are Control Center).
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_ch_agent_execute_endpoint_exists(self):
        """CH POST /internal/agent/execute is registered — not a 404.

        Expected result: **PASS**

        CH registers ``agent_execute_router`` in ``_register_routers()`` (see
        ``app/communication_hub/main.py``).  A missing-body request returns
        422 (validation error), proving the route exists.  404 would indicate
        the router is not mounted.
        """
        await _skip_if_unreachable(_ch_url(), "Communication Hub")

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Empty body → 422 if route exists, 404 if not registered
            response = await client.post(
                f"{_ch_url()}/internal/agent/execute",
                json={},
            )

        assert response.status_code != 404, (
            "CH /internal/agent/execute returned 404 — route not registered. "
            "Ensure agent_execute_router is included in "
            "app/communication_hub/main.py _register_routers()."
        )
        # Valid outcomes: 422 (bad body), 401 (cert check on path), 200/502/503 (forwarding)
        assert response.status_code in (200, 401, 422, 500, 502, 503), (
            f"Unexpected status {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_ch_forwards_to_agent_runtime(self, ch_client):
        """CH /internal/agent/execute attempts to forward the request to AR.

        Expected result: **PASS** (partial)

        CH has forwarding logic in ``app/communication_hub/api/internal/agent_execute.py``.
        It builds an httpx client and POSTs to ``{AGENT_RUNTIME_URL}/execute``.

        With the current bug:
        - CH sends its own cert (``service:communication-hub``) to AR
        - AR rejects it because AR only accepts ``service:control-center``
        - AR returns 401 → CH wraps this as 502 to the caller

        The test accepts 200 (full success) or 502/503 (CH tried to forward but AR
        rejected the cert / was unreachable).  A 404 would mean CH has no forwarding
        route, which would be a separate failure.
        """
        await _skip_if_unreachable(_ch_url(), "Communication Hub")

        payload = {
            "session_id": str(uuid.uuid4()),
            "agent_type_id": str(uuid.uuid4()),
            "input_data": {"test": True},
        }
        response = await ch_client.post("/internal/agent/execute", json=payload)

        # 404 or 405 would mean CH endpoint does not exist / wrong method
        assert response.status_code not in (404, 405), (
            f"CH /internal/agent/execute not found or wrong method. "
            f"Got {response.status_code}: {response.text[:200]}"
        )

        # CH forwarding attempt outcomes:
        # 200  → CH forwarded successfully, AR accepted (correct architecture when fully fixed)
        # 401  → CH cert check rejected ch_client's test-service cert (if cert check enforced)
        # 502  → CH forwarded but AR rejected CH's cert (current bug — AR needs to accept CH cert)
        # 503  → AR was not running when CH attempted the forward
        assert response.status_code in (200, 401, 422, 502, 503), (
            f"Unexpected status from CH forwarding attempt: "
            f"{response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_ch_adds_certificate_header(self):
        """CH loads its service certificate and uses it for outbound calls to AR.

        Expected result: **PASS**

        CH's startup loads a 30-day service certificate (``service:communication-hub``)
        via ``CommHubCertificateManager``.  The health endpoint exposes
        ``cert_expires_at`` when the certificate is loaded successfully.

        The forwarding code in ``agent_execute.py`` reads ``cert_manager.cert_path``
        and ``cert_manager.key_path`` and adds the PEM to the
        ``X-Client-Certificate`` header (dev mode) or configures mTLS (prod).

        Failure here means CH has no certificate — it cannot authenticate to AR.
        """
        await _skip_if_unreachable(_ch_url(), "Communication Hub")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{_ch_url()}/health")

        assert response.status_code == 200
        data = response.json()
        assert data.get("cert_expires_at") is not None, (
            "Communication Hub has no cert_expires_at — CH has not loaded a service "
            "certificate.  CH cannot authenticate outbound calls to Agent Runtime "
            "without a cert.  Ensure COMM_HUB_CERT_PATH / SERVICE_BOOTSTRAP_KEY are "
            "set so CH bootstraps its certificate from Control Center on startup."
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_ch_rejects_non_cc_certs(self, ch_client):
        """CH /internal/agent/execute rejects callers that are not Control Center.

        Expected result: **FAIL** (architecture bug)

        ``ControlPlaneMiddleware`` in Communication Hub has an explicit bypass for
        ``/internal/agent/execute``::

            if request.url.path == _AGENT_EXECUTE_PATH:
                return await call_next(request)  # ← no cert check!

        This allows ANY caller — not just Control Center — to trigger agent execution.
        The test sends the ``service:test-service`` cert (not ``service:control-center``)
        and asserts it is rejected with 401.  Because the path is exempt, it passes
        through and the assertion fails.

        Fix:
            Remove the ``_AGENT_EXECUTE_PATH`` exemption from
            ``app/communication_hub/middleware/control_plane.py`` and enforce
            ``service:control-center`` cert validation on this path.
        """
        await _skip_if_unreachable(_ch_url(), "Communication Hub")

        payload = {
            "session_id": str(uuid.uuid4()),
            "agent_type_id": str(uuid.uuid4()),
        }
        # ch_client carries service:test-service cert — not service:control-center
        response = await ch_client.post("/internal/agent/execute", json=payload)

        assert response.status_code == 401, (
            f"ARCHITECTURE BUG: CH /internal/agent/execute accepted a non-CC cert "
            f"(status {response.status_code}, expected 401). "
            f"The path is currently EXEMPT from ControlPlaneMiddleware cert validation. "
            f"Fix: Remove the _AGENT_EXECUTE_PATH exemption in "
            f"app/communication_hub/middleware/control_plane.py and require "
            f"service:control-center cert on /internal/agent/execute."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Class 2: Control Center Calls Communication Hub
# ═══════════════════════════════════════════════════════════════════════════════


class TestControlCenterCallsCommunicationHub:
    """Verify CC uses CommunicationHubClient to reach CH, NOT AgentRuntimeClient to reach AR.

    All tests in this class **FAIL** because ``GatewayLifecycleHandler
    ._trigger_execution_via_comm_hub()`` imports ``AgentRuntimeClient`` and calls
    ``POST /execute`` on Agent Runtime directly, bypassing Communication Hub entirely.
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_lifecycle_handler_calls_ch_not_ar(self):
        """GatewayLifecycleHandler._trigger_execution_via_comm_hub calls CH, NOT AR.

        Expected result: **FAIL** (architecture bug)

        The method name is misleading — despite being called
        ``_trigger_execution_via_comm_hub``, it currently:

        1. Imports ``AgentRuntimeClient`` from
           ``app.services.control_center.agent_runtime_client``
        2. Calls ``client.trigger_execution()`` which POSTs to AR ``/execute``

        Correct behaviour:

        1. Import ``CommunicationHubClient`` from
           ``app.services.control_center.comm_hub_client``
        2. POST ``/internal/agent/execute`` on Communication Hub

        Fix:
            In ``app/services/gateway/lifecycle_handler.py`` replace::

                from app.services.control_center.agent_runtime_client import AgentRuntimeClient
                client = AgentRuntimeClient()
                await client.trigger_execution(...)

            with::

                from app.services.control_center.comm_hub_client import CommunicationHubClient
                client = CommunicationHubClient()
                await client.trigger_execution(...)  # calls CH /internal/agent/execute
        """
        from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler

        source = inspect.getsource(
            GatewayLifecycleHandler._trigger_execution_via_comm_hub
        )

        # 1. Must NOT use AgentRuntimeClient (direct AR bypass)
        assert "AgentRuntimeClient" not in source, (
            "ARCHITECTURE BUG: _trigger_execution_via_comm_hub imports AgentRuntimeClient. "
            "CC is calling AR directly, bypassing Communication Hub. "
            "Replace AgentRuntimeClient with CommunicationHubClient.\n"
            f"Current source snippet:\n{source[:500]}"
        )

        # 2. Must use CommunicationHubClient
        assert "CommunicationHubClient" in source, (
            "ARCHITECTURE BUG: _trigger_execution_via_comm_hub does not use "
            "CommunicationHubClient.  CC must route execution through CH.\n"
            f"Current source snippet:\n{source[:500]}"
        )

        # 3. The target endpoint must be CH's agent-execute path
        assert "/internal/agent/execute" in source, (
            "ARCHITECTURE BUG: _trigger_execution_via_comm_hub does not reference "
            "CH endpoint /internal/agent/execute.\n"
            f"Current source snippet:\n{source[:500]}"
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cc_uses_comm_hub_client(self):
        """GatewayLifecycleHandler uses CommHubClient (not AgentRuntimeClient) for execution.

        Expected result: **FAIL** (architecture bug)

        Code inspection confirms ``_trigger_execution_via_comm_hub`` imports
        ``AgentRuntimeClient``.  The class-level dependency should be
        ``CommunicationHubClient``.

        This test is complementary to ``test_lifecycle_handler_calls_ch_not_ar`` —
        it verifies the import rather than the endpoint URL.
        """
        from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler

        # Inspect the full class source to check which client modules are referenced
        class_source = inspect.getsource(GatewayLifecycleHandler)

        # The execution-trigger path must reference CommHubClient, not AgentRuntimeClient
        assert "CommunicationHubClient" in class_source, (
            "ARCHITECTURE BUG: GatewayLifecycleHandler does not reference "
            "CommunicationHubClient anywhere.  The class must use "
            "CommunicationHubClient to forward execution triggers to CH."
        )

        assert "AgentRuntimeClient" not in class_source, (
            "ARCHITECTURE BUG: GatewayLifecycleHandler references AgentRuntimeClient. "
            "Remove all direct AR calls from the lifecycle handler.  "
            "Execution triggers must go through Communication Hub."
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cc_includes_certificate(self, cc_client):
        """Control Center is reachable and responds with correct service identity.

        Expected result: **PASS**

        This test verifies CC is running and the service cert mechanism works — the
        ``cc_client`` fixture carries a ``service:test-service`` certificate that CC's
        ``require_service_certificate`` accepts on ``/internal/*`` routes.

        CC also maintains its own service certificate (``CC_CERT_PATH``) for outbound
        calls.  The health endpoint confirms CC is alive; cert presence for outbound
        calls is confirmed by the CommunicationHubClient / AgentRuntimeClient source.
        """
        await _skip_if_unreachable(_cc_url(), "Control Center")

        response = await cc_client.get("/health")
        assert response.status_code == 200, (
            f"CC /health returned {response.status_code}: {response.text[:200]}"
        )
        data = response.json()
        assert data.get("service") == "control-center", (
            f"Expected service='control-center', got: {data}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Class 3: Agent Runtime Only Accepts Communication Hub
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentRuntimeOnlyAcceptsCommunicationHub:
    """Verify AR /execute only accepts service:communication-hub certificate.

    All tests in this class **FAIL** because AR's ``ControlCenterCertificateMiddleware``
    is configured with ``_EXPECTED_SERVICE_NAME = "control-center"``.

    Correct configuration: ``_EXPECTED_SERVICE_NAME = "communication-hub"``
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_ar_rejects_cc_cert_on_execute(self):
        """AR /execute middleware is NOT configured to accept service:control-center.

        Expected result: **FAIL** (architecture bug)

        ``ControlCenterCertificateMiddleware._EXPECTED_SERVICE_NAME`` is currently
        ``"control-center"``.  This means AR accepts direct calls from Control Center,
        making it possible for CC to bypass Communication Hub.

        The correct value is ``"communication-hub"`` — only CH should be able to
        reach AR ``/execute``.

        Fix:
            In ``app/agent_runtime/middleware.py`` change::

                _EXPECTED_SERVICE_NAME = "control-center"

            to::

                _EXPECTED_SERVICE_NAME = "communication-hub"
        """
        from app.agent_runtime.middleware import _EXPECTED_SERVICE_NAME

        assert _EXPECTED_SERVICE_NAME != "control-center", (
            f"ARCHITECTURE BUG: AR /execute accepts 'service:control-center' cert. "
            f"_EXPECTED_SERVICE_NAME = {_EXPECTED_SERVICE_NAME!r} (should not be 'control-center'). "
            f"This means CC can call AR directly, bypassing Communication Hub. "
            f"Fix: Change _EXPECTED_SERVICE_NAME to 'communication-hub' in "
            f"app/agent_runtime/middleware.py."
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_ar_accepts_ch_cert_on_execute(self):
        """AR /execute middleware is configured to accept service:communication-hub cert.

        Expected result: **FAIL** (architecture bug)

        ``_EXPECTED_SERVICE_NAME`` is ``"control-center"``, not ``"communication-hub"``.
        AR will reject Communication Hub's cert, breaking the intended forwarding path.

        When fixed (``_EXPECTED_SERVICE_NAME = "communication-hub"``), this test passes
        and CH can successfully reach AR ``/execute``.
        """
        from app.agent_runtime.middleware import _EXPECTED_SERVICE_NAME

        assert _EXPECTED_SERVICE_NAME == "communication-hub", (
            f"ARCHITECTURE BUG: AR middleware expects '{_EXPECTED_SERVICE_NAME}' cert on /execute. "
            f"Expected: 'communication-hub' (so CH can call AR). "
            f"With current config AR would reject Communication Hub's cert with 401, "
            f"causing CH to return 502 to Control Center. "
            f"Fix: _EXPECTED_SERVICE_NAME = 'communication-hub' in app/agent_runtime/middleware.py."
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_ar_middleware_enforces_ch_only(self, ar_client):
        """AR /execute rejection error message names communication-hub as the expected caller.

        Expected result: **FAIL** (architecture bug)

        When AR rejects a certificate on ``/execute``, the error response currently
        references ``service:control-center`` as the expected CN (because
        ``_EXPECTED_SERVICE_NAME = "control-center"``).  After the fix, the error
        would reference ``service:communication-hub``.

        The test calls AR ``/execute`` with the ``service:test-service`` cert (which
        is always rejected), then checks that the rejection message confirms the
        *correct* expected caller (``communication-hub``).
        """
        await _skip_if_unreachable(_ar_url(), "Agent Runtime")

        response = await ar_client.post(
            "/execute",
            json={
                "session_id": str(uuid.uuid4()),
                "agent_type_id": str(uuid.uuid4()),
            },
        )

        # AR should always reject the test-service cert on /execute — 401 or 503 (no CA)
        assert response.status_code in (401, 503), (
            f"AR /execute returned unexpected {response.status_code} for test-service cert. "
            f"Response: {response.text[:200]}"
        )

        if response.status_code == 401:
            # The rejection detail must reference communication-hub as the expected CN.
            # Currently it references control-center — this assertion FAILS.
            error_text = response.text.lower()
            assert "communication-hub" in error_text, (
                f"ARCHITECTURE BUG: AR /execute rejection does not mention 'communication-hub'. "
                f"The error currently references 'control-center' as the expected service. "
                f"After fixing _EXPECTED_SERVICE_NAME = 'communication-hub', the rejection "
                f"message will correctly identify CH as the only valid caller. "
                f"Actual error: {response.text[:300]}"
            )
        else:
            # 503 means CA cert not configured — middleware config not checked
            pytest.skip(
                "AR returned 503 (CA_CERT_PATH not configured) — cannot inspect rejection message."
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Class 4: Full Flow End-to-End
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullFlowEndToEnd:
    """Full integration tests: CC → CH → AR with AgentJob enqueue.

    Both tests **FAIL** with the current implementation because:

    * CC calls AR directly (bypassing CH)
    * AR accepts ``service:control-center`` cert (enabling the bypass)

    When both bugs are fixed, ``test_cc_trigger_reaches_ar_via_ch`` will pass and
    ``test_execution_flow_never_bypasses_ch`` will confirm the bypass is impossible.
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cc_trigger_reaches_ar_via_ch(self):
        """Full architecture: CC execution trigger is routed through Communication Hub.

        Expected result: **FAIL** (architecture bug)

        This test verifies the two code-level invariants that make the full flow work:

        1. ``_trigger_execution_via_comm_hub`` uses ``CommunicationHubClient``
           (not ``AgentRuntimeClient``) — ensures CC sends to CH.
        2. AR middleware is configured for ``service:communication-hub``
           (not ``service:control-center``) — ensures only CH can reach AR.

        Both are currently wrong, so the test fails.

        When both are fixed, calls from CC go to CH, CH forwards to AR with its
        ``service:communication-hub`` cert, AR accepts and enqueues the session.
        """
        await _skip_if_unreachable(_cc_url(), "Control Center")
        await _skip_if_unreachable(_ch_url(), "Communication Hub")
        await _skip_if_unreachable(_ar_url(), "Agent Runtime")

        from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler
        from app.agent_runtime.middleware import _EXPECTED_SERVICE_NAME

        handler_source = inspect.getsource(
            GatewayLifecycleHandler._trigger_execution_via_comm_hub
        )

        # Invariant 1: CC must route through CH
        cc_routes_via_ch = (
            "CommunicationHubClient" in handler_source
            and "AgentRuntimeClient" not in handler_source
        )

        # Invariant 2: AR must only accept CH cert
        ar_accepts_ch_only = _EXPECTED_SERVICE_NAME == "communication-hub"

        assert cc_routes_via_ch and ar_accepts_ch_only, (
            f"ARCHITECTURE BUG: Full CC → CH → AR flow is broken.\n"
            f"  CC routes via CH: {cc_routes_via_ch} "
            f"(AgentRuntimeClient in source: {'AgentRuntimeClient' in handler_source})\n"
            f"  AR accepts CH cert: {ar_accepts_ch_only} "
            f"(AR _EXPECTED_SERVICE_NAME = {_EXPECTED_SERVICE_NAME!r})\n"
            f"Fix both bugs to restore the correct execution path."
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_execution_flow_never_bypasses_ch(self):
        """Negative test: CC cannot reach AR /execute directly — only CH can.

        Expected result: **FAIL** (architecture bug)

        AR's current configuration (``_EXPECTED_SERVICE_NAME = "control-center"``)
        allows Control Center to call AR ``/execute`` directly, bypassing Communication
        Hub.  The correct configuration (``"communication-hub"``) would make it
        impossible for any service other than CH to reach AR ``/execute``.

        This test asserts the bypass is structurally impossible by checking both the
        AR middleware configuration AND the CC handler source.

        When fixed:
        - AR middleware rejects all non-``service:communication-hub`` certs on ``/execute``
        - CC handler uses ``CommunicationHubClient``, not ``AgentRuntimeClient``
        - A direct CC → AR call would be rejected with 401
        """
        from app.agent_runtime.middleware import _EXPECTED_SERVICE_NAME
        from app.services.gateway.lifecycle_handler import GatewayLifecycleHandler

        handler_source = inspect.getsource(
            GatewayLifecycleHandler._trigger_execution_via_comm_hub
        )

        bypass_possible = (
            _EXPECTED_SERVICE_NAME == "control-center"
            or "AgentRuntimeClient" in handler_source
        )

        assert not bypass_possible, (
            f"ARCHITECTURE BUG: Direct CC → AR bypass is possible.\n"
            f"  AR _EXPECTED_SERVICE_NAME = {_EXPECTED_SERVICE_NAME!r} "
            f"(should be 'communication-hub' to block direct CC access)\n"
            f"  AgentRuntimeClient in CC handler: {'AgentRuntimeClient' in handler_source} "
            f"(should be False — CC must use CommunicationHubClient)\n"
            f"Fix:\n"
            f"  1. app/agent_runtime/middleware.py: "
            f"_EXPECTED_SERVICE_NAME = 'communication-hub'\n"
            f"  2. app/services/gateway/lifecycle_handler.py: "
            f"replace AgentRuntimeClient with CommunicationHubClient in "
            f"_trigger_execution_via_comm_hub()"
        )
