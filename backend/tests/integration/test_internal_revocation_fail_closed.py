"""Integration-style tests for remote revocation fail-closed policy."""
from __future__ import annotations

import os

import pytest

from app.services.certificates.revocation_service import RevocationService


@pytest.mark.asyncio
async def test_remote_revocation_check_fails_closed_on_transport_error(monkeypatch: pytest.MonkeyPatch):
    """Remote revocation check treats transport errors as revoked by default."""

    class _FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, _url):
            raise RuntimeError("network down")

    import httpx

    monkeypatch.delenv("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: _FailingClient())

    service = RevocationService()
    revoked = await service.check_remote("abc123", "http://control-center:8000")

    assert revoked is True


@pytest.mark.asyncio
async def test_remote_revocation_check_allows_dev_opt_in_fallback(monkeypatch: pytest.MonkeyPatch):
    """Development-only explicit fallback can opt out of fail-closed behavior."""

    class _FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, _url):
            raise RuntimeError("network down")

    import httpx

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", "true")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: _FailingClient())

    service = RevocationService()
    revoked = await service.check_remote("abc123", "http://control-center:8000")

    assert revoked is False

    # Ensure we do not leak this opt-in to other tests.
    os.environ.pop("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", None)
