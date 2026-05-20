"""Unit tests for GET /health endpoint (app/routes/health.py).

Verifies status code, response body, slug value, and that no auth is required.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routes.health import health_router


@pytest.fixture
def health_app():
    """Minimal FastAPI app with only the health router — no lifespan."""
    app = FastAPI()
    app.include_router(health_router)
    return app


@pytest.fixture
async def client(health_app):
    async with AsyncClient(
        transport=ASGITransport(app=health_app), base_url="http://test"
    ) as c:
        yield c


async def test_health_returns_200(client):
    response = await client.get("/health")
    assert response.status_code == 200


async def test_health_body_status_ok(client):
    body = (await client.get("/health")).json()
    assert body["status"] == "ok"


async def test_health_body_contains_slug(client):
    body = (await client.get("/health")).json()
    assert "slug" in body
    assert isinstance(body["slug"], str)
    assert len(body["slug"]) > 0


async def test_health_slug_is_demo(client):
    """Default APP_SLUG is 'demo' (set via conftest env vars → AppSettings default)."""
    body = (await client.get("/health")).json()
    assert body["slug"] == "demo"


async def test_health_no_auth_required(client):
    """Health endpoint must be unauthenticated — no Authorization header needed."""
    response = await client.get("/health")
    assert response.status_code == 200
