"""Security tests — Certificate-type enforcement on /internal/* endpoints.

Verifies the fix for the critical vulnerability where Agent Runtime instances
could call /internal/authorize/tool-call directly using their certificate
serial number, bypassing the security model.

Covers:
  - No certificate → 403 on /internal/certificates/validate
  - No certificate → 403 on /internal/authorize/tool-call
  - Agent-instance certificate → 403 on /internal/certificates/validate
  - Agent-instance certificate → 403 on /internal/authorize/tool-call
  - Service certificate → request reaches endpoint (no auth 403)

The test uses a real in-memory CA to issue both certificate types and an async
HTTP client pointed at the FastAPI application.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.certificate_authority import (
    CertificateAuthorityService,
    CertificateType,
    IssuedCertificate,
    issue_service_certificate,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


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
async def agent_cert(
    initialized_ca: CertificateAuthorityService,
    db_session: AsyncSession,
) -> IssuedCertificate:
    """Issue an agent-instance certificate."""
    return await initialized_ca.issue(
        agent_type_id=uuid.uuid4(),
        instance_id="test-instance-security",
        db=db_session,
    )


@pytest_asyncio.fixture
async def service_cert(initialized_ca: CertificateAuthorityService) -> IssuedCertificate:
    """Issue a service certificate for 'communication-hub'."""
    return await issue_service_certificate("communication-hub")


# ── /internal/certificates/validate ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_endpoint_no_cert_returns_403(async_client: AsyncClient):
    """Calling /internal/certificates/validate without a certificate returns 403."""
    response = await async_client.post(
        "/api/v1/internal/certificates/validate",
        json={"certificate_pem": "fake", "requested_operation": "test"},
    )
    assert response.status_code == 403
    assert "certificate" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_validate_endpoint_agent_cert_returns_403(
    async_client: AsyncClient,
    agent_cert: IssuedCertificate,
):
    """Agent-instance certificates are rejected by /internal/certificates/validate."""
    response = await async_client.post(
        "/api/v1/internal/certificates/validate",
        headers={"X-Client-Certificate": agent_cert.certificate_pem},
        json={"certificate_pem": agent_cert.certificate_pem, "requested_operation": "test"},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "agent-instance" in detail or "service certificate required" in detail.lower()


@pytest.mark.asyncio
async def test_validate_endpoint_service_cert_passes_auth(
    async_client: AsyncClient,
    service_cert: IssuedCertificate,
):
    """Service certificate passes the auth check on /internal/certificates/validate.

    The endpoint will still return a validation result (valid/invalid) for the
    *body* certificate — we just confirm auth succeeds (not 403).
    """
    response = await async_client.post(
        "/api/v1/internal/certificates/validate",
        headers={"X-Client-Certificate": service_cert.certificate_pem},
        json={"certificate_pem": service_cert.certificate_pem, "requested_operation": "test"},
    )
    # Auth passes; endpoint may return 200 with valid/invalid body — not 403
    assert response.status_code != 403


# ── /internal/authorize/tool-call ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_authorize_endpoint_no_cert_returns_403(async_client: AsyncClient):
    """Calling /internal/authorize/tool-call without a certificate returns 403."""
    response = await async_client.post(
        "/api/v1/internal/authorize/tool-call",
        json={
            "certificate_serial_number": "123456",
            "tool_name": "some_tool",
        },
    )
    assert response.status_code == 403
    assert "certificate" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_authorize_endpoint_agent_cert_returns_403(
    async_client: AsyncClient,
    agent_cert: IssuedCertificate,
):
    """Agent Runtime MUST NOT be able to call /internal/authorize/tool-call.

    This is the critical security test: an agent-instance certificate must be
    rejected so that Agent Runtime processes cannot obtain identity tokens directly.
    """
    response = await async_client.post(
        "/api/v1/internal/authorize/tool-call",
        headers={"X-Client-Certificate": agent_cert.certificate_pem},
        json={
            "certificate_serial_number": agent_cert.serial_number,
            "tool_name": "some_tool",
        },
    )
    assert response.status_code == 403, (
        "SECURITY: Agent-instance certificate must NOT be accepted by "
        "/internal/authorize/tool-call — this endpoint is service-only"
    )
    detail = response.json()["detail"]
    assert "agent-instance" in detail or "service certificate required" in detail.lower()


@pytest.mark.asyncio
async def test_authorize_endpoint_service_cert_passes_auth(
    async_client: AsyncClient,
    service_cert: IssuedCertificate,
):
    """Service certificate passes auth on /internal/authorize/tool-call.

    The endpoint may still return 4xx/5xx for business-logic reasons (unknown
    serial number, etc.) but must NOT return 403 for missing/invalid *service* cert.
    """
    response = await async_client.post(
        "/api/v1/internal/authorize/tool-call",
        headers={"X-Client-Certificate": service_cert.certificate_pem},
        json={
            "certificate_serial_number": "nonexistent-serial",
            "tool_name": "some_tool",
        },
    )
    # Auth gate passed; business logic may return 200 with authorized=False, or 404/422
    assert response.status_code != 403, (
        "Service certificate should not be rejected by the auth gate"
    )


# ── CN parsing for both cert types ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_issued_agent_cert_cn_uses_legacy_format(
    initialized_ca: CertificateAuthorityService,
    db_session: AsyncSession,
):
    """Agent-instance certificates use the '{uuid}:{instance_id}' CN format."""
    from cryptography import x509 as cryptography_x509
    from cryptography.x509.oid import NameOID

    agent_type_id = uuid.uuid4()
    issued = await initialized_ca.issue(agent_type_id, "cn-format-test", db_session)

    cert = cryptography_x509.load_pem_x509_certificate(issued.certificate_pem.encode())
    cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value

    assert cn == f"{agent_type_id}:cn-format-test", (
        f"Expected CN '{agent_type_id}:cn-format-test', got {cn!r}"
    )


@pytest.mark.asyncio
async def test_issued_service_cert_cn_format(initialized_ca: CertificateAuthorityService):
    """Service certificates use the 'service:' CN prefix."""
    from cryptography import x509 as cryptography_x509
    from cryptography.x509.oid import NameOID

    issued = await initialized_ca.issue_service("my-service")
    cert = cryptography_x509.load_pem_x509_certificate(issued.certificate_pem.encode())
    cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value

    assert cn == "service:my-service", f"Unexpected CN: {cn!r}"


@pytest.mark.asyncio
async def test_validate_service_cert_returns_service_cert_type(
    initialized_ca: CertificateAuthorityService,
    db_session: AsyncSession,
):
    """Validating a service certificate returns cert_type='service' in the result."""
    issued = await issue_service_certificate("comm-hub")
    result = await initialized_ca.validate(issued.certificate_pem, db_session, "test")

    assert result.valid is True
    assert result.cert_type == CertificateType.service
    assert result.service_name == "comm-hub"
    assert result.agent_type_id is None


@pytest.mark.asyncio
async def test_validate_agent_cert_returns_agent_instance_cert_type(
    initialized_ca: CertificateAuthorityService,
    db_session: AsyncSession,
):
    """Validating an agent-instance certificate returns cert_type='agent-instance'."""
    agent_type_id = uuid.uuid4()
    issued = await initialized_ca.issue(agent_type_id, "type-check-instance", db_session)
    result = await initialized_ca.validate(issued.certificate_pem, db_session, "test")

    assert result.valid is True
    assert result.cert_type == CertificateType.agent_instance
    assert result.agent_type_id == agent_type_id
    assert result.service_name is None
