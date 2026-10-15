"""Shared-slot retirement — every tenant resolves ONLY its own provider.

Product rule: EVERY tenant uses ONLY its own identity provider (root
uses its own).  There is NO shared provider and NO candidate chain.
A tenant without its own enabled provider for a scope simply has no
OIDC login for that scope.  Tenancy OFF ⇒ the ROOT tenant's providers
only.  NULL-tenant (shared) rows are inert legacy data — never loaded.

Pins: own-slot-only resolution (multi-tenancy ON); fail-closed None for
tenant-less / unconfigured tenants; NULL-tenant rows ignored on load;
tenancy-OFF root-slot-only unchanged.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.oidc_client import OIDCError  # noqa: E402
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


class TestOwnSlotOnlyResolution:
    """Multi-tenancy ON: ONLY the tenant's OWN (tenant, scope) slot
    resolves — no shared slot, no root-slot fallback chain."""

    @pytest_asyncio.fixture
    async def registry(self, db):
        """Tenancy ON; the ONLY provider row lives in the ROOT tenant slot
        (the legacy adopted-platform-provider situation — inert now)."""
        await _set_tenancy(db, True)
        db.add(_provider_row("user", _system_id(), "https://adopted.example.com"))
        await db.commit()
        registry = OIDCProviderRegistry()
        await registry.initialize(db)
        return registry

    async def test_tenant_less_lookup_resolves_none(self, registry):
        """(a) Tenant-less lookups resolve NOTHING — no shared slot, no
        root fallback (no tenant resolved = no providers)."""
        assert registry.get_provider("user", None) is None

    async def test_tenant_less_request_bootstrap_validates_via_all_providers(
        self, db, registry
    ):
        """(a) end-to-end: a tenant-less request (login bootstrap, before a
        workspace is chosen) validates against ALL tenants' providers —
        the issuer that validates identifies the realm.  No tenant claim
        is injected (no resolved context to bind)."""
        import app.middleware.auth as auth_module

        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _FakeOIDCClient
        ):
            claims = await auth_module._try_oidc_token("tok", None)
        assert claims is not None
        assert "tenant" not in claims

    async def test_b_tenant_without_own_config_resolves_none(self, registry):
        """(b) Tenant X (no own config) resolves None — fail-closed, the
        root-slot provider does NOT serve other tenants."""
        assert registry.get_provider("user", _x_id()) is None

    async def test_b_tenant_login_context_fails_without_own_provider(
        self, registry
    ):
        """(b) middleware level: tenant X's login context has no candidates
        → validation fails (no OIDC login for that tenant)."""
        import app.middleware.auth as auth_module

        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _FakeOIDCClient
        ):
            claims = await auth_module._try_oidc_token("tok", CTX_X)
        assert claims is None

    async def test_c_tenant_own_config_resolves(self, db, registry):
        """(c) Tenant X's OWN config resolves for X once configured."""
        db.add(_provider_row("user", _x_id(), "https://x-own.example.com"))
        await db.commit()
        await registry.reload(db)
        provider = registry.get_provider("user", _x_id())
        assert provider is not None
        assert provider.issuer_url == "https://x-own.example.com"

    async def test_shared_slot_ignored_on_load(self, db, registry):
        """A NULL-tenant (shared) row is NEVER loaded — inert legacy data;
        it resolves for nobody."""
        db.add(_provider_row("user", None, "https://shared.example.com"))
        await db.commit()
        await registry.reload(db)
        assert registry.get_provider("user", None) is None
        assert registry.get_provider("user", _x_id()) is None
        # and it is not cached at all
        assert all(k[0] is not None for k in registry._providers)

    async def test_no_provider_anywhere_is_fail_closed_none(self, db):
        """Fail-closed preserved: no providers anywhere → None (both
        lookup kinds)."""
        await _set_tenancy(db, True)
        registry = OIDCProviderRegistry()
        await registry.initialize(db)
        assert registry.get_provider("user", None) is None
        assert registry.get_provider("user", _x_id()) is None

    async def test_tenancy_off_default_provider_is_explicit(self, db):
        """Tenancy OFF: the ROOT tenant IS the default tenant — the ONLY
        lookup is the explicit ``get_default_provider``; a tenant-addressed
        lookup raises (no hidden root fallback for arbitrary tenant ids).
        NULL-tenant (shared) rows are never loaded and other tenants'
        rows never resolve."""
        await _set_tenancy(db, False)
        db.add(_provider_row("user", _system_id(), "https://root.example.com"))
        db.add(_provider_row("user", None, "https://legacy.example.com"))
        db.add(_provider_row("user", _x_id(), "https://stale-x.example.com"))
        await db.commit()
        registry = OIDCProviderRegistry()
        await registry.initialize(db)

        default = registry.get_default_provider("user")
        assert default is not None
        assert default.issuer_url == "https://root.example.com"
        assert registry.get_provider("user", None).issuer_url == (
            "https://root.example.com"
        )
        for tenant_id in (_x_id(), _system_id()):
            with pytest.raises(ValueError, match="get_default_provider"):
                registry.get_provider("user", tenant_id)
            with pytest.raises(ValueError, match="get_default_provider"):
                registry.get_provider_candidates("user", tenant_id)

    async def test_system_tenant_itself_resolves_own_slot(self, registry):
        """The system (root) tenant's own context resolves its own slot."""
        provider = registry.get_provider("user", _system_id())
        assert provider is not None
        assert provider.issuer_url == "https://adopted.example.com"


class _IssuerGatedOIDCClient:
    """Fake OIDC client that only validates tokens signed by ONE issuer
    (models the real "Unknown key id" failure when the validator probes
    the WRONG provider)."""

    signing_issuer: str | None = None
    captured_issuers: list[str] = []

    def __init__(self, *, issuer_url, client_id, **kwargs):
        self._issuer = issuer_url
        type(self).captured_issuers.append(issuer_url)

    async def validate_token(self, token):
        if self._issuer != type(self).signing_issuer:
            raise OIDCError(f"Unknown key id (available: {self._issuer} keys)")
        return {"sub": "user-1", "email": "u@example.test"}


class TestSingleCandidateResolution:
    """get_provider_candidates returns a SINGLE candidate (the tenant's
    own slot) or an empty list — never a chain."""

    @pytest_asyncio.fixture
    async def registry(self, db):
        """Tenancy ON; root slot and X's own slot configured; a legacy
        NULL-tenant row present (must be ignored)."""
        await _set_tenancy(db, True)
        db.add(_provider_row("user", None, "https://acme.example.com"))
        db.add(_provider_row("user", _system_id(), "https://parthenon.example.com"))
        db.add(_provider_row("user", _x_id(), "https://x-own.example.com"))
        await db.commit()
        registry = OIDCProviderRegistry()
        await registry.initialize(db)
        return registry

    async def test_candidates_own_slot_only(self, registry):
        """Candidates: own slot only for a resolved tenant; empty for a
        tenant-less lookup; the NULL-tenant row never appears."""
        issuers = [p.issuer_url for p in registry.get_provider_candidates("user", _x_id())]
        assert issuers == ["https://x-own.example.com"]

        assert registry.get_provider_candidates("user", None) == []
        root = registry.get_provider_candidates("user", _system_id())
        assert [p.issuer_url for p in root] == ["https://parthenon.example.com"]
        # The shared (NULL-tenant) slot never appears anywhere.
        for tenant_id in (None, _x_id(), _system_id()):
            for p in registry.get_provider_candidates("user", tenant_id):
                assert p.issuer_url != "https://acme.example.com"

    async def test_tenancy_off_candidates_default_slot_only(self, db):
        """Tenancy OFF: candidates come from the DEFAULT (root-tenant)
        slot only — a tenant-addressed candidates call raises instead of
        silently resolving root; NULL-tenant rows never load."""
        await _set_tenancy(db, False)
        db.add(_provider_row("user", _system_id(), "https://root.example.com"))
        db.add(_provider_row("user", None, "https://legacy.example.com"))
        await db.commit()
        registry = OIDCProviderRegistry()
        await registry.initialize(db)
        candidates = registry.get_provider_candidates("user", None)
        assert [p.issuer_url for p in candidates] == ["https://root.example.com"]
        with pytest.raises(ValueError, match="get_default_provider"):
            registry.get_provider_candidates("user", _x_id())

    async def test_tenant_context_validates_own_provider_only(self, registry):
        """Token validation probes ONLY the tenant's own provider — a
        root-slot-signed token does NOT validate in X's context."""
        import app.middleware.auth as auth_module

        _IssuerGatedOIDCClient.signing_issuer = "https://parthenon.example.com"
        _IssuerGatedOIDCClient.captured_issuers = []
        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _IssuerGatedOIDCClient
        ):
            claims = await auth_module._try_oidc_token("tok", CTX_X)
        assert claims is None, (
            "a foreign (root-slot) token must NOT validate in tenant X's "
            "context — X's own provider is the only candidate"
        )
        assert _IssuerGatedOIDCClient.captured_issuers == ["https://x-own.example.com"]

    async def test_own_signed_token_validates_and_injects_claim(self, registry):
        """A token signed by X's OWN provider validates and gets X's claim
        injected (semantics unchanged)."""
        import app.middleware.auth as auth_module

        _IssuerGatedOIDCClient.signing_issuer = "https://x-own.example.com"
        _IssuerGatedOIDCClient.captured_issuers = []
        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _IssuerGatedOIDCClient
        ):
            claims = await auth_module._try_oidc_token("tok", CTX_X)
        assert claims is not None
        assert _IssuerGatedOIDCClient.captured_issuers == ["https://x-own.example.com"]
        assert claims.get("tenant") == CTX_X.slug

    async def test_untrusted_key_fails_closed(self, registry):
        """A token signed by an unknown/untrusted key fails → 401 path."""
        import app.middleware.auth as auth_module

        _IssuerGatedOIDCClient.signing_issuer = "https://evil.example.com"
        _IssuerGatedOIDCClient.captured_issuers = []
        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _IssuerGatedOIDCClient
        ):
            claims = await auth_module._try_oidc_token("tok", CTX_X)
        assert claims is None
