"""Integration tests for the health endpoint and basic API structure."""

import os
import uuid

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok() -> None:
    """GET /health should return 200 with status ok without authentication."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_protected_endpoint_returns_401_without_token() -> None:
    """Protected endpoints should return 401 without Authorization header."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/roles")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_setup_init_is_public() -> None:
    """POST /api/v1/setup/init should be accessible without authentication (not return 401)."""
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession

    app = create_app()

    # Mock the database session to avoid real DB connection
    mock_session = AsyncMock(spec=AsyncSession)
    # Return None for scalar_one_or_none (no existing admin) then flush/refresh
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_execute_result)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()

    role_mock = MagicMock()
    role_mock.id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    identity_mock = MagicMock()
    identity_mock.id = uuid.UUID("00000000-0000-0000-0000-000000000002")

    added_objects = []
    mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    async def mock_refresh(obj, *args, **kwargs):
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()

    mock_session.refresh = mock_refresh

    async def override_get_db():
        yield mock_session

    from app.db.session import get_db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/setup/init")

    assert response.status_code != 401, "setup/init should not return 401"
