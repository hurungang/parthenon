"""FIX-20260930-075014 — JIT default tenant role on first OIDC sign-in.

Identity-model refinement pinned here:

- ``IdentityProviderConfig.default_tenant_role`` — nullable, one of the four
  seeded preset keys (tenant_system_admin / agent_manager / agent_executor /
  agent_viewer).
- On an OIDC sign-in with a RESOLVED tenant context (multi-tenancy ON), the
  provider that validated the token (own / shared / SYSTEM-slot fallback)
  MAY carry a default role.  When the user has NO active membership in that
  tenant, JIT provisions: active ``TenantUserMembership`` (member,
  not root) + the tenant's preset ``Role`` via ``UserRole`` — idempotent.
- Unset default → NO JIT → the existing ``no_access_to_workspace`` 403 path
  (unchanged).
- Platform-password logins NEVER JIT (only OIDC-linked identities via a
  provider with a default set).
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.resource_types import RT_AGENT_MANAGEMENT  # noqa: E402
from app.core.tenant_context import TenantContext, set_tenant_context  # noqa: E402
from app.db.models.identity import Role  # noqa: E402
from app.db.models.identity_provider_config import IdentityProviderConfig  # noqa: E402
from app.db.models.platform_user import PlatformUser  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_audit_event import (  # noqa: E402
    TenantAuditEvent,
    TenantAuditEventType,
)
from app.db.models.tenant_membership import TenantUserMembership  # noqa: E402
from app.db.models.user_role import UserRole  # noqa: E402
from app.db.session import Base, get_db  # noqa: E402
from app.db.tenant_scoping import (  # noqa: E402
    apply_tenant_scope,
    flush_scope_miss_audits,
    register_tenant_scope_listener,
)
from app.main import create_app  # noqa: E402
from app.middleware.auth import JWTAuthMiddleware  # noqa: E402
from app.services.oidc_provider_registry import OIDCProviderRegistry  # noqa: E402
from app.services.tenancy.default_tenant_roles import (  # noqa: E402
    AGENT_VIEWER_ROLE_NAME,
    seed_default_tenant_roles,
)

TAG = uuid.uuid4().hex[:8]

SYSTEM_TENANT_ID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")
TENANT_X_ID = uuid.UUID("eeeeeeee-0000-0000-0000-000000000002")

CTX_X = TenantContext(tenant_id=TENANT_X_ID, slug=f"tenant-x-{TAG}", name="Tenant X")

SUB_NEW = f"oidc-newbie-{TAG}"


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
async def seeded_engine():
    """System tenant + tenant X (default roles seeded for X); tenancy ON."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    register_tenant_scope_listener()
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        system = Tenant(name="System", slug=f"system-{TAG}", is_system_tenant=True)
        system.id = SYSTEM_TENANT_ID
        tenant_x = Tenant(name="Tenant X", slug=f"tenant-x-{TAG}")
        tenant_x.id = TENANT_X_ID
        db.add_all([system, tenant_x])
        await db.flush()
        await seed_default_tenant_roles(db, TENANT_X_ID)
        await _set_tenancy(db, True)
        await db.commit()
    yield engine
    await engine.dispose()


def _provider_row(scope, tenant_id, issuer, default_role=None):
    return IdentityProviderConfig(
        provider_scope=scope,
        provider_type="keycloak",
        display_name=f"{scope}-{tenant_id or 'shared'}",
        issuer_url=issuer,
        client_id=f"client-{scope}",
        encrypted_client_secret=None,
        is_enabled=True,
        tenant_id=tenant_id,
        default_tenant_role=default_role,
    )


class _FakeRegistry:
    """Registry stub mirroring the real resolution order (own → shared →
    system slot)."""

    def __init__(self, providers: dict, root_tenant_id: uuid.UUID | None = None):
        self._providers = providers
        self._root_tenant_id = str(root_tenant_id) if root_tenant_id else None
        self.initialized = True
        self._multi_tenancy_enabled = True

    def get_provider(self, scope, tenant_id=None, is_system_tenant=False):
        tenant_key = str(tenant_id) if tenant_id else None
        entry = self._providers.get((tenant_key, scope))
        if entry is None and tenant_key is not None:
            entry = self._providers.get((None, scope))
        if (
            entry is None
            and self._root_tenant_id
            and self._root_tenant_id != tenant_key
        ):
            entry = self._providers.get((self._root_tenant_id, scope))
        if entry is None:
            return None
        return SimpleNamespace(
            issuer_url=entry[0],
            client_id=entry[1],
            claim_mappings={},
            default_tenant_role=entry[2] if len(entry) > 2 else None,
        )

    def get_decrypted_secret(self, scope, tenant_id=None, is_system_tenant=False):
        return None


def _fake_request(ctx):
    request = SimpleNamespace()
    request.state = SimpleNamespace()
    request.state.tenant_context = ctx
    # Phase 11: a resolved context is tenancy-ON in these tests.
    request.state.tenancy_enabled = ctx is not None
    request.url = SimpleNamespace(path="/api/v1/dashboard/summary")
    request.method = "GET"
    request.client = SimpleNamespace(host="10.0.0.9")
    return request


async def _sign_in(engine, claims, ctx, providers):
    """Run the middleware's user-sync path the way a validated OIDC token
    would trigger it (registry + AsyncSessionLocal patched to the test DB)."""
    import app.db.session as db_session_module
    import app.main as main_module

    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    mw = JWTAuthMiddleware(app=None)
    with patch.object(main_module, "_get_registry", lambda: _FakeRegistry(providers, SYSTEM_TENANT_ID)), \
            patch.object(db_session_module, "AsyncSessionLocal", SessionLocal):
        await mw._sync_user_and_groups(_fake_request(ctx), dict(claims))


class TestJitDefaultTenantRole:
    async def test_d_first_sign_in_grants_membership_and_viewer_role(
        self, seeded_engine
    ):
        """(d) first OIDC sign-in to tenant X with provider default
        agent_viewer → active membership + 'Agent Viewer' role granted;
        dashboard-level authorize passes."""
        providers = {(str(TENANT_X_ID), "user"): ("https://x.example.com", "c", "agent_viewer")}
        await _sign_in(
            seeded_engine,
            {"sub": SUB_NEW, "email": f"{SUB_NEW}@example.test", "_provider_scope": "user"},
            CTX_X,
            providers,
        )

        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            user = (
                await db.execute(select(PlatformUser).where(PlatformUser.sub == SUB_NEW))
            ).scalar_one()
            membership = (
                await db.execute(
                    select(TenantUserMembership).where(
                        TenantUserMembership.tenant_id == TENANT_X_ID,
                        TenantUserMembership.user_id == user.id,
                    )
                )
            ).scalar_one()
            assert membership.status.value == "active"
            assert membership.is_root is False
            role = (
                await db.execute(
                    select(Role).where(
                        Role.tenant_id == TENANT_X_ID,
                        Role.name == AGENT_VIEWER_ROLE_NAME,
                    )
                )
            ).scalar_one()
            assignment = (
                await db.execute(
                    select(UserRole).where(
                        UserRole.user_id == user.id, UserRole.role_id == role.id
                    )
                )
            ).scalar_one()
            assert assignment is not None

        # dashboard-level authorize passes for the JIT viewer
        SessionLocal2 = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal2() as session:
            register_tenant_scope_listener()
            apply_tenant_scope(session, TENANT_X_ID)
            from app.api.deps import authorize_identity

            claims = await authorize_identity(
                session,
                {"sub": SUB_NEW, "tenant": CTX_X.slug},
                RT_AGENT_MANAGEMENT,
                "read",
                tenant_id=TENANT_X_ID,
            )
            assert claims["sub"] == SUB_NEW

    async def test_e_second_sign_in_is_idempotent(self, seeded_engine):
        """(e) second sign-in → no duplicate membership / role assignment."""
        claims = {"sub": SUB_NEW, "email": f"{SUB_NEW}@example.test", "_provider_scope": "user"}
        providers = {(str(TENANT_X_ID), "user"): ("https://x.example.com", "c", "agent_viewer")}
        await _sign_in(seeded_engine, claims, CTX_X, providers)
        await _sign_in(seeded_engine, claims, CTX_X, providers)

        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            user = (
                await db.execute(select(PlatformUser).where(PlatformUser.sub == SUB_NEW))
            ).scalar_one()
            memberships = (
                await db.execute(
                    select(TenantUserMembership).where(
                        TenantUserMembership.user_id == user.id
                    )
                )
            ).scalars().all()
            assert len(memberships) == 1, (
                "IDEMPOTENCY (FIX-20260930-075014 / e): the second sign-in "
                "must not create a duplicate membership"
            )
            role_rows = (
                await db.execute(select(UserRole).where(UserRole.user_id == user.id))
            ).scalars().all()
            assert len(role_rows) == 1

    async def test_f_unset_default_jit_nothing_and_403_path_unchanged(
        self, seeded_engine
    ):
        """(f) unset default + no membership → NO JIT; the existing
        no_access_to_workspace 403 path is unchanged."""
        providers = {(str(TENANT_X_ID), "user"): ("https://x.example.com", "c", None)}
        await _sign_in(
            seeded_engine,
            {"sub": SUB_NEW, "email": f"{SUB_NEW}@example.test", "_provider_scope": "user"},
            CTX_X,
            providers,
        )

        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            user = (
                await db.execute(select(PlatformUser).where(PlatformUser.sub == SUB_NEW))
            ).scalar_one()
            memberships = (
                await db.execute(
                    select(TenantUserMembership).where(
                        TenantUserMembership.user_id == user.id
                    )
                )
            ).scalars().all()
            assert memberships == [], "no JIT without a configured default role"

        SessionLocal2 = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal2() as session:
            register_tenant_scope_listener()
            apply_tenant_scope(session, TENANT_X_ID)
            from app.api.deps import authorize_identity

            with pytest.raises(HTTPException) as excinfo:
                await authorize_identity(
                    session,
                    {"sub": SUB_NEW, "tenant": CTX_X.slug},
                    RT_AGENT_MANAGEMENT,
                    "read",
                    tenant_id=TENANT_X_ID,
                )
            assert excinfo.value.status_code == 403
            assert excinfo.value.detail == "no_access_to_workspace"

    async def test_g_shared_provider_default_applies_in_tenant_context(
        self, seeded_engine
    ):
        """(g) the SHARED provider's default applies in every tenant's login
        context."""
        providers = {(None, "user"): ("https://shared.example.com", "c", "agent_viewer")}
        await _sign_in(
            seeded_engine,
            {"sub": SUB_NEW, "email": f"{SUB_NEW}@example.test", "_provider_scope": "user"},
            CTX_X,
            providers,
        )
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            user = (
                await db.execute(select(PlatformUser).where(PlatformUser.sub == SUB_NEW))
            ).scalar_one()
            membership = (
                await db.execute(
                    select(TenantUserMembership).where(
                        TenantUserMembership.user_id == user.id
                    )
                )
            ).scalar_one()
            assert membership.tenant_id == TENANT_X_ID

    async def test_h_system_slot_fallback_provider_jit(self, seeded_engine):
        """(h) the SYSTEM-slot fallback provider (the adopted platform
        provider) with a default role JITs in tenant X's context too."""
        providers = {
            (str(SYSTEM_TENANT_ID), "user"): (
                "https://adopted.example.com", "c", "agent_viewer"
            )
        }
        await _sign_in(
            seeded_engine,
            {"sub": SUB_NEW, "email": f"{SUB_NEW}@example.test", "_provider_scope": "user"},
            CTX_X,
            providers,
        )
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            user = (
                await db.execute(select(PlatformUser).where(PlatformUser.sub == SUB_NEW))
            ).scalar_one()
            membership = (
                await db.execute(
                    select(TenantUserMembership).where(
                        TenantUserMembership.user_id == user.id
                    )
                )
            ).scalar_one()
            assert membership.tenant_id == TENANT_X_ID

    async def test_platform_password_login_never_jits(self, seeded_engine):
        """Platform-password (platform-account) claims carry no
        ``_provider_scope`` — NO JIT even though a provider default exists."""
        providers = {(str(TENANT_X_ID), "user"): ("https://x.example.com", "c", "agent_viewer")}
        await _sign_in(
            seeded_engine,
            {"sub": SUB_NEW, "email": f"{SUB_NEW}@example.test"},  # no _provider_scope
            CTX_X,
            providers,
        )
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            user = (
                await db.execute(select(PlatformUser).where(PlatformUser.sub == SUB_NEW))
            ).scalar_one()
            memberships = (
                await db.execute(
                    select(TenantUserMembership).where(
                        TenantUserMembership.user_id == user.id
                    )
                )
            ).scalars().all()
            assert memberships == [], "platform-password logins must NEVER JIT"

    async def test_jit_records_audit_event(self, seeded_engine):
        """JIT provisioning records a tenant audit event (existing
        ``self_serve_registration`` type) for the tenant."""
        providers = {(str(TENANT_X_ID), "user"): ("https://x.example.com", "c", "agent_viewer")}
        await _sign_in(
            seeded_engine,
            {"sub": SUB_NEW, "email": f"{SUB_NEW}@example.test", "_provider_scope": "user"},
            CTX_X,
            providers,
        )
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            events = (
                await db.execute(
                    select(TenantAuditEvent).where(
                        TenantAuditEvent.event_type
                        == TenantAuditEventType.self_serve_registration,
                        TenantAuditEvent.tenant_id == TENANT_X_ID,
                    )
                )
            ).scalars().all()
            assert len(events) >= 1, (
                "AUDIT (FIX-20260930-075014): JIT role assignment must record "
                "a tenant audit event"
            )

    async def test_endpoint_level_first_sign_in_passes_data_call(self, seeded_engine):
        """End-to-end: after the JIT sign-in, a real permission-gated call in
        tenant X passes (middleware sim) — the membership gate in
        authorize_identity finds the JIT-created membership."""
        providers = {(str(TENANT_X_ID), "user"): ("https://x.example.com", "c", "agent_viewer")}
        await _sign_in(
            seeded_engine,
            {"sub": SUB_NEW, "email": f"{SUB_NEW}@example.test", "_provider_scope": "user"},
            CTX_X,
            providers,
        )

        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        app = create_app()

        async def override_get_db():
            async with SessionLocal() as session:
                register_tenant_scope_listener()
                apply_tenant_scope(session, TENANT_X_ID)
                yield session
                await flush_scope_miss_audits(session)
                await session.commit()

        app.dependency_overrides[get_db] = override_get_db

        async def patched_dispatch(self, request, call_next):
            set_tenant_context(request, CTX_X)
            request.state.identity = {
                "sub": SUB_NEW, "tenant": CTX_X.slug, "roles": [],
            }
            request.state.is_super_admin = False
            return await call_next(request)

        with patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/platform-users")

        assert response.status_code == 200, (
            f"JIT ADMISSION (FIX-20260930-075014 / d): after the JIT sign-in "
            f"a dashboard-level data call in tenant X must pass, got "
            f"{response.status_code} {response.text!r}"
        )
