"""Internal certificate validation endpoint — service-to-service only.

Called by the Communication Hub to validate agent client certificates
before processing tool call requests.

Authentication: Internal service-to-service call.  In production this endpoint
should be network-isolated (not exposed to the public internet).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.api.deps import require_service_certificate
from app.db.session import DbSession
from app.schemas.certificates import (
    CertificateValidateRequest,
    CertificateValidateResponse,
)
from app.services.certificate_authority import CertificateAuthorityService

logger = logging.getLogger(__name__)

InternalCertificatesRouter = APIRouter(
    prefix="/internal/certificates",
    tags=["internal"],
)

_ca_service = CertificateAuthorityService()


@InternalCertificatesRouter.get(
    "/revoked/{serial_number}",
    summary="Lightweight revocation check for Agent Runtime and Communication Hub",
)
async def check_certificate_revoked(
    serial_number: str,
    db: DbSession,
) -> dict:
    """Return whether a certificate serial number appears in the revocation list.

    This endpoint is intentionally unauthenticated.  It is network-isolated in
    production (not routed through the public API gateway) and reveals only a
    boolean revocation status — no PII or sensitive data.

    Agent Runtime uses this endpoint from its inbound certificate validation
    middleware to confirm Control Center's service certificate has not been
    revoked.  Communication Hub may use the same path when its service cert
    cannot authenticate to the protected ``/validate`` endpoint.

    Task 4.4 — revocation check for all three services.
    """
    from sqlalchemy import select

    from app.db.models.agent_security import CertificateRevocationEntry

    result = await db.execute(
        select(CertificateRevocationEntry).where(
            CertificateRevocationEntry.serial_number == serial_number
        )
    )
    revoked = result.scalar_one_or_none() is not None
    return {"revoked": revoked, "serial_number": serial_number}


@InternalCertificatesRouter.post(
    "/validate",
    response_model=CertificateValidateResponse,
    dependencies=[Depends(require_service_certificate)],
)
async def validate_certificate_internal(
    request: CertificateValidateRequest,
    db: DbSession,
) -> CertificateValidateResponse:
    """Validate an agent client certificate (internal service-to-service call).

    The Communication Hub calls this endpoint on every tool call to verify the
    agent's certificate before processing the request.

    Returns validation result including agent_type_id and instance_id on success,
    or reason for failure on rejection.
    """
    result = await _ca_service.validate(
        cert_pem=request.certificate_pem,
        db=db,
        validated_by_service="communication-hub",
        requested_operation=request.requested_operation,
    )
    await db.commit()  # Persist validation log

    return CertificateValidateResponse(
        valid=result.valid,
        agent_type_id=result.agent_type_id,
        instance_id=result.instance_id,
        serial_number=result.serial_number,
        expires_at=result.expires_at,
        reason=result.reason,
    )
