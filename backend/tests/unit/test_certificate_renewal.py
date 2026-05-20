"""Unit tests — Certificate renewal logic (Task 7.2).

Tests for both CertificateManager (Agent Runtime, 24h) and
CommHubCertificateManager (Communication Hub, 30d):

  - Renewal threshold: triggers at 80% of certificate lifetime
  - Successful renewal atomically swaps the in-memory certificate
  - Failed renewal does not corrupt in-memory state (rollback)
  - run_renewal_task retries every 5 minutes on failure
  - Certificate swap does not interrupt service (old cert returned until new one is ready)

These are pure unit tests — no real CA or HTTP server required.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_runtime.certificate_manager import (
    CertificateManager,
    CertificateLoadError,
    _RENEWAL_THRESHOLD_FRACTION,
    _DEFAULT_CERT_VALIDITY_HOURS,
    _CHECK_INTERVAL_SECONDS,
    _RENEWAL_RETRY_SECONDS,
)
from app.communication_hub.certificate_manager import (
    CommHubCertificateManager,
    CertificateLoadError as CHCertificateLoadError,
    _DEFAULT_CERT_VALIDITY_DAYS,
    _CHECK_INTERVAL_SECONDS as CH_CHECK_INTERVAL_SECONDS,
    _RENEWAL_RETRY_SECONDS as CH_RENEWAL_RETRY_SECONDS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _inject_cert_state(
    manager: CertificateManager | CommHubCertificateManager,
    expires_at: datetime,
    cert_pem: str = "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n",
    key_pem: str = "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----\n",
    ca_cert_pem: str = "-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----\n",
    serial: str = "99999",
) -> None:
    """Directly inject certificate state into a manager without loading from disk."""
    manager._cert_pem = cert_pem
    manager._key_pem = key_pem
    manager._ca_cert_pem = ca_cert_pem
    manager._serial_number = serial
    manager._expires_at = expires_at
    manager._control_center_url = "http://localhost:8000"


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Runtime CertificateManager — 24h cert
# ═══════════════════════════════════════════════════════════════════════════════


class TestARRenewalThreshold:
    """Tests for check_certificate_expiration() renewal trigger."""

    def test_fresh_cert_does_not_trigger_renewal(self):
        """A brand-new cert (< 80% elapsed) should not trigger renewal."""
        manager = CertificateManager()
        # Cert issued now, expires in 24h → 0% elapsed → no renewal
        _inject_cert_state(manager, expires_at=_now_utc() + timedelta(hours=24))
        assert manager.check_certificate_expiration() is False

    def test_cert_at_exactly_79_percent_does_not_trigger(self):
        """79% lifetime elapsed → below threshold → no renewal."""
        manager = CertificateManager()
        total = _DEFAULT_CERT_VALIDITY_HOURS  # 24
        elapsed_fraction = 0.79
        remaining_hours = total * (1.0 - elapsed_fraction)
        _inject_cert_state(manager, expires_at=_now_utc() + timedelta(hours=remaining_hours))
        assert manager.check_certificate_expiration() is False

    def test_cert_at_exactly_80_percent_triggers_renewal(self):
        """80% lifetime elapsed → at threshold → triggers renewal."""
        manager = CertificateManager()
        total = _DEFAULT_CERT_VALIDITY_HOURS  # 24
        elapsed_fraction = 0.80
        remaining_hours = total * (1.0 - elapsed_fraction)
        # Subtract 1 second to ensure we're past the threshold
        _inject_cert_state(
            manager,
            expires_at=_now_utc() + timedelta(hours=remaining_hours) - timedelta(seconds=1),
        )
        assert manager.check_certificate_expiration() is True

    def test_expired_cert_triggers_renewal(self):
        """Expired cert always triggers renewal."""
        manager = CertificateManager()
        _inject_cert_state(manager, expires_at=_now_utc() - timedelta(seconds=1))
        assert manager.check_certificate_expiration() is True

    def test_no_cert_triggers_renewal(self):
        """Manager with no cert loaded always triggers renewal."""
        manager = CertificateManager()
        assert manager.check_certificate_expiration() is True

    def test_renewal_constants(self):
        """Verify renewal threshold and check interval are set to expected values."""
        assert _RENEWAL_THRESHOLD_FRACTION == 0.80
        assert _DEFAULT_CERT_VALIDITY_HOURS == 24
        assert _CHECK_INTERVAL_SECONDS == 3600  # 1 hour
        assert _RENEWAL_RETRY_SECONDS == 300   # 5 minutes


class TestARRenewalSuccess:
    """Tests for successful renewal — certificate swap."""

    @pytest.mark.asyncio
    async def test_successful_renewal_replaces_cert(self):
        """Successful renewal atomically replaces the in-memory certificate."""
        manager = CertificateManager()
        old_serial = "old-111"
        _inject_cert_state(
            manager,
            expires_at=_now_utc() + timedelta(hours=4),  # past 80% of 24h
            serial=old_serial,
        )

        new_cert_pem = "-----BEGIN CERTIFICATE-----\nnew\n-----END CERTIFICATE-----\n"
        new_key_pem = "-----BEGIN RSA PRIVATE KEY-----\nnew-key\n-----END RSA PRIVATE KEY-----\n"
        new_serial = "new-222"

        async def fake_validate():
            # Simulate successful validation — update serial as side-effect
            manager._serial_number = new_serial
            manager._expires_at = _now_utc() + timedelta(hours=24)

        with patch.object(manager, "validate_certificate_against_ca", new=AsyncMock(side_effect=fake_validate)):
            with patch.object(manager, "_cert_path", None):
                await manager.switch_certificate(new_cert_pem, new_key_pem)

        assert manager._cert_pem == new_cert_pem
        assert manager._key_pem == new_key_pem
        assert manager._serial_number == new_serial

    @pytest.mark.asyncio
    async def test_failed_renewal_rolls_back_cert(self):
        """If validation fails after switch, old cert is restored."""
        manager = CertificateManager()
        old_cert = "-----BEGIN CERTIFICATE-----\nold\n-----END CERTIFICATE-----\n"
        old_key = "-----BEGIN RSA PRIVATE KEY-----\nold-key\n-----END RSA PRIVATE KEY-----\n"
        _inject_cert_state(
            manager,
            expires_at=_now_utc() + timedelta(hours=4),
            cert_pem=old_cert,
            key_pem=old_key,
            serial="old-serial",
        )

        bad_cert = "-----BEGIN CERTIFICATE-----\nbad\n-----END CERTIFICATE-----\n"

        async def fake_validate_fails():
            raise CertificateLoadError("Invalid certificate")

        with patch.object(manager, "validate_certificate_against_ca", new=AsyncMock(side_effect=fake_validate_fails)):
            with pytest.raises(CertificateLoadError):
                await manager.switch_certificate(bad_cert, "bad-key")

        # Old cert must be restored
        assert manager._cert_pem == old_cert
        assert manager._key_pem == old_key

    @pytest.mark.asyncio
    async def test_run_renewal_task_retries_on_failure(self):
        """run_renewal_task retries every _RENEWAL_RETRY_SECONDS on failure."""
        manager = CertificateManager()
        # Cert past 80% threshold
        _inject_cert_state(
            manager,
            expires_at=_now_utc() + timedelta(hours=4),  # 83% elapsed in 24h cert
        )

        sleep_calls: list[float] = []
        renew_call_count = 0

        async def fake_renew():
            nonlocal renew_call_count
            renew_call_count += 1
            raise CertificateLoadError("CC unavailable")

        async def fake_sleep(seconds: float):
            sleep_calls.append(seconds)
            # Allow the first sleep (_CHECK_INTERVAL_SECONDS) through so the
            # renewal code is reached; cancel on the second sleep (retry delay).
            if len(sleep_calls) >= 2:
                raise asyncio.CancelledError()

        with patch.object(manager, "renew_certificate", new=AsyncMock(side_effect=fake_renew)):
            with patch("asyncio.sleep", new=AsyncMock(side_effect=fake_sleep)):
                with pytest.raises(asyncio.CancelledError):
                    await manager.run_renewal_task()

        # Should have retried with _RENEWAL_RETRY_SECONDS delay
        assert renew_call_count >= 1
        assert any(s == _RENEWAL_RETRY_SECONDS for s in sleep_calls)


# ═══════════════════════════════════════════════════════════════════════════════
# Communication Hub CommHubCertificateManager — 30d cert
# ═══════════════════════════════════════════════════════════════════════════════


class TestCHRenewalThreshold:
    """Tests for CommHubCertificateManager renewal trigger."""

    def test_fresh_service_cert_does_not_trigger_renewal(self):
        """Brand-new 30-day service cert → no renewal needed."""
        manager = CommHubCertificateManager()
        _inject_cert_state(manager, expires_at=_now_utc() + timedelta(days=30))
        assert manager.check_certificate_expiration() is False

    def test_service_cert_at_80_percent_triggers_renewal(self):
        """At 80% of 30-day cert → triggers renewal (6 days remaining)."""
        manager = CommHubCertificateManager()
        # 80% of 30 days = 24 days elapsed → 6 days remaining
        remaining = timedelta(days=30 * (1.0 - 0.80)) - timedelta(seconds=1)
        _inject_cert_state(manager, expires_at=_now_utc() + remaining)
        assert manager.check_certificate_expiration() is True

    def test_expired_service_cert_triggers_renewal(self):
        """Expired service cert triggers renewal."""
        manager = CommHubCertificateManager()
        _inject_cert_state(manager, expires_at=_now_utc() - timedelta(minutes=1))
        assert manager.check_certificate_expiration() is True

    def test_ch_renewal_constants(self):
        """Verify CH renewal threshold constants are set correctly."""
        assert _DEFAULT_CERT_VALIDITY_DAYS == 30
        assert CH_CHECK_INTERVAL_SECONDS == 86400  # 24 hours
        assert CH_RENEWAL_RETRY_SECONDS == 300     # 5 minutes

    @pytest.mark.asyncio
    async def test_ch_run_renewal_task_retries_on_failure(self):
        """CH run_renewal_task retries every _RENEWAL_RETRY_SECONDS on failure."""
        manager = CommHubCertificateManager()
        _inject_cert_state(manager, expires_at=_now_utc() + timedelta(days=5))

        sleep_calls: list[float] = []
        renew_count = 0

        async def fake_renew():
            nonlocal renew_count
            renew_count += 1
            raise CertificateLoadError("CC unavailable")

        async def fake_sleep(seconds: float):
            sleep_calls.append(seconds)
            # Allow the first sleep (_CHECK_INTERVAL_SECONDS) through so the
            # renewal code is reached; cancel on the second sleep (retry delay).
            if len(sleep_calls) >= 2:
                raise asyncio.CancelledError()

        with patch.object(manager, "renew_certificate", new=AsyncMock(side_effect=fake_renew)):
            with patch("asyncio.sleep", new=AsyncMock(side_effect=fake_sleep)):
                with pytest.raises(asyncio.CancelledError):
                    await manager.run_renewal_task()

        assert renew_count >= 1
        assert any(s == CH_RENEWAL_RETRY_SECONDS for s in sleep_calls)


class TestCHRenewalSwap:
    """Tests for CommHubCertificateManager atomic cert swap."""

    @pytest.mark.asyncio
    async def test_ch_successful_switch_certificate(self):
        """CH successful renewal atomically replaces in-memory cert."""
        manager = CommHubCertificateManager()
        old_cert = "-----BEGIN CERTIFICATE-----\nch-old\n-----END CERTIFICATE-----\n"
        _inject_cert_state(manager, expires_at=_now_utc() + timedelta(days=5), cert_pem=old_cert)

        new_cert = "-----BEGIN CERTIFICATE-----\nch-new\n-----END CERTIFICATE-----\n"
        new_key = "-----BEGIN RSA PRIVATE KEY-----\nch-new-key\n-----END RSA PRIVATE KEY-----\n"

        async def fake_validate_and_parse():
            manager._serial_number = "ch-new-serial"
            manager._expires_at = _now_utc() + timedelta(days=30)

        with patch.object(manager, "_validate_and_parse", new=AsyncMock(side_effect=fake_validate_and_parse)):
            await manager._switch_certificate(new_cert, new_key)

        assert manager._cert_pem == new_cert
        assert manager._serial_number == "ch-new-serial"

    @pytest.mark.asyncio
    async def test_ch_failed_switch_rolls_back(self):
        """CH switch rolls back on validation failure."""
        manager = CommHubCertificateManager()
        old_cert = "-----BEGIN CERTIFICATE-----\nch-old\n-----END CERTIFICATE-----\n"
        old_key = "-----BEGIN RSA PRIVATE KEY-----\nch-old-key\n-----END RSA PRIVATE KEY-----\n"
        _inject_cert_state(manager, expires_at=_now_utc() + timedelta(days=5), cert_pem=old_cert, key_pem=old_key)

        async def fake_validate_fails():
            raise CHCertificateLoadError("Bad CH cert")

        with patch.object(manager, "_validate_and_parse", new=AsyncMock(side_effect=fake_validate_fails)):
            with pytest.raises(CHCertificateLoadError):
                await manager._switch_certificate("bad-cert", "bad-key")

        assert manager._cert_pem == old_cert
        assert manager._key_pem == old_key
