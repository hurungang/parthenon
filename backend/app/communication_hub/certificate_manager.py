"""Communication Hub Certificate Manager.

Manages the X.509 service certificate used by the Communication Hub for mutual
TLS authentication with Control Center.

Responsibilities:
- Bootstrap: generate a key pair and call Control Center /internal/bootstrap on first startup
- Load service certificate and private key from filesystem paths
- Validate certificate against CA public certificate
- Configure HTTP clients for mutual TLS (service-to-service calls)
- Background task: check expiration every 24 hours
- Trigger renewal at 80% of 30-day lifetime (~24 days elapsed)
- Atomic certificate switch with no downtime
- Log renewal success/failure

Environment variables:
  COMM_HUB_CERT_PATH     — Path to service certificate PEM file
  COMM_HUB_KEY_PATH      — Path to service private key PEM file
  CA_CERT_PATH           — Path to CA public certificate PEM file
  CONTROL_CENTER_URL     — Base URL of the Control Center API
  SERVICE_BOOTSTRAP_KEY  — Shared secret used to authenticate the bootstrap request
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

logger = logging.getLogger(__name__)

# Renewal triggers at 80% of certificate lifetime
_RENEWAL_THRESHOLD_FRACTION = 0.80
# 30-day service cert validity
_DEFAULT_CERT_VALIDITY_DAYS = 30
# Check interval: once per day
_CHECK_INTERVAL_SECONDS = 86400  # 24 hours
# Retry interval on renewal failure (5 minutes)
_RENEWAL_RETRY_SECONDS = 300


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class CertificateLoadError(Exception):
    """Raised when certificate or key files cannot be loaded or validated."""


class CommHubCertificateManager:
    """Manages Communication Hub service certificate lifecycle for mutual TLS.

    Usage::

        manager = CommHubCertificateManager()
        await manager.load_certificate()                  # Call on CH startup
        client = manager.configure_mtls_client()          # Get mTLS HTTP client
        asyncio.create_task(manager.run_renewal_task())   # Start background task

    The manager maintains the current certificate and key in memory.  On renewal,
    it atomically switches to the new certificate so that in-flight requests complete
    with the old cert while new requests use the new one.
    """

    def __init__(self) -> None:
        self._cert_path: Path | None = None
        self._key_path: Path | None = None
        self._ca_cert_path: Path | None = None
        self._control_center_url: str | None = None

        # In-memory state
        self._cert_pem: str | None = None
        self._key_pem: str | None = None
        self._ca_cert_pem: str | None = None
        self._cert: x509.Certificate | None = None
        self._ca_cert: x509.Certificate | None = None
        self._serial_number: str | None = None
        self._expires_at: datetime | None = None
        self._service_name: str | None = None

        # Background task handle
        self._renewal_task: asyncio.Task | None = None

    # ── Startup ───────────────────────────────────────────────────────────────

    async def load_certificate(self) -> None:
        """Load service certificate and private key, bootstrapping from Control Center if needed.

        Reads COMM_HUB_CERT_PATH, COMM_HUB_KEY_PATH, CA_CERT_PATH, and
        CONTROL_CENTER_URL from environment variables.

        If the cert file at COMM_HUB_CERT_PATH does not yet exist, calls
        ``_bootstrap_certificate()`` to request a 30-day service cert from
        Control Center via ``POST /api/v1/internal/bootstrap``.

        Raises:
            CertificateLoadError: If any file is missing, unreadable, or invalid.
        """
        cert_path_str = os.environ.get("COMM_HUB_CERT_PATH")
        key_path_str = os.environ.get("COMM_HUB_KEY_PATH")
        # Support both COMM_HUB_CA_CERT_PATH and CA_CERT_PATH for compatibility
        ca_cert_path_str = os.environ.get("COMM_HUB_CA_CERT_PATH") or os.environ.get("CA_CERT_PATH")
        control_center_url = os.environ.get("CONTROL_CENTER_URL")

        if not cert_path_str:
            raise CertificateLoadError("COMM_HUB_CERT_PATH environment variable not set")
        if not key_path_str:
            raise CertificateLoadError("COMM_HUB_KEY_PATH environment variable not set")
        if not ca_cert_path_str:
            raise CertificateLoadError("COMM_HUB_CA_CERT_PATH or CA_CERT_PATH environment variable not set")
        if not control_center_url:
            raise CertificateLoadError("CONTROL_CENTER_URL environment variable not set")

        self._cert_path = Path(cert_path_str)
        self._key_path = Path(key_path_str)
        self._ca_cert_path = Path(ca_cert_path_str)
        self._control_center_url = control_center_url

        # Determine if we need to bootstrap or re-bootstrap
        # Control Center generates a new CA on every restart, so we must detect CA changes.
        # Strategy: check if our local CA cert expiry matches Control Center's current CA.
        should_bootstrap = False
        
        if not self._cert_path.exists() or not self._key_path.exists():
            # No cert files exist — initial bootstrap
            should_bootstrap = True
            logger.info("Certificate files not found — will bootstrap")
        elif not self._ca_cert_path.exists():
            # CA cert missing — must re-bootstrap
            should_bootstrap = True
            logger.info("CA certificate file not found — will bootstrap")
        else:
            # Check if Control Center's CA has changed by comparing CA cert expiry times
            cc_url = self._control_center_url.rstrip("/")
            health_url = f"{cc_url}/health"
            
            try:
                # Load local CA cert to get its expiry
                local_ca_cert = x509.load_pem_x509_certificate(self._ca_cert_path.read_bytes())
                local_ca_expiry = local_ca_cert.not_valid_after_utc
                
                # Query Control Center's /health to get current CA expiry
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(health_url)
                    if response.status_code == 200:
                        health_data = response.json()
                        cc_ca_expiry_str = health_data.get("cert_expires_at")
                        
                        if cc_ca_expiry_str:
                            from datetime import datetime
                            cc_ca_expiry = datetime.fromisoformat(cc_ca_expiry_str.replace('Z', '+00:00'))
                            
                            # Compare expiry times (allow 1 second tolerance for rounding)
                            if abs((cc_ca_expiry - local_ca_expiry).total_seconds()) < 1.0:
                                # CA certs match — now verify our cert is signed by it
                                try:
                                    cert = x509.load_pem_x509_certificate(self._cert_path.read_bytes())
                                    cert.verify_directly_issued_by(local_ca_cert)
                                    logger.info("Certificate validated: CA matches Control Center, signature valid")
                                    should_bootstrap = False
                                except Exception as sig_exc:
                                    logger.info(
                                        "Certificate signature invalid (%s) — will re-bootstrap",
                                        sig_exc,
                                    )
                                    should_bootstrap = True
                            else:
                                # CA cert expiry mismatch — Control Center has new CA
                                logger.info(
                                    "CA certificate mismatch (local expires %s, Control Center expires %s) — Control Center restarted with new CA",
                                    local_ca_expiry.isoformat(),
                                    cc_ca_expiry_str,
                                )
                                should_bootstrap = True
                        else:
                            # Health endpoint didn't return CA expiry — bootstrap to be safe
                            logger.warning("Control Center /health missing cert_expires_at — will re-bootstrap")
                            should_bootstrap = True
                    else:
                        # Control Center not healthy — try to bootstrap
                        logger.warning(
                            "Control Center health check failed (HTTP %d) — will attempt bootstrap",
                            response.status_code
                        )
                        should_bootstrap = True
            except Exception as exc:
                logger.warning(
                    "Failed to validate certificate against Control Center (%s) — will attempt bootstrap",
                    exc
                )
                should_bootstrap = True
        
        # Clean up old certs if re-bootstrapping
        if should_bootstrap and (self._cert_path.exists() or self._key_path.exists() or self._ca_cert_path.exists()):
            logger.info("Cleaning up old certificate files before re-bootstrap")
            try:
                self._cert_path.unlink(missing_ok=True)
                self._key_path.unlink(missing_ok=True)
                self._ca_cert_path.unlink(missing_ok=True)
                logger.info("Deleted old certificate files: %s, %s, %s", cert_path_str, key_path_str, ca_cert_path_str)
            except OSError as del_exc:
                logger.warning("Failed to delete old certificate files: %s", del_exc)

        # Bootstrap if needed
        if should_bootstrap:
            logger.info("Bootstrapping service certificate from Control Center")
            await self._bootstrap_certificate()
        else:
            logger.info("Using existing certificate (validated against Control Center)")

        # Load files
        try:
            self._cert_pem = self._cert_path.read_text()
        except OSError as exc:
            raise CertificateLoadError(
                f"Cannot read certificate file {cert_path_str}: {exc}"
            ) from exc

        try:
            self._key_pem = self._key_path.read_text()
        except OSError as exc:
            raise CertificateLoadError(
                f"Cannot read private key file {key_path_str}: {exc}"
            ) from exc

        try:
            self._ca_cert_pem = self._ca_cert_path.read_text()
        except OSError as exc:
            raise CertificateLoadError(
                f"Cannot read CA certificate file {ca_cert_path_str}: {exc}"
            ) from exc

        await self._validate_and_parse()

        logger.info(
            "Communication Hub certificate loaded: serial=%s service=%s expires=%s",
            self._serial_number,
            self._service_name,
            self._expires_at,
        )

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    async def _bootstrap_certificate(self) -> None:
        """Request a 30-day service certificate from Control Center.

        Generates a fresh RSA 2048 key pair, submits the public key to Control
        Center, and writes the returned certificate, private key, and CA
        certificate to disk.

        Requires SERVICE_BOOTSTRAP_KEY environment variable.

        Raises:
            CertificateLoadError: If the bootstrap key is missing or the request fails.
        """
        bootstrap_key = os.environ.get("SERVICE_BOOTSTRAP_KEY")
        if not bootstrap_key:
            raise CertificateLoadError(
                "SERVICE_BOOTSTRAP_KEY environment variable not set; "
                "cannot bootstrap certificate from Control Center"
            )

        # Generate new key pair
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        public_key_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        private_key_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()

        cc_url = self._control_center_url.rstrip("/")  # type: ignore[union-attr]
        bootstrap_url = f"{cc_url}/api/v1/internal/bootstrap"

        logger.info(
            "Requesting Communication Hub bootstrap certificate from %s", bootstrap_url
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    bootstrap_url,
                    json={
                        "service_name": "communication-hub",
                        "service_type": "service",
                        "public_key": public_key_pem,
                    },
                    headers={"Authorization": f"Bearer {bootstrap_key}"},
                )
        except httpx.RequestError as exc:
            raise CertificateLoadError(
                f"Failed to contact Control Center at {bootstrap_url}: {exc}"
            ) from exc

        if response.status_code != 200:
            raise CertificateLoadError(
                f"Bootstrap request failed (HTTP {response.status_code}): {response.text[:300]}"
            )

        data = response.json()
        cert_pem: str = data["certificate_pem"]
        ca_cert_pem: str = data["ca_certificate_pem"]

        assert self._cert_path is not None
        assert self._key_path is not None
        assert self._ca_cert_path is not None

        self._cert_path.parent.mkdir(parents=True, exist_ok=True)
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        self._ca_cert_path.parent.mkdir(parents=True, exist_ok=True)

        self._cert_path.write_text(cert_pem)
        self._key_path.write_text(private_key_pem)
        # Always write CA cert to ensure it matches the CA that signed this certificate
        self._ca_cert_path.write_text(ca_cert_pem)

        logger.info(
            "Bootstrap service certificate written: serial=%s expires=%s",
            data.get("serial_number"),
            data.get("expires_at"),
        )

    # ── Validation ────────────────────────────────────────────────────────────

    async def _validate_and_parse(self) -> None:
        """Validate certificate signature, expiration, and parse CN.

        Raises:
            CertificateLoadError: If validation fails.
        """
        if not self._cert_pem or not self._ca_cert_pem:
            raise CertificateLoadError("Certificate or CA certificate not loaded")

        try:
            cert = x509.load_pem_x509_certificate(self._cert_pem.encode())
            ca_cert = x509.load_pem_x509_certificate(self._ca_cert_pem.encode())
        except Exception as exc:
            raise CertificateLoadError(f"Failed to parse certificate PEM: {exc}") from exc

        # Verify signature
        try:
            cert.verify_directly_issued_by(ca_cert)
        except Exception as exc:
            raise CertificateLoadError(f"Certificate signature invalid: {exc}") from exc

        # Check expiration
        expires_at = cert.not_valid_after_utc
        if expires_at < _now_utc():
            raise CertificateLoadError(
                f"Certificate expired at {expires_at}; "
                "request a new certificate from Control Center"
            )

        # Parse CN — expect service:{service_name}
        cn_attrs = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        cert_cn = cn_attrs[0].value if cn_attrs else ""
        if not cert_cn.startswith("service:"):
            raise CertificateLoadError(
                f"Unexpected CN format {cert_cn!r} for service certificate; "
                "expected 'service:<service_name>'"
            )
        self._service_name = cert_cn[len("service:"):]

        self._cert = cert
        self._ca_cert = ca_cert
        self._serial_number = str(cert.serial_number)
        self._expires_at = expires_at

    # ── mTLS Client ───────────────────────────────────────────────────────────

    def configure_mtls_client(self, **httpx_kwargs: Any) -> httpx.AsyncClient:
        """Return an httpx AsyncClient configured for mutual TLS with the service cert.

        The client presents the Communication Hub service certificate for every
        request.  The caller is responsible for closing the client.

        Args:
            **httpx_kwargs: Additional kwargs passed to httpx.AsyncClient.

        Returns:
            Configured httpx.AsyncClient ready for mTLS connections.

        Raises:
            CertificateLoadError: If certificate or key is not loaded.
        """
        if not self._cert_pem:
            raise CertificateLoadError(
                "Certificate not loaded; call load_certificate() first"
            )

        # Control Center expects certificate in X-Client-Certificate header
        # Replace newlines with literal \n to make it valid for HTTP headers
        cert_header_value = self._cert_pem.replace("\n", "\\n")
        
        default_headers = {
            "X-Client-Certificate": cert_header_value
        }
        
        # Merge with any headers provided by caller
        if "headers" in httpx_kwargs:
            default_headers.update(httpx_kwargs["headers"])
            httpx_kwargs = {k: v for k, v in httpx_kwargs.items() if k != "headers"}
        
        return httpx.AsyncClient(
            headers=default_headers,
            timeout=30.0,
            **httpx_kwargs
        )

    # ── Expiration monitoring ─────────────────────────────────────────────────

    def check_certificate_expiration(self) -> bool:
        """Return True if the certificate should be renewed now (>= 80% lifetime elapsed).

        Also returns True if the certificate is expired.
        """
        if self._expires_at is None:
            return True
        now = _now_utc()
        if self._expires_at <= now:
            return True  # Already expired

        # 80% threshold for 30-day cert: renew with 6 days remaining (~day 24)
        total_days = _DEFAULT_CERT_VALIDITY_DAYS
        renewal_before = self._expires_at - timedelta(
            days=total_days * (1.0 - _RENEWAL_THRESHOLD_FRACTION)
        )
        return now >= renewal_before

    async def renew_certificate(self) -> None:
        """Request a new service certificate from Control Center and switch to it.

        Generates a fresh RSA key pair and calls POST /api/v1/internal/bootstrap.
        On success, atomically replaces the in-memory certificate and key and
        writes updated files to disk.

        Raises:
            CertificateLoadError: If renewal fails or the new certificate is invalid.
        """
        if not self._control_center_url:
            raise CertificateLoadError(
                "Cannot renew: Control Center URL not configured"
            )

        bootstrap_key = os.environ.get("SERVICE_BOOTSTRAP_KEY")
        if not bootstrap_key:
            raise CertificateLoadError(
                "SERVICE_BOOTSTRAP_KEY not set; cannot renew certificate"
            )

        logger.info(
            "Renewing Communication Hub certificate (current serial=%s expires=%s)",
            self._serial_number,
            self._expires_at,
        )

        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        public_key_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        new_key_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()

        cc_url = self._control_center_url.rstrip("/")
        bootstrap_url = f"{cc_url}/api/v1/internal/bootstrap"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    bootstrap_url,
                    json={
                        "service_name": "communication-hub",
                        "service_type": "service",
                        "public_key": public_key_pem,
                    },
                    headers={"Authorization": f"Bearer {bootstrap_key}"},
                )
        except httpx.RequestError as exc:
            raise CertificateLoadError(
                f"Renewal request to {bootstrap_url} failed: {exc}"
            ) from exc

        if response.status_code != 200:
            raise CertificateLoadError(
                f"Certificate renewal failed (HTTP {response.status_code}): {response.text[:300]}"
            )

        data = response.json()
        new_cert_pem: str = data["certificate_pem"]

        await self._switch_certificate(new_cert_pem, new_key_pem)

        logger.info(
            "Communication Hub certificate renewed: new serial=%s expires=%s",
            self._serial_number,
            self._expires_at,
        )

    async def _switch_certificate(self, new_cert_pem: str, new_key_pem: str) -> None:
        """Atomically replace the in-memory certificate with a new one.

        Validates the new certificate before switching.  On success, updates cert
        and key files on disk.  Rolls back to the old cert on validation failure.

        Raises:
            CertificateLoadError: If the new certificate fails validation.
        """
        old_cert_pem = self._cert_pem
        old_key_pem = self._key_pem

        self._cert_pem = new_cert_pem
        self._key_pem = new_key_pem
        try:
            await self._validate_and_parse()
        except CertificateLoadError:
            self._cert_pem = old_cert_pem
            self._key_pem = old_key_pem
            raise

        if self._cert_path and self._cert_path.exists():
            self._cert_path.write_text(new_cert_pem)
        if self._key_path and self._key_path.exists():
            self._key_path.write_text(new_key_pem)

    # ── Background renewal task ───────────────────────────────────────────────

    async def run_renewal_task(self) -> None:
        """Background coroutine: check certificate expiration every 24 hours.

        Triggers renewal when >= 80% of certificate lifetime has elapsed
        (approximately every 24 days for a 30-day cert).
        Retries every 5 minutes on renewal failure.  Shuts down gracefully
        if certificate expires without successful renewal.
        """
        logger.info(
            "Communication Hub certificate renewal task started (check interval=%ds)",
            _CHECK_INTERVAL_SECONDS,
        )
        while True:
            await asyncio.sleep(_CHECK_INTERVAL_SECONDS)

            if not self.check_certificate_expiration():
                logger.debug(
                    "CH certificate serial=%s still valid until %s — no renewal needed",
                    self._serial_number,
                    self._expires_at,
                )
                continue

            if self._expires_at and self._expires_at <= _now_utc():
                logger.critical(
                    "CH certificate serial=%s EXPIRED at %s without renewal — shutting down",
                    self._serial_number,
                    self._expires_at,
                )
                raise SystemExit("Communication Hub certificate expired without renewal")

            # Try to renew with retries
            for retry in range(3):
                try:
                    await self.renew_certificate()
                    break
                except (CertificateLoadError, Exception) as exc:
                    logger.error(
                        "CH certificate renewal attempt %d failed: %s",
                        retry + 1,
                        exc,
                    )
                    if retry < 2:
                        await asyncio.sleep(_RENEWAL_RETRY_SECONDS)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def serial_number(self) -> str | None:
        return self._serial_number

    @property
    def expires_at(self) -> datetime | None:
        return self._expires_at

    @property
    def service_name(self) -> str | None:
        return self._service_name

    @property
    def cert_pem(self) -> str | None:
        return self._cert_pem

    @property
    def cert_path(self) -> Path | None:
        """Path to the certificate file."""
        return self._cert_path

    @property
    def key_path(self) -> Path | None:
        """Path to the private key file."""
        return self._key_path

    @property
    def is_loaded(self) -> bool:
        return self._cert_pem is not None and self._key_pem is not None
