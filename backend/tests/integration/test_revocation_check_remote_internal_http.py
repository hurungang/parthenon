"""Regression tests: check_remote must egress via internal_httpx_client.

Root cause fixed here: ``RevocationService.check_remote`` used a raw
``httpx.AsyncClient`` (no mTLS cert, no SSL context) so the TLS handshake
against Control Center failed and fail-closed semantics incorrectly treated
every certificate as revoked (A2A delegation HTTP 401 "Certificate has been
revoked").  These tests pin the factory-based egress behavior.
"""
from __future__ import annotations

import logging

import httpx
import pytest

from app.services.certificates.revocation_service import RevocationService


@pytest.fixture(autouse=True)
def _no_insecure_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ALLOW_INSECURE_INTERNAL_CALL_FALLBACK", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "test")


@pytest.mark.asyncio
async def test_check_remote_uses_internal_httpx_client_with_cert(monkeypatch):
    """check_remote builds the client via internal_httpx_client, passing the
    SSL context and forwarding the caller's mTLS cert pair."""
    import app.core.internal_http as internal_http_module
    import app.services.certificates.revocation_service as rv_module

    captured_kwargs: dict = {}
    captured_urls: list[str] = []

    real_factory = internal_http_module.internal_httpx_client

    def _factory(**kwargs):
        captured_kwargs.update(kwargs)
        return real_factory(
            transport=httpx.MockTransport(
                lambda request: (
                    captured_urls.append(str(request.url)),
                    httpx.Response(200, json={"revoked": False}),
                )[1]
            )
        )

    monkeypatch.setattr(internal_http_module, "internal_httpx_client", _factory)

    service = RevocationService()
    revoked = await service.check_remote(
        "abc123",
        "http://control-center:8000",
        client_cert=("/certs/ch.crt", "/certs/ch.key"),
    )

    assert revoked is False
    assert captured_urls == [
        "http://control-center:8000/api/v1/internal/certificates/revoked/abc123"
    ]
    # verify must come from get_ssl_context(); cert pair forwarded.
    from app.core.ssl_context import get_ssl_context

    assert captured_kwargs.get("verify") is get_ssl_context()
    assert captured_kwargs.get("cert") == ("/certs/ch.crt", "/certs/ch.key")


@pytest.mark.asyncio
async def test_check_remote_failure_fail_closes_with_repr(monkeypatch, caplog):
    """On transport failure the check still fail-closes and the log record
    contains repr(exc) so empty-message exceptions are diagnosable."""

    class _FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, _url):
            raise RuntimeError()  # deliberately empty message

    def _factory(**_kwargs):
        return _FailingClient()

    import app.core.internal_http as internal_http_module

    monkeypatch.setattr(internal_http_module, "internal_httpx_client", _factory)

    service = RevocationService()
    with caplog.at_level(
        logging.ERROR, logger="app.services.certificates.revocation_service"
    ):
        revoked = await service.check_remote("abc123", "http://control-center:8000")

    assert revoked is True
    assert "RuntimeError()" in caplog.text


@pytest.mark.asyncio
async def test_check_remote_without_cert_pair_still_works(monkeypatch):
    """client_cert is optional — None must not be passed as httpx cert kwarg."""
    import app.core.internal_http as internal_http_module
    import app.services.certificates.revocation_service as rv_module

    captured_kwargs: dict = {}
    real_factory = internal_http_module.internal_httpx_client

    def _factory(**kwargs):
        captured_kwargs.update(kwargs)
        return real_factory(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"revoked": True})
            )
        )

    monkeypatch.setattr(internal_http_module, "internal_httpx_client", _factory)

    service = RevocationService()
    revoked = await service.check_remote("abc123", "http://control-center:8000")
    assert revoked is True
    assert "cert" not in captured_kwargs
