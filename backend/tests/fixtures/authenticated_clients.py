"""Authenticated httpx client fixtures for live integration tests.

Provides session-scoped pytest fixtures for calling Control Center, Agent
Runtime, and Communication Hub using the test service's X.509 certificate.

The test service certificate is a 30-day service cert (CN ``service:test-service``)
bootstrapped from Control Center on first use.  The certificate is forwarded via
the ``X-Client-Certificate`` HTTP header so that ``require_service_certificate``
(CC) and ``ControlCenterCertificateMiddleware`` (AR) recognise it.

**Note on AR/CH access:**
Control Center's ``require_service_certificate`` accepts any valid service cert
(CN prefix ``service:``), so ``cc_client`` has access to all ``/internal/*``
routes on CC.  Agent Runtime's middleware only accepts ``service:control-center``,
so ``ar_client`` is restricted to exempt paths (``/health``, etc.).

Usage (import at test-file level or via conftest)::

    pytest_plugins = ["tests.fixtures.authenticated_clients"]

    async def test_example(cc_client):
        response = await cc_client.get("/health")
        assert response.status_code == 200

Environment variables:
    TEST_SERVICE_BOOTSTRAP_KEY  — bootstrap key (required)
    CONTROL_CENTER_URL          — CC base URL (default: http://localhost:8000)
    AGENT_RUNTIME_URL           — AR base URL (default: http://localhost:8001)
    COMMUNICATION_HUB_URL       — CH base URL (default: http://localhost:8002)
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio

from tests.fixtures.test_service_certificate import (
    TestServiceBootstrapError,
    TestServiceCertificateManager,
)

_DEFAULT_CC_URL = "http://localhost:8000"
_DEFAULT_AR_URL = "http://localhost:8001"
_DEFAULT_CH_URL = "http://localhost:8002"


@pytest_asyncio.fixture(scope="session")
async def test_cert_manager() -> TestServiceCertificateManager:
    """Session-scoped test service certificate manager.

    Bootstraps the test service certificate from Control Center once per
    session.  Skips (via :func:`pytest.skip`) if CC is unreachable or the
    bootstrap key is not configured — this avoids spurious failures when the
    live services are not running.

    Yields:
        A bootstrapped :class:`TestServiceCertificateManager`.
    """
    manager = TestServiceCertificateManager()
    try:
        await manager.bootstrap()
    except TestServiceBootstrapError as exc:
        pytest.skip(
            f"Test service bootstrap failed — live services may not be running: {exc}"
        )
    yield manager
    manager.cleanup()


@pytest_asyncio.fixture(scope="session")
async def cc_client(test_cert_manager: TestServiceCertificateManager):
    """Session-scoped authenticated client targeting Control Center.

    Forwards the test service cert via ``X-Client-Certificate``.  Accepted by
    CC's ``require_service_certificate`` for all ``/internal/*`` routes.

    Yields:
        A configured ``httpx.AsyncClient`` with base URL pointed at CC.
    """
    cc_url = os.environ.get("CONTROL_CENTER_URL", _DEFAULT_CC_URL)
    client = test_cert_manager.get_header_client(base_url=cc_url)
    yield client
    await client.aclose()


@pytest_asyncio.fixture(scope="session")
async def ar_client(test_cert_manager: TestServiceCertificateManager):
    """Session-scoped authenticated client targeting Agent Runtime.

    Forwards the test service cert via ``X-Client-Certificate``.  AR's
    middleware only permits ``service:control-center``, so this client is
    accepted on exempt paths (``/health``) but rejected on ``/execute``.

    Yields:
        A configured ``httpx.AsyncClient`` with base URL pointed at AR.
    """
    ar_url = os.environ.get("AGENT_RUNTIME_URL", _DEFAULT_AR_URL)
    client = test_cert_manager.get_header_client(base_url=ar_url)
    yield client
    await client.aclose()


@pytest_asyncio.fixture(scope="session")
async def ch_client(test_cert_manager: TestServiceCertificateManager):
    """Session-scoped authenticated client targeting Communication Hub.

    Forwards the test service cert via ``X-Client-Certificate``.  CH middleware
    restricts ``/dispatch`` to ``service:control-center``, so this client is
    accepted on exempt paths (``/health``) only.

    Yields:
        A configured ``httpx.AsyncClient`` with base URL pointed at CH.
    """
    ch_url = os.environ.get("COMMUNICATION_HUB_URL", _DEFAULT_CH_URL)
    client = test_cert_manager.get_header_client(base_url=ch_url)
    yield client
    await client.aclose()
