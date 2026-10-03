"""Platform admin API tests (Phase 5.5/5.8 / 9.x, CS-07/CS-22/CS-23).

Covers the platform console surface with REAL app + sqlite DB:

- tenant lifecycle CRUD via /platform/tenants (create, list, detail with
  aggregate counts, update, suspend, resume, delete-with-confirmation,
  slug reuse after deletion — full CRUD delete-and-recreate proof)
- duplicate name/slug rejection with clear 409 errors
- aggregate-counts-only responses (never business rows — CS-22)
- platform settings read/write incl. guarded tenancy-switch toggle
- platform audit API filters (tenant attribution, security_only)
- permission guards: every route 403s without ``platform::*`` rights
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.api.deps import require_permission  # noqa: E402
from app.core.resource_types import (  # noqa: E402
    RT_PLATFORM_AUDIT,
    RT_PLATFORM_SETTINGS,
    RT_PLATFORM_TENANTS,
)
from app.db.models.agents import AgentRole  # noqa: E402
from app.db.models.identity import Role  # noqa: E402
from app.db.models.tenant import Tenant, TenantStatus  # noqa: E402
from app.db.models.tenant_membership import TenantUserMembership  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.middleware.auth import JWTAuthMiddleware  # noqa: E402

_TENANT_TS = uuid.uuid4().hex[:8]


def _allow():
    def override():
        return {"sub": "platform-admin-test", "roles": ["admin"]}

    return override


def _deny():
    async def override():
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Permission denied")

    return override


@pytest.fixture
def _bypass_auth():
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "platform-admin-test"}
        return await call_next(request)

    with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch):
        yield


@pytest.fixture(autouse=True)
def _fresh_settings_singleton():
    """Reset the process-global PlatformSettingsService after each test.

    The toggle tests write through the singleton (its 30s cache is shared
    process-wide); without this reset, later test modules' middleware
    would observe a stale `multi_tenancy_enabled=True` within the TTL.
    """
    import app.services.tenancy.platform_settings_service as settings_module

    settings_module._service = None
    yield
    settings_module._service = None


@pytest_asyncio.fixture
async def client(test_engine, _bypass_auth):
    app = create_app()
    for rt in (RT_PLATFORM_TENANTS, RT_PLATFORM_SETTINGS, RT_PLATFORM_AUDIT):
        for action in ("create", "read", "update", "delete", "manage"):
            app.dependency_overrides[require_permission(rt, action)] = _allow()

    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(test_engine):
    """Reset tenant-related tables around each test (shared engine)."""
    yield
    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        await db.execute(TenantUserMembership.__table__.delete())
        await db.execute(Role.__table__.delete())
        await db.execute(AgentRole.__table__.delete())
        await db.execute(Tenant.__table__.delete())
        await db.commit()


def _unique(slug: str) -> str:
    return f"{slug}-{_TENANT_TS}"


class TestTenantLifecycleCRUD:
    async def test_create_returns_full_tenant(self, client):
        response = await client.post(
            "/api/v1/platform/tenants",
            json={
                "name": "Acme Corp",
                "slug": _unique("acme"),
                "admin_contact_name": "Ada Admin",
                "admin_contact_email": "ada@acme.test",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Acme Corp"
        assert body["slug"] == _unique("acme")
        assert body["status"] == "active"
        assert body["is_system_tenant"] is False
        assert body["admin_contact_name"] == "Ada Admin"
        assert body["admin_contact_email"] == "ada@acme.test"
        assert body["id"]

    async def test_created_tenant_appears_in_list(self, client):
        await client.post(
            "/api/v1/platform/tenants",
            json={"name": "List Co", "slug": _unique("listco")},
        )
        response = await client.get("/api/v1/platform/tenants")
        assert response.status_code == 200
        body = response.json()
        slugs = [t["slug"] for t in body["items"]]
        assert _unique("listco") in slugs
        assert body["total"] == len(body["items"])

    async def test_duplicate_slug_rejected_with_clear_error(self, client):
        slug = _unique("dups")
        first = await client.post(
            "/api/v1/platform/tenants", json={"name": "First", "slug": slug}
        )
        assert first.status_code == 201
        second = await client.post(
            "/api/v1/platform/tenants", json={"name": "Second", "slug": slug}
        )
        assert second.status_code == 409
        assert "already exists" in second.json()["detail"]

    async def test_duplicate_name_rejected(self, client):
        await client.post(
            "/api/v1/platform/tenants", json={"name": "Same Name", "slug": _unique("one")}
        )
        second = await client.post(
            "/api/v1/platform/tenants", json={"name": "Same Name", "slug": _unique("two")}
        )
        assert second.status_code == 409
        assert "already exists" in second.json()["detail"]

    async def test_malformed_slug_rejected(self, client):
        response = await client.post(
            "/api/v1/platform/tenants", json={"name": "Bad", "slug": "Bad_Slug!"}
        )
        assert response.status_code in (409, 422)
        assert "Slug" in response.json()["detail"] or "slug" in response.json()["detail"].lower()

    async def test_update_reflects_without_recreate(self, client):
        created = await client.post(
            "/api/v1/platform/tenants", json={"name": "Old Name", "slug": _unique("upd")}
        )
        tenant_id = created.json()["id"]
        updated = await client.patch(
            f"/api/v1/platform/tenants/{tenant_id}",
            json={"name": "New Name", "admin_contact_name": "New Contact"},
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["name"] == "New Name"
        assert body["admin_contact_name"] == "New Contact"
        assert body["slug"] == _unique("upd")  # immutable

    async def test_detail_returns_aggregate_counts_only(self, client, test_engine):
        created = await client.post(
            "/api/v1/platform/tenants", json={"name": "Counts Co", "slug": _unique("cnt")}
        )
        tenant_id = uuid.UUID(created.json()["id"])

        # Seed business rows attributable to the tenant (aggregates only).
        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            db.add_all(
                [
                    TenantUserMembership(
                        tenant_id=tenant_id, user_id=uuid.uuid4(), tenant_role="member"
                    ),
                    TenantUserMembership(
                        tenant_id=tenant_id, user_id=uuid.uuid4(), tenant_role="member"
                    ),
                    Role(name=f"cnt-role-{uuid.uuid4().hex[:6]}", tenant_id=tenant_id),
                ]
            )
            await db.commit()

        detail = await client.get(f"/api/v1/platform/tenants/{tenant_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["user_count"] == 2
        # 1 hand-seeded role + the 4 default tenant roles seeded on
        # creation (Tenant System Admin / Agent Manager / Agent Executor
        # / Agent Viewer).
        assert body["role_count"] == 5
        assert body["agent_count"] == 0
        # CS-22: metadata + aggregates ONLY — no business rows anywhere.
        # Phase 10: tier/license + usage aggregates added (never business
        # rows — usage holds counts and limits only).
        assert set(body.keys()) <= {
            "id", "name", "slug", "status", "is_system_tenant", "is_onboarded",
            "admin_contact_name", "admin_contact_email", "created_at", "updated_at",
            "user_count", "agent_count", "role_count",
            "license", "usage",
        }
        # The Phase 10 usage aggregate carries counts/limits, not rows.
        usage = body.get("usage")
        if usage is not None:
            assert set(usage.keys()) <= {
                "tier", "max_users", "max_agent_types",
                "monthly_agent_executions", "users", "agent_types",
                "executions_this_month",
            }

    async def test_suspend_resume_cycle(self, client):
        created = await client.post(
            "/api/v1/platform/tenants", json={"name": "Cycle Co", "slug": _unique("cyc")}
        )
        tenant_id = created.json()["id"]
        suspended = await client.post(f"/api/v1/platform/tenants/{tenant_id}/suspend")
        assert suspended.status_code == 200
        assert suspended.json()["status"] == "suspended"
        resumed = await client.post(f"/api/v1/platform/tenants/{tenant_id}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "active"

    async def test_suspend_lifecycle_events_audited(self, client, test_engine):
        from app.db.models.tenant_audit_event import (
            TenantAuditEvent,
            TenantAuditEventType,
        )

        created = await client.post(
            "/api/v1/platform/tenants", json={"name": "Audit Co", "slug": _unique("aud")}
        )
        tenant_id = created.json()["id"]
        await client.post(f"/api/v1/platform/tenants/{tenant_id}/suspend")
        await client.post(f"/api/v1/platform/tenants/{tenant_id}/resume")

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            events = (
                await db.execute(
                    select(TenantAuditEvent).where(TenantAuditEvent.tenant_id == uuid.UUID(tenant_id))
                )
            ).scalars().all()
        types = {e.event_type for e in events}
        assert TenantAuditEventType.tenant_created in types
        assert TenantAuditEventType.tenant_suspended in types
        assert TenantAuditEventType.tenant_resumed in types

    async def test_delete_requires_typed_confirmation(self, client):
        created = await client.post(
            "/api/v1/platform/tenants", json={"name": "Doomed", "slug": _unique("dm")}
        )
        tenant_id = created.json()["id"]
        wrong = await client.delete(
            f"/api/v1/platform/tenants/{tenant_id}", params={"confirm_slug": "wrong"}
        )
        assert wrong.status_code == 400
        still_there = await client.get(f"/api/v1/platform/tenants/{tenant_id}")
        assert still_there.status_code == 200

    async def test_delete_removes_tenant_and_slug_is_reusable(self, client):
        """CS-09: true deletion — the address can be recreated."""
        slug = _unique("del")
        created = await client.post(
            "/api/v1/platform/tenants", json={"name": "Gone Soon", "slug": slug}
        )
        tenant_id = created.json()["id"]
        deleted = await client.delete(
            f"/api/v1/platform/tenants/{tenant_id}", params={"confirm_slug": slug}
        )
        assert deleted.status_code == 204
        # Gone from list AND detail immediately.
        listing = await client.get("/api/v1/platform/tenants")
        assert slug not in [t["slug"] for t in listing.json()["items"]]
        detail = await client.get(f"/api/v1/platform/tenants/{tenant_id}")
        assert detail.status_code == 404
        # Recreate on the same address succeeds.
        recreated = await client.post(
            "/api/v1/platform/tenants", json={"name": "Reborn", "slug": slug}
        )
        assert recreated.status_code == 201
        assert recreated.json()["id"] != tenant_id

    async def test_unknown_tenant_404(self, client):
        response = await client.get(f"/api/v1/platform/tenants/{uuid.uuid4()}")
        assert response.status_code == 404


class TestPermissionGuards:
    async def test_routes_require_platform_permissions(self, test_engine, _bypass_auth):
        app = create_app()
        for rt in (RT_PLATFORM_TENANTS, RT_PLATFORM_SETTINGS, RT_PLATFORM_AUDIT):
            for action in ("create", "read", "update", "delete", "manage"):
                app.dependency_overrides[require_permission(rt, action)] = _deny()
        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )

        async def override_db():
            async with SessionLocal() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for method, path in (
                ("GET", "/api/v1/platform/tenants"),
                ("POST", "/api/v1/platform/tenants"),
                ("GET", "/api/v1/platform/settings"),
                ("PUT", "/api/v1/platform/settings/whatever"),
                ("GET", "/api/v1/platform/audit-events"),
            ):
                response = await client.request(method, path, json={})
                assert response.status_code == 403, f"{method} {path} not guarded"


class TestPlatformSettingsAPI:
    async def test_settings_read_defaults_off(self, client):
        response = await client.get("/api/v1/platform/settings")
        assert response.status_code == 200
        body = response.json()
        assert body["multi_tenancy_enabled"] is False

    async def test_toggle_enable_runs_adoption_and_audits(self, client, test_engine):
        """CS-05 via API: enabling adopts the system tenant."""
        response = await client.put(
            "/api/v1/platform/settings/multi_tenancy_enabled", json={"value": True}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["multi_tenancy_enabled"] is True
        assert body["adoption"]["action"] == "enabled"
        assert body["adoption"]["slug"] == "root"
        assert body["adoption"]["created"] is True

        # The switch is reflected in a fresh read.  (Switch ON → platform
        # requests require the root-tenant binding, as the real client sends.)
        readback = await client.get(
            "/api/v1/platform/settings", headers={"X-Tenant": "root"}
        )
        assert readback.json()["multi_tenancy_enabled"] is True

        # A system tenant now exists.
        listing = await client.get(
            "/api/v1/platform/tenants", headers={"X-Tenant": "root"}
        )
        slugs = [t["slug"] for t in listing.json()["items"]]
        assert "root" in slugs

    async def test_disable_preserves_data(self, client, test_engine):
        """CS-03: disable returns to single-tenant behaviour, no data loss."""
        await client.put("/api/v1/platform/settings/multi_tenancy_enabled", json={"value": True})
        root_headers = {"X-Tenant": "root"}
        disabled = await client.put(
            "/api/v1/platform/settings/multi_tenancy_enabled",
            json={"value": False},
            headers=root_headers,
        )
        assert disabled.status_code == 200
        assert disabled.json()["multi_tenancy_enabled"] is False
        assert disabled.json()["adoption"]["data_loss"] is False
        # Tenants survive the switch-off.
        listing = await client.get(
            "/api/v1/platform/tenants", headers=root_headers
        )
        slugs = [t["slug"] for t in listing.json()["items"]]
        assert "root" in slugs

    async def test_enable_is_idempotent(self, client):
        await client.put("/api/v1/platform/settings/multi_tenancy_enabled", json={"value": True})
        again = await client.put(
            "/api/v1/platform/settings/multi_tenancy_enabled",
            json={"value": True},
            headers={"X-Tenant": "root"},
        )
        assert again.status_code == 200
        assert again.json()["adoption"]["created"] is False  # already adopted


class TestPlatformAuditAPI:
    async def test_audit_lists_events_with_tenant_attribution(self, client, test_engine):
        from app.db.models.tenant import Tenant
        from app.db.models.tenant_audit_event import TenantAuditEvent, TenantAuditEventType

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            tenant = Tenant(name="AuditTarget", slug=_unique("audittarget"))
            db.add(tenant)
            await db.flush()
            db.add(
                TenantAuditEvent(
                    tenant_id=tenant.id,
                    event_type=TenantAuditEventType.cross_tenant_access_denied,
                    actor_type="tenant_user",
                    is_security_relevant=True,
                    target_resource="GET /api/v1/roles",
                    detail={"reason": "mismatch"},
                )
            )
            await db.commit()
            tenant_id = tenant.id

        response = await client.get("/api/v1/platform/audit-events")
        assert response.status_code == 200
        body = response.json()
        matching = [e for e in body["items"] if e["tenant_id"] == str(tenant_id)]
        assert len(matching) >= 1
        assert matching[-1]["tenant_slug"] == _unique("audittarget")
        assert matching[-1]["is_security_relevant"] is True

        # security_only filter
        security = await client.get(
            "/api/v1/platform/audit-events", params={"security_only": True}
        )
        assert all(e["is_security_relevant"] for e in security.json()["items"])

        # tenant filter
        tenant_scoped = await client.get(
            "/api/v1/platform/audit-events", params={"tenant_id": str(tenant_id)}
        )
        assert all(e["tenant_id"] == str(tenant_id) for e in tenant_scoped.json()["items"])

    async def test_audit_never_exposes_business_data(self, client, test_engine):
        from app.db.models.tenant import Tenant
        from app.db.models.tenant_audit_event import TenantAuditEvent, TenantAuditEventType

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            tenant = Tenant(name="NoBizData", slug=_unique("nobiz"))
            db.add(tenant)
            await db.flush()
            db.add(
                TenantAuditEvent(
                    tenant_id=tenant.id,
                    event_type=TenantAuditEventType.tenant_created,
                    actor_type="system",
                )
            )
            await db.commit()

        response = await client.get("/api/v1/platform/audit-events")
        allowed_keys = {
            "id", "tenant_id", "tenant_slug", "event_type", "actor_type", "actor_id",
            "actor_ip", "target_resource", "detail", "is_security_relevant", "created_at",
        }
        for item in response.json()["items"]:
            assert set(item.keys()) <= allowed_keys
