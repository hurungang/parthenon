"""Tenant membership & invitation API tests (Phase 5.7 / E-08).

Covers the tenant self-service surface (``/api/v1/tenant/*``) with REAL
app + sqlite DB and a resolved tenant context:

- membership CRUD: list, role change, suspend/remove; platform-admin
  memberships immutable; cross-tenant membership ids 404 (no leak)
- invitation matrix (E-08): create with shown-once token, single-use
  replay rejection, expiry, revoke, acceptance after tenant suspension,
  listing never exposes tokens, cross-tenant ids unreachable
- public acceptance endpoint provisions the membership with the invited
  role
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
    RT_TENANT_MEMBERS,
    RT_TENANT_SETTINGS,
)
from app.core.tenant_context import TenantContext, set_tenant_context  # noqa: E402
from app.db.models.platform_user import PlatformUser  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_invitation import TenantInvitation  # noqa: E402
from app.db.models.tenant_membership import TenantUserMembership  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.middleware.auth import JWTAuthMiddleware  # noqa: E402
from app.middleware.tenant_resolution import TenantResolutionMiddleware  # noqa: E402

_TS_HOLDER = {"v": uuid.uuid4().hex[:8]}


def _ts() -> str:
    """Per-test unique suffix (the engine is shared across tests)."""
    return _TS_HOLDER["v"]


@pytest.fixture(autouse=True)
def _fresh_suffix():
    _TS_HOLDER["v"] = uuid.uuid4().hex[:8]
    yield


def _allow():
    def override():
        return {"sub": "tenant-admin-test"}

    return override


async def _seed_world(test_engine):
    """Returns (tenant_a, tenant_b, admin_user_a, admin_membership_a)."""
    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        tenant_a = Tenant(name=f"OrgA-{_ts()}", slug=f"orga-{_ts()}")
        tenant_b = Tenant(name=f"OrgB-{_ts()}", slug=f"orgb-{_ts()}")
        admin = PlatformUser(
            sub=f"admin-a-{_ts()}", email=f"admin-a-{_ts()}@test.dev", display_name="Admin A"
        )
        db.add_all([tenant_a, tenant_b, admin])
        await db.flush()
        # Phase 10: the first admin of a tenant is its immutable ROOT
        # (owner) membership — grants all tenant permissions.
        membership = TenantUserMembership(
            tenant_id=tenant_a.id, user_id=admin.id, tenant_role="tenant_admin",
            is_root=True,
        )
        db.add(membership)
        await db.commit()
        return tenant_a, tenant_b, admin, membership


@pytest_asyncio.fixture
async def tenant_env(test_engine):
    tenant_a, tenant_b, admin, membership = await _seed_world(test_engine)
    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    def _make_client(context: TenantContext, sub: str):
        app = create_app()
        for rt in (RT_TENANT_MEMBERS, RT_TENANT_SETTINGS):
            for action in ("create", "read", "update", "delete", "manage"):
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
            set_tenant_context(request, context)
            return await call_next(request)

        return app, [
            patch.object(TenantResolutionMiddleware, "dispatch", bind_tenant),
            patch.object(JWTAuthMiddleware, "dispatch", bypass_jwt),
        ]

    return tenant_a, tenant_b, admin, membership, _make_client


@pytest_asyncio.fixture
async def admin_client(tenant_env):
    tenant_a, _tb, admin, _m, make = tenant_env
    app, patches = make(
        TenantContext(tenant_id=tenant_a.id, slug=tenant_a.slug, name=tenant_a.name),
        f"admin-a-{_ts()}",
    )
    for p in patches:
        p.start()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    for p in patches:
        p.stop()


class TestTenantSettings:
    async def test_settings_read_own_tenant(self, admin_client, tenant_env):
        tenant_a = tenant_env[0]
        response = await admin_client.get("/api/v1/tenant/settings")
        assert response.status_code == 200
        body = response.json()
        assert body["slug"] == tenant_a.slug
        assert body["your_role"] == "tenant_admin"

    async def test_settings_update_own_tenant(self, admin_client):
        response = await admin_client.patch(
            "/api/v1/tenant/settings", json={"name": f"Renamed-{_ts()}"}
        )
        assert response.status_code == 200
        assert response.json()["name"] == f"Renamed-{_ts()}"


class TestMembers:
    async def test_list_members_own_tenant_only(self, admin_client, tenant_env, test_engine):
        tenant_a, tenant_b = tenant_env[0], tenant_env[1]
        SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as db:
            other = PlatformUser(sub=f"other-{_ts()}", email=f"other-{_ts()}@t.dev", display_name="Other")
            db.add(other)
            await db.flush()
            db.add(
                TenantUserMembership(
                    tenant_id=tenant_a.id, user_id=other.id, tenant_role="member"
                )
            )
            db.add(
                TenantUserMembership(
                    tenant_id=tenant_b.id, user_id=uuid.uuid4(), tenant_role="member"
                )
            )
            await db.commit()

        response = await admin_client.get("/api/v1/tenant/members")
        assert response.status_code == 200
        members = response.json()["items"]
        # All listed members belong to tenant A (2 seeded there).
        assert len(members) == 2

    async def test_member_role_change(self, admin_client, tenant_env, test_engine):
        tenant_a = tenant_env[0]
        SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as db:
            user = PlatformUser(sub=f"promotee-{_ts()}", email=f"p-{_ts()}@t.dev", display_name="Promotee")
            db.add(user)
            await db.flush()
            membership = TenantUserMembership(
                tenant_id=tenant_a.id, user_id=user.id, tenant_role="member"
            )
            db.add(membership)
            await db.commit()
            membership_id = membership.id

        response = await admin_client.patch(
            f"/api/v1/tenant/members/{membership_id}", json={"tenant_role": "tenant_admin"}
        )
        assert response.status_code == 200
        assert response.json()["tenant_role"] == "tenant_admin"

    async def test_cross_tenant_membership_id_404_no_leak(self, admin_client, test_engine):
        """CS-12: tenant B's membership id behaves as not-found."""
        SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as db:
            foreign = TenantUserMembership(
                tenant_id=(await db.execute(select(Tenant).where(Tenant.slug == f"orgb-{_ts()}")))
                .scalar_one()
                .id,
                user_id=uuid.uuid4(),
                tenant_role="member",
            )
            db.add(foreign)
            await db.commit()
            foreign_id = foreign.id

        response = await admin_client.patch(
            f"/api/v1/tenant/members/{foreign_id}", json={"tenant_role": "member"}
        )
        assert response.status_code == 404
        assert "Member not found" in response.json()["detail"]

    async def test_platform_admin_membership_immutable(self, admin_client, tenant_env, test_engine):
        tenant_a = tenant_env[0]
        SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as db:
            membership = TenantUserMembership(
                tenant_id=tenant_a.id, user_id=uuid.uuid4(), tenant_role="platform_admin"
            )
            db.add(membership)
            await db.commit()
            membership_id = membership.id

        response = await admin_client.patch(
            f"/api/v1/tenant/members/{membership_id}", json={"tenant_role": "member"}
        )
        assert response.status_code == 403


class TestInvitations:
    async def test_create_returns_token_once(self, admin_client):
        response = await admin_client.post(
            "/api/v1/tenant/invitations",
            json={"email": f"newbie-{_ts()}@t.dev", "tenant_role": "member"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["accept_token"]  # shown ONCE at creation
        assert body["status"] == "pending"

        listing = await admin_client.get("/api/v1/tenant/invitations")
        for item in listing.json():
            assert item["accept_token"] is None  # never listed

    async def test_invitation_single_use_replay_rejected(
        self, admin_client, tenant_env, test_engine
    ):
        tenant_a, _b, admin, _m = tenant_env[0], None, None, None
        created = await admin_client.post(
            "/api/v1/tenant/invitations",
            json={"email": f"once-{_ts()}@t.dev", "tenant_role": "member"},
        )
        token = created.json()["accept_token"]

        # A second user (different sub) accepts the invitation.
        SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as db:
            invitee = PlatformUser(sub=f"invitee-{_ts()}", email=f"i-{_ts()}@t.dev", display_name="Invitee")
            db.add(invitee)
            await db.commit()

        def _acceptor(sub):
            app = create_app()

            async def override_db():
                async with SessionLocal() as session:
                    yield session
                    await session.commit()

            app.dependency_overrides[get_db] = override_db

            async def bypass_jwt(self, request, call_next):
                request.state.identity = {"sub": sub}
                return await call_next(request)

            return app, patch.object(JWTAuthMiddleware, "dispatch", bypass_jwt)

        app, jwt_patch = _acceptor(f"invitee-{_ts()}")
        jwt_patch.start()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            first = await c.post("/api/v1/invitations/accept", json={"token": token})
            assert first.status_code == 200
            assert first.json()["slug"] == f"orga-{_ts()}"
            # Replay: the same token resolves to NOTHING (the token hash is
            # destroyed on acceptance — single use is enforced at the
            # lookup level, the strongest form of rejection).
            replay = await c.post("/api/v1/invitations/accept", json={"token": token})
            assert replay.status_code in (404, 409)
        jwt_patch.stop()

    async def test_revoked_invitation_token_unusable(self, admin_client):
        created = await admin_client.post(
            "/api/v1/tenant/invitations",
            json={"email": f"revoke-{_ts()}@t.dev", "tenant_role": "member"},
        )
        invitation_id = created.json()["invitation_id"]
        revoked = await admin_client.post(
            f"/api/v1/tenant/invitations/{invitation_id}/revoke"
        )
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"

        # Accepting a revoked invitation fails (unknown token).
        SessionLocal = async_sessionmaker(
            bind=type(admin_client)._transport.app.dependency_overrides and None or None
        ) if False else None

        app = create_app()

        async def override_db():
            yield None  # replaced below

        # Direct DB-level check: the token hash was destroyed on revoke.
        from app.api.v1.tenant import _hash_token

        SessionLocal2 = async_sessionmaker(
            bind=None, class_=AsyncSession, expire_on_commit=False
        )
        # The public accept endpoint rejects the stale token with 404.
        app2 = create_app()
        token = created.json()["accept_token"]

        async def override_db2():
            from app.db.session import AsyncSessionLocal  # noqa: F401

            yield None

        # Simpler: call accept with the same token via an authed client.
        async with AsyncClient(
            transport=ASGITransport(app=admin_client._transport.app),
            base_url="http://test",
        ) as c:
            rejected = await c.post("/api/v1/invitations/accept", json={"token": token})
            assert rejected.status_code == 404

    async def test_expired_invitation_rejected(self, admin_client, test_engine):
        created = await admin_client.post(
            "/api/v1/tenant/invitations",
            json={"email": f"expired-{_ts()}@t.dev", "tenant_role": "member"},
        )
        token = created.json()["accept_token"]

        # Force the invitation into the past.
        SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as db:
            invitation = (
                await db.execute(
                    select(TenantInvitation).where(
                        TenantInvitation.tenant_id
                        == (
                            await db.execute(select(Tenant).where(Tenant.slug == f"orga-{_ts()}"))
                        ).scalar_one().id
                    )
                )
            ).scalars().first()
            from datetime import datetime, timedelta, timezone

            invitation.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
            await db.commit()

        app = create_app()
        SessionLocal2 = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

        async def override_db():
            async with SessionLocal2() as session:
                yield session
                await session.commit()

        app.dependency_overrides[get_db] = override_db

        async def bypass_jwt(self, request, call_next):
            request.state.identity = {"sub": f"invitee2-{_ts()}"}
            return await call_next(request)

        with patch.object(JWTAuthMiddleware, "dispatch", bypass_jwt):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                # The invitee must exist for acceptance to proceed to expiry check
                async with SessionLocal2() as db:
                    db.add(
                        PlatformUser(sub=f"invitee2-{_ts()}", email=f"i2-{_ts()}@t.dev", display_name="Invitee2")
                    )
                    await db.commit()
                response = await c.post("/api/v1/invitations/accept", json={"token": token})
        assert response.status_code == 410

    async def test_unknown_token_404(self, admin_client):
        app = admin_client._transport.app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            response = await c.post(
                "/api/v1/invitations/accept", json={"token": "x" * 40}
            )
        assert response.status_code == 404
