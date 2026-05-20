"""Certificate Authority API endpoints (Control Center public-facing).

Endpoints:
  GET  /certificates/ca        — Retrieve CA public certificate
  POST /certificates/issue     — Issue new agent instance certificate (admin only)
  POST /certificates/revoke    — Revoke agent instance certificate (admin only)
"""
from __future__ import annotations

import logging
from datetime import timezone

from cryptography import x509
from fastapi import APIRouter, HTTPException, status

from app.api.deps import require_admin
from app.db.session import DbSession
from app.schemas.certificates import (
    CACertificateResponse,
    CertificateIssueRequest,
    CertificateIssueResponse,
    CertificateRevokeRequest,
    CertificateRevokeResponse,
)
from app.services.certificate_authority import (
    CertificateAuthorityService,
    get_ca_certificate,
    get_ca_certificate_pem,
)
from fastapi import Depends

logger = logging.getLogger(__name__)

CertificatesRouter = APIRouter(prefix="/certificates", tags=["certificates"])

_ca_service = CertificateAuthorityService()


@CertificatesRouter.get("/ca", response_model=CACertificateResponse)
async def get_ca_certificate_endpoint() -> CACertificateResponse:
    """Retrieve the CA public certificate for distribution to Agent Runtime instances.

    This endpoint is public (no authentication required) — the CA certificate is not
    sensitive, and agent instances need it to validate their own certificates on startup.
    """
    cert_pem = get_ca_certificate_pem()
    ca_cert = get_ca_certificate()
    if cert_pem is None or ca_cert is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CA not initialized; Control Center startup may still be in progress.",
        )

    return CACertificateResponse(
        certificate_pem=cert_pem,
        expires_at=ca_cert.not_valid_after_utc,
        serial_number=str(ca_cert.serial_number),
    )


@CertificatesRouter.post(
    "/issue",
    response_model=CertificateIssueResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def issue_certificate(
    request: CertificateIssueRequest,
    db: DbSession,
) -> CertificateIssueResponse:
    """Issue a new agent instance certificate.

    Generates a 2048-bit RSA key pair, signs a certificate with the CA private key,
    and stores the certificate in the database.  Returns the certificate PEM, private key
    PEM, serial number, and expiration timestamp.

    The private key is returned ONCE and NOT stored — the caller must store it securely.
    """
    try:
        issued = await _ca_service.issue(
            agent_type_id=request.agent_type_id,
            instance_id=request.instance_id,
            db=db,
        )
        await db.commit()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to issue certificate: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Certificate issuance failed.",
        ) from exc

    return CertificateIssueResponse(
        certificate_pem=issued.certificate_pem,
        private_key_pem=issued.private_key_pem,
        serial_number=issued.serial_number,
        expires_at=issued.expires_at,
    )


@CertificatesRouter.post(
    "/revoke",
    response_model=CertificateRevokeResponse,
    dependencies=[Depends(require_admin)],
)
async def revoke_certificate(
    request: CertificateRevokeRequest,
    db: DbSession,
    claims: dict = Depends(require_admin),
) -> CertificateRevokeResponse:
    """Revoke an agent instance certificate.

    Adds the certificate to the revocation list and marks it as revoked in the database.
    Subsequent validation attempts will return outcome=revoked.
    """
    revoked_by = str(claims.get("sub", "admin"))
    try:
        revoked_at = await _ca_service.revoke(
            serial_number=request.serial_number,
            revoked_by=revoked_by,
            reason=request.reason,
            db=db,
        )
        await db.commit()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to revoke certificate: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Certificate revocation failed.",
        ) from exc

    return CertificateRevokeResponse(
        revoked_at=revoked_at,
        serial_number=request.serial_number,
    )
