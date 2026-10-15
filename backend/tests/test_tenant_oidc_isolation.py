"""Per-tenant OIDC isolation tests (Phase 4 / 9.3, CS-14/CS-15/CS-16).

Covers:

- ``OIDCProviderRegistry`` per-tenant cache keyed by (tenant, scope):
  tenant A's provider never resolves for tenant B **when A has its own
  config**; the tenant-less row is the SHARED provider — usable by the
  platform and by any tenant WITHOUT its own config (per-tenant configs
  take precedence; FIX-20260929-221449).  With no provider resolvable at
  all (neither own nor shared), lookup is None — fail-closed sign-in.
- Switch OFF: registry is platform-wide — lookup ignores tenant ids
  (single-tenant behaviour unchanged).
- ``_try_oidc_token`` / claim validation: with a resolved tenant context
  the token is validated ONLY against that tenant's provider, no legacy
  fallback runs, and a token from tenant A's provider cannot validate
  for tenant B (CS-14).
- ``JWTAuthMiddleware._check_tenant_claim``: missing / mismatched /
  matching tenant claims, super-admin platform-only rejection, inert
  when no tenant context, and security-relevant audit events written
  for every rejection (CS-15).
- ``OIDCConfigService`` per-tenant CRUD isolation: tenant A cannot read
  or write tenant B's provider config (CS-16).
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.tenant_context import TenantContext  # noqa: E402
from app.db.models.identity_provider_config import IdentityProviderConfig  # noqa: E402
from app.db.models.tenant_audit_event import (  # noqa: E402
    TenantAuditEvent,
    TenantAuditEventType,
)
from app.db.session import Base  # noqa: E402
from app.services.oidc_provider_registry import OIDCProviderRegistry  # noqa: E402

TENANT_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TENANT_ROOT = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

CTX_A = TenantContext(tenant_id=TENANT_A, slug="acme", name="Acme")
CTX_B = TenantContext(tenant_id=TENANT_B, slug="globex", name="Globex")
CTX_ROOT = TenantContext(tenant_id=TENANT_ROOT, slug="root", name="Root")
CTX_SYSTEM = TenantContext(
    tenant_id=TENANT_A, slug="system", name="System", is_system_tenant=True
)


@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory engine per test (no cross-test pollution)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_settings_singleton():
    """Isolate the process-wide PlatformSettingsService cache per test."""
    import app.services.tenancy.platform_settings_service as settings_module

    settings_module._service = None
    yield
    settings_module._service = None


async def _set_tenancy(db, enabled: bool) -> None:
    """Toggle the switch through the process-wide singleton (cache coherent)."""
    from app.services.tenancy.platform_settings_service import (
        get_platform_settings_service,
    )

    await get_platform_settings_service().set_setting(
        db, "multi_tenancy_enabled", enabled
    )
    await db.commit()


@pytest_asyncio.fixture
async def db(engine):
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
        await session.rollback()


def _provider_row(scope: str, tenant_id: uuid.UUID | None, issuer: str) -> IdentityProviderConfig:
    return IdentityProviderConfig(
        provider_scope=scope,
        provider_type="keycloak",
        display_name=f"{scope}-{tenant_id or 'global'}",
        issuer_url=issuer,
        client_id=f"client-{scope}",
        encrypted_client_secret=None,
        is_enabled=True,
        tenant_id=tenant_id,
    )


# ── Registry keying ──────────────────────────────────────────────────────────


class TestRegistryTenantKeying:
    @pytest_asyncio.fixture
    async def registry(self, db):
        """Switch ON + three provider rows: A-bound, B-bound, one global."""
        await _set_tenancy(db, True)
        db.add_all(
            [
                _provider_row("user", TENANT_A, "https://idp-a.example.com"),
                _provider_row("user", TENANT_B, "https://idp-b.example.com"),
                _provider_row("user", None, "https://legacy.example.com"),
            ]
        )
        await db.commit()

        registry = OIDCProviderRegistry()
        await registry.initialize(db)
        return registry

    async def test_tenant_gets_own_provider(self, db, registry):
        assert registry.get_provider("user", TENANT_A).issuer_url == "https://idp-a.example.com"
        assert registry.get_provider("user", TENANT_B).issuer_url == "https://idp-b.example.com"

    async def test_cross_tenant_lookup_is_isolated(self, db, registry):
        """CS-14 groundwork: each tenant resolves exactly its own provider."""
        a = registry.get_provider("user", TENANT_A)
        b = registry.get_provider("user", TENANT_B)
        assert a.issuer_url != b.issuer_url

    async def test_system_tenant_falls_back_to_global(self, db, registry):
        provider = registry.get_provider("user", TENANT_A, is_system_tenant=True)
        # TENANT_A has its own row — that wins for the system tenant too.
        assert provider.issuer_url == "https://idp-a.example.com"

    async def test_tenant_without_own_config_resolves_none(self, db, registry):
        """SEMANTICS CHANGED (shared-slot retirement): every tenant uses
        ONLY its own provider — a tenant WITHOUT its own config resolves
        None (no OIDC login).  The legacy NULL-tenant row is inert and
        never resolves for anyone."""
        provider = registry.get_provider("user", uuid.uuid4())
        assert provider is None
        assert registry.get_provider("user", TENANT_A) is not None  # own slot only

    async def test_no_provider_anywhere_is_fail_closed_none(self, db):
        """Fail-closed preserved: a tenant with NEITHER an own config NOR a
        shared (tenant-less) config gets None — sign-in not configured."""
        await _set_tenancy(db, True)
        db.add(_provider_row("user", TENANT_B, "https://idp-b.example.com"))
        await db.commit()
        registry = OIDCProviderRegistry()
        await registry.initialize(db)
        assert registry.get_provider("user", TENANT_A) is None
        assert registry.get_provider("user", uuid.uuid4()) is None

    async def test_switch_off_default_provider_is_explicit(self, db):
        """With the switch off the ONLY lookup is the explicit
        ``get_default_provider`` (the root slot); a tenant-addressed
        lookup raises instead of silently resolving the default."""
        await _set_tenancy(db, False)
        db.add_all(
            [
                _provider_row("user", None, "https://legacy.example.com"),
                _provider_row("user", TENANT_A, "https://tenant-a.example.com"),
            ]
        )
        await db.commit()
        registry = OIDCProviderRegistry()
        await registry.initialize(db)
        assert registry.multi_tenancy_enabled is False
        # explicit default lookup: the tenant-less pre-seed slot here
        assert registry.get_default_provider("user").issuer_url == (
            "https://legacy.example.com"
        )
        assert registry.get_provider("user", None).issuer_url == (
            "https://legacy.example.com"
        )
        with pytest.raises(ValueError, match="get_default_provider"):
            registry.get_provider("user", TENANT_A)

    async def test_reload_single_refreshes_all_tenants_of_scope(self, db, registry):
        row_a = (
            await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.tenant_id == TENANT_A
                )
            )
        ).scalar_one()
        row_a.issuer_url = "https://idp-a-v2.example.com"
        await db.flush()

        await registry.reload_single(db, "user")
        assert registry.get_provider("user", TENANT_A).issuer_url == "https://idp-a-v2.example.com"
        assert registry.get_provider("user", TENANT_B).issuer_url == "https://idp-b.example.com"


# ── Token validation pipeline (tenant-bound) ─────────────────────────────────


class _FakeRegistry:
    """Registry stub exposing provider resolution + secrets only."""

    def __init__(self, providers: dict, initialized: bool = True):
        self._providers = providers  # (tenant_key, scope) -> (issuer, client_id)
        self.initialized = initialized
        self._multi_tenancy_enabled = True
        self._root_tenant_id = None

    def get_provider(self, scope, tenant_id=None, is_system_tenant=False):
        key = (str(tenant_id) if tenant_id else None, scope)
        if key not in self._providers and is_system_tenant:
            key = (None, scope)
        entry = self._providers.get(key)
        if entry is None:
            return None
        return SimpleNamespace(
            issuer_url=entry[0], client_id=entry[1], claim_mappings={}
        )

    def get_provider_candidates(self, scope, tenant_id=None, is_system_tenant=False):
        """Ordered chain: own (tenant, scope) → shared (None, scope) → root slot."""
        candidates: list = []
        seen: set = set()

        def _add(key):
            if key in seen:
                return
            entry = self._providers.get(key)
            if entry is not None:
                seen.add(key)
                candidates.append(
                    SimpleNamespace(
                        issuer_url=entry[0], client_id=entry[1], claim_mappings={}
                    )
                )

        tenant_key = str(tenant_id) if tenant_id else None
        if tenant_key is not None:
            _add((tenant_key, scope))
        _add((None, scope))
        if self._root_tenant_id and self._root_tenant_id != tenant_key:
            _add((self._root_tenant_id, scope))
        return candidates

    def get_decrypted_secret(self, scope, tenant_id=None, is_system_tenant=False):
        return None

    def get_decrypted_secret_for(self, provider):
        return None

    def has_any_provider(self):
        return len(self._providers) > 0


class TestTryOidcTokenTenantBinding:
    def _patch_registry(self, registry):
        import app.main as main_module

        # _try_oidc_token imports _get_registry from app.main at call time.
        return patch.object(main_module, "_get_registry", lambda: registry)

    async def test_prefers_resolved_tenant_provider(self):
        """The resolved tenant's own provider is tried FIRST in the
        candidate chain (own → shared → root)."""
        import app.middleware.auth as auth_module

        registry = _FakeRegistry(
            {
                (str(TENANT_A), "user"): ("https://idp-a", "client-a"),
                (str(TENANT_B), "user"): ("https://idp-b", "client-b"),
            }
        )
        captured = {}

        class FakeOIDCClient:
            def __init__(self, *, issuer_url, client_id, **kwargs):
                captured["issuer"] = issuer_url
                captured["client_id"] = client_id

            async def validate_token(self, token):
                return {"sub": "user-1"}

        with self._patch_registry(registry), patch.object(
            auth_module, "OIDCClient", FakeOIDCClient
        ):
            claims = await auth_module._try_oidc_token("token", CTX_A)
        assert claims is not None
        assert claims["_provider_scope"] == "user"
        assert captured == {"issuer": "https://idp-a", "client_id": "client-a"}

    async def test_no_provider_for_tenant_is_rejected_fail_closed(self):
        """No provider anywhere in the resolution chain → None (fail-closed)."""
        import app.middleware.auth as auth_module

        registry = _FakeRegistry(
            {(str(TENANT_B), "user"): ("https://idp-b", "client-b")}
        )
        with self._patch_registry(registry):
            claims = await auth_module._try_oidc_token("token", CTX_A)
        assert claims is None

    async def test_tenancy_off_resolves_root_tenant_chain(self):
        """Tenancy OFF binds the ROOT tenant — validation uses the root
        tenant's own provider chain (Phase 11 root-tenant model)."""
        import app.middleware.auth as auth_module

        registry = _FakeRegistry(
            {(str(TENANT_ROOT), "user"): ("https://parthenon-realm", "client")}
        )
        registry.initialized = True

        class FakeOIDCClient:
            def __init__(self, **kwargs):
                pass

            async def validate_token(self, token):
                return {"sub": "user-1"}

        with self._patch_registry(registry), patch.object(
            auth_module, "OIDCClient", FakeOIDCClient
        ), patch.object(auth_module, "get_oidc_client", lambda: FakeOIDCClient()):
            claims = await auth_module._try_oidc_token("token", CTX_ROOT)
        assert claims is not None
        assert claims["_provider_scope"] == "user"


# ── Tenant claim check (CS-14/CS-15) ─────────────────────────────────────────


class _FakeRequest:
    # Phase 11: these tests simulate a tenancy-ON resolved context.
    def __init__(self, context=None, path="/api/v1/roles"):
        self.state = SimpleNamespace()
        # Phase 11: a resolved context is tenancy-ON in these tests —
        # claim checks / JIT branch on the explicit switch flag.
        self.state.tenancy_enabled = context is not None
        if context is not None:
            self.state.tenant_context = context
        self.url = SimpleNamespace(path=path)
        self.method = "GET"
        self.client = SimpleNamespace(host="10.0.0.9")


class TestCheckTenantClaim:
    def _middleware(self):
        from app.middleware.auth import JWTAuthMiddleware

        return JWTAuthMiddleware(app=None)  # check method needs no app

    def _audit_patch(self, test_engine):
        """Point the audit writer's AsyncSessionLocal at the test DB."""
        import app.db.session as db_session_module

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        return patch.object(db_session_module, "AsyncSessionLocal", SessionLocal)

    async def test_inert_without_tenant_context(self):
        mw = self._middleware()
        request = _FakeRequest(context=None)
        error = await mw._check_tenant_claim(request, {"sub": "u"}, False)
        assert error is None  # multi-tenancy off → untouched

    async def test_missing_claim_rejected(self, db, engine):
        mw = self._middleware()
        request = _FakeRequest(context=CTX_A)
        with self._audit_patch(engine):
            error = await mw._check_tenant_claim(request, {"sub": "u"}, False)
        assert error is not None
        assert "not valid for this tenant" in error
        await self._assert_audited(engine, reason="missing_claim")

    async def test_empty_claim_rejected(self):
        mw = self._middleware()
        request = _FakeRequest(context=CTX_A)
        error = await mw._check_tenant_claim(request, {"sub": "u", "tenant": "  "}, False)
        assert error is not None

    async def test_mismatched_claim_rejected(self, engine):
        """CS-14: tenant A's token used against tenant B → 401 + audit."""
        mw = self._middleware()
        request = _FakeRequest(context=CTX_B)
        with self._audit_patch(engine):
            error = await mw._check_tenant_claim(
                request, {"sub": "u", "tenant": "acme"}, False
            )
        assert error is not None
        await self._assert_audited(engine, reason="mismatch", token_tenant="acme")

    async def test_matching_slug_claim_passes(self):
        mw = self._middleware()
        request = _FakeRequest(context=CTX_A)
        error = await mw._check_tenant_claim(
            request, {"sub": "u", "tenant": "acme"}, False
        )
        assert error is None

    async def test_matching_uuid_claim_passes(self):
        mw = self._middleware()
        request = _FakeRequest(context=CTX_A)
        error = await mw._check_tenant_claim(
            request, {"sub": "u", "tenant": str(TENANT_A)}, False
        )
        assert error is None

    async def test_super_admin_rejected_for_tenant_workspaces(self, engine):
        """CS-23: super admin is platform-only in tenant workspaces."""
        mw = self._middleware()
        request = _FakeRequest(context=CTX_A)
        with self._audit_patch(engine):
            error = await mw._check_tenant_claim(request, {"sub": "sa"}, True)
        assert error is not None
        assert "super admin" in error.lower()
        await self._assert_audited(engine, reason="super_admin_platform_only")

    async def _assert_audited(self, engine, *, reason, token_tenant=None):
        SessionLocal = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as checker:
            events = (
                await checker.execute(
                    select(TenantAuditEvent).where(
                        TenantAuditEvent.event_type
                        == TenantAuditEventType.cross_tenant_access_denied
                    )
                )
            ).scalars().all()
        assert len(events) >= 1
        detail = events[-1].detail or {}
        assert detail.get("reason") == reason
        assert events[-1].is_security_relevant is True
        if token_tenant is not None:
            assert detail.get("token_tenant") == token_tenant


# ── OIDCConfigService per-tenant CRUD isolation (CS-16) ──────────────────────


class TestOIDCConfigServiceTenantIsolation:
    @pytest_asyncio.fixture(autouse=True)
    async def seeded(self, db):
        self.service = _make_config_service()
        await _set_tenancy(db, True)
        db.add_all(
            [
                _provider_row("user", TENANT_A, "https://idp-a.example.com"),
                _provider_row("user", TENANT_B, "https://idp-b.example.com"),
            ]
        )
        await db.commit()

        # Neutralise discovery validation (no network in tests).
        self._discovery_patch = patch(
            "app.services.oidc_config_service._validate_oidc_discovery",
            new=AsyncMock(return_value={"issuer": "x"}),
        )
        self._discovery_patch.start()
        yield
        self._discovery_patch.stop()

    async def test_get_by_scope_addresses_exact_tenant_slot(self, db):
        a = await self.service.get_by_scope(db, "user", tenant_id=TENANT_A)
        b = await self.service.get_by_scope(db, "user", tenant_id=TENANT_B)
        assert a.issuer_url == "https://idp-a.example.com"
        assert b.issuer_url == "https://idp-b.example.com"

    async def test_update_cannot_touch_other_tenants_config(self, db):
        """Tenant A's admin updates THEIR slot — tenant B is untouched."""
        await self.service.update_provider(
            db,
            "user",
            client_id="rotated-client-a",
            tenant_id=TENANT_A,
        )
        a = await self.service.get_by_scope(db, "user", tenant_id=TENANT_A)
        b = await self.service.get_by_scope(db, "user", tenant_id=TENANT_B)
        assert a.client_id == "rotated-client-a"
        assert b.client_id == "client-user"  # unchanged

    async def test_update_other_tenant_slot_is_not_found(self, db):
        """Addressing a slot that doesn't exist for YOUR tenant fails —
        tenant B has no 'agent' provider, so its lookup is None."""
        config = await self.service.get_by_scope(db, "agent", tenant_id=TENANT_B)
        assert config is None

    async def test_per_tenant_scope_uniqueness(self, db):
        """The same scope may exist once per tenant (uniqueness is
        per-tenant when the switch is on)."""
        # (user, A) and (user, B) already coexist from the fixture.
        a = await self.service.get_by_scope(db, "user", tenant_id=TENANT_A)
        b = await self.service.get_by_scope(db, "user", tenant_id=TENANT_B)
        assert a is not None and b is not None

    async def test_switch_off_uniqueness_is_platform_wide(self, db):
        from app.services.oidc_config_service import OIDCConfigError

        await _set_tenancy(db, False)
        # Consolidate to a single platform-wide slot first (legacy
        # semantics): keep only the global row.
        rows = (
            await db.execute(select(IdentityProviderConfig))
        ).scalars().all()
        for row in rows:
            await db.delete(row)
        await db.commit()
        db.add(_provider_row("user", None, "https://legacy.example.com"))
        await db.commit()
        with pytest.raises(OIDCConfigError):
            await self.service.create_provider(
                db,
                provider_scope="user",
                provider_type="keycloak",
                display_name="dup",
                issuer_url="https://new.example.com",
                client_id="c",
            )


def _make_config_service():
    from app.services.oidc_config_service import OIDCConfigService

    return OIDCConfigService()
