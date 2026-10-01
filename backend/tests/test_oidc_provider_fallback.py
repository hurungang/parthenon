"""FIX-20260930-075014 — provider resolution falls back to the SYSTEM tenant slot.

The adopted platform provider (the OIDC config bound to the implicit
``is_system_tenant`` tenant) previously only resolved for the system tenant
itself: a tenant-less lookup (e.g. ``GET /auth/tenant-memberships``) and a
tenant WITHOUT its own/shared config both resolved ``None`` → "All auth
tiers failed" → session wipe → login loop.

Resolution order (both tenant-scoped and tenant-less lookups):

    own (tenant, scope) slot → shared (None, scope) slot → SYSTEM
    tenant's (system_id, scope) slot

Pins: tenancy-OFF unchanged (single global provider); fail-closed preserved
when NO provider exists anywhere; a tenant's OWN config still wins.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.tenant_context import TenantContext  # noqa: E402
from app.db.models.identity_provider_config import IdentityProviderConfig  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.services.oidc_provider_registry import OIDCProviderRegistry  # noqa: E402

TAG = uuid.uuid4().hex[:8]

SYSTEM_TENANT_ID = uuid.uuid4()
TENANT_X_ID = uuid.uuid4()

CTX_X = TenantContext(tenant_id=TENANT_X_ID, slug=f"tenant-x-{TAG}", name="Tenant X")


@pytest.fixture(autouse=True)
def _fresh_settings_singleton():
    import app.services.tenancy.platform_settings_service as settings_module

    settings_module._service = None
    yield
    settings_module._service = None


async def _set_tenancy(db, enabled: bool) -> None:
    from app.services.tenancy.platform_settings_service import (
        get_platform_settings_service,
    )

    await get_platform_settings_service().set_setting(
        db, "multi_tenancy_enabled", enabled
    )
    await db.commit()


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        system = Tenant(name="System", slug=f"system-{TAG}", is_system_tenant=True)
        system.id = SYSTEM_TENANT_ID
        tenant_x = Tenant(name="Tenant X", slug=f"tenant-x-{TAG}")
        tenant_x.id = TENANT_X_ID
        session.add_all([system, tenant_x])
        await session.flush()
        yield session
        await session.rollback()
    await engine.dispose()


def _system_id() -> uuid.UUID:
    return SYSTEM_TENANT_ID


def _x_id() -> uuid.UUID:
    return TENANT_X_ID


def _provider_row(scope, tenant_id, issuer):
    return IdentityProviderConfig(
        provider_scope=scope,
        provider_type="keycloak",
        display_name=f"{scope}-{tenant_id or 'shared'}",
        issuer_url=issuer,
        client_id=f"client-{scope}",
        encrypted_client_secret=None,
        is_enabled=True,
        tenant_id=tenant_id,
    )


class _FakeOIDCClient:
    captured = {}

    def __init__(self, *, issuer_url, client_id, **kwargs):
        type(self).captured["issuer"] = issuer_url
        type(self).captured["client_id"] = client_id

    async def validate_token(self, token):
        return {"sub": "user-1", "email": "u@example.test"}


def _patch_registry(registry):
    import app.main as main_module

    return patch.object(main_module, "_get_registry", lambda: registry)


class TestSystemTenantSlotFallback:
    """A — the adopted platform provider serves tenant-less and other-tenant
    lookups via the SYSTEM tenant slot fallback."""

    @pytest_asyncio.fixture
    async def registry(self, db):
        """Tenancy ON; the ONLY provider row lives in the SYSTEM tenant slot
        (the adopted-platform-provider situation from the defect report)."""
        await _set_tenancy(db, True)
        db.add(_provider_row("user", _system_id(), "https://adopted.example.com"))
        await db.commit()
        registry = OIDCProviderRegistry()
        await registry.initialize(db)
        return registry

    async def test_a_tenant_less_lookup_resolves_system_slot(self, registry):
        """(a) Tenant-less lookups (platform surfaces, /auth/tenant-memberships)
        resolve the SYSTEM tenant's slot when no shared config exists.
        Today: None → 'All auth tiers failed' → login loop."""
        provider = registry.get_provider("user", None)
        assert provider is not None, (
            "SYSTEM-TENANT FALLBACK MISSING (FIX-20260930-075014 / a): the "
            "adopted platform provider lives only in the system-tenant slot — "
            "a tenant-less lookup must fall back to it, got None"
        )
        assert provider.issuer_url == "https://adopted.example.com"

    async def test_a_tenant_less_request_validates_token(self, db, registry):
        """(a) end-to-end: a tenant-less request validates against the
        system-slot provider (today `_try_oidc_token` returns None)."""
        import app.middleware.auth as auth_module

        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _FakeOIDCClient
        ):
            claims = await auth_module._try_oidc_token("tok", None)
        assert claims is not None, (
            "TENANT-LESS OIDC VALIDATION FAILS (FIX-20260930-075014 / a): the "
            "'All auth tiers failed' loop — a tenant-less request must validate "
            "the token against the adopted (system-slot) provider"
        )
        assert claims["_provider_scope"] == "user"
        # tenant-less validation injects NO tenant claim (semantics unchanged)
        assert claims.get("tenant") is None

    async def test_b_tenant_without_own_or_shared_resolves_system_slot(
        self, registry
    ):
        """(b) Tenant X (no own config, no shared config) resolves the SYSTEM
        provider for its login context — one provider serves all tenants."""
        provider = registry.get_provider("user", _x_id())
        assert provider is not None, (
            "SYSTEM-TENANT FALLBACK MISSING FOR TENANT CONTEXT "
            "(FIX-20260930-075014 / b): a tenant without own/shared config "
            "must resolve the adopted system provider"
        )
        assert provider.issuer_url == "https://adopted.example.com"

    async def test_b_tenant_login_context_validates_against_system_provider(
        self, registry
    ):
        """(b) middleware level: tenant X's login context validates the token
        via the system-slot provider AND injects the tenant claim (semantics
        unchanged)."""
        import app.middleware.auth as auth_module

        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _FakeOIDCClient
        ):
            claims = await auth_module._try_oidc_token("tok", CTX_X)
        assert claims is not None
        assert _FakeOIDCClient.captured["issuer"] == "https://adopted.example.com"
        assert claims.get("tenant") == CTX_X.slug

    async def test_c_tenant_own_config_wins_over_system_slot(self, db, registry):
        """(c) precedence pin: X's OWN config still wins over the system-slot
        fallback."""
        db.add(_provider_row("user", _x_id(), "https://x-own.example.com"))
        await db.commit()
        await registry.reload(db)
        provider = registry.get_provider("user", _x_id())
        assert provider is not None
        assert provider.issuer_url == "https://x-own.example.com", (
            "PRECEDENCE (FIX-20260930-075014 / c): the tenant's OWN provider "
            "slot must win over the system-tenant fallback"
        )

    async def test_shared_slot_still_precedes_system_slot(self, db, registry):
        """Ordering within the fallback: shared (None) slot beats the system
        slot for both tenant-less and tenant-scoped lookups."""
        db.add(_provider_row("user", None, "https://shared.example.com"))
        await db.commit()
        await registry.reload(db)
        assert registry.get_provider("user", None).issuer_url == (
            "https://shared.example.com"
        )
        assert registry.get_provider("user", _x_id()).issuer_url == (
            "https://shared.example.com"
        )

    async def test_no_provider_anywhere_is_fail_closed_none(self, db):
        """Fail-closed preserved: no provider anywhere → None (both lookup
        kinds)."""
        await _set_tenancy(db, True)
        registry = OIDCProviderRegistry()
        await registry.initialize(db)
        assert registry.get_provider("user", None) is None
        assert registry.get_provider("user", _x_id()) is None

    async def test_tenancy_off_unchanged(self, db):
        """Tenancy OFF: byte-for-byte legacy — the tenant-less global slot is
        the only resolution; no system-slot behaviour."""
        await _set_tenancy(db, False)
        db.add(_provider_row("user", _system_id(), "https://stale-system.example.com"))
        db.add(_provider_row("user", None, "https://legacy.example.com"))
        await db.commit()
        registry = OIDCProviderRegistry()
        await registry.initialize(db)
        assert registry.get_provider("user", None).issuer_url == "https://legacy.example.com"
        assert registry.get_provider("user", _x_id()).issuer_url == "https://legacy.example.com"

    async def test_system_tenant_itself_resolves_own_slot(self, registry):
        """The system tenant's own context resolves its own (adopted) slot —
        direct lookup, not through the fallback."""
        provider = registry.get_provider("user", _system_id())
        assert provider is not None
        assert provider.issuer_url == "https://adopted.example.com"
