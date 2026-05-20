"""Internal bootstrap endpoint — certificate issuance for peer services.

Peer services (Agent Runtime, Communication Hub) call this endpoint on startup
to obtain a CA-signed X.509 certificate before they have any mTLS credential.
Because the caller has no certificate yet, authentication uses a per-service
bootstrap key validated in the ``Authorization: Bearer <key>`` header.

Environment variables required on Control Center:
  AGENT_RUNTIME_BOOTSTRAP_KEY — shared secret for agent-runtime service
  COMM_HUB_BOOTSTRAP_KEY      — shared secret for communication-hub service

The endpoint is network-isolated in production (not routed through the public
API gateway).  In dev it is accessible via the standard HTTP port but requires
a valid bootstrap key.
"""
from __future__ import annotations

import logging
import os
import secrets
import uuid

from fastapi import APIRouter, Header, HTTPException

from app.schemas.certificates import BootstrapRequest, BootstrapResponse
from app.services.certificate_authority import CertificateAuthorityService

logger = logging.getLogger(__name__)

InternalBootstrapRouter = APIRouter(
    prefix="/internal/bootstrap",
    tags=["internal"],
)

_ca_service = CertificateAuthorityService()

# Validity in hours per service_type
_AGENT_INSTANCE_VALIDITY_HOURS = 24
_SERVICE_VALIDITY_HOURS = 24 * 30  # 30 days

# Allowed service names and the env var that holds their bootstrap key
_SERVICE_KEY_ENV: dict[str, str] = {
    "agent-runtime": "AGENT_RUNTIME_BOOTSTRAP_KEY",
    "communication-hub": "COMM_HUB_BOOTSTRAP_KEY",
    "test-service": "TEST_SERVICE_BOOTSTRAP_KEY",
}


@InternalBootstrapRouter.post(
    "",
    response_model=BootstrapResponse,
    summary="Issue a CA-signed certificate to a bootstrapping peer service",
)
async def bootstrap_service_certificate(
    request: BootstrapRequest,
    authorization: str = Header(..., alias="Authorization"),
) -> BootstrapResponse:
    """Issue a CA-signed certificate to a peer service on startup.

    The caller supplies its service name, certificate type, and locally generated
    public key.  Control Center signs the public key and returns the certificate
    plus the CA public certificate for validation.

    Auth: ``Authorization: Bearer <service-specific-bootstrap-key>``

    Validity:
    - ``agent_instance``: 24 hours (Agent Runtime)
    - ``service``: 30 days (Communication Hub)

    CN formats:
    - ``agent_instance``: ``agent-instance:agent-runtime:{uuid}``
    - ``service``: ``service:{service_name}``
    """
    # ── Validate Authorization header ─────────────────────────────────────────
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="invalid bootstrap key for service")

    bearer_key = authorization[7:]
    if not bearer_key:
        raise HTTPException(status_code=401, detail="invalid bootstrap key for service")

    # ── Map service_name to expected bootstrap key ────────────────────────────
    key_env_var = _SERVICE_KEY_ENV.get(request.service_name)
    if key_env_var is None:
        logger.warning(
            "Bootstrap rejected: unknown service_name=%r", request.service_name
        )
        raise HTTPException(status_code=401, detail="invalid bootstrap key for service")

    expected_key = os.environ.get(key_env_var)
    if not expected_key:
        logger.error(
            "Bootstrap key env var %s is not set; cannot bootstrap service=%s",
            key_env_var,
            request.service_name,
        )
        raise HTTPException(status_code=503, detail="bootstrap not configured")

    if not secrets.compare_digest(bearer_key, expected_key):
        logger.warning(
            "Bootstrap rejected: invalid key for service=%r", request.service_name
        )
        raise HTTPException(status_code=401, detail="invalid bootstrap key for service")

    # ── Determine CN and validity ─────────────────────────────────────────────
    if request.service_type == "agent_instance":
        validity_hours = _AGENT_INSTANCE_VALIDITY_HOURS
        # Use hex format (32 chars) instead of hyphenated (36 chars) to fit in 64-char CN limit
        instance_uuid = uuid.uuid4().hex
        cn = f"agent-instance:{request.service_name}:{instance_uuid}"
    else:
        validity_hours = _SERVICE_VALIDITY_HOURS
        cn = f"service:{request.service_name}"

    # ── Issue certificate ─────────────────────────────────────────────────────
    try:
        issued = await _ca_service.issue_from_public_key(
            public_key_pem=request.public_key,
            cn=cn,
            validity_hours=validity_hours,
        )
    except ValueError as exc:
        logger.warning("Bootstrap failed for service=%r: %s", request.service_name, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.error("CA not initialized during bootstrap: %s", exc)
        raise HTTPException(status_code=503, detail="CA not initialized") from exc

    ca_pem = _ca_service.get_ca_pem() or ""

    logger.info(
        "Bootstrap certificate issued: service=%s type=%s cn=%s serial=%s expires=%s",
        request.service_name,
        request.service_type,
        cn,
        issued.serial_number,
        issued.expires_at,
    )

    return BootstrapResponse(
        certificate_pem=issued.certificate_pem,
        ca_certificate_pem=ca_pem,
        serial_number=issued.serial_number,
        expires_at=issued.expires_at,
    )
