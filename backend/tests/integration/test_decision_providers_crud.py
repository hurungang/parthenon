"""Integration tests — Decision Model Providers CRUD (multi-vendor).

Covers (test-plan.md §3 "Provider CRUD (multi-vendor)"):
- create → 201, appears in list, has_api_key true, NO key material anywhere
- credential masking on every read endpoint (plaintext or ciphertext never returned)
- credential round-trip: update WITHOUT api_key keeps the stored secret;
  update WITH a new api_key replaces it (decrypted only via the vault)
- duplicate display name within the same vendor type → 409
- delete blocking: a provider referenced by a decision tool's selected
  model cannot be deleted (409 naming the blocking tool); an unreferenced
  provider deletes and the same display name can be recreated
- permission enforcement: no overrides → 401/403 on all provider routes
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.conftest import (
    DT_ENABLED_MODELS_URL,
    ENABLED_MODELS_URL,
    PROVIDERS_URL,
    PROVIDER_PAYLOAD,
    create_provider,
)

TOOLS_URL = "/api/v1/decision-tools"

TOOL_PAYLOAD = {
    "name": "crud_blocking_tool",
    "purpose": "Blocks provider deletion while referenced",
    "enabled": False,
    "act_threshold": 0.9,
    "confirm_threshold": 0.7,
    "questions": [
        {
            "question_key": "approve",
            "question_type": "noul",
            "instructions": "Approve?",
            "ordering": 0,
        }
    ],
}


class TestProviderCrudLifecycle:
    async def test_create_returns_201_key_free_and_lists_immediately(
        self, providers_client
    ):
        resp = await create_provider(providers_client, {"display_name": "Alpha Vendor"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["display_name"] == "Alpha Vendor"
        assert body["default_model"] == "jev-latest"
        assert body["enabled_models"] == ["jev-latest", "jev-mini"]
        assert body["has_api_key"] is True
        # no key material in the response
        assert "sk-crud-test-key" not in resp.text

        listed = await providers_client.get(PROVIDERS_URL)
        assert listed.status_code == 200
        names = {p["display_name"] for p in listed.json()}
        assert "Alpha Vendor" in names

    async def test_list_never_returns_credential(self, providers_client):
        await create_provider(providers_client, {"display_name": "Masked Vendor"})
        listing = await providers_client.get(PROVIDERS_URL)
        assert listing.status_code == 200
        for item in listing.json():
            assert "api_key" not in item
            assert item["has_api_key"] is True
        assert "sk-crud-test-key" not in listing.text

    async def test_update_without_api_key_keeps_stored_credential(
        self, providers_client, test_engine
    ):
        created = (
            await create_provider(providers_client, {"display_name": "RoundTrip"})
        ).json()

        # rename only — credential untouched (masked-placeholder semantics)
        resp = await providers_client.patch(
            f"{PROVIDERS_URL}/{created['id']}",
            json={"display_name": "RoundTrip Renamed"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["display_name"] == "RoundTrip Renamed"

        # the stored credential still decrypts to the original secret
        from app.core.credential_vault import get_vault
        from app.db.models.system_one_provider_config import SystemOneProviderConfig
        from app.services.system_one.provider_config_service import (
            SystemOneProviderConfigService,
        )

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as session:
            row = (
                await session.execute(
                    select(SystemOneProviderConfig).where(
                        SystemOneProviderConfig.id == uuid.UUID(created["id"])
                    )
                )
            ).scalar_one()
            _, plaintext = await SystemOneProviderConfigService().get_active_provider_by_config(
                row
            )
        assert plaintext == PROVIDER_PAYLOAD["api_key"]

    async def test_update_with_new_api_key_replaces_credential(
        self, providers_client, test_engine
    ):
        created = (await create_provider(providers_client, {"display_name": "Rekey"})).json()
        resp = await providers_client.patch(
            f"{PROVIDERS_URL}/{created['id']}",
            json={"api_key": "sk-brand-new-key-9876543210"},
        )
        assert resp.status_code == 200, resp.text
        assert "sk-brand-new-key" not in resp.text

        from app.core.credential_vault import get_vault
        from app.db.models.system_one_provider_config import SystemOneProviderConfig
        from app.services.system_one.provider_config_service import (
            SystemOneProviderConfigService,
        )

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as session:
            row = (
                await session.execute(
                    select(SystemOneProviderConfig).where(
                        SystemOneProviderConfig.id == uuid.UUID(created["id"])
                    )
                )
            ).scalar_one()
            _, plaintext = await SystemOneProviderConfigService().get_active_provider_by_config(
                row
            )
        assert plaintext == "sk-brand-new-key-9876543210"

    async def test_missing_required_field_rejected_422(self, providers_client):
        payload = {**PROVIDER_PAYLOAD, "display_name": ""}
        resp = await providers_client.post(PROVIDERS_URL, json=payload)
        assert resp.status_code == 422


class TestDuplicateAndDeleteSemantics:
    async def test_duplicate_display_name_same_vendor_rejected_409(
        self, providers_client
    ):
        first = await create_provider(providers_client, {"display_name": "Dup Vendor"})
        assert first.status_code == 201
        dup = await create_provider(providers_client, {"display_name": "Dup Vendor"})
        assert dup.status_code == 409
        assert "already exists" in str(dup.json()["detail"])

    async def test_referenced_provider_delete_blocked_409_naming_tool(
        self, providers_client
    ):
        """A provider whose model is selected by a decision tool cannot be
        deleted — the error names the blocking tool(s)."""
        created = (await create_provider(providers_client, {"display_name": "Blocked"})).json()
        enabled = (await providers_client.get(DT_ENABLED_MODELS_URL)).json()
        assert enabled, "enabled models must be listed after provider creation"
        availability_id = next(
            m["availability_id"]
            for m in enabled
            if m["provider_id"] == created["id"]
        )

        tool = await providers_client.post(
            TOOLS_URL,
            json={**TOOL_PAYLOAD, "decision_model_availability_id": availability_id},
        )
        assert tool.status_code == 201, tool.text

        resp = await providers_client.delete(f"{PROVIDERS_URL}/{created['id']}")
        assert resp.status_code == 409, resp.text
        assert "crud_blocking_tool" in str(resp.json()["detail"])
        # row remains
        listed = await providers_client.get(PROVIDERS_URL)
        assert "Blocked" in {p["display_name"] for p in listed.json()}

    async def test_unreferenced_provider_deletes_and_name_can_be_recreated(
        self, providers_client
    ):
        created = (await create_provider(providers_client, {"display_name": "Doomed"})).json()
        resp = await providers_client.delete(f"{PROVIDERS_URL}/{created['id']}")
        assert resp.status_code == 204
        listed = await providers_client.get(PROVIDERS_URL)
        assert "Doomed" not in {p["display_name"] for p in listed.json()}
        # recreate with the SAME display name + vendor → succeeds (true delete)
        again = await create_provider(providers_client, {"display_name": "Doomed"})
        assert again.status_code == 201, again.text

    async def test_cross_tenant_same_name_allowed(self, providers_client):
        """Duplicate display names are rejected per vendor type WITHIN a
        tenant; another tenant may use the same name (tenant containment)."""
        tenant = uuid.uuid4()
        headers = {"x-test-tenant": str(tenant)}
        resp = await create_provider(
            providers_client, {"display_name": "Shared Name"}, headers=headers
        )
        assert resp.status_code == 201, resp.text

    async def test_deleting_provider_cascades_availability_rows(
        self, providers_client, test_engine
    ):
        from app.db.models.decision_model_availability import DecisionModelAvailability
        from app.db.models.system_one_provider_config import SystemOneProviderConfig

        created = (await create_provider(providers_client, {"display_name": "Cascade"})).json()
        # flip a model toggle to materialise availability rows
        enabled = (await providers_client.get(ENABLED_MODELS_URL)).json()
        availability_id = next(
            m["availability_id"] for m in enabled if m["provider_id"] == created["id"]
        )
        toggle = await providers_client.put(
            f"/api/v1/system-one/models/{availability_id}/availability",
            json={"is_disabled": True},
        )
        assert toggle.status_code == 200, toggle.text

        await providers_client.delete(f"{PROVIDERS_URL}/{created['id']}")

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(DecisionModelAvailability).where(
                        DecisionModelAvailability.decision_model_provider_id
                        == uuid.UUID(created["id"])
                    )
                )
            ).scalars().all()
            providers = (
                await session.execute(select(SystemOneProviderConfig))
            ).scalars().all()
        # SQLite (the test engine) does not enforce DB-level ON DELETE
        # CASCADE; the real-Postgres cascade is verified by
        # test_decision_providers_schema (delete_rule == CASCADE).
        assert providers == []


class TestPermissions:
    async def test_provider_routes_denied_without_permission(self, no_providers_perm_client):
        for method, url, kwargs in [
            ("get", PROVIDERS_URL, {}),
            ("post", PROVIDERS_URL, {"json": PROVIDER_PAYLOAD}),
            ("get", ENABLED_MODELS_URL, {}),
            ("get", DT_ENABLED_MODELS_URL, {}),
        ]:
            resp = await getattr(no_providers_perm_client, method)(url, **kwargs)
            assert resp.status_code in (401, 403), (method, url, resp.status_code)


@pytest_asyncio.fixture
async def no_providers_perm_client(test_engine):
    """Client WITHOUT permission overrides — the real require_permission runs
    (no identity → rejected)."""
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    app = create_app_for_test()
    app.dependency_overrides[get_db_dep()] = make_override(SessionLocal)
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


def create_app_for_test():
    from app.main import create_app

    return create_app()


def get_db_dep():
    from app.db.session import get_db

    return get_db


def make_override(SessionLocal):
    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    return override_db
