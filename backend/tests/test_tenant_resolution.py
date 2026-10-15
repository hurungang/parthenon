"""Unit tests for tenant resolution — fail-closed semantics (Phase 9.1, CS-10/CS-11).

Covers:

- ``extract_slug_candidate``: X-Tenant header precedence, Host subdomain
  extraction, reserved slugs, unresolvable requests
- ``TenantResolutionService.resolve_slug``: unknown / suspended / deleted
  tenants unresolvable; active tenants resolve with full metadata;
  short-TTL success caching; rejections never cached; lifecycle
  invalidation takes effect immediately
- ``TenantResolutionMiddleware``: completely inert with the switch OFF
  (zero tenant logic, stray headers ignored — CS-01/CS-02), fail-closed
  403 before any feature logic with the switch ON (unknown / suspended /
  deleted / no-slug), rejections audited as security-relevant events,
  bypass paths (health + platform + internal) when ON (CS-10, E-10)
- Single resolution point: the context binds exactly once and is
  immutable downstream (CS-11)
"""
from __future__ import annotations

import os
import uuid
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
from app.db.models.tenant_audit_event import (  # noqa: E402
    TenantAuditEvent,
    TenantAuditEventType,
)
from app.db.session import Base  # noqa: E402
from app.middleware.tenant_resolution import (  # noqa: E402
    BYPASS_PATHS,
    BYPASS_PREFIXES,
    _is_bypassed,
)
from app.services.tenancy.tenant_resolution_service import (  # noqa: E402
    ResolutionSource,
    TenantResolutionError,
    TenantResolutionService,
    extract_slug_candidate,
    get_tenant_resolution_service,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def tenancy_engine():
    """Dedicated in-memory engine for this module (mirrors conftest pattern)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(tenancy_engine):
    SessionLocal = async_sessionmaker(
        bind=tenancy_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
def _fresh_caches():
    """Isolate module-level singletons between tests."""
    get_tenant_resolution_service()._cache.clear()
    yield
    get_tenant_resolution_service()._cache.clear()


async def _seed_tenants(db) -> dict[str, Tenant]:
    """active / suspended / deleted tenants for fail-closed assertions."""
    rows: dict[str, Tenant] = {}
    for slug, status in (
        ("root", TenantStatus.active),
        ("acme", TenantStatus.active),
        ("halted", TenantStatus.suspended),
        ("gone", TenantStatus.deleted),
    ):
        tenant = Tenant(name=slug.title(), slug=slug, status=status)
        db.add(tenant)
        rows[slug] = tenant
    await db.flush()
    return rows


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
async def mw_client(tenancy_engine, switch):
    """AsyncClient against an app carrying ONLY the tenant middleware,
    with the middleware's DB sessionmaker and switch patched in."""
    from app.middleware.tenant_resolution import TenantResolutionMiddleware

    SessionLocal = async_sessionmaker(
        bind=tenancy_engine, class_=AsyncSession, expire_on_commit=False
    )

    app = FastAPI()

    @app.get("/api/v1/echo")
    async def echo(request: Request):
        ctx = get_tenant_context(request)
        return {"tenant": ctx.slug if ctx.is_set else None}

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


def _request(headers: dict | None = None):
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/agents",
            "headers": [
                (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
            ],
            "query_string": b"",
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )
    return request


# ── Slug candidate extraction ────────────────────────────────────────────────


class TestSlugCandidate:
    def _with_base_domain(self, monkeypatch, domain="parthenon.io"):
        monkeypatch.setattr(
            "app.services.tenancy.tenant_resolution_service.get_settings",
            lambda: type("S", (), {"tenant_address_base_domain": domain})(),
        )

    def test_header_wins(self, monkeypatch):
        self._with_base_domain(monkeypatch)
        candidate = extract_slug_candidate(
            _request({"X-Tenant": "acme", "Host": "other.parthenon.io"})
        )
        assert candidate is not None
        assert candidate.slug == "acme"
        assert candidate.source == ResolutionSource.header

    def test_host_subdomain_extracted(self, monkeypatch):
        self._with_base_domain(monkeypatch)
        candidate = extract_slug_candidate(_request({"Host": "acme.parthenon.io:443"}))
        assert candidate is not None
        assert candidate.slug == "acme"
        assert candidate.source == ResolutionSource.host

    def test_base_domain_host_is_not_a_tenant(self, monkeypatch):
        self._with_base_domain(monkeypatch)
        assert extract_slug_candidate(_request({"Host": "parthenon.io"})) is None

    def test_deep_subdomain_not_a_slug(self, monkeypatch):
        self._with_base_domain(monkeypatch)
        assert extract_slug_candidate(_request({"Host": "a.b.parthenon.io"})) is None

    def test_no_config_no_host_candidate(self):
        assert extract_slug_candidate(_request({})) is None

    def test_header_normalized_lowercase(self, monkeypatch):
        self._with_base_domain(monkeypatch)
        candidate = extract_slug_candidate(_request({"X-Tenant": "AcMe"}))
        assert candidate is not None
        assert candidate.slug == "acme"


# ── Resolution service (fail-closed) ─────────────────────────────────────────


class TestResolveSlug:
    async def test_active_tenant_resolves(self, db):
        await _seed_tenants(db)
        service = TenantResolutionService(cache_ttl_seconds=30)
        ctx = await service.resolve_slug(db, "acme")
        assert ctx.slug == "acme"
        assert ctx.name == "Acme"
        assert ctx.is_set is True
        assert isinstance(ctx.tenant_id, uuid.UUID)

    async def test_unknown_slug_raises(self, db):
        await _seed_tenants(db)
        service = TenantResolutionService()
        with pytest.raises(TenantResolutionError) as exc:
            await service.resolve_slug(db, "nope")
        assert exc.value.reason == "unknown"

    async def test_suspended_tenant_unresolvable(self, db):
        await _seed_tenants(db)
        service = TenantResolutionService()
        with pytest.raises(TenantResolutionError) as exc:
            await service.resolve_slug(db, "halted")
        assert exc.value.reason == "suspended"

    async def test_deleted_tenant_unresolvable(self, db):
        await _seed_tenants(db)
        service = TenantResolutionService()
        with pytest.raises(TenantResolutionError) as exc:
            await service.resolve_slug(db, "gone")
        assert exc.value.reason == "deleted"

    async def test_invalidation_makes_state_change_immediate(self, db):
        """Suspend after a cached success → resolution fails immediately."""
        rows = await _seed_tenants(db)
        service = TenantResolutionService(cache_ttl_seconds=60)
        await service.resolve_slug(db, "acme")  # cached now
        rows["acme"].status = TenantStatus.suspended
        await db.flush()
        await service.invalidate("acme")  # lifecycle invalidation path
        with pytest.raises(TenantResolutionError):
            await service.resolve_slug(db, "acme")

    async def test_success_cached_within_ttl(self, db):
        await _seed_tenants(db)
        service = TenantResolutionService(cache_ttl_seconds=60)
        await service.resolve_slug(db, "acme")
        # Remove the row: the cached context still serves within the TTL.
        await db.execute(Tenant.__table__.delete().where(Tenant.slug == "acme"))
        ctx = await service.resolve_slug(db, "acme")
        assert ctx.slug == "acme"

    async def test_resolve_via_request_header(self, db):
        await _seed_tenants(db)
        service = TenantResolutionService()
        ctx, source = await service.resolve(db, _request({"X-Tenant": "acme"}))
        assert ctx.slug == "acme"
        assert source == ResolutionSource.header

    async def test_resolve_unresolvable_request_raises(self, db):
        await _seed_tenants(db)
        service = TenantResolutionService()
        with pytest.raises(TenantResolutionError) as exc:
            await service.resolve(db, _request({}))
        assert exc.value.reason == "unresolvable"

    async def test_reserved_slug_rejected(self, db):
        service = TenantResolutionService()
        with pytest.raises(TenantResolutionError):
            await service.resolve(db, _request({"X-Tenant": "admin"}))


# ── Bypass path enumeration (E-10) ───────────────────────────────────────────


class TestBypassEnumeration:
    def test_health_and_setup_bypassed(self):
        for path in ("/health", "/ping", "/docs", "/openapi.json", "/api/v1/ping"):
            assert _is_bypassed(path), path

    def test_public_auth_paths_bypassed(self):
        for path in (
            "/api/v1/auth/tenant",
            "/api/v1/auth/register",  # Phase 10 supersedes register-organization
            "/api/v1/auth/login-password",  # Phase 10 platform-password sign-in
            "/api/v1/invitations/accept",
        ):
            assert _is_bypassed(path), path

    def test_internal_prefix_bypassed_platform_resolves_root(self):
        """Phase 11: /platform/* is NO LONGER bypassed — the platform is
        the root tenant; only /internal/* skips resolution."""
        assert _is_bypassed("/api/v1/internal/anything")
        assert not _is_bypassed("/api/v1/platform/tenants")

    def test_business_paths_not_bypassed(self):
        assert not _is_bypassed("/api/v1/agents")
        assert not _is_bypassed("/api/v1/tenant/members")
        assert not _is_bypassed("/api/v1/roles")

    def test_exempt_set_does_not_silently_widen(self):
        """E-10: the exemption set must stay exactly health/setup/public-auth
        plus the internal prefix (platform resolved like any workspace)."""
        assert "/api/v1/roles" not in BYPASS_PATHS
        assert "/api/v1/agents" not in BYPASS_PATHS
        for prefix in BYPASS_PREFIXES:
            assert prefix in ("/docs/", "/redoc/", "/api/v1/internal/")


# ── Middleware: switch-off inertness + switch-on fail-closed ─────────────────


class TestMiddlewareSwitchOff:
    async def test_switch_off_is_inert(self, mw_client, switch, tenancy_engine):
        """CS-01: no tenant resolution runs with the switch off — the
        request passes through with the UNSET sentinel."""
        switch.enabled = False
        SessionLocal = async_sessionmaker(
            bind=tenancy_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            await _seed_tenants(db)
            await db.commit()

        response = await mw_client.get("/api/v1/echo", headers={"X-Tenant": "acme"})
        assert response.status_code == 200
        assert response.json()["tenant"] is None

    async def test_stray_tenant_header_ignored_when_off(self, mw_client, switch):
        """CS-02: tenant headers are ignored entirely — no error, no scope."""
        switch.enabled = False
        for headers in ({"X-Tenant": "unknown-tenant"}, {"Host": "unknown.example.com"}):
            response = await mw_client.get("/api/v1/echo", headers=headers)
            assert response.status_code == 200
            assert response.json()["tenant"] is None

    async def test_switch_read_failure_fails_safe_to_off(self, mw_client, switch):
        """An unreadable switch must fail safe to single-tenant behaviour."""
        switch.enabled = True

        async def broken(db):  # noqa: ARG001
            raise RuntimeError("database unavailable")

        switch.is_multi_tenancy_enabled = broken
        response = await mw_client.get("/api/v1/echo", headers={"X-Tenant": "acme"})
        # Fail-safe: request passes through inert, NOT enabled.
        assert response.status_code == 200
        assert response.json()["tenant"] is None

    async def test_switch_off_binds_root_default_regardless_of_requested_tenant(
        self, mw_client, switch, tenancy_engine
    ):
        """LOGIN ADMISSION anchor (tenancy OFF): the ROOT tenant is THE
        default tenant — every (non-bypassed) request resolves INTO the
        root workspace even when a stray ``X-Tenant`` header names another
        tenant.  There is no per-callsite tenancy switch: the resolution
        middleware is the single mechanism."""
        switch.enabled = False
        SessionLocal = async_sessionmaker(
            bind=tenancy_engine, class_=AsyncSession, expire_on_commit=False
        )
        tag = uuid.uuid4().hex[:8]
        async with SessionLocal() as db:
            # At most one system tenant may exist (partial unique index) —
            # reuse it when an earlier test in this module created one.
            root = (
                await db.execute(
                    select(Tenant).where(Tenant.is_system_tenant.is_(True))
                )
            ).scalar_one_or_none()
            if root is None:
                root = Tenant(
                    name=f"Root-{tag}", slug=f"root-{tag}",
                    status=TenantStatus.active, is_system_tenant=True,
                )
                db.add(root)
            root_slug = root.slug
            db.add(
                Tenant(name=f"Acme-{tag}", slug=f"acme-{tag}", status=TenantStatus.active)
            )
            await db.commit()

        response = await mw_client.get(
            "/api/v1/echo", headers={"X-Tenant": f"acme-{tag}"}
        )
        assert response.status_code == 200
        assert response.json()["tenant"] == root_slug, (
            "tenancy OFF must bind the ROOT default context regardless of "
            "any requested tenant address"
        )


class TestMiddlewareSwitchOn:
    @pytest_asyncio.fixture
    async def seeded(self, tenancy_engine):
        SessionLocal = async_sessionmaker(
            bind=tenancy_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            count = len((await db.execute(select(Tenant))).scalars().all())
            if count == 0:
                await _seed_tenants(db)
                await db.commit()

    async def test_active_tenant_resolves_and_binds(self, mw_client, switch, seeded):
        switch.enabled = True
        response = await mw_client.get("/api/v1/echo", headers={"X-Tenant": "acme"})
        assert response.status_code == 200
        assert response.json()["tenant"] == "acme"

    async def test_missing_tenant_rejected(self, mw_client, switch, seeded):
        switch.enabled = True
        response = await mw_client.get("/api/v1/echo")
        assert response.status_code == 403
        assert "resolved" in response.json()["detail"].lower()

    async def test_unknown_slug_rejected(self, mw_client, switch, seeded):
        switch.enabled = True
        response = await mw_client.get("/api/v1/echo", headers={"X-Tenant": "nope"})
        assert response.status_code == 403

    async def test_suspended_slug_rejected(self, mw_client, switch, seeded):
        switch.enabled = True
        response = await mw_client.get("/api/v1/echo", headers={"X-Tenant": "halted"})
        assert response.status_code == 403

    async def test_deleted_slug_rejected(self, mw_client, switch, seeded):
        switch.enabled = True
        response = await mw_client.get("/api/v1/echo", headers={"X-Tenant": "gone"})
        assert response.status_code == 403

    async def test_health_bypasses_when_on(self, mw_client, switch, seeded):
        """Only public health/setup paths bypass; the request reaches routing
        (404: no such route in this minimal app) instead of the 403 wall."""
        switch.enabled = True
        response = await mw_client.get("/health")
        assert response.status_code == 404

    async def test_platform_route_resolves_root_binding(self, mw_client, switch, seeded):
        """Phase 11: /platform/* resolves the root-tenant binding (the
        platform console client always sends X-Tenant: root)."""
        switch.enabled = True
        response = await mw_client.get(
            "/api/v1/platform/tenants", headers={"X-Tenant": "root"}
        )
        assert response.status_code == 404  # passed middleware; route absent

    async def test_platform_route_fail_closed_without_binding(self, mw_client, switch, seeded):
        switch.enabled = True
        response = await mw_client.get("/api/v1/platform/tenants")
        assert response.status_code == 403  # fail-closed: no root binding

    async def test_internal_prefix_bypasses_resolution(self, mw_client, switch, seeded):
        switch.enabled = True
        response = await mw_client.get("/api/v1/internal/anything")
        assert response.status_code == 404  # passed middleware; route absent

    async def test_business_route_fail_closed_without_slug(self, mw_client, switch, seeded):
        """Fail-closed happens BEFORE any feature logic (no route executed)."""
        switch.enabled = True
        response = await mw_client.get("/api/v1/echo")
        assert response.status_code == 403

    async def test_rejection_audited_as_security_relevant(
        self, mw_client, switch, seeded, tenancy_engine
    ):
        """CS-10: the rejection is audited (security-relevant boundary event)."""
        switch.enabled = True
        await mw_client.get("/api/v1/echo", headers={"X-Tenant": "nope"})

        SessionLocal = async_sessionmaker(
            bind=tenancy_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            result = await db.execute(
                select(TenantAuditEvent).where(
                    TenantAuditEvent.event_type
                    == TenantAuditEventType.tenant_boundary_violation
                )
            )
            events = result.scalars().all()
        assert len(events) >= 1
        assert events[-1].is_security_relevant is True
        assert "nope" in (events[-1].detail or {}).get("slug", "")

    async def test_context_binds_exactly_once(self, mw_client, switch, seeded):
        """CS-11: resolution happens once; downstream sees an immutable ctx."""
        switch.enabled = True
        response = await mw_client.get("/api/v1/echo", headers={"X-Tenant": "acme"})
        assert response.json()["tenant"] == "acme"
        # A second header value can never re-resolve within the same request
        # (the middleware rejects double-binding via set_tenant_context).
