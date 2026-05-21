"""Agent Runtime — Inbound Certificate Validation Middleware.

Validates that all incoming requests (except health and docs paths) carry a
valid Communication Hub service certificate. Agent Runtime only accepts
execution/delegation requests from Communication Hub; any request without a
``CN=service:communication-hub`` certificate issued by the Parthenon CA is rejected.

Security guarantees enforced by this middleware (task 4.2):

- Requests without ``X-Client-Certificate`` header → **401 Unauthorized**
- Certificates with invalid CA signature → **401 Unauthorized**
- Certificates that have expired → **401 Unauthorized**
- Certificates not issued to ``service:control-center`` → **401 Unauthorized**
- Revoked certificates (checked via Control Center revocation API) → **401**
- ``/health``, ``/docs``, ``/redoc``, ``/openapi.json`` are exempt (liveness
  probes and Swagger UI must not require mTLS).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.services.certificates.revocation_service import (
    RevocationService,
    validate_service_cert_locally,
)

logger = logging.getLogger(__name__)

# Paths that bypass certificate enforcement (liveness probes, docs)
_EXEMPT_PATHS: frozenset[str] = frozenset({
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
})

# The only service whose certificate is accepted by Agent Runtime
_EXPECTED_SERVICE_NAME = "communication-hub"

_revocation_service = RevocationService()


def _load_ca_cert_pem() -> str | None:
    """Load the CA public certificate PEM from the path in ``CA_CERT_PATH``."""
    ca_path = os.environ.get("CA_CERT_PATH")
    if not ca_path:
        return None
    try:
        return Path(ca_path).read_text()
    except OSError as exc:
        logger.error("Cannot read CA certificate from %s: %s", ca_path, exc)
        return None


def _get_control_center_url() -> str:
    return os.environ.get("CONTROL_CENTER_URL", "").rstrip("/")


def _extract_client_cert(request: Request) -> str | None:
    """Extract client certificate PEM from the request.

    Checks ``X-Client-Certificate`` header first (reverse-proxy / nginx
    ``$ssl_client_cert`` forwarding), then ``request.state.client_certificate``
    (set by a TLS termination layer if present).
    
    For HTTP development mode, the header contains escaped newlines (\\n) that
    must be restored to actual newlines for PEM parsing.
    """
    header_cert = request.headers.get("X-Client-Certificate")
    if header_cert:
        try:
            # First try URL decoding (nginx $ssl_client_cert is URL-encoded)
            from urllib.parse import unquote
            cert = unquote(header_cert)
            # Then restore newlines from HTTP header escaping (\\n → \n)
            cert = cert.replace("\\n", "\n")
            return cert
        except Exception:
            return header_cert
    return getattr(request.state, "client_certificate", None)


class ControlCenterCertificateMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces Communication Hub service-cert authentication on AR routes.

    Applied to every request except those in :data:`_EXEMPT_PATHS`.  The
    middleware validates the ``X-Client-Certificate`` header against the CA
    certificate loaded from ``CA_CERT_PATH``, confirms the CN is
    ``service:communication-hub``, and checks revocation via Control Center's
    lightweight revocation API.

    On success the validated service name and certificate serial number are
    attached to ``request.state`` for downstream handlers.

    Task 4.2 — inbound certificate validation in Agent Runtime.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Exempt paths pass through without certificate enforcement
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        # 1. Extract client certificate from request
        cert_pem = _extract_client_cert(request)
        if not cert_pem:
            logger.warning(
                "AR inbound: rejected %s %s — no client certificate",
                request.method,
                request.url.path,
            )
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Service certificate required — no client certificate provided"
                },
            )

        # 2. Load CA cert for local validation (no DB / network needed for this step)
        ca_cert_pem = _load_ca_cert_pem()
        if not ca_cert_pem:
            logger.error(
                "AR inbound: CA_CERT_PATH not configured — cannot validate certificates"
            )
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Certificate validation unavailable — CA not configured"
                },
            )

        # 3. Validate signature, expiry, and CN locally (no DB / network)
        result = validate_service_cert_locally(
            cert_pem=cert_pem,
            ca_cert_pem=ca_cert_pem,
            expected_service_name=_EXPECTED_SERVICE_NAME,
        )
        if not result.valid:
            logger.warning(
                "AR inbound: rejected %s %s — cert validation failed: %s",
                request.method,
                request.url.path,
                result.reason,
            )
            return JSONResponse(
                status_code=401,
                content={"detail": f"Invalid certificate: {result.reason}"},
            )

        # 4. Check revocation via Control Center (task 4.4)
        control_center_url = _get_control_center_url()
        if control_center_url and result.serial_number:
            revoked = await _revocation_service.check_remote(
                serial_number=result.serial_number,
                control_center_url=control_center_url,
            )
            if revoked:
                logger.warning(
                    "AR inbound: rejected revoked certificate serial=%s on %s %s",
                    result.serial_number,
                    request.method,
                    request.url.path,
                )
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Certificate has been revoked"},
                )

        # 5. Attach validated identity to request state for downstream handlers
        request.state.service_name = result.service_name
        request.state.service_cert_serial = result.serial_number

        return await call_next(request)
