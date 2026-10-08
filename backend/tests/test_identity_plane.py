"""FIX-20260929-221449 — the identity plane is platform-level.

Three product decisions are pinned here:

1. **Identity plane is platform-level.**  Resolving "who is this request
   from" (PlatformUser by cryptographic ``sub``, JIT provisioning) must be
   EXEMPT from the session's tenant scope: the scoping choke point
   (``app.db.tenant_scoping``) applies the PlatformUser membership-join
   strategy to every SELECT — correct for the data plane (user lists must
   show only co-members), wrong for the identity plane (a user with no
   membership in the resolved tenant is INVISIBLE to their own auth, so
   ``authorize_identity`` 403s with "user must re-authenticate" and the
   frontend bounce-loops to login).  The opt-out is an explicit execution
   option (``{"tenant_scope": "exempt"}``) exposed through the
   :func:`app.db.tenant_scoping.execute_unscoped` helper.  Data-plane user
   LISTING keeps the membership-join strategy (test_tenant_user_leak.py
   stays green; T7 pins it here too).

2. **Shared identity providers.**  An ``IdentityProviderConfig`` with a
   NULL ``tenant_id`` is the SHARED provider — usable by the platform AND
   by any tenant whose login context resolves to it.  Per-tenant configs
   take precedence for their tenant.  A token validated against a slot
   resolvable for the resolved tenant (own OR shared) gets the ``tenant``
   claim injected from the RESOLVED LOGIN CONTEXT: cross-tenant safety no
   longer derives from provider binding but from membership gates +
   row-level data scoping (a user without membership gets 403s, never
   data).

3. **No-membership UX (backend part).**  An authenticated user whose
   PlatformUser exists but has NO active membership in the resolved tenant
   gets a clean structured 403 ``{"detail": "no_access_to_workspace", ...}``
   — never "user must re-authenticate" (which the frontend treats as an
   auth failure and bounce-loops on).
"""
from __future__ import annotations

import os
import time
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

from app.core.resource_types import RT_SYSTEM_PERMISSIONS  # noqa: E402
from app.core.tenant_context import TenantContext, set_tenant_context  # noqa: E402
from app.db.models.identity_provider_config import IdentityProviderConfig  # noqa: E402
from app.db.models.platform_user import PlatformUser  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_membership import TenantUserMembership  # noqa: E402
from app.db.session import Base, get_db  # noqa: E402
from app.db.tenant_scoping import (  # noqa: E402
    apply_tenant_scope,
    flush_scope_miss_audits,
    register_tenant_scope_listener,
)
from app.main import create_app  # noqa: E402
from app.middleware.auth import JWTAuthMiddleware  # noqa: E402
from app.services.oidc_provider_registry import OIDCProviderRegistry  # noqa: E402
from app.services.permissions.user_cache_service import UserCacheService  # noqa: E402

TAG = uuid.uuid4().hex[:8]

TENANT_SYSTEM_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
TENANT_X_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000002")
TENANT_Y_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000003")

CTX_X = TenantContext(tenant_id=TENANT_X_ID, slug=f"tenant-x-{TAG}", name="Tenant X")
CTX_Y = TenantContext(tenant_id=TENANT_Y_ID, slug=f"tenant-y-{TAG}", name="Tenant Y")

SUB_SYS_ONLY = f"sys-only-{TAG}"     # member of the SYSTEM tenant only
SUB_X_ROOT = f"x-root-{TAG}"         # root member of tenant X
SUB_NOBODY = f"nobody-{TAG}"         # no memberships at all


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_settings_singleton():
    """Isolate the process-wide PlatformSettingsService cache per test."""
    import app.services.tenancy.platform_settings_service as settings_module

    settings_module._service = None
    yield
    settings_module._service = None


async def _set_tenancy(db, enabled: bool) -> None:
    """Toggle the switch through the process-wide singleton (cache coherent)."""
    from app.services.tenancy.platform_settings_service import (
        get_platform_settings_service,
    )

    await get_platform_settings_service().set_setting(
        db, "multi_tenancy_enabled", enabled
    )
    await db.commit()


@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory engine per test (no cross-test pollution)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_engine(engine):
    """System tenant + tenant X (+Y), each with its membership population:
    sys-only (SYSTEM member), x-root (X root member), nobody (no membership)."""
    register_tenant_scope_listener()
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        system = Tenant(
            name="System", slug=f"system-{TAG}", is_system_tenant=True
        )
        system.id = TENANT_SYSTEM_ID
        tenant_x = Tenant(name="Tenant X", slug=f"tenant-x-{TAG}")
        tenant_x.id = TENANT_X_ID
        tenant_y = Tenant(name="Tenant Y", slug=f"tenant-y-{TAG}")
        tenant_y.id = TENANT_Y_ID
        db.add_all([system, tenant_x, tenant_y])
        await db.flush()

        sys_only = PlatformUser(
            sub=SUB_SYS_ONLY,
            email=f"sys-only-{TAG}@example.test",
            display_name="System Only",
        )
        x_root = PlatformUser(
            sub=SUB_X_ROOT,
            email=f"x-root-{TAG}@example.test",
            display_name="X Root",
        )
        nobody = PlatformUser(
            sub=SUB_NOBODY,
            email=f"nobody-{TAG}@example.test",
            display_name="Nobody",
        )
        db.add_all([sys_only, x_root, nobody])
        await db.flush()

        db.add_all(
            [
                # the ADOPTED user: an active membership in the SYSTEM tenant only
                TenantUserMembership(
                    tenant_id=TENANT_SYSTEM_ID,
                    user_id=sys_only.id,
                    tenant_role="member",
                    status="active",
                ),
                # tenant X's owner
                TenantUserMembership(
                    tenant_id=TENANT_X_ID,
                    user_id=x_root.id,
                    tenant_role="member",
                    is_root=True,
                    status="active",
                ),
            ]
        )
        await db.commit()
    return engine


@pytest_asyncio.fixture
async def scoped_db_x(seeded_engine):
    """Session scoped to tenant X — what a tenant-X-context request gets."""
    SessionLocal = async_sessionmaker(
        bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        apply_tenant_scope(session, TENANT_X_ID)
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def unscoped_db(seeded_engine):
    SessionLocal = async_sessionmaker(
        bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        yield session
        await session.rollback()


def _provider_row(
    scope: str, tenant_id: uuid.UUID | None, issuer: str
) -> IdentityProviderConfig:
    return IdentityProviderConfig(
        provider_scope=scope,
        provider_type="keycloak",
        display_name=f"{scope}-{tenant_id or 'shared'}",
        issuer_url=issuer,
        client_id=f"client-{scope}",
        encrypted_client_secret=None,
        is_enabled=True,
        tenant_id=tenant_id,
    )


# ── T1: identity resolution is tenant-scope-exempt ───────────────────────────


class TestIdentityPlaneIsScopeExempt:
    async def test_authorized_user_with_system_tenant_membership_only_resolves_in_tenant_x_context(
        self, scoped_db_x
    ):
        """T1 — a user with a membership ONLY in the system tenant (the
        adopted-user situation) must RESOLVE in a tenant-X context.

        Today the scoped session hides the PlatformUser (membership-join)
        so authorize_identity 403s "User not found in platform. Please
        re-authenticate."  Post-fix the identity lookup is scope-exempt and
        the failure (if any) is a clean no-membership denial — never a
        re-authentication prompt.
        """
        from app.api.deps import authorize_identity

        claims = {"sub": SUB_SYS_ONLY, "email": f"sys-only-{TAG}@example.test"}
        with pytest.raises(HTTPException) as excinfo:
            await authorize_identity(
                scoped_db_x,
                claims,
                RT_SYSTEM_PERMISSIONS,
                "read",
                tenant_id=TENANT_X_ID,
            )

        detail = excinfo.value.detail
        assert excinfo.value.status_code == 403
        assert detail == "no_access_to_workspace", (
            f"IDENTITY PLANE SCOPED (FIX-20260929-221449 / T1): the "
            f"PlatformUser exists but the tenant-scoped lookup hid it — "
            f"authorize_identity must resolve the user and deny with the "
            f"structured no-membership shape, got detail={detail!r}"
        )
        assert "re-authenticate" not in str(excinfo.value.extra).lower()
        assert excinfo.value.extra.get("required_permission", {}).get(
            "resource_type"
        ) == RT_SYSTEM_PERMISSIONS

    async def test_get_user_by_sub_resolves_on_scoped_session(self, scoped_db_x):
        """Identity-plane helper: PlatformUser-by-sub must resolve on a
        tenant-scoped session (today it returns None)."""
        user = await UserCacheService().get_user_by_sub(scoped_db_x, SUB_SYS_ONLY)
        assert user is not None, (
            "IDENTITY PLANE SCOPED (FIX-20260929-221449): PlatformUser-by-sub "
            "is an identity-plane lookup — it must resolve regardless of the "
            "session's tenant scope"
        )
        assert user.sub == SUB_SYS_ONLY

    async def test_execute_unscoped_helper_sees_hidden_user(self, scoped_db_x):
        """The explicit opt-out: execute_unscoped() returns the row the
        scoped session hides; a plain execute() keeps hiding it."""
        from app.db.tenant_scoping import execute_unscoped

        plain = (
            await scoped_db_x.execute(select(PlatformUser))
        ).scalars().all()
        assert [u.sub for u in plain] == [SUB_X_ROOT], (
            "data-plane select must keep the membership-join strategy"
        )

        exempt = (
            await execute_unscoped(scoped_db_x, select(PlatformUser))
        ).scalars().all()
        assert {u.sub for u in exempt} == {SUB_SYS_ONLY, SUB_X_ROOT, SUB_NOBODY}


# ── T2: JIT provisioning on a scoped session ─────────────────────────────────


class TestJitProvisioningIsScopeExempt:
    async def test_upsert_user_on_scoped_session_returns_existing_invisible_user(
        self, scoped_db_x
    ):
        """T2 — JIT upsert for an existing-but-invisible user must return
        the EXISTING row (identity plane), never insert a duplicate.

        Today the scoped select misses the user, the email-conflict lookup
        misses it too, and the INSERT violates the unique ``sub`` →
        IntegrityError at flush (swallowed upstream by the auth middleware's
        fire-and-log wrapper → the user silently never gets provisioned).
        """
        svc = UserCacheService()
        user = await svc.upsert_user(
            scoped_db_x,
            sub=SUB_SYS_ONLY,
            email=f"sys-only-{TAG}@example.test",
            display_name="System Only",
        )
        assert user.sub == SUB_SYS_ONLY

        rows = (
            await scoped_db_x.execute(
                select(PlatformUser).where(PlatformUser.sub == SUB_SYS_ONLY)
            )
        ).scalars().all()
        # the pre-existing row — through the identity-plane exempt lookup
        existing = await UserCacheService().get_user_by_sub(scoped_db_x, SUB_SYS_ONLY)
        assert user.id == existing.id, (
            "JIT UPSERT DUPLICATED (FIX-20260929-221449 / T2): upsert_user on a "
            "scoped session must return the existing PlatformUser row, not "
            "insert a second one"
        )
        assert len(
            (await execute_unscoped_rows(scoped_db_x, PlatformUser.sub == SUB_SYS_ONLY))
        ) == 1, "exactly one PlatformUser row must exist for the sub"


async def execute_unscoped_rows(db, predicate):
    """Count rows matching predicate via the identity-plane exempt path."""
    from app.db.tenant_scoping import execute_unscoped

    return (
        await execute_unscoped(db, select(PlatformUser).where(predicate))
    ).scalars().all()


# ── T3/T4: shared identity providers ─────────────────────────────────────────


class _FakeRequest:
    def __init__(self, context, path="/api/v1/dashboard/summary"):
        self.state = SimpleNamespace()
        # Phase 11: a resolved context is tenancy-ON in these tests.
        self.state.tenancy_enabled = context is not None
        if context is not None:
            self.state.tenant_context = context
        self.url = SimpleNamespace(path=path)
        self.method = "GET"
        self.client = SimpleNamespace(host="10.0.0.9")


class _FakeOIDCClientBase:
    _claims: dict = {}
    captured: dict = {}

    def __init__(self, *, issuer_url, client_id, **kwargs):
        type(self).captured["issuer"] = issuer_url
        type(self).captured["client_id"] = client_id

    async def validate_token(self, token: str) -> dict:
        return dict(self._claims)


def _fake_oidc_client(claims: dict) -> type:
    return type("FakeOIDCClient", (_FakeOIDCClientBase,), {"_claims": dict(claims)})


def _realistic_claims() -> dict:
    now = int(time.time())
    return {
        "sub": SUB_SYS_ONLY,
        "email": f"sys-only-{TAG}@example.test",
        "name": "System Only",
        "iat": now,
        "exp": now + 3600,
    }


def _patch_registry(registry):
    import app.main as main_module

    return patch.object(main_module, "_get_registry", lambda: registry)


class TestSharedIdentityProvider:
    """A NULL-tenant IdentityProviderConfig is the SHARED provider: usable
    by the platform AND by any tenant without its own config; per-tenant
    configs take precedence."""

    @pytest_asyncio.fixture
    async def shared_registry(self, seeded_engine):
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            await _set_tenancy(db, True)
            db.add(_provider_row("user", None, "https://shared.example.com"))
            await db.commit()
            registry = OIDCProviderRegistry()
            await registry.initialize(db)
        return registry

    async def test_t3_shared_provider_validates_tenant_login_context_and_injects_claim(
        self, shared_registry
    ):
        """T3 — tenant X has NO own config; the shared (NULL-tenant)
        provider must validate the token for X's login context AND the
        ``tenant`` claim must be injected from the RESOLVED CONTEXT.
        Today: fail-closed None (shared slot not a fallback) → sign-in
        impossible for any tenant without its own provider."""
        import app.middleware.auth as auth_module

        claims_payload = _realistic_claims()  # no native tenant claim
        with _patch_registry(shared_registry), patch.object(
            auth_module, "OIDCClient", _fake_oidc_client(claims_payload)
        ):
            claims = await auth_module._try_oidc_token("tok", CTX_X)

        assert claims is not None, (
            "SHARED PROVIDER NOT RESOLVED (FIX-20260929-221449 / T3): a "
            "tenant whose login context resolves but that has no OWN provider "
            "config must validate against the SHARED (NULL-tenant) provider"
        )
        assert _FakeOIDCClientBase.captured["issuer"] == "https://shared.example.com"
        assert claims["_provider_scope"] == "user"
        # claim injected from the resolved login context
        assert claims.get("tenant") == CTX_X.slug

        # and the claim check accepts the injected claim for that tenant
        from app.middleware.auth import JWTAuthMiddleware

        error = await JWTAuthMiddleware(app=None)._check_tenant_claim(
            _FakeRequest(CTX_X), claims, False
        )
        assert error is None

    async def test_t4_tenant_own_config_wins_over_shared(self, seeded_engine, shared_registry):
        """T4 (precedence pin) — when tenant X ALSO has its own provider,
        the own slot validates the token (the shared slot only fills gaps)."""
        import app.middleware.auth as auth_module

        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            db.add(_provider_row("user", TENANT_X_ID, "https://x-own.example.com"))
            await db.commit()
            await shared_registry.reload(db)

        with _patch_registry(shared_registry), patch.object(
            auth_module, "OIDCClient", _fake_oidc_client(_realistic_claims())
        ):
            claims = await auth_module._try_oidc_token("tok", CTX_X)

        assert claims is not None
        assert _FakeOIDCClientBase.captured["issuer"] == "https://x-own.example.com", (
            "T4 PRECEDENCE: the tenant's OWN provider slot must win over the "
            "shared provider when both exist"
        )
        assert claims.get("tenant") == CTX_X.slug

    async def test_registry_shared_slot_resolves_for_any_tenant(self, shared_registry):
        assert shared_registry.get_provider("user", TENANT_X_ID) is not None
        assert shared_registry.get_provider("user", TENANT_Y_ID) is not None

    async def test_registry_platform_surface_resolves_shared_slot(self, shared_registry):
        provider = shared_registry.get_provider("user", None)
        assert provider is not None
        assert provider.issuer_url == "https://shared.example.com"

    async def test_registry_no_provider_at_all_is_fail_closed_none(self, seeded_engine):
        """A tenant with neither an own config NOR a shared config still
        resolves None — fail-closed sign-in is preserved."""
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            await _set_tenancy(db, True)
            # only TENANT_Y has a provider — nobody shares it
            db.add(_provider_row("user", TENANT_Y_ID, "https://y-only.example.com"))
            await db.commit()
            registry = OIDCProviderRegistry()
            await registry.initialize(db)

        assert registry.get_provider("user", TENANT_X_ID) is None
        assert registry.get_provider("user", None) is None

    async def test_tenancy_off_everything_uses_root_provider(self, seeded_engine):
        """Tenancy OFF: the ROOT tenant IS the default tenant — every
        lookup resolves the ROOT tenant's slot; NULL-tenant (shared) and
        other tenants' providers never resolve."""
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            await _set_tenancy(db, False)
            db.add(_provider_row("user", None, "https://legacy.example.com"))
            db.add(_provider_row(
                "user", TENANT_SYSTEM_ID, "https://root.example.com"
            ))
            db.add(_provider_row("user", TENANT_X_ID, "https://stale-x.example.com"))
            await db.commit()
            registry = OIDCProviderRegistry()
            await registry.initialize(db)

        for tenant_id in (None, TENANT_X_ID, TENANT_Y_ID, TENANT_SYSTEM_ID):
            provider = registry.get_provider("user", tenant_id)
            assert provider is not None
            assert provider.issuer_url == "https://root.example.com"


# ── T5/T6: no-membership UX + member access (endpoint level) ─────────────────


def _make_auth_patch(sub: str, ctx: TenantContext):
    """Replace the JWT middleware: bind the tenant context + identity the
    way a validated shared-provider token would arrive."""

    async def patched_dispatch(self, request, call_next):
        set_tenant_context(request, ctx)
        request.state.identity = {"sub": sub, "tenant": ctx.slug, "roles": []}
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


class TestNoMembershipForbiddenShape:
    @pytest_asyncio.fixture
    async def client_factory(self, seeded_engine):
        # Phase 11 note: the membership gate is keyed on the resolved
        # tenant being a CUSTOMER tenant (≠ root) in any switch state, so
        # these tests need no switch manipulation.
        SessionLocal = async_sessionmaker(
            bind=seeded_engine, class_=AsyncSession, expire_on_commit=False
        )

        def _make(sub: str, ctx: TenantContext):
            app = create_app()

            async def override_get_db():
                async with SessionLocal() as session:
                    register_tenant_scope_listener()
                    apply_tenant_scope(session, ctx.tenant_id)
                    yield session
                    await flush_scope_miss_audits(session)
                    await session.commit()

            app.dependency_overrides[get_db] = override_get_db
            auth_patch = _make_auth_patch(sub, ctx)
            auth_patch.start()
            return app, auth_patch

        return _make

    async def _call(self, factory_result):
        app, auth_patch = factory_result
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.get("/api/v1/platform-users")
        finally:
            auth_patch.stop()

    async def test_t5_no_membership_data_call_is_clean_403_no_access_to_workspace(
        self, client_factory
    ):
        """T5 — an authenticated user with NO membership in tenant X gets a
        structured 403 no_access_to_workspace on a data call — NOT the
        re-authentication 403 that triggers frontend redirect loops."""
        response = await self._call(client_factory(SUB_NOBODY, CTX_X))

        assert response.status_code == 403
        body = response.json()
        assert isinstance(body, dict)
        assert body.get("detail") == "no_access_to_workspace", (
            f"NO-MEMBERSHIP UX (FIX-20260929-221449 / T5): an authenticated "
            f"user without a membership must get the clean structured "
            f"no_access_to_workspace 403, got {body!r}"
        )
        assert "re-authenticate" not in str(body).lower()
        # structured permission shape so the frontend surfaces a permission
        # denial (never an auth failure / logout)
        assert body.get("required_permission", {}).get("resource_type") == (
            RT_SYSTEM_PERMISSIONS
        )

    async def test_t6_member_data_call_passes(self, client_factory, seeded_engine):
        """T6 — the same data call for a user WITH an active membership in
        tenant X (via the shared provider login context) is allowed."""
        response = await self._call(client_factory(SUB_X_ROOT, CTX_X))

        assert response.status_code == 200, (
            f"MEMBER DENIED (FIX-20260929-221449 / T6): a root member of "
            f"tenant X must pass authorize for a tenant-X data call, got "
            f"{response.status_code} {response.text!r}"
        )
        emails = [u["email"] for u in response.json()]
        assert emails == [f"x-root-{TAG}@example.test"]

    async def test_authorize_identity_allows_root_member_for_business_module(
        self, scoped_db_x
    ):
        """Dashboard-level authorize: the ROOT membership grants every
        non-platform module inside its tenant.

        Phase 11: the root blanket grant (and the whole membership gate)
        applies when the tenancy switch is ON — enable it for this test
        (the OFF default context is the root tenant with role-driven
        authz, no membership requirement)."""
        from app.services.tenancy.platform_settings_service import (
            get_platform_settings_service,
        )

        await get_platform_settings_service().set_setting(
            scoped_db_x, "multi_tenancy_enabled", True
        )
        await scoped_db_x.commit()

        from app.api.deps import authorize_identity

        claims = {"sub": SUB_X_ROOT, "tenant": CTX_X.slug}
        result = await authorize_identity(
            scoped_db_x,
            claims,
            "agent::agent_types",
            "read",
            tenant_id=TENANT_X_ID,
        )
        assert result is claims


# ── T7: the data plane keeps the membership-join strategy ────────────────────


class TestDataPlaneUserListingStillScoped:
    async def test_t7_scoped_user_list_excludes_non_members(self, scoped_db_x):
        """T7 (pin) — a plain (data-plane) PlatformUser select on a
        tenant-X session lists ONLY X's active members.  The identity-plane
        exemption must never loosen the data plane (test_tenant_user_leak
        stays green)."""
        rows = (await scoped_db_x.execute(select(PlatformUser))).scalars().all()
        assert {u.sub for u in rows} == {SUB_X_ROOT}, (
            "DATA PLANE LOOSENED (FIX-20260929-221449 / T7): the plain "
            "data-plane user query must keep the membership-join strategy — "
            "only X's active members are visible"
        )

    async def test_scoped_get_of_non_member_is_none(self, scoped_db_x):
        """db.get of a non-member id stays not-found on the scoped session
        (the leak test's 404 contract at the ORM level).  The exempt
        lookup only fetches the id; the entity is expunged first so the
        scoped get() re-queries (identity-map short-circuit avoided)."""
        from app.db.tenant_scoping import execute_unscoped

        nobody = (
            await execute_unscoped(
                scoped_db_x, select(PlatformUser).where(PlatformUser.sub == SUB_NOBODY)
            )
        ).scalar_one()
        nobody_id = nobody.id
        scoped_db_x.expunge_all()
        assert await scoped_db_x.get(PlatformUser, nobody_id) is None
