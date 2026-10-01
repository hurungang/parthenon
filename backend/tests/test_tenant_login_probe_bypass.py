"""Login-page bootstrap probe bypass — reproduction tests for FIX-20260929-121120 (Defect A).

The login page calls two PUBLIC endpoints BEFORE any authentication or
tenant context exists (backend/app/api/v1/system_config.py):

- ``GET /api/v1/system/identity-providers`` (``list_identity_providers`` —
  docstring: "Public endpoint — accessible before OIDC auth so the login
  page can discover available providers")
- ``GET /api/v1/system/super-admin/status`` (``get_super_admin_status`` —
  env-based, no database involved)

``TenantResolutionMiddleware.BYPASS_PATHS``
(backend/app/middleware/tenant_resolution.py) does not list them, so in
multi-tenant mode the login page's own bootstrap probes are rejected 403
"Tenant could not be resolved" (unresolvable, slug=None) by this
middleware BEFORE ``JWTAuthMiddleware`` — which would let the public
endpoints through — ever sees the request.

Desired end state pinned here:

- READ probes (``GET``) must pass tenant resolution WITHOUT a tenant
  context and reach the route (200 — the routes are public pre-auth).
- WRITES (``POST`` / ``PUT`` / ``DELETE``) to
  ``/api/v1/system/identity-providers`` are tenant-scoped and must STILL
  be rejected fail-closed by tenant resolution when no tenant context can
  be resolved.  The bypass must therefore be METHOD-AWARE (GET only) —
  never a blanket path bypass.

Pre-fix status: A1 + A2 FAIL (403 from resolution); the write pins pass
today and MUST keep passing after the method-aware fix lands.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.tenant_context import get_tenant_context  # noqa: E402
from app.db.models.tenant import Tenant, TenantStatus  # noqa: E402
from app.db.session import Base  # noqa: E402
from app.services.tenancy.tenant_resolution_service import (  # noqa: E402
    get_tenant_resolution_service,
)

PROBE_LIST_PATH = "/api/v1/system/identity-providers"
PROBE_STATUS_PATH = "/api/v1/system/super-admin/status"


# ── Fixtures (mirrors test_tenant_resolution.py) ─────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def probe_engine():
    """Dedicated in-memory engine for this module (mirrors conftest pattern)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_caches():
    """Isolate module-level singletons between tests."""
    get_tenant_resolution_service()._cache.clear()
    yield
    get_tenant_resolution_service()._cache.clear()


class _Switch:
    """Controllable tenancy-switch stub handed to the middleware."""

    def __init__(self):
        self.enabled = False

    async def is_multi_tenancy_enabled(self, db):  # noqa: ARG002
        return self.enabled


@pytest.fixture
def switch():
    return _Switch()


@pytest_asyncio.fixture
async def mw_client(probe_engine, switch):
    """AsyncClient against an app carrying ONLY the tenant middleware (plus
    minimal stand-in routes for the two public probe endpoints and the
    tenant-scoped identity-provider writes), with the middleware's DB
    sessionmaker and switch patched in."""
    from app.middleware.tenant_resolution import TenantResolutionMiddleware

    SessionLocal = async_sessionmaker(
        bind=probe_engine, class_=AsyncSession, expire_on_commit=False
    )

    app = FastAPI()

    @app.get(PROBE_LIST_PATH)
    async def probe_list_identity_providers(request: Request):
        ctx = get_tenant_context(request)
        return {"reached": True, "tenant": ctx.slug if ctx.is_set else None}

    @app.post(PROBE_LIST_PATH, status_code=201)
    async def probe_create_identity_provider(request: Request):  # noqa: ARG001
        return {"reached": True}

    @app.put(PROBE_LIST_PATH + "/{scope}")
    async def probe_update_identity_provider(scope: str, request: Request):  # noqa: ARG001
        return {"reached": True, "scope": scope}

    @app.delete(PROBE_LIST_PATH + "/{scope}", status_code=204)
    async def probe_delete_identity_provider(scope: str, request: Request):  # noqa: ARG001
        return None

    @app.get(PROBE_STATUS_PATH)
    async def probe_super_admin_status(request: Request):  # noqa: ARG001
        return {"reached": True, "is_enabled": False}

    app.add_middleware(TenantResolutionMiddleware)

    import app.db.session as db_session_module
    import app.services.tenancy.platform_settings_service as settings_module

    with patch.object(db_session_module, "AsyncSessionLocal", SessionLocal), patch.object(
        settings_module, "get_platform_settings_service", lambda: switch
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


@pytest_asyncio.fixture
async def seeded(probe_engine):
    """One active tenant (guarded so the module-scoped engine seeds once)."""
    SessionLocal = async_sessionmaker(
        bind=probe_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as db:
        count = len((await db.execute(select(Tenant))).scalars().all())
        if count == 0:
            db.add(Tenant(name="Acme", slug="acme", status=TenantStatus.active))
            await db.commit()


# ── A1/A2 — public READ probes must be reachable without tenant context ──────


class TestLoginProbeReachability:
    """Multi-tenancy ON, NO tenant context: the login page's public
    bootstrap probes must pass tenant resolution and reach the route —
    NOT the resolution 403 'unresolvable slug=None'.

    BOTH TESTS FAIL TODAY (403 "Tenant could not be resolved" before the
    auth middleware, which treats the endpoints as public, ever runs).
    """

    async def test_get_identity_providers_reaches_route_without_tenant_context(
        self, mw_client, switch, seeded
    ):
        """A1: GET /api/v1/system/identity-providers — public pre-auth probe."""
        switch.enabled = True
        response = await mw_client.get(PROBE_LIST_PATH)
        assert response.status_code == 200, (
            "LOGIN PROBE BYPASS GAP (FIX-20260929-121120 / A1): the public "
            f"login-page probe GET {PROBE_LIST_PATH} was rejected with "
            f"{response.status_code} ({response.text}) in multi-tenant mode "
            "with no tenant context. It must reach the route (public pre-auth "
            "endpoint) — add it to TenantResolutionMiddleware's bypass as a "
            "METHOD-AWARE GET-only bypass, never a blanket path bypass."
        )
        assert response.json()["reached"] is True

    async def test_get_super_admin_status_reaches_route_without_tenant_context(
        self, mw_client, switch, seeded
    ):
        """A2: GET /api/v1/system/super-admin/status — env-based public probe."""
        switch.enabled = True
        response = await mw_client.get(PROBE_STATUS_PATH)
        assert response.status_code == 200, (
            "LOGIN PROBE BYPASS GAP (FIX-20260929-121120 / A2): the public "
            f"login-page probe GET {PROBE_STATUS_PATH} was rejected with "
            f"{response.status_code} ({response.text}) in multi-tenant mode "
            "with no tenant context. It must reach the route (public pre-auth, "
            "env-based endpoint) — add it to TenantResolutionMiddleware's "
            "bypass as a METHOD-AWARE GET-only bypass."
        )
        assert response.json()["reached"] is True


# ── A3 — SECURITY PIN: tenant-scoped WRITES stay fail-closed ─────────────────


class TestLoginProbeWritesStayFailClosed:
    """Multi-tenancy ON, NO tenant context: identity-provider WRITES are
    tenant-scoped and must STILL be rejected by tenant resolution.

    These tests PASS TODAY and MUST KEEP PASSING after the method-aware
    bypass fix — they prevent the fix from degenerating into a blanket
    path bypass that would let unauthenticated, tenant-less writers
    mutate identity provider configuration.
    """

    async def test_post_identity_providers_rejected_without_tenant_context(
        self, mw_client, switch, seeded
    ):
        switch.enabled = True
        response = await mw_client.post(PROBE_LIST_PATH, json={})
        assert response.status_code == 403, (
            "SECURITY REGRESSION (FIX-20260929-121120 / A3): POST "
            f"{PROBE_LIST_PATH} without a tenant context must stay rejected "
            "fail-closed by tenant resolution — the probe bypass must be "
            "method-aware (GET only)."
        )
        assert "resolved" in response.json()["detail"].lower()
        # The route must never execute (rejected BEFORE feature logic).
        assert response.json().get("reached") is None

    async def test_put_identity_providers_rejected_without_tenant_context(
        self, mw_client, switch, seeded
    ):
        switch.enabled = True
        response = await mw_client.put(PROBE_LIST_PATH + "/user", json={})
        assert response.status_code == 403, (
            "SECURITY REGRESSION (FIX-20260929-121120 / A3): PUT "
            f"{PROBE_LIST_PATH}/{{scope}} without a tenant context must stay "
            "rejected fail-closed by tenant resolution — the probe bypass "
            "must be method-aware (GET only)."
        )
        assert "resolved" in response.json()["detail"].lower()
        assert response.json().get("reached") is None

    async def test_delete_identity_providers_rejected_without_tenant_context(
        self, mw_client, switch, seeded
    ):
        switch.enabled = True
        response = await mw_client.delete(PROBE_LIST_PATH + "/user")
        assert response.status_code == 403, (
            "SECURITY REGRESSION (FIX-20260929-121120 / A3): DELETE "
            f"{PROBE_LIST_PATH}/{{scope}} without a tenant context must stay "
            "rejected fail-closed by tenant resolution — the probe bypass "
            "must be method-aware (GET only)."
        )
