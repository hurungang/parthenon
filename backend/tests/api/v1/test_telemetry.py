"""API tests for GET /api/v1/telemetry/config."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware


def _bypass_auth():
    """Patch JWTAuthMiddleware to inject identity claims without a real token."""

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-user", "roles": ["user"]}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _block_auth():
    """Patch JWTAuthMiddleware to return 401 for all requests (no token)."""
    from fastapi.responses import JSONResponse

    async def patched_dispatch(self, request, call_next):
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


@pytest.mark.asyncio
async def test_telemetry_config_endpoint_authenticated() -> None:
    """Authenticated GET /api/v1/telemetry/config returns 200 with correct schema."""
    app = create_app()
    with _bypass_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/telemetry/config")

    assert response.status_code == 200
    data = response.json()
    assert "otlp_http_endpoint" in data
    assert "service_name" in data
    assert "traces_enabled" in data
    assert "metrics_enabled" in data
    # Ensure no credential fields are present
    assert "token" not in data
    assert "credential" not in data


@pytest.mark.asyncio
async def test_telemetry_config_endpoint_unauthenticated() -> None:
    """Unauthenticated GET /api/v1/telemetry/config returns 401."""
    app = create_app()
    with _block_auth():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/telemetry/config")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_telemetry_config_returns_service_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Endpoint returns the configured service name from TelemetrySettings."""
    monkeypatch.setenv("TELEMETRY__SERVICE_NAME", "my-test-service")

    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        app = create_app()
        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/telemetry/config")

        assert response.status_code == 200
        assert response.json()["service_name"] == "my-test-service"
    finally:
        get_settings.cache_clear()
