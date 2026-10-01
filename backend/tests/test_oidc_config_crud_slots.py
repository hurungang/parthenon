"""OIDC provider CRUD slot-addressing tests (FIX-20261001-010107).

Covers:

- ``OIDCConfigService.get_by_scope`` shared-slot lookup: ``tenant_id=None``
  MUST produce ``tenant_id IS NULL`` (the ``== None`` form compiled to
  ``tenant_id = NULL`` which matches nothing — the latent NULL-comparison
  bug that made every shared-slot write fail with 400 "No provider config
  exists").
- Handler-level slot addressing: ``/system/identity-providers`` CRUD
  derives ``tenant_id`` from the RESOLVED tenant context
  (``core/tenant_context.py`` on ``request.state``) and passes it into the
  service — a workspace request addresses that tenant's ``(tenant, scope)``
  slot only.
- Platform surface: the SHARED (NULL-tenant) provider config is managed
  from ``/platform/identity-providers`` (bypassed prefix, guarded by
  ``platform::settings``), which calls the same service with
  ``tenant_id=None``.  ``/system/*`` writes WITHOUT a tenant context stay
  fail-closed 403 (A3 pins in test_tenant_login_probe_bypass.py).
- Privacy: the public ``GET /system/identity-providers`` listing returns
  ONLY the shared configs when no tenant context resolves, and shared +
  own-tenant configs with a workspace context — NEVER other tenants'
  metadata.
- Middleware soft resolution: a bypassed public GET carrying a valid
  ``X-Tenant`` binds the tenant context (so workspace-scoped reads see
  shared + own); an invalid slug degrades to the shared-only public view
  (never a 403 on a public read).
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.tenant_context import TenantContext, get_tenant_context  # noqa: E402
from app.db.models.identity_provider_config import IdentityProviderConfig  # noqa: E402
from app.db.session import Base, get_db  # noqa: E402
from app.services.oidc_config_service import OIDCConfigService  # noqa: E402

TENANT_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

CTX_A = TenantContext(tenant_id=TENANT_A, slug="acme", name="Acme")
CTX_B = TenantContext(tenant_id=TENANT_B, slug="globex", name="Globex")

USER_PATH = "/api/v1/system/identity-providers"
PLATFORM_PATH = "/api/v1/platform/identity-providers"


@pytest_asyncio.fixture
async def engine():
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
async def db(engine):
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
        await session.rollback()


def _provider_row(scope: str, tenant_id, issuer: str) -> IdentityProviderConfig:
    from datetime import datetime, timezone

    return IdentityProviderConfig(
        provider_scope=scope,
        provider_type="keycloak",
        display_name=f"{scope}-{tenant_id or 'global'}",
        issuer_url=issuer,
        client_id=f"client-{scope}",
        encrypted_client_secret=None,
        is_enabled=True,
        tenant_id=tenant_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ── Service-level: shared-slot NULL predicate ────────────────────────────────


class TestSharedSlotLookup:
    async def test_get_by_scope_shared_slot_resolves_null_tenant_row(self, db):
        """FIX-20261001-010107 (latent bug): with multi-tenancy ON and
        tenant_id=None the SQL must be ``tenant_id IS NULL`` — the legacy
        ``== None`` form compiled to ``tenant_id = NULL`` (matches nothing),
        so every shared-slot CRUD operation failed with 400."""
        await _set_tenancy(db, True)
        db.add(_provider_row("user", None, "https://shared.example.com"))
        await db.commit()
        config = await OIDCConfigService().get_by_scope(db, "user", tenant_id=None)
        assert config is not None
        assert config.issuer_url == "https://shared.example.com"

    async def test_get_by_scope_shared_slot_ignores_tenant_rows(self, db):
        """The shared lookup must not match a tenant-bound row either."""
        await _set_tenancy(db, True)
        db.add(_provider_row("user", TENANT_A, "https://idp-a.example.com"))
        await db.commit()
        config = await OIDCConfigService().get_by_scope(db, "user", tenant_id=None)
        assert config is None


# ── Handler-level app harness ────────────────────────────────────────────────


class _TestCtxMiddleware(BaseHTTPMiddleware):
    """Stands in for TenantResolutionMiddleware + JWTAuthMiddleware: binds
    the tenant context from X-Test-Tenant-Id and a super-admin identity."""

    async def dispatch(self, request, call_next):
        tenant_id = request.headers.get("x-test-tenant-id")
        if tenant_id:
            request.state.tenant_context = TenantContext(
                tenant_id=uuid.UUID(tenant_id),
                slug=request.headers.get("x-test-tenant-slug", "t"),
                name="T",
            )
        request.state.identity = {
            "is_super_admin": True,
            "sub": "tester",
            "username": "tester",
        }
        return await call_next(request)


@pytest_asyncio.fixture
async def api(db, engine):
    """Test app with the real system + platform routers, session overridden."""
    from app.api.v1.system_config import SystemConfigRouter

    app = FastAPI()
    app.add_middleware(_TestCtxMiddleware)

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    # Discovery validation + registry hot-reload: no network / no app.main.
    with patch(
        "app.services.oidc_config_service._validate_oidc_discovery",
        new=AsyncMock(return_value={"issuer": "x"}),
    ), patch(
        "app.api.v1.system_config._reload_registry",
        new=AsyncMock(),
    ):
        app.include_router(SystemConfigRouter, prefix="/api/v1")

        # Platform surface (added by the fix) — neutralise the
        # platform::settings permission guard for these tests.
        try:
            from app.api.v1.platform.identity_providers import (
                PlatformIdentityProvidersRouter,
            )
        except ImportError:
            pytest.fail(
                "FIX-20261001-010107: /platform/identity-providers routes are "
                "missing — the shared (NULL-tenant) provider config has no "
                "manageable admin surface"
            )
        app.include_router(PlatformIdentityProvidersRouter, prefix="/api/v1")

        for route in app.routes:
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            for dep in dependant.dependencies:
                app.dependency_overrides.setdefault(dep.call, _allow)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


async def _allow():  # pragma: no cover — overridden dependency stub
    return None


@pytest_asyncio.fixture
async def seeded_two_tenants(db):
    """Tenancy ON + (user, A) and (user, B) provider rows."""
    await _set_tenancy(db, True)
    db.add_all(
        [
            _provider_row("user", TENANT_A, "https://idp-a.example.com"),
            _provider_row("user", TENANT_B, "https://idp-b.example.com"),
        ]
    )
    await db.commit()


def _hdrs(ctx: TenantContext | None) -> dict:
    if ctx is None:
        return {}
    return {"x-test-tenant-id": str(ctx.tenant_id), "x-test-tenant-slug": ctx.slug}


class TestTenantContextCrud:
    """T1–T3: /system/* CRUD addresses the RESOLVED tenant's slot."""

    async def test_t1_update_uses_resolved_tenant_slot(self, api, db, seeded_two_tenants):
        resp = await api.put(
            f"{USER_PATH}/user",
            json={"issuer_url": "https://idp-a-v2.example.com"},
            headers=_hdrs(CTX_A),
        )
        assert resp.status_code == 200, resp.text
        rows = {
            r.tenant_id: r
            for r in (
                await db.execute(
                    select(IdentityProviderConfig).where(
                        IdentityProviderConfig.provider_scope == "user"
                    )
                )
            ).scalars()
        }
        assert rows[TENANT_A].issuer_url == "https://idp-a-v2.example.com"
        assert rows[TENANT_B].issuer_url == "https://idp-b.example.com"

    async def test_t2_create_scopes_to_resolved_tenant(self, api, db, seeded_two_tenants):
        resp = await api.post(
            USER_PATH,
            json={
                "provider_scope": "agent",
                "provider_type": "keycloak",
                "display_name": "A agent",
                "issuer_url": "https://a-agent.example.com",
                "client_id": "client-agent",
            },
            headers=_hdrs(CTX_A),
        )
        assert resp.status_code == 201, resp.text
        rows = (
            await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.provider_scope == "agent"
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].tenant_id == TENANT_A

    async def test_t3_toggle_and_delete_hit_only_resolved_tenant(self, api, db, seeded_two_tenants):
        resp = await api.patch(
            f"{USER_PATH}/user/toggle",
            json={"is_enabled": False},
            headers=_hdrs(CTX_A),
        )
        assert resp.status_code == 200, resp.text
        rows = {
            r.tenant_id: r
            for r in (
                await db.execute(
                    select(IdentityProviderConfig).where(
                        IdentityProviderConfig.provider_scope == "user"
                    )
                )
            ).scalars()
        }
        assert rows[TENANT_A].is_enabled is False
        assert rows[TENANT_B].is_enabled is True

        resp = await api.delete(f"{USER_PATH}/user", headers=_hdrs(CTX_A))
        assert resp.status_code == 204, resp.text
        rows = {
            r.tenant_id
            for r in (
                await db.execute(
                    select(IdentityProviderConfig).where(
                        IdentityProviderConfig.provider_scope == "user"
                    )
                )
            ).scalars()
        }
        assert rows == {TENANT_B}  # only B remains

    async def test_update_without_tenant_context_targets_shared_slot(
        self, api, db, seeded_two_tenants
    ):
        """Platform-context-shaped request on /system/*: the middleware A3
        pins keep writes fail-closed 403 (resolution rejects before the
        handler).  Here the test middleware admits the request (super admin)
        — the handler must address the SHARED slot (tenant_id=None), not
        silently fail against ``tenant_id = NULL`` rows."""
        db.add(_provider_row("user", None, "https://shared.example.com"))
        await db.commit()
        resp = await api.put(
            f"{USER_PATH}/user",
            json={"issuer_url": "https://shared-v2.example.com"},
        )
        assert resp.status_code == 200, resp.text
        shared = (
            await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.tenant_id.is_(None),
                    IdentityProviderConfig.provider_scope == "user",
                )
            )
        ).scalar_one()
        assert shared.issuer_url == "https://shared-v2.example.com"


class TestPlatformSurface:
    """T4: the SHARED provider config is managed from /platform/*.  The
    shared slot must never be addressable from a tenant-scoped request."""

    async def test_t4_platform_create_targets_shared_slot(self, api, db, seeded_two_tenants):
        resp = await api.post(
            PLATFORM_PATH,
            json={
                "provider_scope": "user",
                "provider_type": "keycloak",
                "display_name": "shared",
                "issuer_url": "https://shared.example.com",
                "client_id": "client-shared",
            },
        )
        assert resp.status_code == 201, resp.text
        shared = (
            await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.tenant_id.is_(None),
                    IdentityProviderConfig.provider_scope == "user",
                )
            )
        ).scalar_one()
        assert shared.issuer_url == "https://shared.example.com"

    async def test_t4_platform_update_toggles_shared_slot(self, api, db, seeded_two_tenants):
        db.add(_provider_row("user", None, "https://shared.example.com"))
        await db.commit()
        resp = await api.put(
            f"{PLATFORM_PATH}/user",
            json={"display_name": "shared-v2"},
        )
        assert resp.status_code == 200, resp.text
        shared = (
            await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.tenant_id.is_(None),
                    IdentityProviderConfig.provider_scope == "user",
                )
            )
        ).scalar_one()
        assert shared.display_name == "shared-v2"
        # Tenant slots untouched.
        a = (
            await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.tenant_id == TENANT_A,
                    IdentityProviderConfig.provider_scope == "user",
                )
            )
        ).scalar_one()
        assert a.display_name == "user-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    async def test_platform_delete_removes_shared_slot_only(self, api, db, seeded_two_tenants):
        db.add(_provider_row("user", None, "https://shared.example.com"))
        await db.commit()
        resp = await api.delete(f"{PLATFORM_PATH}/user")
        assert resp.status_code == 204, resp.text
        remaining = (
            await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.tenant_id.is_(None)
                )
            )
        ).scalars().all()
        assert remaining == []

    async def test_platform_list_returns_shared_only(self, api, db, seeded_two_tenants):
        db.add(_provider_row("user", None, "https://shared.example.com"))
        await db.commit()
        resp = await api.get(PLATFORM_PATH)
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        assert [i["display_name"] for i in items] == ["user-global"]


class TestPublicListPrivacy:
    """T5: the public listing never leaks other tenants' metadata."""

    async def test_no_tenant_context_returns_shared_only(self, api, db, seeded_two_tenants):
        db.add(_provider_row("user", None, "https://shared.example.com"))
        await db.commit()
        resp = await api.get(USER_PATH)
        assert resp.status_code == 200
        names = {i["display_name"] for i in resp.json()["items"]}
        assert names == {"user-global"}  # NO idp-a / idp-b rows

    async def test_tenant_context_returns_shared_plus_own(self, api, db, seeded_two_tenants):
        db.add(_provider_row("user", None, "https://shared.example.com"))
        await db.commit()
        resp = await api.get(USER_PATH, headers=_hdrs(CTX_A))
        assert resp.status_code == 200
        names = {i["display_name"] for i in resp.json()["items"]}
        assert names == {"user-global", f"user-{TENANT_A}"}

    async def test_never_other_tenants_rows(self, api, db, seeded_two_tenants):
        resp = await api.get(USER_PATH, headers=_hdrs(CTX_A))
        names = {i["display_name"] for i in resp.json()["items"]}
        assert names == {f"user-{TENANT_A}"}  # B excluded


# ── Middleware: soft resolution on the bypassed public GET ───────────────────


class TestBypassedGetSoftResolution:
    async def test_valid_x_tenant_binds_context_on_public_get(self, engine):
        """A bypassed public GET carrying a VALID X-Tenant binds the tenant
        context (so the listing returns shared + own for the workspace)."""
        from app.middleware.tenant_resolution import TenantResolutionMiddleware
        from app.db.models.tenant import Tenant, TenantStatus

        SessionLocal = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            await _set_tenancy(db, True)
            db.add(
                Tenant(
                    id=TENANT_A, name="Acme", slug="acme", status=TenantStatus.active
                )
            )
            await db.commit()

        app = FastAPI()

        @app.get(USER_PATH)
        async def probe(request: FastAPIRequest):
            ctx = get_tenant_context(request)
            return {"tenant": ctx.slug if ctx.is_set else None}

        app.add_middleware(TenantResolutionMiddleware)

        import app.db.session as db_session_module
        import app.services.tenancy.platform_settings_service as settings_module

        class _Switch:
            async def is_multi_tenancy_enabled(self, db_):  # noqa: ARG002
                return True

        with patch.object(
            db_session_module, "AsyncSessionLocal", SessionLocal
        ), patch.object(
            settings_module, "get_platform_settings_service", lambda: _Switch()
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(USER_PATH, headers={"X-Tenant": "acme"})
        assert resp.status_code == 200
        assert resp.json()["tenant"] == "acme"

    async def test_invalid_x_tenant_degrades_to_shared_only_public_get(self, engine):
        """An INVALID slug on a public read must NOT 403 (login-page probe
        must stay reachable) — it degrades to the context-less shared view."""
        from app.middleware.tenant_resolution import TenantResolutionMiddleware

        SessionLocal = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            await _set_tenancy(db, True)

        app = FastAPI()

        @app.get(USER_PATH)
        async def probe(request: FastAPIRequest):
            ctx = get_tenant_context(request)
            return {"tenant": ctx.slug if ctx.is_set else None}

        app.add_middleware(TenantResolutionMiddleware)

        import app.db.session as db_session_module
        import app.services.tenancy.platform_settings_service as settings_module

        class _Switch:
            async def is_multi_tenancy_enabled(self, db_):  # noqa: ARG002
                return True

        with patch.object(
            db_session_module, "AsyncSessionLocal", SessionLocal
        ), patch.object(
            settings_module, "get_platform_settings_service", lambda: _Switch()
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(USER_PATH, headers={"X-Tenant": "no-such-tenant"})
        assert resp.status_code == 200
        assert resp.json()["tenant"] is None


from fastapi import Request as FastAPIRequest  # noqa: E402
