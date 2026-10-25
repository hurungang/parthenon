"""Tests for CC service-certificate self-renewal (``cc_service_cert_renewal``).

CC's service certificate authenticates every CC → CH / CC → AR internal call.
It used to be issued once and never renewed — silent expiry broke the mesh.
These tests pin the renewal contract:

- expired / near-expiry / missing cert → re-issued (new expiry > old,
  subject ``CN=service:control-center`` preserved)
- still-valid cert → untouched
- issuance failure → logged, NOT raised, existing files intact
- ``CC_SERVICE_CERT_RENEWAL_DAYS`` env controls the window
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.core import cc_service_cert_renewal as renewal


def _make_cert_pem(cn: str, days_valid: int) -> tuple[str, str, datetime]:
    """Self-signed test cert; returns (cert_pem, key_pem, expiry_utc)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=days_valid)
    not_before = (
        now - timedelta(days=-days_valid + 1) if days_valid < 0 else now - timedelta(minutes=5)
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Parthenon Service"),
        ]))
        .issuer_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "Parthenon Root CA"),
        ]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(expiry)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    return cert_pem, key_pem, expiry


def _issue_fn_factory(issued_log: list, days_valid: int = 365):
    """Stand-in for the CA module's ``issue_service_certificate``."""

    async def _issue(service_name: str, *, validity_days: int | None = None,
                     san_dns_names=None, san_ips=None,
                     include_tls_extended_key_usage: bool = False):
        issued_log.append({
            "service_name": service_name,
            "validity_days": validity_days,
            "san_dns": san_dns_names,
            "san_ips": san_ips,
            "eku": include_tls_extended_key_usage,
        })
        cert_pem, key_pem, expiry = _make_cert_pem(
            f"service:{service_name}", validity_days or days_valid
        )
        return SimpleNamespace(
            certificate_pem=cert_pem,
            private_key_pem=key_pem,
            serial_number="test-serial",
            expires_at=expiry,
        )

    return _issue


def _write_cert(cert_dir: Path, days_valid: int) -> datetime:
    cert_pem, key_pem, expiry = _make_cert_pem("service:control-center", days_valid)
    (cert_dir / renewal.CERT_FILENAME).write_text(cert_pem)
    (cert_dir / renewal.KEY_FILENAME).write_text(key_pem)
    return expiry


def _read_expiry(cert_dir: Path) -> datetime:
    cert = x509.load_pem_x509_certificate(
        (cert_dir / renewal.CERT_FILENAME).read_bytes()
    )
    return cert.not_valid_after_utc


@pytest.fixture
def cert_dir(tmp_path, monkeypatch):
    """Isolated cert dir + clean env (not the repo's certs/ directory)."""
    d = tmp_path / "certs" / "control-center"
    d.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(renewal.RENEWAL_DAYS_ENV, raising=False)
    return d


class TestRenewal:
    @pytest.mark.asyncio
    async def test_expired_cert_is_reissued(self, cert_dir):
        """Expired cert → re-issued; new expiry later than the old; subject kept."""
        old_expiry = _write_cert(cert_dir, days_valid=-1)  # already expired
        issued_log: list = []

        renewed = await renewal.renew_cc_service_certificate_if_needed(
            cert_dir, issue_fn=_issue_fn_factory(issued_log)
        )

        assert renewed is True
        new_expiry = _read_expiry(cert_dir)
        assert new_expiry > old_expiry + timedelta(days=300)
        # Subject preserved (CN the mesh validates).
        cert = x509.load_pem_x509_certificate(
            (cert_dir / renewal.CERT_FILENAME).read_bytes()
        )
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        assert cn == "service:control-center"
        # Renewal issuance parameters: 365 days, loopback SANs, TLS EKUs.
        assert issued_log[0]["validity_days"] == 365
        assert issued_log[0]["san_dns"] == ["localhost"]
        assert issued_log[0]["san_ips"] == ["127.0.0.1"]
        assert issued_log[0]["eku"] is True
        # Key file rewritten too (matched pair).
        assert "PRIVATE KEY-----" in (cert_dir / renewal.KEY_FILENAME).read_text()
        # No .tmp leftovers.
        assert not list(cert_dir.glob("*.tmp"))

    @pytest.mark.asyncio
    async def test_valid_cert_is_untouched(self, cert_dir):
        """Cert with plenty of validity left → no renewal, files unchanged."""
        _write_cert(cert_dir, days_valid=60)
        before = (cert_dir / renewal.CERT_FILENAME).read_bytes()
        issued_log: list = []

        renewed = await renewal.renew_cc_service_certificate_if_needed(
            cert_dir, issue_fn=_issue_fn_factory(issued_log)
        )

        assert renewed is False
        assert issued_log == []
        assert (cert_dir / renewal.CERT_FILENAME).read_bytes() == before

    @pytest.mark.asyncio
    async def test_near_expiry_within_default_window_is_reissued(self, cert_dir):
        """10 days remaining < default 30-day window → renewed."""
        _write_cert(cert_dir, days_valid=10)
        issued_log: list = []

        renewed = await renewal.renew_cc_service_certificate_if_needed(
            cert_dir, issue_fn=_issue_fn_factory(issued_log)
        )

        assert renewed is True
        assert len(issued_log) == 1

    @pytest.mark.asyncio
    async def test_env_threshold_widens_narrows_window(self, cert_dir, monkeypatch):
        """``CC_SERVICE_CERT_RENEWAL_DAYS=5``: a 10-day cert is left alone."""
        monkeypatch.setenv(renewal.RENEWAL_DAYS_ENV, "5")
        _write_cert(cert_dir, days_valid=10)
        issued_log: list = []

        renewed = await renewal.renew_cc_service_certificate_if_needed(
            cert_dir, issue_fn=_issue_fn_factory(issued_log)
        )

        assert renewed is False
        assert issued_log == []

    @pytest.mark.asyncio
    async def test_missing_cert_is_issued(self, cert_dir):
        """No cert on disk (fresh install) → issued."""
        issued_log: list = []

        renewed = await renewal.renew_cc_service_certificate_if_needed(
            cert_dir, issue_fn=_issue_fn_factory(issued_log)
        )

        assert renewed is True
        assert _read_expiry(cert_dir) > datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_issuance_failure_logged_not_raised(self, cert_dir):
        """CA failure → returns False, never raises, old files intact."""
        old_pem, old_key, _ = _make_cert_pem("service:control-center", -1)
        (cert_dir / renewal.CERT_FILENAME).write_text(old_pem)
        (cert_dir / renewal.KEY_FILENAME).write_text(old_key)

        async def _boom(*args, **kwargs):
            raise RuntimeError("CA not initialized")

        renewed = await renewal.renew_cc_service_certificate_if_needed(
            cert_dir, issue_fn=_boom
        )

        assert renewed is False  # logged, NOT raised
        assert (cert_dir / renewal.CERT_FILENAME).read_text() == old_pem
        assert (cert_dir / renewal.KEY_FILENAME).read_text() == old_key

    @pytest.mark.asyncio
    async def test_unreadable_cert_is_renewed(self, cert_dir):
        """Corrupt PEM (e.g. truncated) → treated as needing renewal."""
        (cert_dir / renewal.CERT_FILENAME).write_text("not a pem")
        (cert_dir / renewal.KEY_FILENAME).write_text("junk")
        issued_log: list = []

        renewed = await renewal.renew_cc_service_certificate_if_needed(
            cert_dir, issue_fn=_issue_fn_factory(issued_log)
        )

        assert renewed is True
        _read_expiry(cert_dir)  # parses now


class TestThresholdParsing:
    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(renewal.RENEWAL_DAYS_ENV, "not-a-number")
        assert renewal.get_renewal_threshold_days() == 30

    def test_default_threshold(self, monkeypatch):
        monkeypatch.delenv(renewal.RENEWAL_DAYS_ENV, raising=False)
        assert renewal.get_renewal_threshold_days() == 30

    def test_window_logic(self):
        now = datetime.now(timezone.utc)
        assert renewal.is_within_renewal_window(None) is True
        assert renewal.is_within_renewal_window(now - timedelta(days=1), now=now) is True
        assert renewal.is_within_renewal_window(
            now + timedelta(days=10), now=now, threshold_days=30
        ) is True
        assert renewal.is_within_renewal_window(
            now + timedelta(days=40), now=now, threshold_days=30
        ) is False
