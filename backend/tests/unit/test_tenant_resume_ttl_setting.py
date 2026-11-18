"""Per-tenant conversation turn resume TTL (answerable window).

Covers Task A of the ``resumable-agent-turn-persistence`` follow-up:

- ``resolve_resume_ttl_seconds`` — platform default (900s), tenant override,
  clamping (minimum 30s), malformed stored values, and the no-tenant case;
- ``set_resume_ttl_seconds`` — persist + clamp;
- ``resolve_resume_expiry`` — ``now + resolved window``;
- Control Center is the authority for a paused turn's ``expires_at``:
  * ``InterveneRequestStore.create_request`` (the pause path) uses the tenant
    value, not the intervention timeout;
  * the internal ``PUT /conversations/{id}/resume`` relay ignores a
    client-supplied ``expires_at`` and applies tenant policy instead;
- the tenant settings API round-trip (``GET`` / ``PATCH /tenant/settings``).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import (
    require_internal_tenant_context,
    require_permission,
    require_service_certificate,
)
from app.api.v1.tenant import require_tenant_manager, require_tenant_membership
from app.core.resource_types import RT_TENANT_SETTINGS
from app.core.tenant_context import TenantContext, set_tenant_context
from app.db.models.agents import AgentInputType, AgentOutputType, AgentType
from app.db.models.conversations import ConversationSession, ConversationStatus
from app.db.models.intervene import InterventionType
from app.db.models.tenant import Tenant, TenantRole
from app.db.models.tenant_membership import TenantUserMembership
from app.db.session import get_db
from app.main import create_app
from app.middleware.auth import JWTAuthMiddleware
from app.middleware.tenant_resolution import TenantResolutionMiddleware
from app.services.agents.intervene_service import InterveneRequestStore
from app.services.conversations.turn_resume_settings import (
    MIN_RESUME_TTL_SECONDS,
    RESUME_TTL_SETTING_KEY,
    platform_resume_ttl_seconds,
    resolve_resume_expiry,
    resolve_resume_ttl_seconds,
    set_resume_ttl_seconds,
)
from app.services.tenancy.tenant_settings_service import set_value

RESUME_URL = "/api/v1/internal/data/conversations/{sid}/resume"


def _ts() -> str:
    return uuid.uuid4().hex[:8]


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on round-trip; compare in UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def _make_tenant(db: AsyncSession) -> Tenant:
    tenant = Tenant(name=f"TTL-{_ts()}", slug=f"ttl-{_ts()}")
    db.add(tenant)
    await db.flush()
    return tenant


class TestResolveResumeTtl:
    @pytest.mark.asyncio
    async def test_default_is_platform_setting(self, db_session: AsyncSession):
        tenant = await _make_tenant(db_session)
        assert await resolve_resume_ttl_seconds(db_session, tenant.id) == 900
        # The platform default constant agrees with the resolver.
        assert platform_resume_ttl_seconds() == 900

    @pytest.mark.asyncio
    async def test_unset_tenant_falls_back_to_default(self, db_session: AsyncSession):
        tenant = await _make_tenant(db_session)
        # Explicitly absent key must not be treated as "0 seconds".
        assert (
            await resolve_resume_ttl_seconds(db_session, tenant.id)
            == platform_resume_ttl_seconds()
        )

    @pytest.mark.asyncio
    async def test_tenant_override_is_respected(self, db_session: AsyncSession):
        tenant = await _make_tenant(db_session)
        await set_value(db_session, tenant.id, RESUME_TTL_SETTING_KEY, 3600)
        assert await resolve_resume_ttl_seconds(db_session, tenant.id) == 3600

    @pytest.mark.asyncio
    async def test_below_minimum_is_clamped(self, db_session: AsyncSession):
        tenant = await _make_tenant(db_session)
        await set_value(db_session, tenant.id, RESUME_TTL_SETTING_KEY, 5)
        assert (
            await resolve_resume_ttl_seconds(db_session, tenant.id)
            == MIN_RESUME_TTL_SECONDS
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stored", ["not-a-number", True, None, "", {}])
    async def test_malformed_value_falls_back_to_default(
        self, db_session: AsyncSession, stored
    ):
        tenant = await _make_tenant(db_session)
        await set_value(db_session, tenant.id, RESUME_TTL_SETTING_KEY, stored)
        assert (
            await resolve_resume_ttl_seconds(db_session, tenant.id)
            == platform_resume_ttl_seconds()
        )

    @pytest.mark.asyncio
    async def test_numeric_string_is_coerced(self, db_session: AsyncSession):
        tenant = await _make_tenant(db_session)
        await set_value(db_session, tenant.id, RESUME_TTL_SETTING_KEY, "1800")
        assert await resolve_resume_ttl_seconds(db_session, tenant.id) == 1800

    @pytest.mark.asyncio
    async def test_no_tenant_resolves_to_platform_default(
        self, db_session: AsyncSession
    ):
        assert (
            await resolve_resume_ttl_seconds(db_session, None)
            == platform_resume_ttl_seconds()
        )

    @pytest.mark.asyncio
    async def test_two_tenants_do_not_share_the_override(
        self, db_session: AsyncSession
    ):
        tenant_a = await _make_tenant(db_session)
        tenant_b = await _make_tenant(db_session)
        await set_value(db_session, tenant_a.id, RESUME_TTL_SETTING_KEY, 3600)
        assert await resolve_resume_ttl_seconds(db_session, tenant_a.id) == 3600
        assert await resolve_resume_ttl_seconds(db_session, tenant_b.id) == 900

    @pytest.mark.asyncio
    async def test_setter_clamps(self, db_session: AsyncSession):
        tenant = await _make_tenant(db_session)
        assert await set_resume_ttl_seconds(db_session, tenant.id, 10) == 30
        assert await resolve_resume_ttl_seconds(db_session, tenant.id) == 30

    @pytest.mark.asyncio
    async def test_expiry_is_now_plus_ttl(self, db_session: AsyncSession):
        tenant = await _make_tenant(db_session)
        await set_value(db_session, tenant.id, RESUME_TTL_SETTING_KEY, 3600)
        now = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)
        expiry = await resolve_resume_expiry(
            db_session, tenant_id=tenant.id, now=now
        )
        assert expiry == now + timedelta(seconds=3600)


class TestPauseExpiryUsesTenantPolicy:
    @pytest.mark.asyncio
    async def test_create_request_uses_tenant_ttl(self, db_session: AsyncSession):
        tenant = await _make_tenant(db_session)
        await set_value(db_session, tenant.id, RESUME_TTL_SETTING_KEY, 3600)
        conv = ConversationSession(
            tenant_id=tenant.id, status=ConversationStatus.active
        )
        agent_type = AgentType(
            name=f"ttl-agent-{_ts()}",
            input_type=AgentInputType.conversation,
            output_type=AgentOutputType.auto,
        )
        db_session.add_all([conv, agent_type])
        await db_session.flush()

        request = await InterveneRequestStore().create_request(
            db_session,
            agent_session_id=None,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.approval,
            reason="create skill",
            conversation_session_id=conv.id,
        )

        from app.services.conversations.turn_resume_store import (
            ConversationTurnResumeStore,
        )

        record = await ConversationTurnResumeStore().get_for_intervention(
            request.id, db_session
        )
        assert record is not None
        assert record.expires_at is not None
        expected = datetime.now(timezone.utc) + timedelta(seconds=3600)
        assert abs((_as_utc(record.expires_at) - expected).total_seconds()) < 30

    @pytest.mark.asyncio
    async def test_create_request_defaults_to_platform_ttl(
        self, db_session: AsyncSession
    ):
        tenant = await _make_tenant(db_session)
        conv = ConversationSession(
            tenant_id=tenant.id, status=ConversationStatus.active
        )
        agent_type = AgentType(
            name=f"ttl-agent-{_ts()}",
            input_type=AgentInputType.conversation,
            output_type=AgentOutputType.auto,
        )
        db_session.add_all([conv, agent_type])
        await db_session.flush()

        request = await InterveneRequestStore().create_request(
            db_session,
            agent_session_id=None,
            agent_type_id=agent_type.id,
            intervention_type=InterventionType.approval,
            reason="create skill",
            conversation_session_id=conv.id,
        )

        from app.services.conversations.turn_resume_store import (
            ConversationTurnResumeStore,
        )

        record = await ConversationTurnResumeStore().get_for_intervention(
            request.id, db_session
        )
        assert record is not None and record.expires_at is not None
        expected = datetime.now(timezone.utc) + timedelta(seconds=900)
        assert abs((_as_utc(record.expires_at) - expected).total_seconds()) < 30


@pytest_asyncio.fixture
async def resume_relay_client(db_session: AsyncSession):
    """The internal resume relay with security bypassed."""
    app = FastAPI()
    from app.api.v1.internal.session_data import InternalSessionDataRouter

    app.include_router(InternalSessionDataRouter, prefix="/api/v1")

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_service_certificate] = lambda: None

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield app, client


class TestResumeRelayIgnoresClientExpiry:
    @pytest.mark.asyncio
    async def test_put_resume_overrides_client_supplied_expiry(
        self, db_session: AsyncSession, resume_relay_client
    ):
        app, client = resume_relay_client
        tenant = await _make_tenant(db_session)
        await set_value(db_session, tenant.id, RESUME_TTL_SETTING_KEY, 3600)
        conv = ConversationSession(
            tenant_id=tenant.id, status=ConversationStatus.active
        )
        db_session.add(conv)
        await db_session.flush()
        app.dependency_overrides[require_internal_tenant_context] = lambda: (
            TenantContext(tenant_id=tenant.id, slug=tenant.slug, name=tenant.name)
        )

        client_supplied = (
            datetime.now(timezone.utc) + timedelta(seconds=60)
        ).isoformat()
        response = await client.put(
            RESUME_URL.format(sid=conv.id),
            json={"expires_at": client_supplied},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["expires_at"] is not None
        expiry = datetime.fromisoformat(body["expires_at"])
        if expiry.tzinfo is None:  # sqlite round-trip loses tzinfo
            expiry = expiry.replace(tzinfo=timezone.utc)
        expected = datetime.now(timezone.utc) + timedelta(seconds=3600)
        assert abs((expiry - expected).total_seconds()) < 30
        # The client's 60-second window was NOT applied.
        assert expiry > datetime.now(timezone.utc) + timedelta(seconds=120)

    @pytest.mark.asyncio
    async def test_checkpoint_lives_for_the_resume_window(
        self, db_session: AsyncSession, resume_relay_client
    ):
        """The saved pause state must not be purged before the answer window."""
        app, client = resume_relay_client
        tenant = await _make_tenant(db_session)
        await set_value(db_session, tenant.id, RESUME_TTL_SETTING_KEY, 3600)
        conv = ConversationSession(
            tenant_id=tenant.id, status=ConversationStatus.active
        )
        db_session.add(conv)
        await db_session.flush()
        app.dependency_overrides[require_internal_tenant_context] = lambda: (
            TenantContext(tenant_id=tenant.id, slug=tenant.slug, name=tenant.name)
        )

        assert (
            await client.put(RESUME_URL.format(sid=conv.id), json={})
        ).status_code == 200
        response = await client.put(
            f"/api/v1/internal/data/conversations/{conv.id}/resume/checkpoint",
            json={
                "payload": {"messages": []},
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=60)
                ).isoformat(),
            },
        )
        assert response.status_code == 200
        expiry = datetime.fromisoformat(response.json()["expires_at"])
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        expected = datetime.now(timezone.utc) + timedelta(seconds=3600)
        assert abs((expiry - expected).total_seconds()) < 30


# ── Tenant settings API round-trip ──────────────────────────────────────────


@pytest_asyncio.fixture
async def tenant_settings_client(test_engine):
    """Tenant settings API app bound to a seeded tenant."""
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as db:
        tenant = Tenant(name=f"TTL-API-{_ts()}", slug=f"ttl-api-{_ts()}")
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)

    membership = TenantUserMembership(
        tenant_id=tenant.id,
        user_id=uuid.uuid4(),
        tenant_role=TenantRole.tenant_admin,
        is_root=True,
    )
    context = TenantContext(tenant_id=tenant.id, slug=tenant.slug, name=tenant.name)

    app = create_app()

    def _allow():
        return {"sub": "ttl-api-tester"}

    for action in ("read", "manage"):
        app.dependency_overrides[
            require_permission(RT_TENANT_SETTINGS, action)
        ] = _allow
    app.dependency_overrides[require_tenant_membership] = lambda: membership
    app.dependency_overrides[require_tenant_manager] = lambda: membership

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    async def bypass_jwt(self, request, call_next):
        request.state.identity = {"sub": "ttl-api-tester"}
        return await call_next(request)

    async def bind_tenant(self, request, call_next):
        set_tenant_context(request, context)
        return await call_next(request)

    with patch.object(JWTAuthMiddleware, "dispatch", bypass_jwt), patch.object(
        TenantResolutionMiddleware, "dispatch", bind_tenant
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, tenant.id, SessionLocal


class TestTenantSettingsApi:
    @pytest.mark.asyncio
    async def test_get_returns_default_when_unset(self, tenant_settings_client):
        client, _tenant_id, _session_factory = tenant_settings_client
        response = await client.get("/api/v1/tenant/settings")
        assert response.status_code == 200
        assert response.json()["conversation_turn_resume_ttl_seconds"] == 900

    @pytest.mark.asyncio
    async def test_patch_round_trip(self, tenant_settings_client):
        client, tenant_id, session_factory = tenant_settings_client
        patched = await client.patch(
            "/api/v1/tenant/settings",
            json={"conversation_turn_resume_ttl_seconds": 3600},
        )
        assert patched.status_code == 200
        assert patched.json()["conversation_turn_resume_ttl_seconds"] == 3600

        fetched = await client.get("/api/v1/tenant/settings")
        assert fetched.status_code == 200
        assert fetched.json()["conversation_turn_resume_ttl_seconds"] == 3600

        # The persisted row drives the pause resolver.
        async with session_factory() as session:
            assert await resolve_resume_ttl_seconds(session, tenant_id) == 3600

    @pytest.mark.asyncio
    async def test_patch_below_minimum_is_rejected(self, tenant_settings_client):
        client, _tenant_id, _session_factory = tenant_settings_client
        response = await client.patch(
            "/api/v1/tenant/settings",
            json={"conversation_turn_resume_ttl_seconds": 10},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_patch_other_fields_keeps_ttl(self, tenant_settings_client):
        client, _tenant_id, _session_factory = tenant_settings_client
        await client.patch(
            "/api/v1/tenant/settings",
            json={"conversation_turn_resume_ttl_seconds": 1800},
        )
        renamed = await client.patch(
            "/api/v1/tenant/settings",
            json={"admin_contact_name": "Ops"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["conversation_turn_resume_ttl_seconds"] == 1800
        assert renamed.json()["admin_contact_name"] == "Ops"
