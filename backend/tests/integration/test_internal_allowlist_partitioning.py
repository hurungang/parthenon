"""Integration tests for internal caller allowlist partitioning and deny logging."""
from __future__ import annotations

import logging
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.certificate_authority import (
    CertificateAuthorityService,
    IssuedCertificate,
    issue_service_certificate,
)


@pytest_asyncio.fixture(autouse=True)
async def reset_ca():
    """Reset module-level CA state before each test for isolation."""
    import app.services.certificate_authority as ca_module

    ca_module._ca_private_key = None
    ca_module._ca_certificate = None
    yield
    ca_module._ca_private_key = None
    ca_module._ca_certificate = None


@pytest_asyncio.fixture
async def initialized_ca(db_session: AsyncSession) -> CertificateAuthorityService:
    """Return an initialized CA service."""
    svc = CertificateAuthorityService()
    await svc.initialize(db_session)
    return svc


@pytest_asyncio.fixture
async def ar_service_cert(initialized_ca: CertificateAuthorityService) -> IssuedCertificate:
    """Issue service certificate for Agent Runtime caller identity."""
    return await issue_service_certificate("agent-runtime")


@pytest_asyncio.fixture
async def ch_service_cert(initialized_ca: CertificateAuthorityService) -> IssuedCertificate:
    """Issue service certificate for Communication Hub caller identity."""
    return await issue_service_certificate("communication-hub")


@pytest.mark.asyncio
async def test_agent_runtime_allowed_for_runtime_data_endpoint(
    async_client: AsyncClient,
    ar_service_cert: IssuedCertificate,
):
    """Agent Runtime caller can reach its allowlisted data endpoint."""
    fake_session_id = uuid.uuid4()
    response = await async_client.get(
        f"/api/v1/internal/data/sessions/{fake_session_id}",
        headers={"X-Client-Certificate": ar_service_cert.certificate_pem},
    )

    # AuthZ passes; 404 is expected for a fake session id.
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_agent_runtime_denied_for_communication_hub_only_endpoint(
    async_client: AsyncClient,
    ar_service_cert: IssuedCertificate,
):
    """Agent Runtime caller is blocked from CH-only internal authorization API."""
    response = await async_client.post(
        "/api/v1/internal/authorize/tool-call",
        headers={"X-Client-Certificate": ar_service_cert.certificate_pem},
        json={
            "certificate_serial_number": "nonexistent-serial",
            "tool_name": "system____save_result",
        },
    )

    assert response.status_code == 403
    detail = response.json().get("detail", {})
    assert detail.get("error") == "internal_endpoint_denied"
    assert detail.get("reason") == "endpoint_not_allowlisted"
    assert detail.get("caller_type") == "agent_runtime"


@pytest.mark.asyncio
async def test_communication_hub_allowed_for_authorize_endpoint(
    async_client: AsyncClient,
    ch_service_cert: IssuedCertificate,
):
    """Communication Hub caller can reach its allowlisted authorization endpoint."""
    response = await async_client.post(
        "/api/v1/internal/authorize/tool-call",
        headers={"X-Client-Certificate": ch_service_cert.certificate_pem},
        json={
            "certificate_serial_number": "nonexistent-serial",
            "tool_name": "system____save_result",
        },
    )

    # AuthZ gate passes; business response can vary but must not be policy 403.
    assert response.status_code != 403


@pytest.mark.asyncio
async def test_communication_hub_denied_for_agent_runtime_only_endpoint(
    async_client: AsyncClient,
    ch_service_cert: IssuedCertificate,
):
    """Communication Hub caller is blocked from AR-only claim queue endpoint."""
    response = await async_client.post(
        "/api/v1/internal/data/sessions/claim-queued",
        headers={"X-Client-Certificate": ch_service_cert.certificate_pem},
        json={"limit": 1},
    )

    assert response.status_code == 403
    detail = response.json().get("detail", {})
    assert detail.get("error") == "internal_endpoint_denied"
    assert detail.get("reason") == "endpoint_not_allowlisted"
    assert detail.get("caller_type") == "communication_hub"


@pytest.mark.asyncio
async def test_policy_denial_emits_structured_audit_event(
    async_client: AsyncClient,
    ar_service_cert: IssuedCertificate,
    caplog: pytest.LogCaptureFixture,
):
    """Blocked internal call emits a structured deny audit event."""
    caplog.set_level(logging.WARNING, logger="app.api.deps")

    await async_client.post(
        "/api/v1/internal/authorize/tool-call",
        headers={"X-Client-Certificate": ar_service_cert.certificate_pem},
        json={
            "certificate_serial_number": "nonexistent-serial",
            "tool_name": "system____save_result",
        },
    )

    deny_events = [
        record.getMessage()
        for record in caplog.records
        if "internal.allowlist.denied" in record.getMessage()
    ]
    assert deny_events, "Expected at least one structured deny audit log event"
    assert any("endpoint_not_allowlisted" in message for message in deny_events)
