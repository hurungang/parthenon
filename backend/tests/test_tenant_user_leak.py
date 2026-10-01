"""Reproduction tests for FIX-20260928-121317 — cross-tenant PlatformUser leak.

ISSUE (pre-fix behaviour, reproduced here): signed in as a tenant root,
the permission module's user list (``GET /api/v1/platform-users``)
returns platform users that have NO active membership in the caller's
tenant (leak from the system tenant), and
``GET /api/v1/platform-users/{id}`` resolves a foreign tenant's user id
(200 instead of 404).

ROOT CAUSE: ``PlatformUser`` deliberately carries no ``tenant_id`` — the
``do_orm_execute`` scoping choke point (app.db.tenant_scoping) therefore
never filters it, and ``backend/app/api/v1/platform_users.py`` runs
``select(PlatformUser)`` unfiltered plus ``db.get(PlatformUser, id)``
which bypasses scoping entirely.

EXPECTED CONTRACT (post-fix):
- In tenant-A context, ``GET /platform-users`` lists ONLY users with an
  ACTIVE ``TenantUserMembership`` in tenant A.
- ``GET /platform-users/{id}`` for a user without an active membership
  in the current tenant responds 404 (with a scope-miss audit event).

These tests are EXPECTED TO FAIL until the fix lands.  The tenant-A
context is established exactly the way production does it: the
``get_db`` dependency override applies ``apply_tenant_scope`` at the
single choke point (same mechanism as ``_maybe_apply_request_tenant_scope``
in app/db/session.py).

Systematic ALL-entity coverage lives in
``backend/tests/test_tenant_isolation_sweep.py``.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from unittest.mock import patch

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.api.deps import require_permission  # noqa: E402
from app.core.resource_types import RT_SYSTEM_PERMISSIONS  # noqa: E402
from app.db.models.platform_user import PlatformUser  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_audit_event import TenantAuditEvent  # noqa: E402
from app.db.models.tenant_membership import TenantUserMembership  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.db.tenant_scoping import (  # noqa: E402
    apply_tenant_scope,
    flush_scope_miss_audits,
    register_tenant_scope_listener,
)
from app.main import create_app  # noqa: E402
from app.middleware.auth import JWTAuthMiddleware  # noqa: E402

_TAG = uuid.uuid4().hex[:8]  # per-module run uniqueness for globally unique columns


@pytest.fixture
def _bypass_auth():
    """Set a request identity without going through OIDC (established pattern)."""

    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "tenant-root-test", "roles": ["admin"]}
        return await call_next(request)

    with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch):
        yield


@pytest_asyncio.fixture(autouse=True)
async def _clean_users_tables(test_engine):
    """Reset the tables this module touches — BEFORE and AFTER each test —
    so assertions are deterministic regardless of suite order on the
    shared session-scoped engine."""
    from sqlalchemy import delete

    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _wipe():
        async with SessionLocal() as db:
            await db.execute(delete(TenantAuditEvent))
            await db.execute(delete(TenantUserMembership))
            await db.execute(delete(PlatformUser))
            await db.execute(delete(Tenant))
            await db.commit()

    await _wipe()
    yield
    await _wipe()


@pytest_asyncio.fixture
async def seeded_two_tenants(test_engine):
    """Tenant A (root + member) and tenant B (root + member), each user
    with an ACTIVE membership in exactly one tenant.  Returns id/email map."""
    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        tenant_a = Tenant(name="Acme A", slug=f"leak-a-{_TAG}")
        tenant_b = Tenant(name="Beta B", slug=f"leak-b-{_TAG}")
        db.add_all([tenant_a, tenant_b])
        await db.flush()

        def _user(label: str) -> PlatformUser:
            return PlatformUser(
                sub=f"sub-{label}-{_TAG}",
                email=f"{label}-{_TAG}@example.test",
                display_name=f"User {label}",
            )

        root_a, member_a = _user("root-a"), _user("member-a")
        root_b, member_b = _user("root-b"), _user("member-b")
        db.add_all([root_a, member_a, root_b, member_b])
        await db.flush()

        db.add_all(
            [
                TenantUserMembership(
                    tenant_id=tenant_a.id, user_id=root_a.id, tenant_role="member", is_root=True
                ),
                TenantUserMembership(tenant_id=tenant_a.id, user_id=member_a.id, tenant_role="member"),
                TenantUserMembership(
                    tenant_id=tenant_b.id, user_id=root_b.id, tenant_role="member", is_root=True
                ),
                TenantUserMembership(tenant_id=tenant_b.id, user_id=member_b.id, tenant_role="member"),
            ]
        )
        await db.commit()
        return {
            "tenant_a_id": tenant_a.id,
            "tenant_b_id": tenant_b.id,
            "member_a_id": member_a.id,
            "root_a_email": root_a.email,
            "member_a_email": member_a.email,
            "member_b_id": member_b.id,
            "root_b_email": root_b.email,
            "member_b_email": member_b.email,
        }


@pytest_asyncio.fixture
async def tenant_a_client(test_engine, seeded_two_tenants, _bypass_auth):
    """Async client whose ``get_db`` dependency runs with tenant A bound at
    the scoping choke point — exactly what a tenant-A-context request gets
    in production multi-tenant mode."""
    app = create_app()
    for action in ("read", "manage", "delete"):
        app.dependency_overrides[require_permission(RT_SYSTEM_PERMISSIONS, action)] = lambda: {
            "sub": "tenant-root-test",
            "roles": ["admin"],
        }

    SessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with SessionLocal() as session:
            register_tenant_scope_listener()
            apply_tenant_scope(session, seeded_two_tenants["tenant_a_id"])
            yield session
            # Mirror production: cross-tenant probes become audit events.
            await flush_scope_miss_audits(session)
            await session.commit()

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


class TestPlatformUserTenantLeakReproduction:
    """Endpoint-level reproduction of FIX-20260928-121317 (both FAIL pre-fix)."""

    async def test_list_platform_users_returns_only_users_with_active_membership_in_current_tenant(
        self, tenant_a_client, seeded_two_tenants
    ):
        """Test A (list): GET /platform-users in tenant-A context must
        contain ONLY tenant A's active members.  Pre-fix, the unfiltered
        ``select(PlatformUser)`` leaks tenant B's users into the response."""
        response = await tenant_a_client.get("/api/v1/platform-users")
        assert response.status_code == 200

        emails = [u["email"] for u in response.json()]

        # Positive control: tenant A's own members are visible.
        assert seeded_two_tenants["root_a_email"] in emails, (
            "tenant A root missing from tenant-A user list"
        )
        assert seeded_two_tenants["member_a_email"] in emails, (
            "tenant A member missing from tenant-A user list"
        )

        # THE BUG: foreign (tenant-B-only) users must NOT be visible.
        leaked = [
            e
            for e in emails
            if e in (seeded_two_tenants["root_b_email"], seeded_two_tenants["member_b_email"])
        ]
        assert not leaked, (
            "CROSS-TENANT USER LEAK: users with no active membership in the "
            f"requesting tenant are listed: {leaked}"
        )
        assert len(emails) == 2, (
            f"expected exactly tenant A's 2 members, got {len(emails)} users: {emails}"
        )

    async def test_detail_of_user_without_membership_in_current_tenant_returns_404(
        self, tenant_a_client, seeded_two_tenants
    ):
        """Test B (detail): GET /platform-users/{id of a B-only user} in
        tenant-A context must 404.  Pre-fix, ``db.get(PlatformUser, id)``
        bypasses scoping entirely and resolves the foreign row (200)."""
        # Control: the caller's own tenant member resolves normally.
        own = await tenant_a_client.get(
            f"/api/v1/platform-users/{seeded_two_tenants['member_a_id']}"
        )
        assert own.status_code == 200, (
            "control failed: own tenant member not resolvable — tenant context "
            "is not applied as expected"
        )

        # THE BUG: a foreign user id must behave as not-found.
        foreign = await tenant_a_client.get(
            f"/api/v1/platform-users/{seeded_two_tenants['member_b_id']}"
        )
        assert foreign.status_code == 404, (
            "CROSS-TENANT USER LEAK: GET /platform-users/{foreign_id} returned "
            f"{foreign.status_code} instead of 404 for a user with no active "
            "membership in the requesting tenant"
        )
