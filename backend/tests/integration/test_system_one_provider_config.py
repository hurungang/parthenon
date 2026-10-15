"""Integration tests for the System One provider configuration API.

Covers: CRUD routes, write-only key semantics (key never in any response),
key update keeping the existing ciphertext when the key is omitted, status
endpoint behavior, encryption at rest, and permission enforcement.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_permission
from app.core.resource_types import RT_SYSTEM_SYSTEM_ONE
from app.db.models.system_one_provider_config import SystemOneProviderConfig
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware


def _bypass_jwt_middleware():
    """Patch JWTAuthMiddleware to inject identity claims without real JWT validation."""
    from unittest.mock import patch as _patch

    async def _patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "test-admin", "roles": ["admin"]}
        return await call_next(request)

    return _patch.object(JWTAuthMiddleware, "dispatch", _patched_dispatch)

PROVIDERS_URL = "/api/v1/system-one/providers"
STATUS_URL = "/api/v1/system-one/status"

CREATE_BODY = {
    "provider_type": "typesafe",
    "display_name": "TypeSafe Jev (test)",
    "base_url": "http://localhost:9999/v1",
    "default_model": "jev-latest",
    "api_key": "sk-super-secret-key-1234567890",
    "enabled": True,
}


def _allow_all():
    async def _dep():
        return {"user_id": "test-user", "permissions": ["*::*"]}

    return _dep


@pytest_asyncio.fixture
async def app_client(test_engine, allow_all: bool = True):
    """App client with DB override; permissions overridden when allow_all.

    Cleans any pre-existing provider rows so tests are hermetic on the
    shared session-scoped test database.
    """
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    async with SessionLocal() as session:
        for row in (
            await session.execute(select(SystemOneProviderConfig))
        ).scalars().all():
            await session.delete(row)
        await session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    if allow_all:
        app.dependency_overrides[require_permission(RT_SYSTEM_SYSTEM_ONE, "read")] = _allow_all()
        app.dependency_overrides[require_permission(RT_SYSTEM_SYSTEM_ONE, "manage")] = _allow_all()

    with _bypass_jwt_middleware():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


@pytest_asyncio.fixture
async def no_permission_client(test_engine):
    """Client WITHOUT the permission override — real require_permission runs."""
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def created_provider_id(app_client) -> str:
    resp = await app_client.post(PROVIDERS_URL, json=CREATE_BODY)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── CRUD + write-only key semantics ───────────────────────────────────────


@pytest.mark.asyncio
async def test_create_provider_returns_201_without_key_material(app_client):
    resp = await app_client.post(PROVIDERS_URL, json=CREATE_BODY)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["display_name"] == CREATE_BODY["display_name"]
    assert body["has_api_key"] is True
    # Write-only: the key never appears anywhere in the response payload.
    assert "api_key" not in body
    assert CREATE_BODY["api_key"] not in resp.text


@pytest.mark.asyncio
async def test_key_is_encrypted_at_rest(app_client, test_engine):
    resp = await app_client.post(PROVIDERS_URL, json=CREATE_BODY)
    assert resp.status_code == 201
    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession)
    async with SessionLocal() as db:
        row = (await db.execute(select(SystemOneProviderConfig))).scalars().first()
        assert row is not None
        # Ciphertext, not plaintext.
        assert row.encrypted_api_key != CREATE_BODY["api_key"]
        assert CREATE_BODY["api_key"] not in row.encrypted_api_key
        assert len(row.encrypted_api_key) > 20


@pytest.mark.asyncio
async def test_list_providers_contains_no_key_material(app_client):
    await app_client.post(PROVIDERS_URL, json=CREATE_BODY)
    resp = await app_client.get(PROVIDERS_URL)
    assert resp.status_code == 200
    assert CREATE_BODY["api_key"] not in resp.text
    items = resp.json()
    assert len(items) == 1
    assert "api_key" not in items[0]


@pytest.mark.asyncio
async def test_update_without_key_keeps_existing_ciphertext(app_client, created_provider_id, test_engine):
    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession)
    async with SessionLocal() as db:
        before = await db.get(SystemOneProviderConfig, __import__("uuid").UUID(created_provider_id))
        cipher_before = before.encrypted_api_key

    resp = await app_client.patch(
        f"{PROVIDERS_URL}/{created_provider_id}",
        json={"display_name": "Renamed only", "enabled": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "Renamed only"

    async with SessionLocal() as db:
        after = await db.get(SystemOneProviderConfig, __import__("uuid").UUID(created_provider_id))
        assert after.encrypted_api_key == cipher_before
        assert after.enabled is False


@pytest.mark.asyncio
async def test_update_with_new_key_replaces_ciphertext(app_client, created_provider_id, test_engine):
    import uuid as uuid_mod

    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession)
    async with SessionLocal() as db:
        before = await db.get(SystemOneProviderConfig, uuid_mod.UUID(created_provider_id))
        cipher_before = before.encrypted_api_key

    resp = await app_client.patch(
        f"{PROVIDERS_URL}/{created_provider_id}",
        json={"api_key": "sk-brand-new-key-9876543210"},
    )
    assert resp.status_code == 200
    assert "sk-brand-new-key-9876543210" not in resp.text

    async with SessionLocal() as db:
        after = await db.get(SystemOneProviderConfig, uuid_mod.UUID(created_provider_id))
        assert after.encrypted_api_key != cipher_before
        assert "sk-brand-new-key-9876543210" not in after.encrypted_api_key


@pytest.mark.asyncio
async def test_delete_provider_returns_204(app_client, created_provider_id):
    resp = await app_client.delete(f"{PROVIDERS_URL}/{created_provider_id}")
    assert resp.status_code == 204
    listing = await app_client.get(PROVIDERS_URL)
    assert listing.json() == []


@pytest.mark.asyncio
async def test_update_unknown_provider_returns_404(app_client):
    import uuid as uuid_mod

    resp = await app_client.patch(
        f"{PROVIDERS_URL}/{uuid_mod.uuid4()}", json={"display_name": "x"}
    )
    assert resp.status_code == 404


# ── Status endpoint ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_unconfigured_before_any_provider(app_client):
    resp = await app_client.get(STATUS_URL)
    assert resp.status_code == 200
    assert resp.json()["configured"] is False


@pytest.mark.asyncio
async def test_status_configured_after_provider_create(app_client, created_provider_id):
    resp = await app_client.get(STATUS_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["model"] == "jev-latest"
    assert CREATE_BODY["api_key"] not in resp.text


@pytest.mark.asyncio
async def test_status_reports_unconfigured_after_provider_delete(app_client, created_provider_id):
    resp = await app_client.delete(f"{PROVIDERS_URL}/{created_provider_id}")
    assert resp.status_code == 204
    status = await app_client.get(STATUS_URL)
    assert status.json()["configured"] is False


# ── Permission enforcement ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provider_routes_denied_without_auth(no_permission_client):
    for method, url, kwargs in [
        ("get", PROVIDERS_URL, {}),
        ("post", PROVIDERS_URL, {"json": CREATE_BODY}),
        ("get", STATUS_URL, {}),
    ]:
        resp = await getattr(no_permission_client, method)(url, **kwargs)
        assert resp.status_code in (401, 403), (method, url, resp.status_code)


# ── Round 2: preset base URL ──────────────────────────────────────────────

from app.schemas.system_one import SYSTEM_ONE_PRESET_BASE_URL  # noqa: E402

PRESET_CREATE_BODY = {
    "provider_type": "typesafe",
    "display_name": "TypeSafe Jev (preset url)",
    "default_model": "jev-latest",
    "api_key": "sk-preset-url-key-1234567890",
    "enabled": True,
}


@pytest.mark.asyncio
async def test_base_url_defaults_to_preset_on_create(app_client):
    resp = await app_client.post(PROVIDERS_URL, json=PRESET_CREATE_BODY)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["base_url"] == SYSTEM_ONE_PRESET_BASE_URL
    assert body["base_url"] == "https://api.typesafe.ai/v1/systemone"


@pytest.mark.asyncio
async def test_update_base_url_persists(app_client):
    """base_url is editable per tenant — update persists it."""
    created = await app_client.post(PROVIDERS_URL, json=PRESET_CREATE_BODY)
    assert created.status_code == 201
    provider_id = created.json()["id"]
    resp = await app_client.patch(
        f"{PROVIDERS_URL}/{provider_id}",
        json={"display_name": "Renamed", "base_url": "http://other.example/v1"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["base_url"] == "http://other.example/v1"

    listing = await app_client.get(PROVIDERS_URL)
    assert listing.json()[0]["base_url"] == "http://other.example/v1"


@pytest.mark.asyncio
async def test_update_base_url_used_verbatim_no_stripping(app_client):
    """base_url is the FULL endpoint URL — stored verbatim, no stripping."""
    created = await app_client.post(PROVIDERS_URL, json=PRESET_CREATE_BODY)
    assert created.status_code == 201
    provider_id = created.json()["id"]
    resp = await app_client.patch(
        f"{PROVIDERS_URL}/{provider_id}",
        json={"base_url": "https://tenant.example/v1/systemone"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["base_url"] == "https://tenant.example/v1/systemone"


@pytest.mark.asyncio
async def test_create_base_url_used_verbatim_no_stripping(app_client):
    body = dict(PRESET_CREATE_BODY)
    body["base_url"] = "https://tenant.example/v1/systemone"
    resp = await app_client.post(PROVIDERS_URL, json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["base_url"] == "https://tenant.example/v1/systemone"


@pytest.mark.asyncio
async def test_create_base_url_verbatim_preserves_other_paths(app_client):
    """No magic suffix: any complete URL (e.g. a proxy) is stored verbatim."""
    body = dict(PRESET_CREATE_BODY)
    body["base_url"] = "http://127.0.0.1:18099/v1/systemone"
    resp = await app_client.post(PROVIDERS_URL, json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["base_url"] == "http://127.0.0.1:18099/v1/systemone"


@pytest.mark.asyncio
async def test_create_base_url_rejects_non_http_scheme(app_client):
    body = dict(PRESET_CREATE_BODY)
    body["base_url"] = "ftp://tenant.example/v1"
    resp = await app_client.post(PROVIDERS_URL, json=body)
    assert resp.status_code == 422, resp.text


# ── Round 2: test-connection endpoint ─────────────────────────────────────


def _patch_typesafe_client(monkeypatch, impl):
    """Patch the client the factory returns at call time."""
    import app.services.system_one.client as client_module

    monkeypatch.setattr(client_module, "get_system_one_client", lambda pt: impl)


@pytest.mark.asyncio
async def test_connection_success_status_only(app_client, created_provider_id, monkeypatch):
    class OkClient:
        async def evaluate(self, **kwargs):
            assert kwargs["api_key"] == CREATE_BODY["api_key"]
            return {"model": "jev-latest", "answers": {}}

    _patch_typesafe_client(monkeypatch, OkClient())
    resp = await app_client.post(f"{PROVIDERS_URL}/{created_provider_id}/test")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # status-only result
    assert body["ok"] is True
    assert isinstance(body["message"], str)
    assert body["latency_ms"] is not None
    # never echoes the key
    assert CREATE_BODY["api_key"] not in resp.text


@pytest.mark.asyncio
async def test_connection_failure_reports_clear_reason(
    app_client, created_provider_id, monkeypatch
):
    class FailingClient:
        async def evaluate(self, **kwargs):
            from app.services.system_one.client import SystemOneClientError

            raise SystemOneClientError("provider endpoint unreachable")

    _patch_typesafe_client(monkeypatch, FailingClient())
    resp = await app_client.post(f"{PROVIDERS_URL}/{created_provider_id}/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "provider endpoint unreachable" in body["message"]
    assert CREATE_BODY["api_key"] not in resp.text


@pytest.mark.asyncio
async def test_connection_unknown_provider_404(app_client):
    import uuid as uuid_mod

    resp = await app_client.post(f"{PROVIDERS_URL}/{uuid_mod.uuid4()}/test")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_connection_denied_without_permission(no_permission_client, monkeypatch):
    import uuid as uuid_mod

    _patch_typesafe_client(monkeypatch, None)  # must never be reached
    resp = await no_permission_client.post(f"{PROVIDERS_URL}/{uuid_mod.uuid4()}/test")
    assert resp.status_code in (401, 403)
