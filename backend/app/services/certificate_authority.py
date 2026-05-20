"""Certificate Authority (CA) Module — Control Center PKI for agent instance certificates.

Responsibilities:
- Generate root CA certificate on first startup (if not exists)
- Issue X.509 certificates to agent instances (CN = agent-type:instance-id)
- Validate certificate signature, expiration, and revocation status
- Revoke certificates and maintain CRL entries
- Extract agent type and instance ID from certificate CN

CA private key is encrypted at rest using the credential vault (AES-256-GCM).
"""
from __future__ import annotations

import enum
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_vault import get_vault
from app.db.models.agent_security import (
    AgentCertificateStatus,
    AgentInstanceCertificate,
    CertificateRevocationEntry,
    CertificateValidationLog,
    CertificateValidationOutcome,
)

logger = logging.getLogger(__name__)


# ── Certificate Type ──────────────────────────────────────────────────────────


class CertificateType(str, enum.Enum):
    """Certificate type encoded in CN prefix."""

    agent_instance = "agent-instance"
    service = "service"


# CA settings
_CA_KEY_BITS = 4096
_CA_VALIDITY_YEARS = 10  # Long-lived CA to avoid expiration during transactions
_CERT_VALIDITY_HOURS = 24  # Agent instance certs: 24 hours

# Service certificate validity (longer than agent instance)
_SERVICE_CERT_VALIDITY_DAYS = 30  # Service certs: 30 days

# CA persistence directory
import os
_CA_STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "certs", "control-center")

# In-memory CA state (loaded/generated on startup)
_ca_private_key: rsa.RSAPrivateKey | None = None
_ca_certificate: x509.Certificate | None = None


# ── Named result types ────────────────────────────────────────────────────────


class CertificateValidationResult(NamedTuple):
    """Result of a certificate validation check."""

    valid: bool
    agent_type_id: uuid.UUID | None
    instance_id: str | None
    serial_number: str | None
    expires_at: datetime | None
    reason: str | None  # Failure reason when valid=False
    cert_type: str | None = None  # "agent-instance" or "service"
    service_name: str | None = None  # Only populated for service certificates


class CnComponents(NamedTuple):
    """Parsed components from a certificate CN."""

    cert_type: str | None  # CertificateType value, or None if CN is invalid
    agent_type_id: uuid.UUID | None  # Only for agent-instance certs
    instance_id: str | None  # Only for agent-instance certs
    service_name: str | None  # Only for service certs


class IssuedCertificate(NamedTuple):
    """Result of certificate issuance."""

    certificate_pem: str
    private_key_pem: str
    serial_number: str
    expires_at: datetime


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _serial_from_uuid() -> int:
    """Generate a unique certificate serial number from a UUID."""
    return uuid.uuid4().int >> 64  # 64-bit positive integer


# ── CA Initialization ─────────────────────────────────────────────────────────


async def initialize_ca(db: AsyncSession) -> x509.Certificate:
    """Ensure the CA certificate exists; generate one if not.

    Persistence strategy (survives uvicorn --reload):
    1. Check in-memory cache
    2. Try to load from disk (backend/certs/control-center/)
    3. Try environment variable (cloud deployments)
    4. Generate new CA and persist to disk

    Args:
        db: Active async database session (not used directly but available for future persistence).

    Returns:
        The CA X.509 certificate object.
    """
    global _ca_private_key, _ca_certificate

    if _ca_certificate is not None:
        return _ca_certificate

    # Ensure CA storage directory exists
    os.makedirs(_CA_STORAGE_DIR, exist_ok=True)

    ca_key_path = os.path.join(_CA_STORAGE_DIR, "ca-key.pem")
    ca_cert_path = os.path.join(_CA_STORAGE_DIR, "ca-cert.pem")

    # 1. Try to load from disk (survives uvicorn --reload)
    if os.path.exists(ca_key_path) and os.path.exists(ca_cert_path):
        try:
            with open(ca_key_path, "rb") as f:
                _ca_private_key = serialization.load_pem_private_key(
                    f.read(), password=None
                )
            with open(ca_cert_path, "rb") as f:
                _ca_certificate = x509.load_pem_x509_certificate(f.read())
            
            logger.info(
                "Loaded CA from disk — serial=%s, expires=%s (survives reload)",
                _ca_certificate.serial_number,
                _ca_certificate.not_valid_after_utc,
            )
            return _ca_certificate
        except Exception as exc:
            logger.warning("Failed to load CA from disk (%s); will regenerate", exc)

    # 2. Try to load from environment variable (cloud deployments)
    vault = get_vault()
    from app.core.config import get_settings
    settings = get_settings()

    stored_key_enc: str | None = getattr(settings, "ca_private_key_encrypted", None)

    if stored_key_enc:
        try:
            key_pem = vault.decrypt(stored_key_enc)
            _ca_private_key = serialization.load_pem_private_key(
                key_pem.encode(), password=None
            )
            _ca_certificate = _build_ca_certificate(_ca_private_key)
            logger.info(
                "Loaded CA from environment — serial=%s, expires=%s",
                _ca_certificate.serial_number,
                _ca_certificate.not_valid_after_utc,
            )
            # Save to disk for future reloads
            _persist_ca_to_disk()
            return _ca_certificate
        except Exception as exc:
            logger.warning("Failed to load CA from environment (%s); generating new CA", exc)

    # 3. Generate new CA and persist to disk
    _ca_private_key = _generate_rsa_key(_CA_KEY_BITS)
    _ca_certificate = _build_ca_certificate(_ca_private_key)

    # Persist to disk so it survives uvicorn --reload
    _persist_ca_to_disk()

    logger.info(
        "Initialized new CA certificate — serial=%s, subject=%s, expires=%s",
        _ca_certificate.serial_number,
        _ca_certificate.subject.rfc4514_string(),
        _ca_certificate.not_valid_after_utc,
    )
    return _ca_certificate


def _generate_rsa_key(bits: int) -> rsa.RSAPrivateKey:
    """Generate an RSA private key."""
    from cryptography.hazmat.backends import default_backend
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=bits,
        backend=default_backend(),
    )


def _build_ca_certificate(private_key: rsa.RSAPrivateKey) -> x509.Certificate:
    """Build a self-signed root CA certificate."""
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Parthenon Agent CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Parthenon"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Control Center"),
    ])
    now = _now_utc()
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(_serial_from_uuid())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365 * _CA_VALIDITY_YEARS))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )


def get_ca_certificate() -> x509.Certificate | None:
    """Return the loaded CA certificate, or None if not initialized."""
    return _ca_certificate


def _persist_ca_to_disk() -> None:
    """Persist CA private key and certificate to disk.
    
    This allows CA to survive uvicorn --reload without regenerating.
    """
    global _ca_private_key, _ca_certificate

    if not _ca_private_key or not _ca_certificate:
        return

    os.makedirs(_CA_STORAGE_DIR, exist_ok=True)

    ca_key_path = os.path.join(_CA_STORAGE_DIR, "ca-key.pem")
    ca_cert_path = os.path.join(_CA_STORAGE_DIR, "ca-cert.pem")

    try:
        # Write private key
        key_pem = _ca_private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with open(ca_key_path, "wb") as f:
            f.write(key_pem)
        
        # Write certificate
        cert_pem = _ca_certificate.public_bytes(serialization.Encoding.PEM)
        with open(ca_cert_path, "wb") as f:
            f.write(cert_pem)
        
        logger.info("CA persisted to disk at %s (survives reload)", _CA_STORAGE_DIR)
    except Exception as exc:
        logger.error("Failed to persist CA to disk: %s", exc)


def get_ca_certificate_pem() -> str | None:
    """Return the CA certificate in PEM format, or None if not initialized."""
    if _ca_certificate is None:
        return None
    return _ca_certificate.public_bytes(serialization.Encoding.PEM).decode()


# ── Certificate Issuance ──────────────────────────────────────────────────────


async def issue_agent_certificate(
    agent_type_id: uuid.UUID,
    instance_id: str,
    db: AsyncSession,
) -> IssuedCertificate:
    """Issue a new X.509 certificate for an agent instance.

    Generates a new RSA key pair for the agent, signs it with the CA private key,
    stores the certificate in the ``agent_instance_certificates`` table, and
    returns the certificate PEM, private key PEM, serial number, and expiration.

    CN format: ``agent-type-id:instance-id``

    Args:
        agent_type_id: UUID of the agent type.
        instance_id: Unique instance identifier (e.g., hostname or job ID).
        db: Active async database session.

    Returns:
        IssuedCertificate with PEM-encoded certificate, private key, serial number, and expiration.

    Raises:
        RuntimeError: If the CA has not been initialized.
    """
    if _ca_private_key is None or _ca_certificate is None:
        raise RuntimeError("CA not initialized; call initialize_ca() first")

    # Generate agent key pair
    agent_private_key = _generate_rsa_key(2048)

    now = _now_utc()
    expires_at = now + timedelta(hours=_CERT_VALIDITY_HOURS)
    serial = _serial_from_uuid()
    cn = f"{agent_type_id}:{instance_id}"

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Parthenon Agent"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(_ca_certificate.subject)
        .public_key(agent_private_key.public_key())
        .serial_number(serial)
        .not_valid_before(now)
        .not_valid_after(expires_at)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(agent_private_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(_ca_private_key.public_key()),
            critical=False,
        )
        .sign(_ca_private_key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = agent_private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    serial_str = str(serial)

    # Store in database
    record = AgentInstanceCertificate(
        agent_type_id=agent_type_id,
        instance_id=instance_id,
        certificate_pem=cert_pem,
        serial_number=serial_str,
        issued_at=now,
        expires_at=expires_at,
        status=AgentCertificateStatus.active,
    )
    db.add(record)
    await db.flush()

    logger.info(
        "Issued certificate for agent_type=%s instance=%s serial=%s expires=%s",
        agent_type_id,
        instance_id,
        serial_str,
        expires_at,
    )
    return IssuedCertificate(
        certificate_pem=cert_pem,
        private_key_pem=key_pem,
        serial_number=serial_str,
        expires_at=expires_at,
    )


async def issue_service_certificate(service_name: str) -> IssuedCertificate:
    """Issue a service certificate for internal service-to-service authentication.

    Service certificates use CN format ``service:{service_name}`` and are NOT
    stored in the agent_instance_certificates table (they are managed as files
    by operators).  Only the CA signature ensures validity; revocation is handled
    by rotating the certificate.

    Args:
        service_name: Logical name for the service (e.g. ``communication-hub``).

    Returns:
        IssuedCertificate with PEM-encoded certificate and private key.

    Raises:
        RuntimeError: If the CA has not been initialized.
    """
    if _ca_private_key is None or _ca_certificate is None:
        raise RuntimeError("CA not initialized; call initialize_ca() first")

    service_key = _generate_rsa_key(2048)
    now = _now_utc()
    expires_at = now + timedelta(hours=_CERT_VALIDITY_HOURS * 30)  # 30-day validity for services
    serial = _serial_from_uuid()
    cn = f"service:{service_name}"

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Parthenon Service"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(_ca_certificate.subject)
        .public_key(service_key.public_key())
        .serial_number(serial)
        .not_valid_before(now)
        .not_valid_after(expires_at)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(service_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(_ca_private_key.public_key()),
            critical=False,
        )
        .sign(_ca_private_key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = service_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    serial_str = str(serial)

    logger.info(
        "Issued service certificate for service=%s serial=%s expires=%s",
        service_name,
        serial_str,
        expires_at,
    )
    return IssuedCertificate(
        certificate_pem=cert_pem,
        private_key_pem=key_pem,
        serial_number=serial_str,
        expires_at=expires_at,
    )


# ── Bootstrap Certificate Issuance ────────────────────────────────────────────


async def issue_certificate_from_public_key(
    public_key_pem: str,
    cn: str,
    validity_hours: int,
) -> IssuedCertificate:
    """Sign an externally-provided public key and issue a certificate.

    Used by the bootstrap endpoint where the calling service generates its own
    key pair locally and submits only the public key for signing.  The private
    key is held exclusively by the caller; ``IssuedCertificate.private_key_pem``
    is always the empty string.

    CN conventions:
    - Agent Runtime: ``agent-instance:agent-runtime:{instance_uuid}``
    - Communication Hub: ``service:communication-hub``

    Args:
        public_key_pem: PEM-encoded RSA public key from the calling service.
        cn: Subject CN to embed in the certificate.
        validity_hours: Certificate validity in hours (24 for agent_instance, 720 for service).

    Returns:
        IssuedCertificate with PEM certificate, empty private_key_pem, serial, and expiry.

    Raises:
        RuntimeError: If the CA has not been initialized.
        ValueError: If ``public_key_pem`` cannot be parsed.
    """
    if _ca_private_key is None or _ca_certificate is None:
        raise RuntimeError("CA not initialized; call initialize_ca() first")

    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    try:
        public_key = load_pem_public_key(public_key_pem.encode())
    except Exception as exc:
        raise ValueError(f"Invalid public key PEM: {exc}") from exc

    now = _now_utc()
    expires_at = now + timedelta(hours=validity_hours)
    serial = _serial_from_uuid()

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Parthenon"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(_ca_certificate.subject)
        .public_key(public_key)
        .serial_number(serial)
        .not_valid_before(now)
        .not_valid_after(expires_at)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(_ca_private_key.public_key()),
            critical=False,
        )
        .sign(_ca_private_key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    serial_str = str(serial)

    logger.info(
        "Issued bootstrap certificate: cn=%s serial=%s expires=%s",
        cn,
        serial_str,
        expires_at,
    )
    return IssuedCertificate(
        certificate_pem=cert_pem,
        private_key_pem="",  # Caller holds the private key
        serial_number=serial_str,
        expires_at=expires_at,
    )


# ── Certificate Validation ────────────────────────────────────────────────────


async def validate_certificate(
    cert_pem: str,
    db: AsyncSession,
    validated_by_service: str = "control-center",
    requested_operation: str | None = None,
) -> CertificateValidationResult:
    """Validate a certificate PEM against the CA.

    Checks:
    1. Certificate signature against CA public certificate
    2. Certificate expiration
    3. Certificate revocation list

    Logs every validation attempt in ``certificate_validation_logs``.

    Args:
        cert_pem: PEM-encoded certificate to validate.
        db: Active async database session.
        validated_by_service: Service performing validation (for audit log).
        requested_operation: Operation being authorized (for audit log).

    Returns:
        CertificateValidationResult with valid status and agent identity details on success.
    """
    if _ca_certificate is None:
        return CertificateValidationResult(
            valid=False,
            agent_type_id=None,
            instance_id=None,
            serial_number=None,
            expires_at=None,
            reason="ca_not_initialized",
        )

    serial_number: str | None = None
    cert_cn: str = "unknown"

    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        serial_number = str(cert.serial_number)
        cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        cert_cn = cn_attrs[0].value if cn_attrs else "unknown"

        # 1. Verify signature (handles RSA with PKCS1v15 and EC keys correctly)
        try:
            cert.verify_directly_issued_by(_ca_certificate)
        except Exception:
            outcome = CertificateValidationOutcome.invalid_signature
            await _log_validation(
                db, serial_number, cert_cn, outcome, "Signature verification failed",
                validated_by_service, requested_operation,
            )
            return CertificateValidationResult(
                valid=False,
                agent_type_id=None,
                instance_id=None,
                serial_number=serial_number,
                expires_at=None,
                reason="invalid_signature",
            )

        # 2. Check expiration
        now = _now_utc()
        expires_at = cert.not_valid_after_utc
        if expires_at < now:
            outcome = CertificateValidationOutcome.expired
            await _log_validation(
                db, serial_number, cert_cn, outcome, "Certificate expired",
                validated_by_service, requested_operation,
            )
            return CertificateValidationResult(
                valid=False,
                agent_type_id=None,
                instance_id=None,
                serial_number=serial_number,
                expires_at=expires_at,
                reason="expired",
            )

        # 3. Check revocation
        revoked = await _is_revoked(serial_number, db)
        if revoked:
            outcome = CertificateValidationOutcome.revoked
            await _log_validation(
                db, serial_number, cert_cn, outcome, "Certificate revoked",
                validated_by_service, requested_operation,
            )
            return CertificateValidationResult(
                valid=False,
                agent_type_id=None,
                instance_id=None,
                serial_number=serial_number,
                expires_at=expires_at,
                reason="revoked",
            )

        # Parse CN to extract certificate type and components
        cn = extract_cn_components(cert_cn)
        if cn.cert_type is None:
            outcome = CertificateValidationOutcome.invalid_signature
            await _log_validation(
                db, serial_number, cert_cn, outcome, f"Invalid CN format: {cert_cn!r}",
                validated_by_service, requested_operation,
            )
            return CertificateValidationResult(
                valid=False,
                agent_type_id=None,
                instance_id=None,
                serial_number=serial_number,
                expires_at=expires_at,
                reason="invalid_cn",
            )

        # Valid
        await _log_validation(
            db, serial_number, cert_cn, CertificateValidationOutcome.valid, None,
            validated_by_service, requested_operation,
        )
        return CertificateValidationResult(
            valid=True,
            agent_type_id=cn.agent_type_id,
            instance_id=cn.instance_id,
            serial_number=serial_number,
            expires_at=expires_at,
            reason=None,
            cert_type=cn.cert_type,
            service_name=cn.service_name,
        )

    except Exception as exc:
        logger.exception("Unexpected error validating certificate: %s", exc)
        await _log_validation(
            db, serial_number or "unknown", cert_cn,
            CertificateValidationOutcome.invalid_signature, str(exc),
            validated_by_service, requested_operation,
        )
        return CertificateValidationResult(
            valid=False,
            agent_type_id=None,
            instance_id=None,
            serial_number=serial_number,
            expires_at=None,
            reason="parse_error",
        )


async def _is_revoked(serial_number: str, db: AsyncSession) -> bool:
    """Check if a serial number is in the revocation list."""
    result = await db.execute(
        select(CertificateRevocationEntry).where(
            CertificateRevocationEntry.serial_number == serial_number
        )
    )
    return result.scalar_one_or_none() is not None


async def _log_validation(
    db: AsyncSession,
    serial_number: str,
    cert_cn: str,
    outcome: CertificateValidationOutcome,
    failure_reason: str | None,
    validated_by_service: str,
    requested_operation: str | None,
) -> None:
    """Insert a certificate validation audit log entry."""
    entry = CertificateValidationLog(
        certificate_serial_number=serial_number,
        certificate_cn=cert_cn,
        validated_at=_now_utc(),
        outcome=outcome,
        failure_reason=failure_reason,
        validated_by_service=validated_by_service,
        requested_operation=requested_operation,
    )
    db.add(entry)
    await db.flush()


# ── Certificate Revocation ────────────────────────────────────────────────────


async def revoke_certificate(
    serial_number: str,
    revoked_by: str,
    reason: str,
    db: AsyncSession,
) -> datetime:
    """Revoke a certificate by adding it to the CRL and updating the certificate record.

    Args:
        serial_number: Certificate serial number to revoke.
        revoked_by: Admin user ID or service that initiated revocation.
        reason: Human-readable revocation reason.
        db: Active async database session.

    Returns:
        Revocation timestamp.

    Raises:
        ValueError: If the certificate is not found or already revoked.
    """
    # Update certificate record
    result = await db.execute(
        select(AgentInstanceCertificate).where(
            AgentInstanceCertificate.serial_number == serial_number
        )
    )
    cert_record = result.scalar_one_or_none()
    if cert_record is None:
        raise ValueError(f"Certificate with serial number {serial_number!r} not found")
    if cert_record.revoked_at is not None:
        raise ValueError(f"Certificate {serial_number!r} is already revoked")

    revoked_at = _now_utc()
    cert_record.revoked_at = revoked_at
    cert_record.revocation_reason = reason
    cert_record.status = AgentCertificateStatus.revoked

    # Add CRL entry
    crl_entry = CertificateRevocationEntry(
        serial_number=serial_number,
        revoked_at=revoked_at,
        revoked_by=revoked_by,
        reason=reason,
    )
    db.add(crl_entry)
    await db.flush()

    logger.info(
        "Revoked certificate serial=%s by=%s reason=%s",
        serial_number,
        revoked_by,
        reason,
    )
    return revoked_at


# ── CN Extraction ─────────────────────────────────────────────────────────────


def extract_cn_components(cert_cn: str) -> CnComponents:
    """Parse certificate type and components from CN.

    Supported formats:

    - New agent-instance: ``agent-instance:{agent_type_id}:{instance_id}``
    - Legacy agent-instance: ``{agent_type_id}:{instance_id}``  (backward compatible)
    - Service: ``service:{service_name}``

    Args:
        cert_cn: Certificate CN value.

    Returns:
        CnComponents with cert_type set on success, or cert_type=None on parse error.
    """
    _invalid = CnComponents(cert_type=None, agent_type_id=None, instance_id=None, service_name=None)
    try:
        if cert_cn.startswith("service:"):
            service_name = cert_cn[len("service:"):]
            if not service_name:
                logger.warning("Service CN %r has empty service name", cert_cn)
                return _invalid
            return CnComponents(
                cert_type=CertificateType.service,
                agent_type_id=None,
                instance_id=None,
                service_name=service_name,
            )

        if cert_cn.startswith("agent-instance:"):
            rest = cert_cn[len("agent-instance:"):]
            colon_idx = rest.index(":")
            type_part = rest[:colon_idx]
            instance_part = rest[colon_idx + 1:]
            # type_part may be a UUID (legacy agent) or a plain string (e.g. "agent-runtime")
            try:
                agent_type_uuid: uuid.UUID | None = uuid.UUID(type_part)
            except ValueError:
                agent_type_uuid = None
            return CnComponents(
                cert_type=CertificateType.agent_instance,
                agent_type_id=agent_type_uuid,
                instance_id=instance_part,
                service_name=None,
            )

        # Legacy / current format: "{uuid}:{instance_id}" — treated as agent-instance
        colon_idx = cert_cn.index(":")
        type_part = cert_cn[:colon_idx]
        instance_part = cert_cn[colon_idx + 1:]
        return CnComponents(
            cert_type=CertificateType.agent_instance,
            agent_type_id=uuid.UUID(type_part),
            instance_id=instance_part,
            service_name=None,
        )
    except (ValueError, IndexError):
        logger.warning("Cannot parse CN %r — unrecognised format", cert_cn)
        return _invalid


# ── Main Service Class ────────────────────────────────────────────────────────


class CertificateAuthorityService:
    """Stateless service facade exposing CA operations.

    All state (CA key and certificate) is held in module-level globals so
    the single CA instance is shared across the application lifecycle.
    """

    async def initialize(self, db: AsyncSession) -> x509.Certificate:
        return await initialize_ca(db)

    async def issue(
        self,
        agent_type_id: uuid.UUID,
        instance_id: str,
        db: AsyncSession,
    ) -> IssuedCertificate:
        return await issue_agent_certificate(agent_type_id, instance_id, db)

    async def issue_service(
        self,
        service_name: str,
    ) -> IssuedCertificate:
        return await issue_service_certificate(service_name)

    async def issue_from_public_key(
        self,
        public_key_pem: str,
        cn: str,
        validity_hours: int,
    ) -> IssuedCertificate:
        return await issue_certificate_from_public_key(public_key_pem, cn, validity_hours)

    async def validate(
        self,
        cert_pem: str,
        db: AsyncSession,
        validated_by_service: str = "control-center",
        requested_operation: str | None = None,
    ) -> CertificateValidationResult:
        return await validate_certificate(
            cert_pem, db, validated_by_service, requested_operation
        )

    async def revoke(
        self,
        serial_number: str,
        revoked_by: str,
        reason: str,
        db: AsyncSession,
    ) -> datetime:
        return await revoke_certificate(serial_number, revoked_by, reason, db)

    def get_ca_pem(self) -> str | None:
        return get_ca_certificate_pem()

    def extract_cn_components(self, cert_cn: str) -> CnComponents:
        return extract_cn_components(cert_cn)
