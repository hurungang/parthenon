"""Licensing & quota enforcement tests (Phase 10.18, CS-32..CS-43).

Sections (REAL app + sqlite DB, pattern of the other Phase 10 files):

- License lifecycle via the platform API (CS-33): assign / change with
  supersede (E-15 history retention, latest active wins) / remove with
  immediate free-tier fallback / invalid input (422) / remove-without-
  license (404) / list+detail carry tier + usage.
- Free-tier fallback (CS-34): unlicensed tenants resolve to the built-in
  free defaults (10 / 5 / 100) visible on both platform and tenant APIs.
- Quota gates per type (CS-35/CS-36/CS-37): user invitation (and the
  member-creating acceptance path), agent-type creation and execution
  submission are blocked with the STRUCTURED tier/limit/usage/upgrade
  payload (HTTP 403), no row created, nothing dispatched; under-quota
  actions always succeed.
- Quota independence (CS-38): exhausting one quota never blocks the
  unrelated quotas.
- Counting semantics (CS-39): users/agent-types derived live (no
  counter rows, can never drift); monthly executions via the counter
  bucket — incremented exactly once per accepted submission at
  acceptance, never refunded, implicit calendar-month reset (E-17
  drift semantics: the counter is authoritative for enforcement and
  visible in usage).
- License API permission guards (CS-43): only the platform admin can
  assign/change/remove licenses or read cross-tenant usage.
- E-20: tenant deletion removes license + quota rows; a recreated
  tenant starts on the free tier with fresh buckets.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

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
    RT_AGENT,
    RT_PLATFORM_TENANTS,
    RT_TENANT_MEMBERS,
    RT_TENANT_SETTINGS,
)
from app.core.tenant_context import TenantContext, set_tenant_context  # noqa: E402
from app.db.models.agents import AgentRole, AgentRoleSkill, AgentType  # noqa: E402
from app.db.models.platform_user import PlatformUser  # noqa: E402
from app.db.models.skills import Skill  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_audit_event import TenantAuditEvent  # noqa: E402
from app.db.models.tenant_license import LicenseTier, TenantLicense  # noqa: E402
from app.db.models.tenant_membership import (  # noqa: E402
    TenantUserMembership,
    TenantUserMembershipStatus,
)
from app.db.models.tenant_quota_usage import QuotaType, TenantQuotaUsage  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.middleware.auth import JWTAuthMiddleware  # noqa: E402
from app.middleware.tenant_resolution import TenantResolutionMiddleware  # noqa: E402
from app.services.tenancy.licensing_service import (  # noqa: E402
    FREE_TIER_LIMITS,
    TenantLicenseError,
    TenantLicensingService,
    get_tenant_licensing_service,
)
from app.services.tenancy.quota_service import (  # noqa: E402
    QuotaExceededError,
    TenantQuotaService,
    get_tenant_quota_service,
)

_TS_HOLDER = {"v": uuid.uuid4().hex[:8]}


def _ts() -> str:
    return _TS_HOLDER["v"]


def _unique(base: str) -> str:
    return f"{base}-{_ts()}"


@pytest.fixture(autouse=True)
def _fresh_suffix():
    _TS_HOLDER["v"] = uuid.uuid4().hex[:8]
    yield


@pytest_asyncio.fixture(autouse=True)
async def _fresh_state(test_engine):
    """Reset the settings singleton + switch row (engine is session-scoped)."""
    import app.services.tenancy.platform_settings_service as settings_module

    from app.db.models.platform_setting import PlatformSetting

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    settings_module._service = None
    async with SessionLocal() as db:
        await db.execute(
            PlatformSetting.__table__.delete().where(
                PlatformSetting.key == "multi_tenancy_enabled"
            )
        )
        await db.commit()
    settings_module._service = None
    yield
    settings_module._service = None


async def _enable_tenancy(test_engine) -> None:
    from app.db.models.platform_setting import PlatformSetting

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(PlatformSetting).where(
                    PlatformSetting.key == "multi_tenancy_enabled"
                )
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(
                PlatformSetting(
                    key="multi_tenancy_enabled",
                    value={"enabled": True},
                    category="tenancy",
                    is_tenant_agnostic=True,
                )
            )
        else:
            row.value = {"enabled": True}
        await db.commit()
    import app.services.tenancy.platform_settings_service as settings_module

    settings_module._service = None


async def _seed_world(test_engine):
    """Tenant + root owner.  Returns (tenant, root_user, session_factory)."""
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as db:
        tenant = Tenant(name=_unique("Licensing Org"), slug=_unique("lic"))
        root = PlatformUser(
            sub=_unique("root"), email=_unique("root@t.dev"), display_name="Root"
        )
        db.add_all([tenant, root])
        await db.flush()
        db.add(
            TenantUserMembership(
                tenant_id=tenant.id, user_id=root.id,
                tenant_role="tenant_admin", is_root=True,
            )
        )
        await db.commit()
        return tenant, root, SessionLocal


@pytest_asyncio.fixture
async def world(test_engine):
    tenant, root, SessionLocal = await _seed_world(test_engine)
    return {"tenant": tenant, "root": root, "sf": SessionLocal, "engine": test_engine}


def _make_client(world: dict, *, platform_admin: bool = False, sub: str | None = None):
    """Client bound to the tenant context; permission overrides per actor."""
    tenant = world["tenant"]
    sub = sub or world["root"].sub
    app = create_app()
    tenant_rts = (RT_TENANT_MEMBERS, RT_TENANT_SETTINGS)
    if platform_admin:
        tenant_rts = tenant_rts + (RT_PLATFORM_TENANTS,)
    for rt in tenant_rts:
        for action in ("create", "read", "update", "delete", "manage"):
            def _allow(rt=rt, action=action):
                def override():
                    return {"sub": sub}
                return override
            app.dependency_overrides[require_permission(rt, action)] = _allow()
    if not platform_admin:
        for action in ("create", "read", "update", "delete", "execute"):
            def _allow_agent(action=action):
                def override():
                    return {"sub": sub}
                return override
            app.dependency_overrides[require_permission(RT_AGENT, action)] = _allow_agent()

    SessionLocal = world["sf"]

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


async def _assign_license(world: dict, tier: str, users: int, types: int, execs: int):
    SessionLocal = world["sf"]
    async with SessionLocal() as db:
        await get_tenant_licensing_service().assign_license(
            db, world["tenant"].id,
            tier=LicenseTier(tier), max_users=users, max_agent_types=types,
            monthly_agent_executions=execs,
        )
        await db.commit()


async def _exhaust_executions(world: dict, used: int) -> None:
    """Seed the monthly bucket with ``used`` executions directly."""
    SessionLocal = world["sf"]
    async with SessionLocal() as db:
        db.add(
            TenantQuotaUsage(
                tenant_id=world["tenant"].id,
                quota_type=QuotaType.monthly_executions,
                period_start=datetime.now(timezone.utc).date().replace(day=1),
                used_count=used,
            )
        )
        await db.commit()


async def _bucket(world: dict) -> int:
    SessionLocal = world["sf"]
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(TenantQuotaUsage).where(
                    TenantQuotaUsage.tenant_id == world["tenant"].id,
                    TenantQuotaUsage.quota_type == QuotaType.monthly_executions,
                )
            )
        ).scalar_one_or_none()
        return row.used_count if row else 0


# ── CS-33/CS-34: license lifecycle via the platform API ─────────────────────


class TestLicenseLifecycleAPI:
    async def test_assign_change_remove_with_supersede_and_free_fallback(
        self, world
    ):
        """CS-33: assign → change (supersede, latest active wins, history
        retained) → remove (immediate free fallback); every step visible
        in the tenant list/detail WITHOUT any reload."""
        app, patches = _make_client(world, platform_admin=True)
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Unlicensed → free defaults visible (CS-34)
                listed = await client.get("/api/v1/platform/tenants")
                assert listed.status_code == 200
                row = next(
                    t for t in listed.json()["items"]
                    if t["id"] == str(world["tenant"].id)
                )
                assert row["license"] is None
                assert row["usage"]["tier"] == "free"
                assert row["usage"]["max_users"] == FREE_TIER_LIMITS.max_users

                # ASSIGN team license
                assigned = await client.put(
                    f"/api/v1/platform/tenants/{world['tenant'].id}/license",
                    json={
                        "tier": "team", "max_users": 25,
                        "max_agent_types": 15, "monthly_agent_executions": 1000,
                    },
                )
                assert assigned.status_code == 200, assigned.text
                assert assigned.json()["tier"] == "team"
                assert assigned.json()["max_users"] == 25

                # CHANGE → supersede
                changed = await client.put(
                    f"/api/v1/platform/tenants/{world['tenant'].id}/license",
                    json={
                        "tier": "enterprise", "max_users": 100,
                        "max_agent_types": 50, "monthly_agent_executions": 10000,
                    },
                )
                assert changed.status_code == 200
                assert changed.json()["tier"] == "enterprise"

                # History retained, latest active wins (E-15)
                SessionLocal = world["sf"]
                async with SessionLocal() as db:
                    rows = (
                        (
                            await db.execute(
                                select(TenantLicense).where(
                                    TenantLicense.tenant_id == world["tenant"].id
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    assert len(rows) == 2
                    actives = [r for r in rows if r.is_active]
                    assert len(actives) == 1
                    assert actives[0].tier == LicenseTier.enterprise
                    superseded = [r for r in rows if not r.is_active]
                    assert len(superseded) == 1
                    assert superseded[0].tier == LicenseTier.team
                    assert superseded[0].unassigned_at is not None

                # REMOVE → immediate free fallback
                removed = await client.delete(
                    f"/api/v1/platform/tenants/{world['tenant'].id}/license"
                )
                assert removed.status_code in (200, 204), removed.text

                listed2 = await client.get("/api/v1/platform/tenants")
                row2 = next(
                    t for t in listed2.json()["items"]
                    if t["id"] == str(world["tenant"].id)
                )
                assert row2["license"] is None
                assert row2["usage"]["tier"] == "free"
                assert row2["usage"]["max_users"] == FREE_TIER_LIMITS.max_users

                # REMOVE with no active license → 404
                again = await client.delete(
                    f"/api/v1/platform/tenants/{world['tenant'].id}/license"
                )
                assert again.status_code == 404
        finally:
            for p in patches:
                p.stop()

        # Audit events for all three actions
        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            events = (
                (
                    await db.execute(
                        select(TenantAuditEvent).where(
                            TenantAuditEvent.tenant_id == world["tenant"].id,
                            TenantAuditEvent.event_type.in_(
                                ["license_assigned", "license_changed",
                                 "license_removed"]
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert {e.event_type.value for e in events} == {
                "license_assigned", "license_changed", "license_removed",
            }

    async def test_invalid_license_input_rejected_with_clear_errors(self, world):
        """CS-33: unknown tier → 422 (schema enum); non-positive limits →
        422 (schema constraints); nothing written."""
        app, patches = _make_client(world, platform_admin=True)
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                bad_tier = await client.put(
                    f"/api/v1/platform/tenants/{world['tenant'].id}/license",
                    json={
                        "tier": "platinum", "max_users": 5,
                        "max_agent_types": 5, "monthly_agent_executions": 100,
                    },
                )
                assert bad_tier.status_code == 422

                bad_limits = await client.put(
                    f"/api/v1/platform/tenants/{world['tenant'].id}/license",
                    json={
                        "tier": "team", "max_users": 0,
                        "max_agent_types": -3, "monthly_agent_executions": 100,
                    },
                )
                assert bad_limits.status_code == 422
        finally:
            for p in patches:
                p.stop()

        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            rows = (
                (
                    await db.execute(
                        select(TenantLicense).where(
                            TenantLicense.tenant_id == world["tenant"].id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert rows == []  # no license row was written

    async def test_license_service_validation_direct(self, world):
        """Service-level validation: unknown tier / zero / negative /
        bool limits rejected before any write."""
        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            svc = get_tenant_licensing_service()
            for kwargs in (
                dict(tier="gold", max_users=5, max_agent_types=5,
                     monthly_agent_executions=100),
                dict(tier=LicenseTier.team, max_users=0, max_agent_types=5,
                     monthly_agent_executions=100),
                dict(tier=LicenseTier.team, max_users=5, max_agent_types=-1,
                     monthly_agent_executions=100),
                dict(tier=LicenseTier.team, max_users=5, max_agent_types=5,
                     monthly_agent_executions=True),  # bool is not a valid int
            ):
                with pytest.raises(TenantLicenseError):
                    await svc.assign_license(db, world["tenant"].id, **kwargs)
            await db.rollback()


# ── CS-35: user quota gate on invitations ───────────────────────────────────


class TestUserQuotaGate:
    async def test_invitation_blocked_over_user_quota_with_structured_payload(
        self, world, test_engine
    ):
        """CS-35: at max_users the invitation is refused with the full
        structured contract and NO invitation row is created; under the
        limit invitations continue to succeed."""
        await _enable_tenancy(test_engine)
        # Root membership exists → used = 1; license max_users = 1.
        await _assign_license(world, "free", users=1, types=5, execs=100)

        app, patches = _make_client(world)
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                blocked = await client.post(
                    "/api/v1/tenant/invitations",
                    json={"email": _unique("newbie@t.dev"), "tenant_role": "member"},
                )
                assert blocked.status_code == 403
                detail = blocked.json()["detail"]
                # The structured contract — rendered as-is by the UI.
                assert detail["code"] == "quota_exhausted"
                assert detail["quota_type"] == "users"
                assert detail["tier"] == "free"
                assert detail["limit"] == 1
                assert detail["used"] == 1
                assert "upgrade" in detail["upgrade_path"].lower()

                # Raise the license → invitations succeed again.
                await _assign_license(world, "team", users=25, types=15, execs=1000)
                allowed = await client.post(
                    "/api/v1/tenant/invitations",
                    json={"email": _unique("newbie@t.dev"), "tenant_role": "member"},
                )
                assert allowed.status_code == 201, allowed.text
        finally:
            for p in patches:
                p.stop()

        # Exactly ONE invitation row exists (the under-limit one).
        from app.db.models.tenant_invitation import TenantInvitation

        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            invites = (
                (
                    await db.execute(
                        select(TenantInvitation).where(
                            TenantInvitation.tenant_id == world["tenant"].id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(invites) == 1

    async def test_invitation_acceptance_blocked_over_quota(
        self, world, test_engine
    ):
        """CS-35: the member-CREATING acceptance path consults the users
        quota too — the invitee receives the structured 403 and no
        membership is created."""
        await _enable_tenancy(test_engine)
        await _assign_license(world, "free", users=1, types=5, execs=100)

        app, patches = _make_client(world)
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # max_users=1 with 1 existing member: creation is at the
                # limit → the invite itself would be blocked.  Lower the
                # acceptance scenario: invite while a 2-slot license is
                # active, then drop to 1 before acceptance.
                await _assign_license(world, "team", users=2, types=15, execs=1000)
                invite = await client.post(
                    "/api/v1/tenant/invitations",
                    json={"email": _unique("friend@t.dev"), "tenant_role": "member"},
                )
                assert invite.status_code == 201
                token = invite.json()["accept_token"]
            await _assign_license(world, "free", users=1, types=5, execs=100)
        finally:
            for p in patches:
                p.stop()

        # A platform user accepts → blocked (no member slot left).
        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            db.add(
                PlatformUser(
                    sub=_unique("invitee"), email=_unique("i@t.dev"),
                    display_name="Invitee",
                )
            )
            await db.commit()

        accept_app = create_app()
        # No permission overrides: acceptance is a PUBLIC path.

        async def accept_db():
            async with SessionLocal() as session:
                yield session
                await session.commit()

        accept_app.dependency_overrides[get_db] = accept_db

        async def bypass_jwt(self, request, call_next):
            request.state.identity = {"sub": world["root"].sub + "-invitee"}
            return await call_next(request)

        # The acceptor must resolve to the seeded invitee — use its sub.
        async with SessionLocal() as db:
            invitee_sub = (
                (
                    await db.execute(
                        select(PlatformUser).where(
                            PlatformUser.display_name == "Invitee"
                        )
                    )
                )
                .scalar_one()
                .sub
            )

        async def bypass_jwt_invitee(self, request, call_next):
            request.state.identity = {"sub": invitee_sub}
            return await call_next(request)

        with patch.object(JWTAuthMiddleware, "dispatch", bypass_jwt_invitee):
            async with AsyncClient(
                transport=ASGITransport(app=accept_app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/invitations/accept", json={"token": token}
                )
                assert response.status_code == 403
                detail = response.json()["detail"]
                assert detail["code"] == "quota_exhausted"
                assert detail["quota_type"] == "users"

        async with SessionLocal() as db:
            memberships = (
                (
                    await db.execute(
                        select(TenantUserMembership).where(
                            TenantUserMembership.tenant_id == world["tenant"].id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(memberships) == 1  # only the root; no new member


# ── CS-36: agent-type quota gate ────────────────────────────────────────────


async def _seed_binding_world(world: dict) -> dict:
    """AgentRole + Skill + role-skill binding for agent-type creation."""
    SessionLocal = world["sf"]
    async with SessionLocal() as db:
        role = AgentRole(name=_unique("agent-role"), tenant_id=world["tenant"].id)
        skill = Skill(name=_unique("skill"))
        db.add_all([role, skill])
        await db.flush()
        db.add(AgentRoleSkill(role_id=role.id, skill_id=skill.id))
        await db.commit()
        return {"role_id": str(role.id), "skill_id": str(skill.id)}


class TestAgentTypeQuotaGate:
    async def test_agent_type_creation_blocked_over_quota(self, world, test_engine):
        """CS-36: at max_agent_types the creation is refused with the
        structured contract and no agent type is created."""
        await _enable_tenancy(test_engine)
        SessionLocal = world["sf"]
        # Free tier: max 5 agent types — seed 5.
        async with SessionLocal() as db:
            for i in range(5):
                db.add(
                    AgentType(
                        name=_unique(f"seeded-type-{i}"),
                        tenant_id=world["tenant"].id,
                    )
                )
            await db.commit()

        bindings = await _seed_binding_world(world)
        app, patches = _make_client(world)
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                blocked = await client.post(
                    "/api/v1/agents/types",
                    json={
                        "name": _unique("over-quota-type"),
                        "role_id": bindings["role_id"],
                        "skill_bindings": [
                            {"skill_id": bindings["skill_id"], "order": 0}
                        ],
                    },
                )
                assert blocked.status_code == 403, blocked.text
                detail = blocked.json()["detail"]
                assert detail["code"] == "quota_exhausted"
                assert detail["quota_type"] == "agent_types"
                assert detail["tier"] == "free"
                assert detail["limit"] == 5
                assert detail["used"] == 5
        finally:
            for p in patches:
                p.stop()

        async with SessionLocal() as db:
            over = (
                await db.execute(
                    select(AgentType).where(
                        AgentType.name == _unique("over-quota-type")
                    )
                )
            ).scalar_one_or_none()
            assert over is None  # nothing created

    async def test_agent_type_creation_under_quota_succeeds(
        self, world, test_engine
    ):
        """CS-36: under-limit creation is unaffected."""
        await _enable_tenancy(test_engine)
        bindings = await _seed_binding_world(world)
        app, patches = _make_client(world)
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                created = await client.post(
                    "/api/v1/agents/types",
                    json={
                        "name": _unique("under-quota-type"),
                        "role_id": bindings["role_id"],
                        "skill_bindings": [
                            {"skill_id": bindings["skill_id"], "order": 0}
                        ],
                    },
                )
                assert created.status_code == 201, created.text
        finally:
            for p in patches:
                p.stop()


# ── CS-37/CS-39: execution quota gate & counting ────────────────────────────


class TestExecutionQuotaGate:
    async def test_execution_blocked_over_quota_never_dispatched(
        self, world, test_engine
    ):
        """CS-37: over the monthly limit the submission is refused with
        the structured contract, the counter is NOT incremented and the
        launch handler is never invoked (nothing reaches CH/AR)."""
        await _enable_tenancy(test_engine)
        await _exhaust_executions(world, used=100)  # free tier limit = 100

        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            agent_type = AgentType(
                name=_unique("blocked-exec-type"), tenant_id=world["tenant"].id
            )
            db.add(agent_type)
            await db.commit()
            type_id = agent_type.id

        app, patches = _make_client(world)
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                with patch(
                    "app.api.v1.agents._lifecycle_handler.launch", new=AsyncMock()
                ) as mock_launch:
                    blocked = await client.post(
                        "/api/v1/agents/sessions",
                        json={
                            "agent_type_id": str(type_id),
                            "input_data": {"prompt": "hello"},
                        },
                    )
                    assert blocked.status_code == 403, blocked.text
                    detail = blocked.json()["detail"]
                    assert detail["code"] == "quota_exhausted"
                    assert detail["quota_type"] == "monthly_executions"
                    assert detail["tier"] == "free"
                    assert detail["limit"] == 100
                    assert detail["used"] == 100
                    mock_launch.assert_not_called()  # never dispatched
        finally:
            for p in patches:
                p.stop()

        assert await _bucket(world) == 100  # counter untouched by refusals

    async def test_execution_under_quota_counts_exactly_once(
        self, world, test_engine
    ):
        """CS-39: within quota the submission is accepted and the counter
        increments EXACTLY once per submission, before any dispatch;
        completion/failure never refunds."""
        await _enable_tenancy(test_engine)
        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            agent_type = AgentType(
                name=_unique("counting-exec-type"), tenant_id=world["tenant"].id
            )
            db.add(agent_type)
            await db.flush()
            job = __import__(
                "app.db.models.agents", fromlist=["AgentJob"]
            ).AgentJob(agent_type_id=agent_type.id)
            db.add(job)
            await db.commit()
            type_id, job_id = agent_type.id, job.id

        app, patches = _make_client(world)
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                with (
                    patch(
                        "app.api.v1.agents.get_recursion_validation_service"
                    ) as mock_recursion,
                    patch(
                        "app.api.v1.agents._lifecycle_handler.launch",
                        new=AsyncMock(return_value={"session_id": str(job_id)}),
                    ),
                ):
                    mock_recursion.return_value.validate_agent_type = AsyncMock()
                    first = await client.post(
                        "/api/v1/agents/sessions",
                        json={
                            "agent_type_id": str(type_id),
                            "input_data": {"prompt": "one"},
                        },
                    )
                    assert first.status_code == 202, first.text
                    second = await client.post(
                        "/api/v1/agents/sessions",
                        json={
                            "agent_type_id": str(type_id),
                            "input_data": {"prompt": "two"},
                        },
                    )
                    assert second.status_code == 202, second.text
        finally:
            for p in patches:
                p.stop()

        assert await _bucket(world) == 2  # exactly once per submission

    async def test_switch_off_execution_gate_inert(self, world, test_engine):
        """With the switch off the gate cannot fire — no quota error even
        with the counter far over the free-tier limit."""
        # NOTE: tenancy NOT enabled.
        await _exhaust_executions(world, used=999)
        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            agent_type = AgentType(
                name=_unique("off-switch-type"), tenant_id=world["tenant"].id
            )
            db.add(agent_type)
            await db.commit()
            type_id = agent_type.id

        app, patches = _make_client(world)
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # The gate is inert, so the request proceeds PAST the
                # quota check — it may fail later on execution plumbing
                # (500 from the sqlite test env), but NEVER with 403
                # quota_exhausted.
                response = await client.post(
                    "/api/v1/agents/sessions",
                    json={
                        "agent_type_id": str(type_id),
                        "input_data": {"prompt": "hi"},
                    },
                )
                assert not (
                    response.status_code == 403
                    and isinstance(response.json().get("detail"), dict)
                    and response.json()["detail"].get("code") == "quota_exhausted"
                ), response.text
        finally:
            for p in patches:
                p.stop()


# ── CS-38: quota independence ───────────────────────────────────────────────


class TestQuotaIndependence:
    async def test_exhausted_quotas_do_not_block_unrelated_actions(
        self, world, test_engine
    ):
        """CS-38: users + executions exhausted → agent-types check still
        allowed; and each gate raises only for its own quota type."""
        await _enable_tenancy(test_engine)
        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            # users exhausted (max_users = 1, root member = 1)
            await get_tenant_licensing_service().assign_license(
                db, world["tenant"].id,
                tier=LicenseTier.free, max_users=1, max_agent_types=5,
                monthly_agent_executions=100,
            )
            await db.commit()

        svc = get_tenant_quota_service()
        async with SessionLocal() as db:
            users_check = await svc.check_users(db, world["tenant"].id)
            assert users_check.allowed is False
            agent_types_check = await svc.check_agent_types(
                db, world["tenant"].id
            )
            assert agent_types_check.allowed is True  # unrelated, unaffected

        await _exhaust_executions(world, used=100)
        async with SessionLocal() as db:
            executions_check = await svc.check_executions(
                db, world["tenant"].id
            )
            assert executions_check.allowed is False
            # …and the agent-types quota STILL passes with both others out.
            assert (await svc.check_agent_types(db, world["tenant"].id)).allowed
            # Each refusal names its own quota type.
            assert users_check.payload.quota_type == "users"
            assert executions_check.payload.quota_type == "monthly_executions"


# ── CS-39/E-17: counter semantics ───────────────────────────────────────────


class TestCounterSemantics:
    async def test_calendar_month_reset(self, world, test_engine):
        """CS-39: a new calendar month starts a fresh bucket — usage
        resets to 0, submissions are accepted again, the old bucket is
        retained as history."""
        await _enable_tenancy(test_engine)
        await _exhaust_executions(world, used=100)
        svc = get_tenant_quota_service()
        SessionLocal = world["sf"]

        async with SessionLocal() as db:
            check = await svc.check_executions(db, world["tenant"].id)
            assert check.allowed is False

            # Age the bucket into LAST month → the current bucket is gone.
            bucket = (
                (
                    await db.execute(
                        select(TenantQuotaUsage).where(
                            TenantQuotaUsage.tenant_id == world["tenant"].id
                        )
                    )
                )
                .scalars()
                .first()
            )
            bucket.period_start = datetime(2020, 1, 1)
            await db.commit()

        async with SessionLocal() as db:
            reset = await svc.check_executions(db, world["tenant"].id)
            assert reset.allowed is True
            assert await svc.get_monthly_executions(db, world["tenant"].id) == 0
            # A new increment starts a fresh bucket…
            assert await svc.increment_executions(db, world["tenant"].id) == 1
            buckets = (
                (
                    await db.execute(
                        select(TenantQuotaUsage).where(
                            TenantQuotaUsage.tenant_id == world["tenant"].id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(buckets) == 2  # old history retained
            await db.rollback()

    async def test_counter_is_authoritative_and_drift_visible(
        self, world, test_engine
    ):
        """E-17: enforcement uses the maintained counter — if it drifts
        from the actual execution records, enforcement and the usage view
        both follow (and thus expose) the counter; users/agent-types are
        derived live and can never drift."""
        await _enable_tenancy(test_engine)
        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            db.add(
                TenantQuotaUsage(
                    tenant_id=world["tenant"].id,
                    quota_type=QuotaType.monthly_executions,
                    period_start=datetime.now(timezone.utc).date().replace(day=1),
                    used_count=999,  # drifted far above any real record
                )
            )
            await db.commit()

        svc = get_tenant_quota_service()
        async with SessionLocal() as db:
            check = await svc.check_executions(db, world["tenant"].id)
            assert check.allowed is False  # enforcement follows the counter
            usage = await svc.get_usage(db, world["tenant"].id)
            assert usage["executions_this_month"] == 999  # drift visible
            # Derived quotas reflect the records exactly (no drift).
            assert usage["users"] == 1
            assert usage["agent_types"] == 0

    async def test_ensure_raises_structured_error(self, world, test_engine):
        """The gates raise the shared contract error with the structured
        payload; inert (no raise) with the switch off."""
        await _enable_tenancy(test_engine)
        await _exhaust_executions(world, used=100)
        svc = get_tenant_quota_service()
        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            with pytest.raises(QuotaExceededError) as exc:
                await svc.ensure_executions(db, world["tenant"].id)
            payload = exc.value.payload
            assert payload.code == "quota_exhausted"
            assert payload.quota_type == "monthly_executions"
            assert payload.limit == 100
            assert payload.used == 100
            assert payload.upgrade_path

        # Switch off → inert.
        import app.services.tenancy.platform_settings_service as settings_module
        from app.db.models.platform_setting import PlatformSetting

        async with SessionLocal() as db:
            await db.execute(
                PlatformSetting.__table__.delete().where(
                    PlatformSetting.key == "multi_tenancy_enabled"
                )
            )
            await db.commit()
        settings_module._service = None
        async with SessionLocal() as db:
            await svc.ensure_executions(db, world["tenant"].id)  # no raise
            await svc.ensure_users(db, world["tenant"].id)  # no raise

    async def test_quota_exhausted_audit_recorded(self, world, test_engine):
        """CS-41 (service level): refusals can be audited as
        ``quota_exhausted`` with the full payload (the scheduler path)."""
        await _enable_tenancy(test_engine)
        await _exhaust_executions(world, used=100)
        svc = get_tenant_quota_service()
        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            check = await svc.check_executions(db, world["tenant"].id)
            await svc.record_quota_exhausted(
                db, world["tenant"].id, check.payload,
                target_resource="scheduled_job:test",
            )
            await db.commit()
        async with SessionLocal() as db:
            events = (
                (
                    await db.execute(
                        select(TenantAuditEvent).where(
                            TenantAuditEvent.event_type == "quota_exhausted",
                            TenantAuditEvent.tenant_id == world["tenant"].id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(events) == 1
            assert events[0].detail["quota_type"] == "monthly_executions"


# ── CS-34/CS-43: tenant-side usage API + permissions ────────────────────────


class TestUsageAPI:
    async def test_usage_endpoint_free_defaults_and_license_reflection(
        self, world, test_engine
    ):
        """CS-34: unlicensed → free defaults for the tenant user too;
        a license change is reflected on the next read (no reload)."""
        await _enable_tenancy(test_engine)
        app, patches = _make_client(world)
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                free = await client.get("/api/v1/tenant/usage")
                assert free.status_code == 200
                body = free.json()
                assert body["tier"] == "free"
                assert body["max_users"] == 10
                assert body["max_agent_types"] == 5
                assert body["monthly_agent_executions"] == 100
                assert body["users"] == 1  # the root membership, live
                assert body["agent_types"] == 0
                assert body["executions_this_month"] == 0

                await _assign_license(world, "enterprise", users=100,
                                      types=50, execs=10000)
                upgraded = await client.get("/api/v1/tenant/usage")
                assert upgraded.status_code == 200
                assert upgraded.json()["tier"] == "enterprise"
                assert upgraded.json()["max_users"] == 100
        finally:
            for p in patches:
                p.stop()

    async def test_usage_endpoint_requires_membership_and_permission(
        self, world, test_engine
    ):
        """CS-43: without tenant::settings read (or a membership) the
        usage read is rejected (fail-closed)."""
        await _enable_tenancy(test_engine)
        app, patches = _make_client(world)
        # REMOVE the settings-read override → the real permission engine
        # runs (no grants for this user beyond the membership path).
        del app.dependency_overrides[require_permission(RT_TENANT_SETTINGS, "read")]
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # NOTE: the root membership grants all tenant permissions,
                # so this exercises the DB-side membership grants path —
                # a root still reads; strip the membership instead:
                pass
            # Strip the membership: no membership → fail-closed 403.
            SessionLocal = world["sf"]
            async with SessionLocal() as db:
                memberships = (
                    (
                        await db.execute(
                            select(TenantUserMembership).where(
                                TenantUserMembership.tenant_id
                                == world["tenant"].id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for m in memberships:
                    await db.delete(m)
                await db.commit()

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                denied = await client.get("/api/v1/tenant/usage")
                assert denied.status_code == 403
        finally:
            for p in patches:
                p.stop()

    async def test_platform_license_api_rejects_non_platform_admins(
        self, world, test_engine
    ):
        """CS-43: a tenant admin (no platform::tenants rights) calling
        the license API is rejected — only the platform admin assigns,
        changes or removes licenses."""
        await _enable_tenancy(test_engine)
        app, patches = _make_client(world, platform_admin=False)
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                put = await client.put(
                    f"/api/v1/platform/tenants/{world['tenant'].id}/license",
                    json={
                        "tier": "team", "max_users": 25,
                        "max_agent_types": 15, "monthly_agent_executions": 1000,
                    },
                )
                assert put.status_code == 403
                delete = await client.delete(
                    f"/api/v1/platform/tenants/{world['tenant'].id}/license"
                )
                assert delete.status_code == 403
        finally:
            for p in patches:
                p.stop()

        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            rows = (
                (
                    await db.execute(
                        select(TenantLicense).where(
                            TenantLicense.tenant_id == world["tenant"].id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert rows == []  # no license was written by the impostor


# ── E-20: tenant deletion with license/quota rows ───────────────────────────


class TestTenantDeletionWithLicenseRows:
    async def test_deletion_removes_license_and_quota_rows_recreate_free(
        self, world, test_engine
    ):
        """E-20: deleting a licensed tenant with quota usage removes the
        license and quota rows (no orphans leaking into aggregates); a
        tenant recreated on the same address starts on the free tier with
        fresh buckets."""
        await _enable_tenancy(test_engine)
        tenant = world["tenant"]
        await _assign_license(world, "team", users=25, types=15, execs=1000)
        await _exhaust_executions(world, used=42)

        app, patches = _make_client(world, platform_admin=True)
        for p in patches:
            p.start()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                deleted = await client.delete(
                    f"/api/v1/platform/tenants/{tenant.id}",
                    params={"confirm_slug": tenant.slug},
                )
                assert deleted.status_code in (200, 204), deleted.text
        finally:
            for p in patches:
                p.stop()

        SessionLocal = world["sf"]
        async with SessionLocal() as db:
            licenses = (
                (
                    await db.execute(
                        select(TenantLicense).where(
                            TenantLicense.tenant_id == tenant.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert licenses == []  # fully removed, no orphans
            quotas = (
                (
                    await db.execute(
                        select(TenantQuotaUsage).where(
                            TenantQuotaUsage.tenant_id == tenant.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert quotas == []

        # Recreate the same address → free tier, fresh (empty) buckets.
        async with SessionLocal() as db:
            reborn = Tenant(name=tenant.name, slug=tenant.slug)
            db.add(reborn)
            await db.commit()
            svc = get_tenant_quota_service()
            usage = await svc.get_usage(db, reborn.id)
            assert usage["tier"] == "free"
            assert usage["executions_this_month"] == 0
