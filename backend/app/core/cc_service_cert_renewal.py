"""Control Center — self-renewal of its own service certificate.

CC's service certificate (``certs/control-center/service-cert.pem``, signed
by the Parthenon CA) authenticates every CC → CH / CC → AR internal call.
Historically it was issued ONCE at first startup and never renewed — when it
expired, every internal call silently broke with certificate rejections.

This module closes that gap:

- **At CC startup** (after the CA is initialized) and on a **daily asyncio
  check**, the on-disk certificate's expiry is read; if it is missing,
  unreadable, expired, or within the renewal window
  (``CC_SERVICE_CERT_RENEWAL_DAYS``, default 30 days remaining), a fresh
  certificate is issued from the CA via
  ``certificate_authority.issue_service_certificate`` (the app's own issuance
  code — NOT an openssl subprocess) and written to
  ``service-cert.pem`` / ``service-key.pem``.
- Failures are logged and never crash startup; a still-valid certificate is
  left untouched.

Renewal is safe for the mesh: every peer validates the certificate against
the CA per-request (subject ``CN=service:control-center``), so swapping in a
fresh cert does not require peer-side updates.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509

logger = logging.getLogger(__name__)

#: Env var controlling the renewal window (days of remaining validity below
#: which the certificate is re-issued).
RENEWAL_DAYS_ENV = "CC_SERVICE_CERT_RENEWAL_DAYS"
DEFAULT_RENEWAL_THRESHOLD_DAYS = 30

#: Default on-disk certificate directory (relative to the backend workdir,
#: matching the existing ``_ensure_cc_service_certificate`` layout).
DEFAULT_CERT_DIR = Path("certs/control-center")
CERT_FILENAME = "service-cert.pem"
KEY_FILENAME = "service-key.pem"

#: Daily check cadence.
DAILY_CHECK_SECONDS = 24 * 60 * 60

#: Issuance parameters for the renewed certificate: 365-day lifetime,
#: loopback SANs, and clientAuth+serverAuth extended key usage.
RENEWAL_VALIDITY_DAYS = 365
RENEWAL_SAN_DNS = ["localhost"]
RENEWAL_SAN_IPS = ["127.0.0.1"]

# Module-level handle for the daily loop task (cancelled on shutdown).
_renewal_task: asyncio.Task | None = None


def get_renewal_threshold_days() -> int:
    """Renewal window in days (env ``CC_SERVICE_CERT_RENEWAL_DAYS``)."""
    raw = os.environ.get(RENEWAL_DAYS_ENV, "").strip()
    try:
        return max(1, int(raw)) if raw else DEFAULT_RENEWAL_THRESHOLD_DAYS
    except ValueError:
        logger.warning(
            "Invalid %s=%r — using default %s days",
            RENEWAL_DAYS_ENV, raw, DEFAULT_RENEWAL_THRESHOLD_DAYS,
        )
        return DEFAULT_RENEWAL_THRESHOLD_DAYS


def read_cert_expiry(cert_path: Path) -> datetime | None:
    """Read the certificate's ``not_valid_after`` (UTC), None if unreadable."""
    try:
        pem = Path(cert_path).read_bytes()
        cert = x509.load_pem_x509_certificate(pem)
        expiry = getattr(cert, "not_valid_after_utc", None)
        if expiry is None:  # cryptography < 42 fallback
            expiry = cert.not_valid_after.replace(tzinfo=timezone.utc)
        return expiry
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("Failed to read certificate expiry from %s", cert_path)
        return None


def is_within_renewal_window(
    expiry: datetime | None,
    now: datetime | None = None,
    threshold_days: int = DEFAULT_RENEWAL_THRESHOLD_DAYS,
) -> bool:
    """True when the cert is missing, unreadable, expired, or near expiry."""
    if expiry is None:
        return True
    now = now or datetime.now(timezone.utc)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry <= now + timedelta(days=threshold_days)


async def renew_cc_service_certificate_if_needed(
    cert_dir: Path | None = None,
    threshold_days: int | None = None,
    *,
    issue_fn=None,
) -> bool:
    """Re-issue CC's service certificate when expired / near expiry.

    Args:
        cert_dir: Certificate directory (default ``certs/control-center``).
        threshold_days: Renewal window override (default: env / 30 days).
        issue_fn: Injectable issuance coroutine (tests); defaults to the CA
            module's ``issue_service_certificate``.

    Returns:
        True when a new certificate was issued and written, False otherwise.
    """
    cert_dir = Path(cert_dir or DEFAULT_CERT_DIR)
    cert_path = cert_dir / CERT_FILENAME
    key_path = cert_dir / KEY_FILENAME
    threshold = threshold_days if threshold_days is not None else get_renewal_threshold_days()

    expiry = read_cert_expiry(cert_path)
    if not is_within_renewal_window(expiry, threshold_days=threshold):
        logger.info(
            "CC service certificate is valid until %s (> %s days) — no renewal needed",
            expiry, threshold,
        )
        return False

    remaining = (
        "missing/unreadable" if expiry is None else f"expires {expiry}"
    )
    logger.warning(
        "CC service certificate requires renewal (%s, renewal window %s days) — re-issuing",
        remaining, threshold,
    )

    if issue_fn is None:
        from app.services.certificate_authority import issue_service_certificate
        issue_fn = issue_service_certificate

    try:
        issued = await issue_fn(
            "control-center",
            validity_days=RENEWAL_VALIDITY_DAYS,
            san_dns_names=RENEWAL_SAN_DNS,
            san_ips=RENEWAL_SAN_IPS,
            include_tls_extended_key_usage=True,
        )
        cert_dir.mkdir(parents=True, exist_ok=True)
        # Atomic-ish write: key + cert replaced only after both PEMs exist.
        tmp_cert, tmp_key = cert_path.with_suffix(".tmp"), key_path.with_suffix(".tmp")
        tmp_cert.write_text(issued.certificate_pem)
        tmp_key.write_text(issued.private_key_pem)
        os.replace(tmp_cert, cert_path)
        os.replace(tmp_key, key_path)
        logger.info(
            "CC service certificate RENEWED: serial=%s expires=%s "
            "(subject CN=service:control-center, SAN localhost/127.0.0.1, "
            "clientAuth+serverAuth)",
            issued.serial_number, issued.expires_at,
        )
        return True
    except Exception:
        # Never crash startup — the old (possibly still valid) cert stays.
        logger.exception(
            "CC service certificate renewal FAILED — keeping existing "
            "certificate; internal CC→CH/AR calls may fail if the cert is "
            "expired. Ensure the CA is initialized."
        )
        return False


async def run_daily_renewal_loop(cert_dir: Path | None = None) -> None:
    """Daily background check: renew if needed, then sleep. Never raises."""
    while True:
        try:
            await renew_cc_service_certificate_if_needed(cert_dir)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily CC service-certificate renewal check failed")
        await asyncio.sleep(DAILY_CHECK_SECONDS)


def start_daily_renewal_task(cert_dir: Path | None = None) -> asyncio.Task | None:
    """Spawn the daily renewal loop (idempotent; safe at startup)."""
    global _renewal_task
    if _renewal_task is not None and not _renewal_task.done():
        return _renewal_task
    _renewal_task = asyncio.create_task(run_daily_renewal_loop(cert_dir))
    logger.info("Daily CC service-certificate renewal check started")
    return _renewal_task


async def stop_daily_renewal_task() -> None:
    """Cancel the daily renewal loop (CC shutdown)."""
    global _renewal_task
    if _renewal_task is not None:
        _renewal_task.cancel()
        try:
            await _renewal_task
        except (asyncio.CancelledError, Exception):
            pass
        _renewal_task = None
