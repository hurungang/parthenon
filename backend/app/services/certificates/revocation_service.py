"""Certificate revocation service.

Provides certificate revocation checking and local (no-DB) certificate
validation for all three Parthenon services:

- **Control Center** (DB access): uses :meth:`RevocationService.check_local`
  which queries the ``certificate_revocation_entries`` table directly.
- **Agent Runtime / Communication Hub** (no DB): uses
  :meth:`RevocationService.check_remote` which calls Control Center's
  lightweight ``GET /api/v1/internal/certificates/revoked/{serial}`` endpoint.

Also exports :func:`validate_service_cert_locally`, which performs certificate
signature, expiry, and CN validation without any database or network access.
Agent Runtime and Communication Hub middleware use this to validate inbound
Control Center service certificates before accepting requests.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import NamedTuple

from cryptography import x509
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── Result type ────────────────────────────────────────────────────────────────


class ServiceCertValidationResult(NamedTuple):
    """Result of a local (no-DB) service certificate validation check."""

    valid: bool
    serial_number: str | None
    cert_type: str | None  # "service" or "agent-instance"
    service_name: str | None  # Only populated for service certs (CN = service:<name>)
    reason: str | None  # Failure reason when valid=False; None on success


# ── Local validation (no DB, no network) ─────────────────────────────────────


def validate_service_cert_locally(
    cert_pem: str,
    ca_cert_pem: str,
    expected_service_name: str | None = None,
) -> ServiceCertValidationResult:
    """Validate a certificate locally without database or network access.

    Checks:

    1. Certificate can be parsed as a valid X.509 PEM.
    2. Certificate signature is issued by the trusted CA.
    3. Certificate has not expired.
    4. CN follows the ``service:<name>`` or ``agent-instance:*`` format.
    5. If *expected_service_name* is given, CN must equal
       ``service:<expected_service_name>``.

    Does **not** check revocation — use :class:`RevocationService` for that.

    Args:
        cert_pem: PEM-encoded certificate to validate.
        ca_cert_pem: PEM-encoded CA public certificate (trusted anchor).
        expected_service_name: When set, the CN must equal
            ``service:<expected_service_name>`` for validation to succeed.

    Returns:
        :class:`ServiceCertValidationResult` with ``valid=True`` on success, or
        ``valid=False`` with a ``reason`` string describing the failure.
    """
    # Parse certificate
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
    except Exception as exc:
        return ServiceCertValidationResult(
            valid=False,
            serial_number=None,
            cert_type=None,
            service_name=None,
            reason=f"cannot_parse_certificate: {exc}",
        )

    # Parse CA certificate
    try:
        ca_cert = x509.load_pem_x509_certificate(ca_cert_pem.encode())
    except Exception as exc:
        return ServiceCertValidationResult(
            valid=False,
            serial_number=None,
            cert_type=None,
            service_name=None,
            reason=f"cannot_parse_ca_certificate: {exc}",
        )

    serial_number = str(cert.serial_number)

    # 1. Verify signature (cert must be directly issued by the CA)
    try:
        cert.verify_directly_issued_by(ca_cert)
    except Exception:
        return ServiceCertValidationResult(
            valid=False,
            serial_number=serial_number,
            cert_type=None,
            service_name=None,
            reason="invalid_signature",
        )

    # 2. Check expiry
    if cert.not_valid_after_utc < _now_utc():
        return ServiceCertValidationResult(
            valid=False,
            serial_number=serial_number,
            cert_type=None,
            service_name=None,
            reason="expired",
        )

    # 3. Parse CN to determine certificate type
    cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    cn = cn_attrs[0].value if cn_attrs else ""

    cert_type: str | None = None
    service_name: str | None = None

    if cn.startswith("service:"):
        cert_type = "service"
        service_name = cn[len("service:"):]
    elif cn.startswith("agent-instance:"):
        cert_type = "agent-instance"
    else:
        return ServiceCertValidationResult(
            valid=False,
            serial_number=serial_number,
            cert_type=None,
            service_name=None,
            reason=f"invalid_cn_format: {cn!r}",
        )

    # 4. Enforce expected service name when caller requires a specific service
    if expected_service_name is not None and service_name != expected_service_name:
        return ServiceCertValidationResult(
            valid=False,
            serial_number=serial_number,
            cert_type=cert_type,
            service_name=service_name,
            reason=(
                f"unexpected_service: expected service:{expected_service_name}, "
                f"got {cn!r}"
            ),
        )

    return ServiceCertValidationResult(
        valid=True,
        serial_number=serial_number,
        cert_type=cert_type,
        service_name=service_name,
        reason=None,
    )


# ── Revocation service ────────────────────────────────────────────────────────


class RevocationService:
    """Certificate revocation checker for all three Parthenon services.

    **Control Center** (has DB access)::

        svc = RevocationService()
        revoked = await svc.check_local(serial_number, db)

    **Agent Runtime** (no DB, agent-instance cert)::

        svc = RevocationService()
        revoked = await svc.check_remote(serial_number, control_center_url)

    **Communication Hub** (no DB, service cert)::

        svc = RevocationService()
        revoked = await svc.check_remote(serial_number, control_center_url)
    """

    async def check_local(self, serial_number: str, db: object) -> bool:
        """Check if a serial number is revoked using the local database.

        Used by Control Center which has direct database access.

        Args:
            serial_number: Certificate serial number (string representation).
            db: Active async ``AsyncSession`` instance.

        Returns:
            ``True`` if the certificate is in the revocation list; ``False`` otherwise.
        """
        from sqlalchemy import select

        from app.db.models.agent_security import CertificateRevocationEntry

        result = await db.execute(  # type: ignore[union-attr]
            select(CertificateRevocationEntry).where(
                CertificateRevocationEntry.serial_number == serial_number
            )
        )
        return result.scalar_one_or_none() is not None

    async def check_remote(
        self,
        serial_number: str,
        control_center_url: str,
    ) -> bool:
        """Check if a serial number is revoked by querying Control Center.

        Used by Agent Runtime and Communication Hub which have no database
        access.  Calls the lightweight
        ``GET /api/v1/internal/certificates/revoked/{serial}`` endpoint on
        Control Center (network-isolated in production).

        **Fail-open**: if Control Center is unreachable the method returns
        ``False`` so that a temporary CC outage does not block all traffic.
        High-security deployments should implement a local CRL cache as a
        future enhancement.

        Args:
            serial_number: Certificate serial number to check.
            control_center_url: Base URL of the Control Center API
                (e.g. ``http://control-center:8000``).

        Returns:
            ``True`` if the certificate is revoked; ``False`` if not revoked
            or if Control Center is unreachable.
        """
        import httpx

        url = (
            f"{control_center_url.rstrip('/')}"
            f"/api/v1/internal/certificates/revoked/{serial_number}"
        )
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                return bool(data.get("revoked", False))
            logger.warning(
                "Revocation check returned unexpected status %s for serial=%s",
                response.status_code,
                serial_number,
            )
            return False
        except Exception as exc:
            logger.warning(
                "Revocation check failed for serial=%s (failing open): %s",
                serial_number,
                exc,
            )
            # Fail open: a temporary CC outage must not block all traffic
            return False
