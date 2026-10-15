"""OIDC provider CRUD slot-addressing tests.

Covers:

- ``OIDCConfigService.get_by_scope``: with multi-tenancy ON the exact
  ``(tenant_id, scope)`` slot is addressed; ``tenant_id=None`` resolves
  NOTHING (the shared NULL-tenant slot is RETIRED — legacy NULL-tenant
  rows are inert).
- Handler-level slot addressing: ``/system/identity-providers`` CRUD
  derives ``tenant_id`` from the RESOLVED tenant context
  (``core/tenant_context.py`` on ``request.state``) and passes it into the
  service — a workspace request addresses that tenant's ``(tenant, scope)``
  slot only.
- Platform surface: the ROOT tenant's provider configs are managed from
  ``/platform/identity-providers`` (bypassed prefix, guarded by
  ``platform::settings``), which calls the same service with
  ``tenant_id=root_tenant_id``.  ``/system/*`` writes WITHOUT a tenant
  context stay fail-closed 403 (A3 pins in test_tenant_login_probe_bypass.py).
- Privacy: the public ``GET /system/identity-providers`` listing returns
  NOTHING without a resolved tenant context, and ONLY the own-tenant
  configs with a workspace context — NEVER other tenants' metadata.
- Middleware soft resolution: a bypassed public GET carrying a valid
  ``X-Tenant`` binds the tenant context; an invalid slug degrades to the
  empty public view (never a 403 on a public read).
"""
from __future__ import annotations

import os
import time
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
from app.services.oidc_config_service import OIDCConfigError, OIDCConfigService

TENANT_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
ROOT_TENANT = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

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
    async def test_get_by_scope_without_tenant_resolves_nothing(self, db):
        """The shared NULL-tenant slot is RETIRED: with multi-tenancy ON
        and tenant_id=None the lookup resolves NOTHING — even a legacy
        NULL-tenant row present in the DB stays inert."""
        await _set_tenancy(db, True)
        db.add(_provider_row("user", None, "https://shared.example.com"))
        await db.commit()
        config = await OIDCConfigService().get_by_scope(db, "user", tenant_id=None)
        assert config is None

    async def test_get_by_scope_without_tenant_ignores_tenant_rows(self, db):
        """The tenant-less lookup must not match a tenant-bound row either."""
        await _set_tenancy(db, True)
        db.add(_provider_row("user", TENANT_A, "https://idp-a.example.com"))
        await db.commit()
        config = await OIDCConfigService().get_by_scope(db, "user", tenant_id=None)
        assert config is None

    async def test_create_without_tenant_is_rejected(self, db):
        """Writes require a resolved tenant — the shared slot is never
        written."""
        await _set_tenancy(db, True)
        with pytest.raises(OIDCConfigError):
            await OIDCConfigService().create_provider(
                db,
                provider_scope="user",
                provider_type="keycloak",
                display_name="shared",
                issuer_url="https://shared.example.com",
                client_id="client-shared",
                tenant_id=None,
            )


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
    """Tenancy ON + (user, A) and (user, B) provider rows + the ROOT tenant."""
    from app.db.models.tenant import Tenant

    await _set_tenancy(db, True)
    db.add(Tenant(id=ROOT_TENANT, name="Root", slug="root", is_system_tenant=True))
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

    async def test_update_without_tenant_context_resolves_nothing(
        self, api, db, seeded_two_tenants
    ):
        """Platform-context-shaped request on /system/*: the middleware A3
        pins keep writes fail-closed 403 (resolution rejects before the
        handler).  Here the test middleware admits the request (super admin)
        — with NO resolved tenant context the handler resolves NOTHING (the
        shared NULL-tenant slot is retired), so the update fails 400."""
        db.add(_provider_row("user", None, "https://shared.example.com"))
        await db.commit()
        resp = await api.put(
            f"{USER_PATH}/user",
            json={"issuer_url": "https://shared-v2.example.com"},
        )
        assert resp.status_code == 400, resp.text
        # The legacy NULL-tenant row is untouched and still inert.
        shared = (
            await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.tenant_id.is_(None),
                    IdentityProviderConfig.provider_scope == "user",
                )
            )
        ).scalar_one()
        assert shared.issuer_url == "https://shared.example.com"


class TestPlatformSurface:
    """The ROOT tenant's provider configs are managed from /platform/*
    (platform admins manage root = their own tenant).  The shared
    NULL-tenant slot is never addressed."""

    async def test_t4_platform_create_targets_root_slot(self, api, db, seeded_two_tenants):
        resp = await api.post(
            PLATFORM_PATH,
            json={
                "provider_scope": "agent",
                "provider_type": "keycloak",
                "display_name": "root-agent",
                "issuer_url": "https://root-agent.example.com",
                "client_id": "client-root-agent",
            },
        )
        assert resp.status_code == 201, resp.text
        root = (
            await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.tenant_id == ROOT_TENANT,
                    IdentityProviderConfig.provider_scope == "agent",
                )
            )
        ).scalar_one()
        assert root.issuer_url == "https://root-agent.example.com"

    async def test_t4_platform_update_toggles_root_slot(self, api, db, seeded_two_tenants):
        db.add(_provider_row("user", ROOT_TENANT, "https://root.example.com"))
        await db.commit()
        resp = await api.put(
            f"{PLATFORM_PATH}/user",
            json={"display_name": "root-v2"},
        )
        assert resp.status_code == 200, resp.text
        root = (
            await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.tenant_id == ROOT_TENANT,
                    IdentityProviderConfig.provider_scope == "user",
                )
            )
        ).scalar_one()
        assert root.display_name == "root-v2"
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

    async def test_platform_delete_removes_root_slot_only(self, api, db, seeded_two_tenants):
        db.add(_provider_row("user", ROOT_TENANT, "https://root.example.com"))
        await db.commit()
        resp = await api.delete(f"{PLATFORM_PATH}/user")
        assert resp.status_code == 204, resp.text
        remaining = (
            await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.tenant_id == ROOT_TENANT
                )
            )
        ).scalars().all()
        assert remaining == []
        # Other tenants' rows untouched.
        others = (
            await db.execute(
                select(IdentityProviderConfig).where(
                    IdentityProviderConfig.tenant_id.in_([TENANT_A, TENANT_B])
                )
            )
        ).scalars().all()
        assert len(others) == 2

    async def test_platform_list_returns_root_only(self, api, db, seeded_two_tenants):
        db.add(_provider_row("user", ROOT_TENANT, "https://root.example.com"))
        await db.commit()
        resp = await api.get(PLATFORM_PATH)
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        assert [i["display_name"] for i in items] == ["user-cccccccc-cccc-cccc-cccc-cccccccccccc"]


class TestPublicListPrivacy:
    """T5: the public listing never leaks other tenants' metadata — and
    with no resolved tenant context it returns NOTHING."""

    async def test_no_tenant_context_returns_empty(self, api, db, seeded_two_tenants):
        db.add(_provider_row("user", None, "https://shared.example.com"))
        await db.commit()
        resp = await api.get(USER_PATH)
        assert resp.status_code == 200
        assert resp.json()["items"] == []  # no tenant resolved = no providers

    async def test_tenant_context_returns_own_only(self, api, db, seeded_two_tenants):
        db.add(_provider_row("user", None, "https://shared.example.com"))
        await db.commit()
        resp = await api.get(USER_PATH, headers=_hdrs(CTX_A))
        assert resp.status_code == 200
        names = {i["display_name"] for i in resp.json()["items"]}
        assert names == {f"user-{TENANT_A}"}  # own only — no shared, no B

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


# ── Test connection: client validation & test-login hardening ───────────────


class TestConnectionClientValidation:
    """test_connection validates the client after discovery and reports
    the outcome in ``client_id_status``; test-login rejects an empty
    client_id and never echoes stored secrets via the status poll."""

    async def test_missing_client_id_is_warning_not_failure(self):
        import app.services.oidc_config_service as svc_module

        discovery = {
            "issuer": "https://idp.example.com",
            "authorization_endpoint": "https://idp.example.com/auth",
        }

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                raise AssertionError("no authorization probe expected without client_id")

        with patch.object(
            svc_module, "_fetch_discovery", AsyncMock(return_value=discovery)
        ), patch.object(svc_module.httpx, "AsyncClient", _Client):
            result = await svc_module.OIDCConfigService().test_connection(
                issuer_url="https://idp.example.com", client_id=""
            )
        assert result["success"] is True  # warning, not failure
        status = result["client_id_status"]
        assert status["status"] == "missing"
        assert status["client_id"] is None
        step = next(s for s in result["steps"] if s["step"] == "client_validation")
        assert step["status"] == "warning"

    async def test_definitive_invalid_client_fails(self):
        import app.services.oidc_config_service as svc_module

        discovery = {
            "issuer": "https://idp.example.com",
            "authorization_endpoint": "https://idp.example.com/auth",
        }
        html = "<html><body><div class='error'>Client not found.</div></body></html>"

        class _Resp:
            status_code = 400
            text = html

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                assert "client_id=ghost-client" in url
                assert "response_type=code" in url
                return _Resp()

        with patch.object(
            svc_module, "_fetch_discovery", AsyncMock(return_value=discovery)
        ), patch.object(svc_module.httpx, "AsyncClient", _Client):
            result = await svc_module.OIDCConfigService().test_connection(
                issuer_url="https://idp.example.com", client_id="ghost-client"
            )
        assert result["success"] is False
        assert result["client_id_status"]["status"] == "invalid"
        step = next(s for s in result["steps"] if s["step"] == "client_validation")
        assert step["status"] == "failed"

    async def test_ambiguous_client_response_passes_ok(self):
        """IdPs commonly render their login page for ANY client_id — only
        a definitive invalid-client error may fail the probe."""
        import app.services.oidc_config_service as svc_module

        discovery = {
            "issuer": "https://idp.example.com",
            "authorization_endpoint": "https://idp.example.com/auth",
        }

        class _Resp:
            status_code = 200
            text = "<html><body>Sign in</body></html>"

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                return _Resp()

        with patch.object(
            svc_module, "_fetch_discovery", AsyncMock(return_value=discovery)
        ), patch.object(svc_module.httpx, "AsyncClient", _Client):
            result = await svc_module.OIDCConfigService().test_connection(
                issuer_url="https://idp.example.com", client_id="parthenon-api"
            )
        assert result["success"] is True
        assert result["client_id_status"]["status"] == "ok"
        assert result["client_id_status"]["client_id"] == "parthenon-api"

    async def test_update_with_empty_client_id_rejected(self, api, db, seeded_two_tenants):
        """The legacy empty-client_id rows (pre-validation) can no longer
        be (re)written without a client_id."""
        resp = await api.put(
            f"{USER_PATH}/user",
            json={"client_id": "  "},
            headers=_hdrs(CTX_A),
        )
        assert resp.status_code == 400
        assert "client_id" in resp.json()["detail"]

    async def _login_session(self, api):
        from app.api.v1.system_config import _test_sessions
        import app.services.oidc_config_service as svc_module

        discovery = {
            "issuer": "https://idp.example.com",
            "authorization_endpoint": "https://idp.example.com/auth",
        }

        class _Resp:
            status_code = 200
            text = "<html><body>Sign in</body></html>"

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                return _Resp()

        with patch.object(
            svc_module, "_fetch_discovery", AsyncMock(return_value=discovery)
        ), patch.object(svc_module.httpx, "AsyncClient", _Client):
            resp = await api.post(
                f"{USER_PATH}/test-login",
                json={
                    "issuer_url": "https://idp.example.com",
                    "client_id": "client-agent",
                    "client_secret": "s3cret-value",
                },
                headers=_hdrs(CTX_A),
            )
        assert resp.status_code == 200, resp.text
        test_id = resp.json()["test_id"]
        return _test_sessions, test_id

    async def test_test_login_requires_client_id(self, api, seeded_two_tenants):
        import app.services.oidc_config_service as svc_module

        discovery = {"issuer": "https://idp.example.com"}
        with patch.object(
            svc_module, "_fetch_discovery", AsyncMock(return_value=discovery)
        ):
            resp = await api.post(
                f"{USER_PATH}/test-login",
                json={"issuer_url": "https://idp.example.com", "client_id": ""},
                headers=_hdrs(CTX_A),
            )
        assert resp.status_code == 400
        assert "client_id" in resp.json()["detail"]

    async def test_test_login_status_never_leaks_secret(self, api, seeded_two_tenants):
        import app.services.oidc_config_service as svc_module

        discovery = {
            "issuer": "https://idp.example.com",
            "authorization_endpoint": "https://idp.example.com/auth",
        }
        with patch.object(
            svc_module, "_fetch_discovery", AsyncMock(return_value=discovery)
        ):
            _sessions, test_id = await self._login_session(api)

        resp = await api.get(
            f"{USER_PATH}/test-login/status/{test_id}", headers=_hdrs(CTX_A)
        )
        assert resp.status_code == 200
        body = resp.text
        assert "s3cret-value" not in body
        assert resp.json()["status"] == "initiated"

    async def test_test_login_status_expires_abandoned_session(
        self, api, seeded_two_tenants
    ):
        import app.api.v1.system_config as sc_module
        import app.services.oidc_config_service as svc_module

        discovery = {
            "issuer": "https://idp.example.com",
            "authorization_endpoint": "https://idp.example.com/auth",
        }
        with patch.object(
            svc_module, "_fetch_discovery", AsyncMock(return_value=discovery)
        ):
            _sessions, test_id = await self._login_session(api)

        # Age the session past the TTL → status poll must terminate it.
        sc_module._test_sessions[test_id]["created_ts"] = (
            time.monotonic() - sc_module._TEST_SESSION_TTL_SECONDS - 1
        )
        resp = await api.get(
            f"{USER_PATH}/test-login/status/{test_id}", headers=_hdrs(CTX_A)
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert "expired" in resp.json()["error"]
