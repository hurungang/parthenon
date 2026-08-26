"""Integration tests for deny-by-default and deny audit event details."""
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
async def unknown_service_cert(initialized_ca: CertificateAuthorityService) -> IssuedCertificate:
    """Issue a valid service cert for an unmapped internal caller identity."""
    return await issue_service_certificate("analytics-service")


@pytest.mark.asyncio
async def test_unknown_internal_service_is_denied_by_default(
    async_client: AsyncClient,
    unknown_service_cert: IssuedCertificate,
):
    """Unknown service identity is rejected before endpoint handler logic."""
    fake_session_id = uuid.uuid4()
    response = await async_client.get(
        f"/api/v1/internal/data/sessions/{fake_session_id}",
        headers={"X-Client-Certificate": unknown_service_cert.certificate_pem},
    )

    assert response.status_code == 403
    detail = response.json().get("detail", {})
    assert detail.get("error") == "internal_endpoint_denied"
    assert detail.get("reason") == "unknown_internal_caller"
    assert detail.get("caller_type") is None


@pytest.mark.asyncio
async def test_unknown_internal_service_denial_emits_structured_event(
    async_client: AsyncClient,
    unknown_service_cert: IssuedCertificate,
    caplog: pytest.LogCaptureFixture,
):
    """Denied call writes structured log fields required for audit evidence."""
    caplog.set_level(logging.WARNING, logger="app.api.deps")

    await async_client.get(
        f"/api/v1/internal/data/sessions/{uuid.uuid4()}",
        headers={"X-Client-Certificate": unknown_service_cert.certificate_pem},
    )

    deny_messages = [
        record.getMessage() for record in caplog.records if "internal.allowlist.denied" in record.getMessage()
    ]
    assert deny_messages, "Expected structured internal deny events in logs"

    deny = "\n".join(deny_messages)
    assert "'caller_identity': 'analytics-service'" in deny
    assert "'deny_reason': 'unknown_internal_caller'" in deny
    assert "'method': 'GET'" in deny
    assert "'/api/v1/internal/data/sessions/" in deny


@pytest.mark.asyncio
async def test_internal_system_tools_rejects_missing_service_certificate(
    async_client: AsyncClient,
):
    """System-tools internal API requires service certificate even on internal path."""
    response = await async_client.post(
        "/api/v1/internal/system-tools/save-data",
        json={
            "session_id": str(uuid.uuid4()),
            "tool_args": {"data_name": "probe", "data_value": {"x": 1}},
        },
    )

    assert response.status_code == 401
    assert "Service certificate required" in str(response.json().get("detail", ""))
