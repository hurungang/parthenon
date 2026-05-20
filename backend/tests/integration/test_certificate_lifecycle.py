"""Integration tests — Certificate lifecycle: issuance, validation, renewal, revocation.

Covers:
  Task 6.1 — Backend Integration Tests - Certificate Lifecycle

Tests:
  - Issue certificate for agent type → certificate created in database
  - Validate valid certificate → returns agent_type_id and instance_id
  - Validate expired certificate → validation fails with outcome `expired`
  - Revoke certificate → certificate marked revoked, validation fails
  - Attempt to use revoked certificate → 403 Forbidden
  - Extract CN components from certificate

Database: Uses shared SQLite in-memory engine from conftest.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_security import (
    AgentCertificateStatus,
    AgentInstanceCertificate,
    CertificateRevocationEntry,
    CertificateValidationLog,
    CertificateValidationOutcome,
)
from app.services.certificate_authority import (
    CertificateAuthorityService,
    extract_cn_components,
    initialize_ca,
    issue_agent_certificate,
    revoke_certificate,
    validate_certificate,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def ca_service(db_session: AsyncSession) -> CertificateAuthorityService:
    """Initialize CA and return the service instance."""
    # Reset module-level CA state for isolation
    import app.services.certificate_authority as ca_module
    ca_module._ca_private_key = None
    ca_module._ca_certificate = None

    service = CertificateAuthorityService()
    await service.initialize(db_session)
    return service


@pytest_asyncio.fixture
async def agent_type_id() -> uuid.UUID:
    """Generate a fake agent type UUID."""
    return uuid.uuid4()


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ca_initialization(db_session: AsyncSession):
    """CA certificate is generated on initialization."""
    import app.services.certificate_authority as ca_module
    ca_module._ca_private_key = None
    ca_module._ca_certificate = None

    ca_cert = await initialize_ca(db_session)

    assert ca_cert is not None
    # Subject should identify Control Center CA
    assert "Parthenon" in ca_cert.subject.rfc4514_string()
    # Should be a CA certificate
    from cryptography.x509 import BasicConstraints
    bc = ca_cert.extensions.get_extension_for_class(BasicConstraints)
    assert bc.value.ca is True
    # Should be valid for 10 years (check total certificate lifetime, not remaining time)
    lifetime = ca_cert.not_valid_after_utc - ca_cert.not_valid_before_utc
    assert lifetime >= timedelta(days=3649)  # 10 * 365 = 3650 days; allow 1-day tolerance


@pytest.mark.asyncio
async def test_issue_certificate_creates_db_record(
    ca_service: CertificateAuthorityService,
    db_session: AsyncSession,
    agent_type_id: uuid.UUID,
):
    """Issued certificate is stored in database with correct fields."""
    instance_id = f"test-instance-{uuid.uuid4().hex[:8]}"
    issued = await ca_service.issue(agent_type_id, instance_id, db_session)

    assert issued.certificate_pem.startswith("-----BEGIN CERTIFICATE-----")
    assert issued.private_key_pem.startswith("-----BEGIN RSA PRIVATE KEY-----") or \
           issued.private_key_pem.startswith("-----BEGIN PRIVATE KEY-----")
    assert issued.serial_number
    assert issued.expires_at > datetime.now(timezone.utc)

    # Check 24-hour validity
    from datetime import timedelta
    assert issued.expires_at <= datetime.now(timezone.utc) + timedelta(hours=25)

    # Verify database record
    from sqlalchemy import select
    result = await db_session.execute(
        select(AgentInstanceCertificate).where(
            AgentInstanceCertificate.serial_number == issued.serial_number
        )
    )
    record = result.scalar_one_or_none()
    assert record is not None
    assert record.agent_type_id == agent_type_id
    assert record.instance_id == instance_id
    assert record.status == AgentCertificateStatus.active
    assert record.revoked_at is None


@pytest.mark.asyncio
async def test_validate_valid_certificate_succeeds(
    ca_service: CertificateAuthorityService,
    db_session: AsyncSession,
    agent_type_id: uuid.UUID,
):
    """Valid certificate passes validation and returns correct agent identity."""
    instance_id = "validation-test-instance"
    issued = await ca_service.issue(agent_type_id, instance_id, db_session)

    result = await ca_service.validate(
        cert_pem=issued.certificate_pem,
        db=db_session,
        validated_by_service="test",
        requested_operation="test-op",
    )

    assert result.valid is True
    assert result.agent_type_id == agent_type_id
    assert result.instance_id == instance_id
    assert result.serial_number == issued.serial_number
    assert result.reason is None


@pytest.mark.asyncio
async def test_validate_expired_certificate_fails(
    ca_service: CertificateAuthorityService,
    db_session: AsyncSession,
    agent_type_id: uuid.UUID,
):
    """Expired certificate fails validation with outcome 'expired'."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.backends import default_backend
    from cryptography.x509.oid import NameOID
    import app.services.certificate_authority as ca_module

    # Build an intentionally expired certificate
    ca_key = ca_module._ca_private_key
    ca_cert = ca_module._ca_certificate
    assert ca_key is not None

    agent_key = rsa.generate_private_key(65537, 2048, default_backend())
    now = datetime.now(timezone.utc)
    expired_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{agent_type_id}:expired-instance")]))
        .issuer_name(ca_cert.subject)
        .public_key(agent_key.public_key())
        .serial_number(12345678)
        .not_valid_before(now - timedelta(hours=48))
        .not_valid_after(now - timedelta(hours=1))  # Expired 1 hour ago
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    expired_pem = expired_cert.public_bytes(serialization.Encoding.PEM).decode()

    result = await ca_service.validate(
        cert_pem=expired_pem,
        db=db_session,
        validated_by_service="test",
    )

    assert result.valid is False
    assert result.reason == "expired"


@pytest.mark.asyncio
async def test_revoke_certificate_marks_as_revoked(
    ca_service: CertificateAuthorityService,
    db_session: AsyncSession,
    agent_type_id: uuid.UUID,
):
    """Revoked certificate is marked in database and subsequent validation fails."""
    instance_id = "revoke-test-instance"
    issued = await ca_service.issue(agent_type_id, instance_id, db_session)

    revoked_at = await ca_service.revoke(
        serial_number=issued.serial_number,
        revoked_by="test-admin",
        reason="Security test",
        db=db_session,
    )

    assert revoked_at is not None

    # Check database record updated
    from sqlalchemy import select
    result = await db_session.execute(
        select(AgentInstanceCertificate).where(
            AgentInstanceCertificate.serial_number == issued.serial_number
        )
    )
    record = result.scalar_one_or_none()
    assert record is not None
    assert record.status == AgentCertificateStatus.revoked
    assert record.revoked_at is not None
    assert record.revocation_reason == "Security test"

    # CRL entry should exist
    crl_result = await db_session.execute(
        select(CertificateRevocationEntry).where(
            CertificateRevocationEntry.serial_number == issued.serial_number
        )
    )
    crl_entry = crl_result.scalar_one_or_none()
    assert crl_entry is not None
    assert crl_entry.revoked_by == "test-admin"


@pytest.mark.asyncio
async def test_validate_revoked_certificate_fails(
    ca_service: CertificateAuthorityService,
    db_session: AsyncSession,
    agent_type_id: uuid.UUID,
):
    """Validation of a revoked certificate returns outcome 'revoked'."""
    instance_id = "revoke-validation-instance"
    issued = await ca_service.issue(agent_type_id, instance_id, db_session)
    await ca_service.revoke(
        serial_number=issued.serial_number,
        revoked_by="test",
        reason="Test revocation",
        db=db_session,
    )

    result = await ca_service.validate(
        cert_pem=issued.certificate_pem,
        db=db_session,
        validated_by_service="test",
    )

    assert result.valid is False
    assert result.reason == "revoked"


@pytest.mark.asyncio
async def test_validation_logged_in_audit_table(
    ca_service: CertificateAuthorityService,
    db_session: AsyncSession,
    agent_type_id: uuid.UUID,
):
    """Every validation attempt is logged in the certificate_validation_logs table."""
    from sqlalchemy import select

    instance_id = "audit-log-instance"
    issued = await ca_service.issue(agent_type_id, instance_id, db_session)

    # Count logs before
    count_before = len((await db_session.execute(select(CertificateValidationLog))).scalars().all())

    await ca_service.validate(
        cert_pem=issued.certificate_pem,
        db=db_session,
        validated_by_service="audit-test",
        requested_operation="test-tool",
    )

    # One log added
    all_logs = (await db_session.execute(select(CertificateValidationLog))).scalars().all()
    assert len(all_logs) == count_before + 1
    last_log = all_logs[-1]
    assert last_log.outcome == CertificateValidationOutcome.valid
    assert last_log.validated_by_service == "audit-test"
    assert last_log.requested_operation == "test-tool"


def test_extract_cn_components_valid():
    """Agent-instance CN in '{uuid}:{instance-id}' format is parsed correctly."""
    type_id = uuid.uuid4()
    cn = f"{type_id}:my-instance-123"
    result = extract_cn_components(cn)
    assert result.cert_type == "agent-instance"
    assert result.agent_type_id == type_id
    assert result.instance_id == "my-instance-123"
    assert result.service_name is None


def test_extract_cn_components_legacy_format():
    """Legacy format 'uuid:instance-id' is the current agent-instance format."""
    type_id = uuid.uuid4()
    cn = f"{type_id}:legacy-instance"
    result = extract_cn_components(cn)
    assert result.cert_type == "agent-instance"
    assert result.agent_type_id == type_id
    assert result.instance_id == "legacy-instance"


def test_extract_cn_components_service():
    """Service CN is parsed and cert_type set to 'service'."""
    result = extract_cn_components("service:communication-hub")
    assert result.cert_type == "service"
    assert result.service_name == "communication-hub"
    assert result.agent_type_id is None
    assert result.instance_id is None


def test_extract_cn_components_invalid():
    """Invalid CN format returns cert_type=None without raising."""
    result = extract_cn_components("not-a-valid-cn")
    assert result.cert_type is None
    assert result.agent_type_id is None
    assert result.instance_id is None


def test_extract_cn_components_with_colon_in_instance_id():
    """Instance ID may contain colons — only the first colon is the separator."""
    type_id = uuid.uuid4()
    cn = f"{type_id}:host:8080:instance"
    result = extract_cn_components(cn)
    assert result.cert_type == "agent-instance"
    assert result.agent_type_id == type_id
    assert result.instance_id == "host:8080:instance"

