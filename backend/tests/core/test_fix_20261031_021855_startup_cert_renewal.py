"""FIX-20261031-021855 reproduction — CC startup cert-renewal NameError.

Live failure at every Control Center startup:

    NameError: name 'renew_cc_service_certificate_if_needed' is not defined
    Failed to ensure Control Center service certificate; internal calls to
    Communication Hub will fail.

``app.main._ensure_cc_service_certificate`` (backend/app/main.py ~L718)
calls ``renew_cc_service_certificate_if_needed()`` but only imports
``start_daily_renewal_task`` from ``app.core.cc_service_cert_renewal`` —
the renewal function is never defined or imported into the module
namespace.  The broad ``except Exception`` swallows the NameError, so
startup "succeeds" while the CC service-certificate ensure/renewal step is
silently skipped every boot.

These tests must currently FAIL with the NameError-shaped symptom
(AttributeError at import-time resolution; renewal mock never invoked).
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")


class TestStartupCertRenewalNameResolves:
    def test_renew_cc_service_certificate_if_needed_resolves_in_main(self):
        """The name used at backend/app/main.py ~L718 must be resolvable in
        the ``app.main`` module namespace (defined or imported)."""
        import app.main as main_module

        assert hasattr(main_module, "renew_cc_service_certificate_if_needed"), (
            "app.main references renew_cc_service_certificate_if_needed() in "
            "_ensure_cc_service_certificate but the name is neither defined "
            "nor imported — every startup raises NameError and the CC "
            "service-certificate renewal is silently skipped"
        )

    def test_ensure_cc_service_certificate_actually_renews(self):
        """Behavioral contract: calling the startup wrapper must invoke the
        real renewal coroutine (exactly once) and never swallow a NameError.

        Patched at the source module — the production-correct resolution is
        ``from app.core.cc_service_cert_renewal import
        renew_cc_service_certificate_if_needed`` alongside
        ``start_daily_renewal_task``.
        """
        import app.main as main_module

        renewal_mock = AsyncMock(return_value=True)
        with patch(
            "app.core.cc_service_cert_renewal.renew_cc_service_certificate_if_needed",
            renewal_mock,
        ):
            with patch(
                "app.core.cc_service_cert_renewal.start_daily_renewal_task"
            ):
                # NameError (if present) must surface — it is a programming
                # error, not an environmental failure to be tolerated.
                import asyncio

                asyncio.run(main_module._ensure_cc_service_certificate())

        renewal_mock.assert_awaited_once()
