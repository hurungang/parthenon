"""Self-serve registration & platform-password sign-in tests (Phase 10.18).

Covers CS-26..CS-29 and E-18 against the PUBLIC ``/api/v1/auth/*``
surface with the REAL app + sqlite DB (pattern of
test_tenant_memberships_invitations.py):

- CS-26 atomic registration: one POST creates the platform account
  (bcrypt credential, platform-issued sub), the tenant and the owner's
  ROOT membership all-or-nothing; the response carries a tenant-bound
  session; a ``self_serve_registration`` audit event is written.
- CS-27 input rules: duplicate email, invalid fields, slug conflicts —
  rejected with clear errors and ZERO partial rows.
- CS-28 one-tenant-per-user: a second registration for an existing
  owner is blocked; no second tenant; no partial data.
- CS-29 switch-off inertness: with ``multi_tenancy_enabled=false``
  (the default) registration is rejected without any side effect and
  discovery exposes no tenant.
- login-password: correct credentials → tenant-bound platform JWT;
  wrong password / unknown account / no-credential account → generic
  401 (no user enumeration).
- E-18 same-email registrations: exactly one succeeds; the DB unique
  constraint on ``PlatformUser.email`` is the authoritative backstop
  (the sqlite StaticPool test engine serializes true concurrency, so
  the race is exercised as immediate back-to-back attempts).
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.db.models.platform_setting import PlatformSetting  # noqa: E402
from app.db.models.platform_user import PlatformUser  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_audit_event import (  # noqa: E402
    TenantAuditEvent,
    TenantAuditEventType,
)
from app.db.models.tenant_membership import TenantUserMembership  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.tenancy import tenant_registration_service as reg_module  # noqa: E402
from app.services.tenancy.platform_account_auth_service import (  # noqa: E402
    validate_platform_account_token,
)

_TS_HOLDER = {"v": uuid.uuid4().hex[:8]}


def _ts() -> str:
    """Per-test unique suffix (the engine is shared across tests)."""
    return _TS_HOLDER["v"]


@pytest.fixture(autouse=True)
def _fresh_suffix():
    """Rotate the unique suffix per test (the engine is shared)."""
    _TS_HOLDER["v"] = uuid.uuid4().hex[:8]
    yield


@pytest_asyncio.fixture(autouse=True)
async def _fresh_state(test_engine):
    """Reset process-global + shared-DB state between tests.

    - PlatformSettingsService singleton: its 30s cache is process-wide;
      stale switch values would leak across tests otherwise.
    - The ``multi_tenancy_enabled`` row: the engine is session-scoped, so
      a previous test's switch-on row must be removed (default is off).
    - Registration throttle buckets + the slowapi limiter: per-IP
      counters shared across tests (same test-client IP).
    """
    import app.services.tenancy.platform_settings_service as settings_module

    settings_module._service = None
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as db:
        await db.execute(
            PlatformSetting.__table__.delete().where(
                PlatformSetting.key == "multi_tenancy_enabled"
            )
        )
        await db.commit()
    settings_module._service = None

    reg_module._attempts.clear()
    from app.api.v1 import auth_tenant

    auth_tenant._limiter.reset()
    yield
    settings_module._service = None
    reg_module._attempts.clear()
    auth_tenant._limiter.reset()


@pytest_asyncio.fixture
async def db_factory(test_engine):
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _factory(commit: bool = False):
        class _Ctx:
            async def __aenter__(self):
                self._session = SessionLocal()
                return self._session

            async def __aexit__(self, *exc):
                if commit:
                    await self._session.commit()
                else:
                    await self._session.rollback()
                await self._session.close()

        return _Ctx()

    return _factory


@pytest_asyncio.fixture
async def client(test_engine):
    """Public client: registration/sign-in need no auth.

    TenantResolutionMiddleware.dispatch is patched to a pass-through: the
    register/login-password paths are bypassed by the real middleware
    anyway, AND the real middleware reads the switch through its own
    (PostgreSQL) session, which would poison the process-global settings
    cache observed by the endpoint's sqlite session in tests.
    """
    from unittest.mock import patch as _patch

    from app.middleware.tenant_resolution import TenantResolutionMiddleware

    app = create_app()
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_db():
        async with SessionLocal() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db] = override_db

    async def passthrough(self, request, call_next):
        return await call_next(request)

    with _patch.object(TenantResolutionMiddleware, "dispatch", passthrough):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


async def _enable_tenancy(test_engine) -> None:
    """Flip the platform switch ON in the test DB (row upsert)."""
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

    settings_module._service = None  # drop the cached read


async def _counts(test_engine) -> tuple[int, int, int]:
    """(users, tenants, memberships) totals for partial-data assertions."""
    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as db:
        users = len((await db.execute(select(PlatformUser))).scalars().all())
        tenants = len((await db.execute(select(Tenant))).scalars().all())
        memberships = len(
            (await db.execute(select(TenantUserMembership))).scalars().all()
        )
    return users, tenants, memberships


VALID = {
    "email": "owner-{ts}@test.dev",
    "password": "Sup3rSecret",
    "organization_name": "Acme Corp {ts}",  # tenant names are unique too
    "slug": "acme-{ts}",
}


def _payload(**overrides) -> dict:
    body = {k: v.replace("{ts}", _ts()) for k, v in VALID.items()}
    body.update(overrides)
    return body


# ── CS-26: atomic happy path ─────────────────────────────────────────────────


class TestRegistrationHappyPath:
    async def test_registration_creates_account_tenant_root_atomically(
        self, client, test_engine
    ):
        """CS-26: one action creates account + tenant + root membership."""
        await _enable_tenancy(test_engine)
        response = await client.post("/api/v1/auth/register", json=_payload())
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["slug"] == f"acme-{_ts()}"
        assert body["name"] == f"Acme Corp {_ts()}"
        assert body["is_root"] is True
        assert body["your_role"] == "tenant_admin"
        assert body["access_token"]
        assert body["tenant_id"]

    async def test_registered_account_uses_platform_credential_and_sub(
        self, client, test_engine
    ):
        """CS-26: the account is platform-issued — bcrypt credential and
        a ``platform_account:`` sub, deliberately outside per-tenant OIDC."""
        await _enable_tenancy(test_engine)
        registered = await client.post("/api/v1/auth/register", json=_payload())
        assert registered.status_code == 200, registered.text

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            user = (
                await db.execute(
                    select(PlatformUser).where(
                        PlatformUser.email == f"owner-{_ts()}@test.dev"
                    )
                )
            ).scalar_one()
            assert user.sub.startswith("platform_account:")
            assert user.password_credential  # stored (hashed)
            assert user.password_credential.startswith("$2")

            membership = (
                await db.execute(
                    select(TenantUserMembership).where(
                        TenantUserMembership.user_id == user.id
                    )
                )
            ).scalar_one()
            assert membership.is_root is True
            assert membership.tenant_role.value == "tenant_admin"

    async def test_registration_writes_self_serve_registration_audit(
        self, client, test_engine
    ):
        """CS-26: a ``self_serve_registration`` audit event is written."""
        await _enable_tenancy(test_engine)
        created = await client.post("/api/v1/auth/register", json=_payload())
        assert created.status_code == 200
        tenant_id = uuid.UUID(created.json()["tenant_id"])

        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            events = (
                (
                    await db.execute(
                        select(TenantAuditEvent).where(
                            TenantAuditEvent.tenant_id == tenant_id
                        )
                    )
                )
            ).scalars().all()
        event_types = {e.event_type.value for e in events}
        assert "self_serve_registration" in event_types

    async def test_registration_token_is_platform_account_tenant_bound(
        self, client, test_engine
    ):
        """CS-26: the returned session is a tenant-bound platform JWT."""
        await _enable_tenancy(test_engine)
        response = await client.post("/api/v1/auth/register", json=_payload())
        token = response.json()["access_token"]
        payload = validate_platform_account_token(token)
        assert payload is not None
        assert payload["tenant"] == f"acme-{_ts()}"
        assert payload.get("platform_account") is True


# ── CS-27: input rules — no partial data ─────────────────────────────────────


class TestRegistrationInputRules:
    async def test_duplicate_email_of_non_owner_rejected_no_partial_data(
        self, client, test_engine
    ):
        """CS-27: an existing account WITHOUT a root membership (e.g. an
        invited member) can't be re-registered — clear 409, no rows."""
        await _enable_tenancy(test_engine)
        # Seed a plain (non-root) platform account.
        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            db.add(
                PlatformUser(
                    sub=f"member-{_ts()}",
                    email=f"member-{_ts()}@test.dev",
                    display_name="Member",
                )
            )
            await db.commit()
        before = await _counts(test_engine)

        response = await client.post(
            "/api/v1/auth/register",
            json=_payload(email=f"member-{_ts()}@test.dev"),
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]
        assert await _counts(test_engine) == before

    async def test_slug_conflict_rejected_no_partial_data(self, client, test_engine):
        """CS-27: slug conflicts are rejected with a clear error and no
        account or membership rows are left behind."""
        await _enable_tenancy(test_engine)
        first = await client.post("/api/v1/auth/register", json=_payload())
        assert first.status_code == 200
        before = await _counts(test_engine)

        conflict = await client.post(
            "/api/v1/auth/register",
            json=_payload(email=f"other-{_ts()}@test.dev"),
        )
        assert conflict.status_code == 409
        assert "already taken" in conflict.json()["detail"]
        assert await _counts(test_engine) == before

    @pytest.mark.parametrize(
        "overrides",
        [
            {"email": "not-an-email"},
            {"password": "short1"},  # < 8 chars
            {"password": "nodigitsonly"},  # no digit
            {"password": "12345678"},  # no letter
            {"organization_name": "   "},  # blank name
        ],
    )
    async def test_invalid_fields_rejected_without_writes(
        self, client, test_engine, overrides
    ):
        """CS-27: invalid fields → 4xx with clear errors and NO rows."""
        await _enable_tenancy(test_engine)
        before = await _counts(test_engine)
        response = await client.post(
            "/api/v1/auth/register", json=_payload(**overrides)
        )
        assert 400 <= response.status_code < 500
        assert await _counts(test_engine) == before

    async def test_missing_fields_rejected_by_schema(self, client, test_engine):
        """CS-27: missing fields → 422 by the request schema itself."""
        await _enable_tenancy(test_engine)
        before = await _counts(test_engine)
        response = await client.post("/api/v1/auth/register", json={"email": "x@y.dev"})
        assert response.status_code == 422
        assert await _counts(test_engine) == before


# ── CS-28: one tenant per user ───────────────────────────────────────────────


class TestOneTenantPerUser:
    async def test_existing_owner_cannot_create_second_tenant(
        self, client, test_engine
    ):
        """CS-28: the owner of an existing tenant is blocked with the
        dedicated one-tenant message; no second tenant is created and no
        partial data remains."""
        await _enable_tenancy(test_engine)
        first = await client.post("/api/v1/auth/register", json=_payload())
        assert first.status_code == 200, first.text
        owned_tenant_id = first.json()["tenant_id"]
        before = await _counts(test_engine)

        blocked = await client.post(
            "/api/v1/auth/register",
            json=_payload(
                email=f"owner-{_ts()}@test.dev",  # same owner email
                slug=f"try-again-{_ts()}",
                organization_name=f"Try Again {_ts()}",
            ),
        )
        assert blocked.status_code == 409
        # The PRD's clear "one tenant per user" message (not the generic
        # duplicate-email error — an owner is distinguishable from a plain
        # existing account).
        assert "only one organization" in blocked.json()["detail"]

        after = await _counts(test_engine)
        assert after == before
        # The owned tenant is untouched and no second tenant (the new
        # slug) was created.  (The engine is session-scoped — scope the
        # assertion to this test's slugs rather than global counts.)
        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            owned = (
                await db.execute(
                    select(Tenant).where(Tenant.id == uuid.UUID(owned_tenant_id))
                )
            ).scalar_one()
            assert owned.slug == f"acme-{_ts()}"
            second = (
                await db.execute(
                    select(Tenant).where(Tenant.slug == f"try-again-{_ts()}")
                )
            ).scalar_one_or_none()
            assert second is None


# ── CS-29: switch-off inertness ──────────────────────────────────────────────


class TestSwitchOffInertness:
    async def test_registration_rejected_with_switch_off_no_side_effects(
        self, client, test_engine
    ):
        """CS-29: with the switch off (default) the public registration
        endpoint is inert — 403, zero rows written."""
        # NOTE: tenancy NOT enabled here (default false).
        before = await _counts(test_engine)
        response = await client.post("/api/v1/auth/register", json=_payload())
        assert response.status_code == 403
        assert "not available" in response.json()["detail"]
        assert await _counts(test_engine) == before

    async def test_switch_off_discovery_exposes_no_tenant(self, client):
        """CS-29: discovery reports the switch state and no tenant."""
        response = await client.get("/api/v1/auth/tenant")
        assert response.status_code == 200
        body = response.json()
        assert body["multi_tenancy_enabled"] is False
        assert body["tenant"] is None


# ── login-password (platform-issued accounts) ────────────────────────────────


class TestLoginPassword:
    async def test_correct_credentials_issue_tenant_bound_token(
        self, client, test_engine
    ):
        await _enable_tenancy(test_engine)
        registered = await client.post("/api/v1/auth/register", json=_payload())
        assert registered.status_code == 200

        response = await client.post(
            "/api/v1/auth/login-password",
            json={
                "email": f"owner-{_ts()}@test.dev",
                "password": "Sup3rSecret",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["tenant_slug"] == f"acme-{_ts()}"
        assert body["tenant_name"] == f"Acme Corp {_ts()}"
        assert body["your_role"] == "tenant_admin"
        payload = validate_platform_account_token(body["access_token"])
        assert payload is not None
        assert payload["tenant"] == f"acme-{_ts()}"

    async def test_wrong_password_generic_401(self, client, test_engine):
        await _enable_tenancy(test_engine)
        await client.post("/api/v1/auth/register", json=_payload())
        response = await client.post(
            "/api/v1/auth/login-password",
            json={"email": f"owner-{_ts()}@test.dev", "password": "WrongPass1"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"

    async def test_unknown_account_same_generic_401_no_enumeration(
        self, client, test_engine
    ):
        """Failures are generic — unknown accounts are indistinguishable
        from wrong passwords (no user enumeration)."""
        response = await client.post(
            "/api/v1/auth/login-password",
            json={"email": f"nobody-{_ts()}@test.dev", "password": "Whatever1"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"


# ── E-18: same-email registrations ──────────────────────────────────────────


class TestSameEmailRace:
    async def test_exactly_one_registration_succeeds_email_unique_backstop(
        self, client, test_engine
    ):
        """E-18: only ONE registration per email ever succeeds — the
        service guard rejects the second attempt cleanly and the DB
        unique constraint on PlatformUser.email is the backstop against
        check-then-insert races.  (The sqlite StaticPool test engine
        serializes real concurrent writes, so the race is exercised as
        immediate back-to-back attempts plus a direct constraint probe.)"""
        await _enable_tenancy(test_engine)
        first = await client.post("/api/v1/auth/register", json=_payload())
        assert first.status_code == 200

        # Raced second attempt (fresh session, post-commit guard check).
        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        service = reg_module.TenantRegistrationService()
        async with SessionLocal() as db:
            with pytest.raises(reg_module.TenantRegistrationError) as exc:
                await service.register(
                    db,
                    email=f"owner-{_ts()}@test.dev",
                    password="Sup3rSecret",
                    organization_name="Race Org",
                    slug=f"race-{_ts()}",
                )
            assert exc.value.status_code == 409
            await db.rollback()

        # Invariant: exactly one account + one tenant for this test's
        # identifiers, no partial rows.
        SessionLocal = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with SessionLocal() as db:
            same_email = (
                await db.execute(
                    select(PlatformUser).where(
                        PlatformUser.email == f"owner-{_ts()}@test.dev"
                    )
                )
            ).scalars().all()
            assert len(same_email) == 1
            raced_slugs = (
                await db.execute(
                    select(Tenant).where(
                        Tenant.slug.in_([f"acme-{_ts()}", f"race-{_ts()}"])
                    )
                )
            ).scalars().all()
            assert len(raced_slugs) == 1
            assert raced_slugs[0].slug == f"acme-{_ts()}"

        # The authoritative backstop: a second PlatformUser row with the
        # same email violates the unique constraint at the DB level.
        from sqlalchemy.exc import IntegrityError

        async with SessionLocal() as db:
            db.add(
                PlatformUser(
                    sub=f"platform_account:{uuid.uuid4()}",
                    email=f"owner-{_ts()}@test.dev",
                    display_name="dupe",
                )
            )
            with pytest.raises(IntegrityError):
                await db.flush()
            await db.rollback()
