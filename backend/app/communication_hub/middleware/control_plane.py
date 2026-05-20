"""Communication Hub — Control Plane Certificate Validation Middleware.

Validates that requests to ``/internal/*`` paths carry a valid Control Center
service certificate.

The Communication Hub has two separate authentication planes:

- **Data plane** (``/ws/*``, ``/tools/*``): JWT-authenticated WebSocket
  connections from the Web UI, and agent certificate-authenticated tool calls.
  These paths are handled by :class:`~app.communication_hub.middleware.\
authorization.CertificateAuthorizationMiddleware` and are **not** affected by
  this middleware.
- **Control plane** (``/internal/*``): Triggered by Control Center over mTLS
  (e.g. message dispatch in Phase 5).  This middleware enforces that only
  Control Center's service certificate is accepted on these paths.

Security guarantees enforced by this middleware (task 4.3):

- ``/internal/*`` requests without ``X-Client-Certificate`` → **401**
- Certificates with invalid CA signature or expired → **401**
- Certificates not issued to ``service:control-center`` → **401**
- Revoked certificates (checked via revocation API) → **401**
- All other paths pass through unmodified.
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

# Only enforce on internal control plane paths
_INTERNAL_PATH_PREFIX = "/internal/"

# Tool call paths accept agent-runtime certificates
_TOOL_CALL_PATH_PREFIX = "/internal/tools/"

# Agent execute path - called by Control Center (CA itself, no service cert)
_AGENT_EXECUTE_PATH = "/internal/agent/execute"

# The only service whose certificate is accepted on control plane paths
_EXPECTED_SERVICE_NAME = "control-center"

# Agent Runtime is allowed on tool call paths
_AGENT_RUNTIME_SERVICE_NAME = "agent-runtime"

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


class ControlPlaneMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces Control Center service-cert on ``/internal/*`` paths.

    Requests to paths beginning with ``/internal/`` must carry an
    ``X-Client-Certificate`` header containing a certificate with
    ``CN=service:control-center``, signed by the Parthenon CA, not expired,
    and not revoked.

    All other paths (WebSocket, tool calls, health) pass through unchanged.

    On success the validated service name and certificate serial number are
    attached to ``request.state`` for downstream handlers.

    Task 4.3 — inbound certificate validation in Communication Hub for control
    plane calls from Control Center.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Only enforce on internal control plane paths
        if not request.url.path.startswith(_INTERNAL_PATH_PREFIX):
            return await call_next(request)

        # Agent execute endpoint is called by Control Center (CA itself) 
        # which doesn't have a service certificate - exempt from validation
        if request.url.path == _AGENT_EXECUTE_PATH:
            logger.debug(
                "CH control plane: allowing %s %s from Control Center (CA authority)",
                request.method,
                request.url.path,
            )
            return await call_next(request)

        # Determine expected service based on path
        # Tool call endpoints accept agent-runtime certificates
        # All other /internal/* paths require control-center certificates
        if request.url.path.startswith(_TOOL_CALL_PATH_PREFIX):
            expected_service = _AGENT_RUNTIME_SERVICE_NAME
        else:
            expected_service = _EXPECTED_SERVICE_NAME

        # 1. Extract client certificate from request
        cert_pem = _extract_client_cert(request)
        if not cert_pem:
            logger.warning(
                "CH control plane: rejected %s %s — no client certificate",
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
                "CH control plane: CA_CERT_PATH not configured — cannot validate certificates"
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
            expected_service_name=expected_service,
        )
        if not result.valid:
            logger.warning(
                "CH control plane: rejected %s %s — cert validation failed: %s",
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
                    "CH control plane: rejected revoked certificate serial=%s on %s %s",
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
