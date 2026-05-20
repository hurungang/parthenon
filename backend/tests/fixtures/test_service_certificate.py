"""Test Service Certificate Manager.

Provides pytest-friendly certificate management for integration tests.
Bootstraps via ``POST /api/v1/internal/bootstrap`` with ``service_type=test_service``
and issues a 30-day service certificate with CN ``service:test-service``.

No background renewal tasks — the certificate is obtained once per test session.

Environment variables (all optional; defaults shown):
    TEST_SERVICE_BOOTSTRAP_KEY  — bootstrap key; must match CC's config (required for live tests)
    CONTROL_CENTER_URL          — base URL of Control Center (default: http://localhost:8000)
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)

_SERVICE_NAME = "test-service"
_SERVICE_TYPE = "test_service"
_DEFAULT_CC_URL = "http://localhost:8000"


class TestServiceBootstrapError(Exception):
    """Raised when the test service certificate cannot be bootstrapped."""


class TestServiceCertificateManager:
    """Manages the test service X.509 certificate for integration test sessions.

    This class mirrors the Communication Hub certificate manager pattern but is
    designed for pytest:

    * No background renewal task — certificate is obtained once per session.
    * Constructor accepts parameters with environment variable fallbacks.
    * Provides :meth:`get_header_client` for HTTP header-based cert forwarding
      (matching how ``require_service_certificate`` reads the cert in dev mode).
    * Cleans up temporary files via :meth:`cleanup`.

    Usage::

        manager = TestServiceCertificateManager()
        await manager.bootstrap()                         # Once per session
        async with manager.get_header_client("http://localhost:8000") as client:
            response = await client.get("/health")
        manager.cleanup()                                 # On teardown

    """

    def __init__(
        self,
        cc_url: str | None = None,
        bootstrap_key: str | None = None,
    ) -> None:
        self._cc_url = (
            (cc_url or os.environ.get("CONTROL_CENTER_URL") or _DEFAULT_CC_URL).rstrip("/")
        )
        self._bootstrap_key = bootstrap_key or os.environ.get("TEST_SERVICE_BOOTSTRAP_KEY") or ""

        # In-memory certificate state
        self._cert_pem: str | None = None
        self._key_pem: str | None = None
        self._ca_cert_pem: str | None = None
        self._serial_number: str | None = None
        self._expires_at: str | None = None
        self._cn: str | None = None

        # Temporary directory for cert files (SSL context needs files)
        self._tmpdir: tempfile.TemporaryDirectory | None = None  # type: ignore[type-arg]
        self._cert_file: Path | None = None
        self._key_file: Path | None = None
        self._ca_cert_file: Path | None = None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_bootstrapped(self) -> bool:
        """True if a certificate has been successfully bootstrapped."""
        return self._cert_pem is not None and self._key_pem is not None

    @property
    def serial_number(self) -> str | None:
        return self._serial_number

    @property
    def expires_at(self) -> str | None:
        return self._expires_at

    @property
    def cert_pem(self) -> str | None:
        return self._cert_pem

    @property
    def ca_cert_pem(self) -> str | None:
        return self._ca_cert_pem

    @property
    def cn(self) -> str | None:
        return self._cn

    def get_parsed_cert(self) -> x509.Certificate:
        """Return the parsed X.509 certificate object.

        Raises:
            TestServiceBootstrapError: If not yet bootstrapped.
        """
        if not self._cert_pem:
            raise TestServiceBootstrapError("Not bootstrapped; call bootstrap() first")
        return x509.load_pem_x509_certificate(self._cert_pem.encode())

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    async def bootstrap(self) -> None:
        """Request a 30-day service certificate from Control Center.

        Generates a fresh RSA 2048 key pair, submits the public key to Control
        Center as ``service_type=test_service``, and stores the returned
        certificate and CA certificate in memory and in a temporary directory.

        Raises:
            TestServiceBootstrapError: If the bootstrap key is missing, Control
                Center is unreachable, or the request fails.
        """
        if not self._bootstrap_key:
            raise TestServiceBootstrapError(
                "TEST_SERVICE_BOOTSTRAP_KEY is not set; "
                "cannot bootstrap test service certificate from Control Center"
            )

        # Generate a fresh RSA 2048 key pair
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        public_key_pem = (
            private_key.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )
        private_key_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()

        bootstrap_url = f"{self._cc_url}/api/v1/internal/bootstrap"
        logger.info("Bootstrapping test service certificate from %s", bootstrap_url)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    bootstrap_url,
                    json={
                        "service_name": _SERVICE_NAME,
                        "service_type": _SERVICE_TYPE,
                        "public_key": public_key_pem,
                    },
                    headers={"Authorization": f"Bearer {self._bootstrap_key}"},
                )
        except httpx.RequestError as exc:
            raise TestServiceBootstrapError(
                f"Failed to contact Control Center at {bootstrap_url}: {exc}"
            ) from exc

        if response.status_code != 200:
            raise TestServiceBootstrapError(
                f"Bootstrap request failed (HTTP {response.status_code}): "
                f"{response.text[:300]}"
            )

        data = response.json()
        self._cert_pem = data["certificate_pem"]
        self._key_pem = private_key_pem
        self._ca_cert_pem = data["ca_certificate_pem"]
        self._serial_number = data.get("serial_number")
        self._expires_at = data.get("expires_at")

        # Parse CN from the issued certificate
        cert = x509.load_pem_x509_certificate(self._cert_pem.encode())
        attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        self._cn = attrs[0].value if attrs else None

        # Write to temp files for potential SSL context use
        self._write_temp_files()

        logger.info(
            "Test service certificate bootstrapped: cn=%s serial=%s expires=%s",
            self._cn,
            self._serial_number,
            self._expires_at,
        )

    def _write_temp_files(self) -> None:
        """Write certificate, key, and CA cert to a temporary directory."""
        if self._tmpdir is None:
            self._tmpdir = tempfile.TemporaryDirectory(prefix="parthenon_test_certs_")
        tmpdir_path = Path(self._tmpdir.name)
        self._cert_file = tmpdir_path / "cert.pem"
        self._key_file = tmpdir_path / "key.pem"
        self._ca_cert_file = tmpdir_path / "ca.pem"
        self._cert_file.write_text(self._cert_pem or "")
        self._key_file.write_text(self._key_pem or "")
        self._ca_cert_file.write_text(self._ca_cert_pem or "")

    # ── Client factory ────────────────────────────────────────────────────────

    def get_header_client(
        self,
        base_url: str,
        timeout: float = 30.0,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.AsyncClient:
        """Return an ``httpx.AsyncClient`` that forwards the cert via header.

        In development (plain HTTP), mTLS is simulated by forwarding the
        certificate PEM in the ``X-Client-Certificate`` header.  This matches
        how ``require_service_certificate`` and
        ``ControlCenterCertificateMiddleware`` read client certs in non-TLS
        deployments.

        Args:
            base_url: Target service base URL (e.g. ``http://localhost:8000``).
            timeout: Default request timeout in seconds.
            extra_headers: Additional headers to include in every request.

        Returns:
            Configured ``httpx.AsyncClient``; caller must close it (or use as
            an async context manager).

        Raises:
            TestServiceBootstrapError: If not yet bootstrapped.
        """
        if not self.is_bootstrapped:
            raise TestServiceBootstrapError(
                "Certificate not bootstrapped; call bootstrap() first"
            )

        # Encode PEM for safe HTTP header transport
        header_cert = (self._cert_pem or "").replace("\n", "\\n")
        headers: dict[str, str] = {"X-Client-Certificate": header_cert}
        if extra_headers:
            headers.update(extra_headers)

        return httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers=headers,
        )

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Delete temporary certificate files."""
        if self._tmpdir is not None:
            try:
                self._tmpdir.cleanup()
            except OSError as exc:
                logger.warning("Failed to clean up cert temp directory: %s", exc)
            self._tmpdir = None
