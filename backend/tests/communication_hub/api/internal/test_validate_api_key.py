"""Tests for the Internal API Key Validation endpoint.

Validates that the /internal/auth/validate-api-key endpoint:
- Accepts valid active keys and returns identity token + permissions
- Rejects revoked keys with 401
- Rejects invalid/unknown key hashes with 401
- Requires service certificate authentication
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from httpx import ASGITransport, AsyncClient
from fastapi import Request

from app.main import create_app
from app.db.session import get_db, DbSession
from app.api.deps import require_service_certificate


async def _mock_require_service_cert(request: Request, db: DbSession):
    """Override for require_service_certificate that passes all checks."""
    request.state.internal_caller_type = "communication_hub"
    request.state.internal_caller_identity = "communication-hub"
    request.state.internal_cert_type = "service"
    return {
        "cert_type": "service",
        "service_name": "communication-hub",
        "caller_type": "communication_hub",
    }


def _mock_validate_key_as_active():
    """Mock validate_api_key_from_hash to return an active key."""
    mock_key = MagicMock()
    mock_key.id = uuid.uuid4()
    mock_key.name = "Test API Key"
    mock_key.agent_identity_id = uuid.uuid4()
    mock_key.agent_role_id = uuid.uuid4()

    return patch(
        "app.api.v1.internal.validate_api_key.validate_api_key_from_hash",
        new_callable=AsyncMock,
        return_value=mock_key,
    )


@pytest.mark.asyncio
async def test_validate_active_key_returns_identity_token():
    """POST /internal/auth/validate-api-key with valid key returns 200 with token."""
    app = create_app()
    app.dependency_overrides[require_service_certificate] = _mock_require_service_cert

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    with _mock_validate_key_as_active(), \
         patch("app.api.v1.internal.validate_api_key.resolve_identity_token",
               new_callable=AsyncMock, return_value="eyJhbGciOiJIUzI1NiJ9.fake-token"), \
         patch("app.api.v1.internal.validate_api_key.resolve_allowed_tools",
               new_callable=AsyncMock, return_value={"server1____tool1", "server1____tool2"}), \
         patch("app.api.v1.internal.validate_api_key.get_role_name",
               new_callable=AsyncMock, return_value="Developer"), \
         patch("app.api.v1.internal.validate_api_key._resolve_skills_for_role",
               new_callable=AsyncMock, return_value=[]), \
         patch("app.api.v1.internal.validate_api_key.create_api_key_usage_log",
               new_callable=AsyncMock), \
         patch("app.api.v1.internal.validate_api_key.update_last_used_at",
               new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/internal/auth/validate-api-key", json={
                "key_hash": "a" * 64,
            })

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert "identity_token" in data
    assert data["identity_token"] == "eyJhbGciOiJIUzI1NiJ9.fake-token"
    assert len(data["permissions"]) == 2


@pytest.mark.asyncio
async def test_validate_revoked_key_returns_401():
    """POST /internal/auth/validate-api-key with revoked key returns 401."""
    app = create_app()
    app.dependency_overrides[require_service_certificate] = _mock_require_service_cert

    from app.db.models.agent_api_key import ApiKeyStatus

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    # Mock the secondary check that finds revoked key
    mock_secondary = MagicMock()
    mock_key = MagicMock()
    mock_key.status = ApiKeyStatus.revoked  # Use real enum for comparison
    mock_key.id = uuid.uuid4()
    mock_secondary.scalar_one_or_none.return_value = mock_key
    mock_session.execute = AsyncMock(return_value=mock_secondary)

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    async def mock_validate_none(key_hash, db):
        return None

    with patch("app.api.v1.internal.validate_api_key.validate_api_key_from_hash",
               new_callable=AsyncMock, side_effect=mock_validate_none), \
         patch("app.api.v1.internal.validate_api_key.create_api_key_usage_log",
               new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/internal/auth/validate-api-key", json={
                "key_hash": "a" * 64,
            })

    assert response.status_code == 401
    assert "revoked" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_validate_invalid_key_returns_401():
    """POST /internal/auth/validate-api-key with unknown key returns 401."""
    app = create_app()
    app.dependency_overrides[require_service_certificate] = _mock_require_service_cert

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_secondary = MagicMock()
    mock_secondary.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_secondary)

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    async def mock_validate_none(key_hash, db):
        return None

    with patch("app.api.v1.internal.validate_api_key.validate_api_key_from_hash",
               new_callable=AsyncMock, side_effect=mock_validate_none):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/internal/auth/validate-api-key", json={
                "key_hash": "b" * 64,
            })

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_validate_empty_key_hash_returns_422():
    """POST /internal/auth/validate-api-key with empty key_hash returns 422."""
    app = create_app()
    app.dependency_overrides[require_service_certificate] = _mock_require_service_cert

    mock_session = AsyncMock()
    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/internal/auth/validate-api-key", json={
            "key_hash": "",
        })

    # Pydantic validates min_length=1 on key_hash, so empty string → 422
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_validate_with_since_parameter():
    """POST /internal/auth/validate-api-key with since parameter resolves skills."""
    app = create_app()
    app.dependency_overrides[require_service_certificate] = _mock_require_service_cert

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    with _mock_validate_key_as_active(), \
         patch("app.api.v1.internal.validate_api_key.resolve_identity_token",
               new_callable=AsyncMock, return_value="eyJhbGciOiJIUzI1NiJ9.fake-token"), \
         patch("app.api.v1.internal.validate_api_key.resolve_allowed_tools",
               new_callable=AsyncMock, return_value={"server1____tool1"}), \
         patch("app.api.v1.internal.validate_api_key.get_role_name",
               new_callable=AsyncMock, return_value="Developer"), \
         patch("app.api.v1.internal.validate_api_key._resolve_skills_for_role",
               new_callable=AsyncMock, return_value=[]), \
         patch("app.api.v1.internal.validate_api_key.create_api_key_usage_log",
               new_callable=AsyncMock), \
         patch("app.api.v1.internal.validate_api_key.update_last_used_at",
               new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/internal/auth/validate-api-key", json={
                "key_hash": "a" * 64,
                "since": "2026-01-01T00:00:00Z",
            })

    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True


@pytest.mark.asyncio
async def test_validate_without_service_cert_returns_401():
    """POST /internal/auth/validate-api-key without service cert returns 401.
    
    Without our override, the real require_service_certificate will reject
    the request with 401 (no X-Client-Certificate header provided).
    """
    app = create_app()

    mock_session = AsyncMock()
    async def db_override():
        yield mock_session

    app.dependency_overrides[get_db] = db_override

    # No service cert override — should fail with 401
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/internal/auth/validate-api-key", json={
            "key_hash": "a" * 64,
        })

    assert response.status_code == 401
