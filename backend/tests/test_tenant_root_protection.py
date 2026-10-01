"""Tenant root protection tests (Phase 10.18, CS-30/CS-31/CS-32).

The tenant root (owner) membership is IMMUTABLE:

- CS-30: a delegated tenant admin cannot demote, suspend or remove the
  root membership through any tenant API path; every attempt is
  rejected with a clear 403 and audited as a security-relevant
  ``root_protection_rejected`` event, leaving the membership untouched.
- CS-31: the platform admin has NO membership-mutation path either —
  platform tenant-update payloads cannot inject root-altering or
  slug-changing fields, and the shared guard rejects a root-targeted
  mutation regardless of the actor.
- Root permission breadth: the root membership grants ALL tenant
  permissions (every module/action of the tenant membership grant
  table) with no additional role grants.
- CS-32: alias editing is root-only; the slug (address) is immutable.
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

from app.api.deps import _TENANT_MEMBERSHIP_GRANTS, _membership_grants, require_permission  # noqa: E402
from app.core.resource_types import RT_TENANT_MEMBERS, RT_TENANT_SETTINGS  # noqa: E402
from app.core.tenant_context import TenantContext, set_tenant_context  # noqa: E402
from app.db.models.platform_user import PlatformUser  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_audit_event import TenantAuditEvent  # noqa: E402
from app.db.models.tenant_membership import TenantUserMembership  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.middleware.auth import JWTAuthMiddleware  # noqa: E402
from app.middleware.tenant_resolution import TenantResolutionMiddleware  # noqa: E402

_TS_HOLDER = {"v": uuid.uuid4().hex[:8]}


def _ts() -> str:
    return _TS_HOLDER["v"]


@pytest.fixture(autouse=True)
def _fresh_suffix():
    _TS_HOLDER["v"] = uuid.uuid4().hex[:8]
    yield


async def _seed_world(test_engine):
    """Tenant A with a ROOT owner, a delegated admin and a plain member.

    Returns (tenant_a, root_user, root_membership, admin_membership,
    member_membership).
    """
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as db:
        tenant = Tenant(name=f"Org-{_ts()}", slug=f"org-{_ts()}")
        root = PlatformUser(
            sub=f"root-{_ts()}", email=f"root-{_ts()}@t.dev", display_name="Root"
        )
        admin = PlatformUser(
            sub=f"admin-{_ts()}", email=f"admin-{_ts()}@t.dev", display_name="Admin"
        )
        member = PlatformUser(
            sub=f"member-{_ts()}", email=f"member-{_ts()}@t.dev", display_name="Member"
        )
        db.add_all([tenant, root, admin, member])
        await db.flush()
        root_m = TenantUserMembership(
            tenant_id=tenant.id, user_id=root.id, tenant_role="tenant_admin",
            is_root=True,
        )
        admin_m = TenantUserMembership(
            tenant_id=tenant.id, user_id=admin.id, tenant_role="tenant_admin",
        )
        member_m = TenantUserMembership(
            tenant_id=tenant.id, user_id=member.id, tenant_role="member",
        )
        db.add_all([root_m, admin_m, member_m])
        await db.commit()
        return tenant, root, root_m, admin_m, member_m


@pytest_asyncio.fixture
async def env(test_engine):
    tenant, root, root_m, admin_m, member_m = await _seed_world(test_engine)
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    def _make_client(sub: str):
        app = create_app()
        for rt in (RT_TENANT_MEMBERS, RT_TENANT_SETTINGS):
            for action in ("create", "read", "update", "delete", "manage"):
                def _allow(sub=sub):
                    def override():
                        return {"sub": sub}
                    return override
                app.dependency_overrides[require_permission(rt, action)] = _allow()

        async def override_db():
            async with SessionLocal() as session:
                yield session
                await session.commit()

        app.dependency_overrides[get_db] = override_db

        async def bypass_jwt(self, request, call_next):
            request.state.identity = {"sub": sub}
            return await call_next(request)

        async def bind_tenant(self, request, call_next):
            set_tenant_context(
                request,
                TenantContext(tenant_id=tenant.id, slug=tenant.slug, name=tenant.name),
            )
            return await call_next(request)

        patches = [
            patch.object(TenantResolutionMiddleware, "dispatch", bind_tenant),
            patch.object(JWTAuthMiddleware, "dispatch", bypass_jwt),
        ]
        return app, patches

    return {
        "tenant": tenant,
        "root": root,
        "root_m": root_m,
        "admin_m": admin_m,
        "member_m": member_m,
        "make_client": _make_client,
        "session_factory": SessionLocal,
    }


def _ids(membership) -> str:
    return str(membership.id)


# ── CS-30: delegated tenant admin cannot touch the root ─────────────────────


class TestRootProtectionAgainstTenantAdmin:
    @pytest.mark.parametrize(
        "payload,action",
        [
            ({"tenant_role": "member"}, "demote"),
            ({"status": "suspended"}, "suspend"),
            ({"status": "removed"}, "remove"),
        ],
    )
    async def test_root_membership_mutation_rejected_and_audited(
        self, env, payload, action
    ):
        """CS-30: demote/suspend/remove of the root → 403 + audit, and
        the root membership is left completely unchanged."""
        client_ctx = env["make_client"](f"admin-{_ts()}")
        app, patches = client_ctx
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.patch(
                    f"/api/v1/tenant/members/{_ids(env['root_m'])}",
                    json=payload,
                )
                assert response.status_code == 403
                assert "root" in response.json()["detail"].lower()
        finally:
            for p in patches:
                p.stop()

        SessionLocal = env["session_factory"]
        async with SessionLocal() as db:
            membership = await db.get(TenantUserMembership, env["root_m"].id)
            assert membership.is_root is True
            assert membership.tenant_role.value == "tenant_admin"
            assert membership.status.value == "active"

            events = (
                (
                    await db.execute(
                        select(TenantAuditEvent).where(
                            TenantAuditEvent.event_type
                            == "root_protection_rejected",
                            TenantAuditEvent.tenant_id == env["tenant"].id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(events) >= 1
            assert all(e.is_security_relevant for e in events)
            assert any(
                _ids(env["root_m"]) in (e.target_resource or "") for e in events
            )

    async def test_root_cannot_be_swapped_via_payload_injection(self, env):
        """CS-31 (tenant path): a payload injecting ``is_root`` onto a
        NON-root member is ignored — no actor can mint a second root."""
        client_ctx = env["make_client"](f"admin-{_ts()}")
        app, patches = client_ctx
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.patch(
                    f"/api/v1/tenant/members/{_ids(env['member_m'])}",
                    json={"tenant_role": "tenant_admin", "is_root": True},
                )
                assert response.status_code == 200
                assert response.json()["is_root"] is False
        finally:
            for p in patches:
                p.stop()

        SessionLocal = env["session_factory"]
        async with SessionLocal() as db:
            member = await db.get(TenantUserMembership, env["member_m"].id)
            assert member.is_root is False
            roots = (
                (
                    await db.execute(
                        select(TenantUserMembership).where(
                            TenantUserMembership.tenant_id == env["tenant"].id,
                            TenantUserMembership.is_root.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(roots) == 1
            assert roots[0].id == env["root_m"].id


# ── CS-31: platform admin has no root-altering path ─────────────────────────


class TestRootProtectionAgainstPlatformAdmin:
    async def test_platform_tenant_update_cannot_alter_root_or_slug(
        self, env, test_engine
    ):
        """CS-31 (platform path): PATCH /platform/tenants/{id} with
        root-altering / slug-changing injections must silently ignore
        them — the root membership and the address stay untouched."""
        from app.core.resource_types import RT_PLATFORM_TENANTS

        tenant = env["tenant"]
        SessionLocal = env["session_factory"]
        app = create_app()
        for action in ("create", "read", "update", "delete", "manage"):
            def _allow():
                def override():
                    return {"sub": "platform-admin"}
                return override
            app.dependency_overrides[require_permission(RT_PLATFORM_TENANTS, action)] = _allow()

        async def override_db():
            async with SessionLocal() as session:
                yield session
                await session.commit()

        app.dependency_overrides[get_db] = override_db

        async def bypass_jwt(self, request, call_next):
            request.state.identity = {"sub": "platform-admin"}
            return await call_next(request)

        with patch.object(JWTAuthMiddleware, "dispatch", bypass_jwt):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.patch(
                    f"/api/v1/platform/tenants/{tenant.id}",
                    json={
                        "name": "Renamed By Platform",
                        "slug": "hijacked-address",  # immutable — must be ignored
                        "is_root": False,  # injection attempt — must be ignored
                        "memberships": [],  # injection attempt — must be ignored
                    },
                )
                assert response.status_code == 200

        async with SessionLocal() as db:
            refreshed = await db.get(Tenant, tenant.id)
            assert refreshed.slug == tenant.slug  # address immutable
            roots = (
                (
                    await db.execute(
                        select(TenantUserMembership).where(
                            TenantUserMembership.tenant_id == tenant.id,
                            TenantUserMembership.is_root.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(roots) == 1
            assert roots[0].id == env["root_m"].id
            assert roots[0].status.value == "active"

    async def test_platform_surface_has_no_membership_mutation_route(self):
        """CS-31 (structural): no platform route mutates memberships —
        the platform admin can never demote/remove/replace the root
        because no such endpoint exists on the platform surface."""
        from app.api.v1.platform import tenants as platform_tenants_module

        app = create_app()
        membership_routes = [
            route.path
            for route in app.routes
            if "platform" in getattr(route, "path", "")
            and "member" in getattr(route, "path", "").lower()
        ]
        assert membership_routes == []
        # And the platform tenants router exposes no membership ops.
        for route in platform_tenants_module.PlatformTenantsRouter.routes:
            assert "member" not in route.path.lower()

    async def test_guard_rejects_root_target_regardless_of_actor(self, env):
        """CS-31: the shared guard is actor-agnostic — a platform-admin
        caller attempting a root-targeted mutation is rejected the same
        way (403 + security-relevant audit)."""
        from app.api.deps import guard_non_root_membership
        from fastapi import HTTPException

        SessionLocal = env["session_factory"]
        async with SessionLocal() as db:
            membership = await db.get(TenantUserMembership, env["root_m"].id)
            with pytest.raises(HTTPException) as exc:
                await guard_non_root_membership(
                    db, membership, request=None, action="platform_demote"
                )
            assert exc.value.status_code == 403
            await db.commit()

        async with SessionLocal() as db:
            events = (
                (
                    await db.execute(
                        select(TenantAuditEvent).where(
                            TenantAuditEvent.event_type
                            == "root_protection_rejected"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert any(
                "platform_demote" in (e.detail or {}).get("action", "")
                for e in events
            )


# ── Root permission breadth (Phase 10.3) ────────────────────────────────────


class TestRootPermissionBreadth:
    async def test_root_grants_all_tenant_permissions(self, env, test_engine):
        """The root membership grants EVERY module/action pair of the
        tenant membership grant table without additional roles."""
        SessionLocal = env["session_factory"]
        async with SessionLocal() as db:
            for module, actions in _TENANT_MEMBERSHIP_GRANTS.items():
                for action in actions:
                    assert await _membership_grants(
                        db, env["root"].id, env["tenant"].id, module, action
                    ), f"root must be granted {module}:{action}"

    async def test_non_root_roles_limited_to_their_grants(self, env, test_engine):
        """A delegated admin does NOT get the root breadth — only the
        entries their role appears in; a plain member gets read-only
        settings."""
        SessionLocal = env["session_factory"]
        async with SessionLocal() as db:
            admin_id = (
                await db.execute(
                    select(PlatformUser).where(
                        PlatformUser.sub == f"admin-{_ts()}"
                    )
                )
            ).scalar_one().id
            member_id = (
                await db.execute(
                    select(PlatformUser).where(
                        PlatformUser.sub == f"member-{_ts()}"
                    )
                )
            ).scalar_one().id

            # Delegated admin: granted where their role is listed …
            assert await _membership_grants(
                db, admin_id, env["tenant"].id, "tenant::members", "manage"
            )
            assert await _membership_grants(
                db, admin_id, env["tenant"].id, "tenant::settings", "manage"
            )
            # … but nothing beyond the table (e.g. an unlisted module).
            assert not await _membership_grants(
                db, admin_id, env["tenant"].id, "agent::types", "create"
            )

            # Plain member: settings read only.
            assert await _membership_grants(
                db, member_id, env["tenant"].id, "tenant::settings", "read"
            )
            assert not await _membership_grants(
                db, member_id, env["tenant"].id, "tenant::members", "manage"
            )


# ── CS-32: root-only alias editing, immutable slug ──────────────────────────


class TestAliasAndSlug:
    async def test_root_can_edit_alias_immediately_audited(self, env):
        """CS-32: the root renames the tenant; the change is returned
        immediately and audited; the slug is untouched."""
        tenant = env["tenant"]
        client_ctx = env["make_client"](f"root-{_ts()}")
        app, patches = client_ctx
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.patch(
                    "/api/v1/tenant/settings",
                    json={"name": f"Renamed-{_ts()}"},
                )
                assert response.status_code == 200, response.text
                body = response.json()
                assert body["name"] == f"Renamed-{_ts()}"
                assert body["slug"] == tenant.slug  # address unchanged
                assert body["is_root"] is True
        finally:
            for p in patches:
                p.stop()

        SessionLocal = env["session_factory"]
        async with SessionLocal() as db:
            refreshed = await db.get(Tenant, tenant.id)
            assert refreshed.name == f"Renamed-{_ts()}"
            assert refreshed.slug == tenant.slug
            events = (
                (
                    await db.execute(
                        select(TenantAuditEvent).where(
                            TenantAuditEvent.event_type == "tenant_updated",
                            TenantAuditEvent.tenant_id == tenant.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert any(
                (e.detail or {}).get("alias") == f"Renamed-{_ts()}" for e in events
            )

    async def test_non_root_admin_cannot_edit_alias(self, env):
        """CS-32: a delegated tenant admin gets a clear 403 and the name
        is unchanged."""
        tenant = env["tenant"]
        client_ctx = env["make_client"](f"admin-{_ts()}")
        app, patches = client_ctx
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.patch(
                    "/api/v1/tenant/settings",
                    json={"name": "Hijacked Name"},
                )
                assert response.status_code == 403
                assert "root" in response.json()["detail"].lower()
        finally:
            for p in patches:
                p.stop()

        SessionLocal = env["session_factory"]
        async with SessionLocal() as db:
            refreshed = await db.get(Tenant, tenant.id)
            assert refreshed.name == tenant.name

    async def test_slug_is_immutable_no_endpoint_accepts_it(self, env):
        """CS-32: the address cannot be changed through any endpoint —
        the settings PATCH schema does not accept a slug and injected
        fields are ignored."""
        tenant = env["tenant"]
        client_ctx = env["make_client"](f"root-{_ts()}")
        app, patches = client_ctx
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.patch(
                    "/api/v1/tenant/settings",
                    json={"name": tenant.name, "slug": "brand-new-address"},
                )
                assert response.status_code == 200
                assert response.json()["slug"] == tenant.slug
        finally:
            for p in patches:
                p.stop()

        SessionLocal = env["session_factory"]
        async with SessionLocal() as db:
            refreshed = await db.get(Tenant, tenant.id)
            assert refreshed.slug == tenant.slug

    async def test_alias_uniqueness_conflict_rejected_slug_untouched(
        self, env, test_engine
    ):
        """E-19: renaming the alias to another tenant's name fails with
        a clear error; the slug is never touched by the failed rename."""
        SessionLocal = env["session_factory"]
        async with SessionLocal() as db:
            other = Tenant(name=f"Other-{_ts()}", slug=f"other-{_ts()}")
            db.add(other)
            await db.commit()

        tenant = env["tenant"]
        client_ctx = env["make_client"](f"root-{_ts()}")
        app, patches = client_ctx
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.patch(
                    "/api/v1/tenant/settings",
                    json={"name": f"Other-{_ts()}"},  # already taken
                )
                assert response.status_code in (409, 422)
        finally:
            for p in patches:
                p.stop()

        async with SessionLocal() as db:
            refreshed = await db.get(Tenant, tenant.id)
            assert refreshed.slug == tenant.slug
            assert refreshed.name == tenant.name  # rename did not apply
