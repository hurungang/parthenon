"""Consolidated multi-tenancy auth-chain regression suite.

End-to-end coverage of the login → connect → chat auth journey that the
multi-tenancy change reworked — every step of which broke independently
during hardening.  Each scenario pins one link of the chain:

1. TOKEN LAYER — an OIDC token validates ONLY against its own tenant's
   provider slot; a foreign tenant's context rejects it; platform-account
   JWTs (HS256, platform-issued) validate through tier-1b; both kinds
   carry/bind the ``tenant`` claim.
2. LOGIN ENDPOINTS — ``GET /auth/tenant`` discovery respects the
   slug→own-slot rule (``sign_in_ready`` only with an own user provider);
   ``GET /auth/tenant-memberships`` works with BOTH token kinds through
   the bootstrap (tenant-less) validation path.
3. PROVIDER SLOTS — (tenant, scope) uniqueness enforced at the DATABASE
   level; NULL-tenant (shared) rows are inert; tenancy OFF resolves the
   ROOT slot only.
4. INTERNAL ENDPOINTS — signed ``X-Internal-Tenant-*`` headers accepted
   (fresh timestamp); headerless / tampered / stale rejected 401
   fail-closed; AR/CH receivers stay forward-only (no signing imports).
5. WS CHAT — the chat WebSocket authenticates BOTH token kinds; a token
   with an unknown tenant slug claim closes 4003; a valid token binds the
   tenant context for the connection; unauthenticated closes 1008.
6. AGENT OAUTH — authorize resolves the own-tenant agent provider only
   (ROOT slot for the tenant-less path); missing provider config yields a
   clear error; token refresh uses the identity's tenant slot strictly.

Pattern: real PostgreSQL (``parthenon_test``) where the database matters
(uniqueness, discovery, memberships, WS tenant resolution, agent OAuth),
unit-style fakes elsewhere — mirroring ``_strict_tenant_utils`` and
``test_tenant_adoption.py``.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.oidc_client import OIDCError  # noqa: E402
from app.core.tenant_context import (  # noqa: E402
    TenantContext,
    get_current_tenant_context,
    reset_current_tenant_context,
    set_current_tenant_context,
)
from app.core.tenant_signature import (  # noqa: E402
    TENANT_SIGNATURE_HEADER,
    TENANT_TIMESTAMP_HEADER,
    build_tenant_signature_headers,
    verify_tenant_signature_headers,
)
from app.db.models.identity_provider_config import IdentityProviderConfig  # noqa: E402
from app.db.models.platform_user import PlatformUser  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_membership import (  # noqa: E402
    TenantUserMembership,
)
from tests.integration._strict_tenant_utils import (  # noqa: E402,F401
    TEST_DB_URL,
    create_two_tenants,
    db,
    make_module_schema_fixture,
)

_schema = make_module_schema_fixture()

TAG = uuid.uuid4().hex[:6]


# ── Shared helpers ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_settings_singleton():
    """Isolate the process-wide PlatformSettingsService cache per test."""
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


def _provider_row(scope, tenant_id, issuer, client_id=None):
    return IdentityProviderConfig(
        provider_scope=scope,
        provider_type="keycloak",
        display_name=f"{scope}-{tenant_id or 'shared'}-{TAG}",
        issuer_url=issuer,
        client_id=client_id or f"client-{scope}-{tenant_id or 'shared'}",
        encrypted_client_secret=None,
        is_enabled=True,
        tenant_id=tenant_id,
    )


async def _fresh_registry(db, enabled: bool):
    """Build and initialize a registry from the current DB state."""
    await _set_tenancy(db, enabled)
    from app.services.oidc_provider_registry import OIDCProviderRegistry

    registry = OIDCProviderRegistry()
    await registry.initialize(db)
    return registry


async def _get_or_create_root(db):
    """Fetch the ROOT tenant (creating it once if missing)."""
    from sqlalchemy import select

    result = await db.execute(
        select(Tenant).where(Tenant.is_system_tenant.is_(True))
    )
    root = result.scalars().first()
    if root is None:
        tag = uuid.uuid4().hex[:6]
        root = Tenant(
            name=f"Root-{tag}", slug=f"root-{tag}", is_system_tenant=True
        )
        db.add(root)
        await db.flush()
    return root


async def _clear_provider_rows(db, scope: str) -> None:
    """Delete all provider rows of *scope* (both NULL-tenant legacy rows —
    limited to one per scope by a partial unique index — and rows of
    root/other tenants staged by earlier tests in the shared schema)."""
    from sqlalchemy import delete

    await db.execute(
        delete(IdentityProviderConfig).where(
            IdentityProviderConfig.provider_scope == scope
        )
    )
    await db.commit()


def _ctx(tenant) -> TenantContext:
    return TenantContext(
        tenant_id=tenant.id, slug=tenant.slug, name=tenant.name
    )


class _IssuersAwareOIDCClient:
    """Fake OIDCClient: a token of the form ``tok-<issuer-tag>`` validates
    ONLY at the provider whose issuer carries that tag — mirroring real
    signature checks (a token from realm A cannot verify in realm B)."""

    captured_issuer: str | None = None

    def __init__(self, *, issuer_url, client_id, **kwargs):
        _IssuersAwareOIDCClient.captured_issuer = issuer_url
        self.issuer_url = issuer_url

    async def validate_token(self, token: str) -> dict:
        tag = token.removeprefix("tok-")
        if tag and tag in self.issuer_url:
            return {"sub": f"user-{tag}", "email": f"{tag}@example.test"}
        raise OIDCError("signature verification failed")


def _patch_registry(registry):
    import app.main as main_module

    return patch.object(main_module, "_get_registry", lambda: registry)


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 1 — TOKEN LAYER
# ═════════════════════════════════════════════════════════════════════════════


class TestTokenLayer:
    @pytest.fixture
    async def two_tenant_setup(self, db):
        """Tenancy ON; tenants A and B each with their OWN user provider,
        with per-tenant issuer tags (token ``tok-<tag>`` only validates at
        the provider whose issuer carries that tag)."""
        tenant_a, tenant_b = await create_two_tenants(db)
        tag_a = f"a{uuid.uuid4().hex[:8]}"
        tag_b = f"b{uuid.uuid4().hex[:8]}"
        issuer_a = f"https://idp-{tag_a}.example.com"
        issuer_b = f"https://idp-{tag_b}.example.com"
        db.add(_provider_row("user", tenant_a.id, issuer_a))
        db.add(_provider_row("user", tenant_b.id, issuer_b))
        await db.commit()
        registry = await _fresh_registry(db, True)
        return tenant_a, tenant_b, registry, tag_a, tag_b

    async def test_oidc_token_validates_against_own_tenant_provider_only(
        self, two_tenant_setup
    ):
        """Tier 2: with tenant A resolved, the token validates against A's
        OWN provider slot — the tenant claim is injected from that login
        context."""
        import app.middleware.auth as auth_module

        tenant_a, _tenant_b, registry, tag_a, _tag_b = two_tenant_setup
        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _IssuersAwareOIDCClient
        ):
            claims = await auth_module._try_oidc_token(f"tok-{tag_a}", _ctx(tenant_a))
        assert claims is not None, "own-slot token must validate"
        assert _IssuersAwareOIDCClient.captured_issuer == (
            f"https://idp-{tag_a}.example.com"
        ), "validation must hit tenant A's OWN provider"
        assert claims["tenant"] == tenant_a.slug, (
            "tenant claim injected from the resolved login context"
        )

    async def test_token_rejected_when_presented_in_another_tenants_context(
        self, two_tenant_setup
    ):
        """Cross-tenant: a token issued by A's provider cannot validate in
        B's context — B's own slot is the only candidate and the signature
        check fails there.  No chain, no shared slot, fail-closed."""
        import app.middleware.auth as auth_module

        tenant_a, tenant_b, registry, tag_a, _tag_b = two_tenant_setup
        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _IssuersAwareOIDCClient
        ):
            assert (
                await auth_module._try_oidc_token(f"tok-{tag_a}", _ctx(tenant_b))
                is None
            ), "A's token must NOT validate in tenant B's context"

    async def test_platform_account_token_validates_via_tier1_hs256(
        self, db, two_tenant_setup
    ):
        """Tier 1b: a platform-issued account JWT (HS256, ``platform_account``
        marker, kid-default secret) validates through the tier pipeline and
        NEVER touches the per-tenant OIDC registry."""
        import app.middleware.auth as auth_module

        tenant_a, _tenant_b, registry, _tag_a, _tag_b = two_tenant_setup
        from app.services.tenancy.platform_account_auth_service import (
            create_platform_account_token,
        )

        user = SimpleNamespace(
            sub=f"platform_account:{uuid.uuid4()}",
            email="owner@example.test",
            display_name="Owner",
        )
        token = create_platform_account_token(user=user, tenant=tenant_a)

        # The registry has no need to participate — assert OIDC is never
        # consulted by spying on the tier-2 function.
        with _patch_registry(registry), patch.object(
            auth_module, "_try_oidc_token", side_effect=AssertionError(
                "platform token must not fall through to OIDC"
            )
        ):
            claims, is_super_admin = await auth_module.validate_raw_token(
                token, _ctx(tenant_a)
            )
        assert is_super_admin is False
        assert claims is not None
        assert claims["platform_account"] is True
        assert claims["tenant"] == tenant_a.slug
        assert claims["tenant_id"] == str(tenant_a.id)

    async def test_both_token_kinds_carry_and_bind_tenant_claim(
        self, two_tenant_setup, db_session_factory_patch
    ):
        """Both kinds bind the tenant claim: OIDC gets it injected from the
        validating login context; the platform token carries it natively —
        both equal to the resolved tenant slug, so the claim check admits
        them and rejects any other tenant."""
        import app.middleware.auth as auth_module
        from app.services.tenancy.platform_account_auth_service import (
            create_platform_account_token,
        )

        tenant_a, tenant_b, registry, tag_a, _tag_b = two_tenant_setup

        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _IssuersAwareOIDCClient
        ):
            oidc_claims = await auth_module._try_oidc_token(
                f"tok-{tag_a}", _ctx(tenant_a)
            )
        assert oidc_claims is not None
        assert oidc_claims["tenant"] == tenant_a.slug

        platform_token = create_platform_account_token(
            user=SimpleNamespace(
                sub=f"platform_account:{uuid.uuid4()}",
                email="owner@example.test",
                display_name="Owner",
            ),
            tenant=tenant_a,
        )
        platform_claims, _ = await auth_module.validate_raw_token(
            platform_token, _ctx(tenant_a)
        )
        assert platform_claims["tenant"] == tenant_a.slug

        # The claim check rejects a valid token presented for the WRONG
        # tenant (mismatch = security-relevant rejection).
        middleware = auth_module.JWTAuthMiddleware(app=None)
        request = _fake_request(_ctx(tenant_b))
        error = await middleware._check_tenant_claim(
            request, platform_claims, is_super_admin=False
        )
        assert error is not None, "tenant claim mismatch must be rejected"
        assert error == "Token is not valid for this tenant"


def _fake_request(resolved_tenant):
    """Minimal request stub carrying a resolved tenant context (tenancy ON)."""
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/probe",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    request = Request(scope)
    request.state.tenant_context = resolved_tenant
    request.state.tenancy_enabled = True
    return request


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 2 — LOGIN ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════


class _FakeSettings:
    """Platform-settings stub for the tenancy switch."""

    def __init__(self, enabled: bool):
        self._enabled = enabled

    async def is_multi_tenancy_enabled(self, db):  # noqa: ANN001
        return self._enabled


def _login_app(db):
    """FastAPI app hosting the real tenant auth router (DB overridden)."""
    from app.api.v1.auth_tenant import TenantAuthRouter
    from app.db.session import get_db

    app = FastAPI()
    app.include_router(TenantAuthRouter, prefix="/api/v1")

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return app


def _bearer_wrapper(app):
    """ASGI wrapper emulating the auth middleware: validates the bearer
    token through the REAL tier pipeline (bootstrap, no tenant context)
    and binds ``request.state.identity`` from the resulting claims."""

    async def middleware(scope, receive, send):
        if scope["type"] == "http":
            headers = {
                k.decode().lower(): v.decode()
                for k, v in scope.get("headers", [])
            }
            auth = headers.get("authorization", "")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else None
            import app.middleware.auth as auth_module

            claims = None
            if token:
                claims, _is_super = await auth_module.validate_raw_token(token, None)
            if claims is None:
                await JSONResponse(
                    {"detail": "Authentication failed"}, status_code=401
                )(scope, receive, send)
                return
            scope.setdefault("state", {})["identity"] = claims
        await app(scope, receive, send)

    return middleware


class TestLoginEndpoints:
    async def test_tenant_discovery_sign_in_ready_only_with_own_user_provider(
        self, db
    ):
        """GET /auth/tenant: an active tenant with its OWN user provider is
        ``sign_in_ready``; a tenant without one is NOT — the shared slot is
        retired and never fills in.  Unknown slugs report no tenant."""
        tenant_a, tenant_b = await create_two_tenants(db)
        await _clear_provider_rows(db, "user")
        db.add(_provider_row("user", tenant_a.id, f"https://a-{TAG}.example.com"))
        # Inert legacy shared row — must NOT make tenant B sign-in ready.
        db.add(_provider_row("user", None, f"https://legacy-{TAG}.example.com"))
        await db.commit()

        registry = await _fresh_registry(db, True)
        import app.api.v1.auth_tenant as auth_tenant_module

        with _patch_registry(registry), patch.object(
            auth_tenant_module,
            "get_platform_settings_service",
            lambda: _FakeSettings(True),
        ):
            transport = ASGITransport(app=_login_app(db))
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                ready = await c.get("/api/v1/auth/tenant", params={"slug": tenant_a.slug})
                not_ready = await c.get("/api/v1/auth/tenant", params={"slug": tenant_b.slug})
                unknown = await c.get("/api/v1/auth/tenant", params={"slug": f"ghost-{TAG}"})

        assert ready.status_code == 200
        body = ready.json()
        assert body["multi_tenancy_enabled"] is True
        assert body["tenant"]["slug"] == tenant_a.slug
        assert body["tenant"]["sign_in_ready"] is True

        assert not_ready.status_code == 200
        assert not_ready.json()["tenant"]["sign_in_ready"] is False, (
            "no own provider ⇒ NOT sign-in ready (shared slot retired)"
        )
        assert unknown.json()["tenant"] is None

    async def test_tenant_discovery_inert_when_tenancy_off(self, db):
        """GET /auth/tenant with the switch OFF carries no tenant at all —
        the deployment defaults entirely to the root tenant."""
        import app.api.v1.auth_tenant as auth_tenant_module

        with patch.object(
            auth_tenant_module,
            "get_platform_settings_service",
            lambda: _FakeSettings(False),
        ):
            transport = ASGITransport(app=_login_app(db))
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                response = await c.get("/api/v1/auth/tenant", params={"slug": "anything"})

        body = response.json()
        assert body["multi_tenancy_enabled"] is False
        assert body["tenant"] is None

    async def test_tenant_memberships_works_with_both_token_kinds_bootstrap(
        self, db
    ):
        """GET /auth/tenant-memberships: BOTH token kinds validate through
        the bootstrap (NO tenant context) tier pipeline and surface the
        caller's own memberships — default tenant first."""
        import app.middleware.auth as auth_module
        from app.services.tenancy.platform_account_auth_service import (
            create_platform_account_token,
        )

        tenant_a, tenant_b = await create_two_tenants(db)
        db.add(_provider_row("user", tenant_a.id, f"https://a-{TAG}.example.com"))
        await db.commit()

        registry = await _fresh_registry(db, True)

        platform_user = PlatformUser(
            sub=f"platform_account:{uuid.uuid4()}",
            email=f"owner-{TAG}@example.test",
            display_name="Owner",
        )
        oidc_user = PlatformUser(
            sub=f"user-{TAG}",
            email=f"federated-{TAG}@example.test",
            display_name="Federated",
        )
        db.add_all([platform_user, oidc_user])
        await db.flush()
        db.add_all([
            TenantUserMembership(
                tenant_id=tenant_a.id, user_id=platform_user.id,
                tenant_role="tenant_admin", is_default=True,
            ),
            TenantUserMembership(
                tenant_id=tenant_b.id, user_id=platform_user.id,
                tenant_role="member", is_default=False,
            ),
            TenantUserMembership(
                tenant_id=tenant_b.id, user_id=oidc_user.id,
                tenant_role="tenant_admin", is_default=True,
            ),
        ])
        await db.commit()

        platform_token = create_platform_account_token(
            user=platform_user, tenant=tenant_a
        )

        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _IssuersAwareOIDCClient
        ):
            transport = ASGITransport(
                app=_bearer_wrapper(_login_app(db))
            )
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                via_platform = await c.get(
                    "/api/v1/auth/tenant-memberships",
                    headers={"Authorization": f"Bearer {platform_token}"},
                )
                via_oidc = await c.get(
                    "/api/v1/auth/tenant-memberships",
                    headers={"Authorization": f"Bearer tok-{TAG}"},
                )
                unauthenticated = await c.get("/api/v1/auth/tenant-memberships")

        assert via_platform.status_code == 200
        platform_items = via_platform.json()["items"]
        assert [i["tenant_slug"] for i in platform_items] == [
            tenant_a.slug, tenant_b.slug
        ], "own memberships, default tenant first"
        assert platform_items[0]["tenant_role"] == "tenant_admin"

        assert via_oidc.status_code == 200
        oidc_items = via_oidc.json()["items"]
        assert [i["tenant_slug"] for i in oidc_items] == [tenant_b.slug], (
            "the OIDC caller sees only their own membership"
        )

        assert unauthenticated.status_code == 401


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 3 — PROVIDER SLOTS
# ═════════════════════════════════════════════════════════════════════════════


class TestProviderSlots:
    async def test_tenant_scope_uniqueness_enforced_at_db_level(self, db):
        """The (tenant_id, provider_scope) UNIQUE constraint lives in the
        DATABASE — a second provider row for the same (tenant, scope) is an
        IntegrityError even outside the service layer."""
        from app.db.models.tenant import Tenant

        suffix = uuid.uuid4().hex[:6]
        tenant = Tenant(name=f"slot-{suffix}", slug=f"slot-{suffix}")
        db.add(tenant)
        await db.flush()
        db.add(_provider_row("user", tenant.id, f"https://one-{TAG}.example.com"))
        await db.commit()

        db.add(_provider_row("user", tenant.id, f"https://two-{TAG}.example.com"))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    async def test_null_tenant_rows_are_inert(self, db):
        """NULL-tenant (shared) rows are inert legacy data: the registry
        never loads them, so a tenant without its own provider resolves
        NOTHING even when a shared row exists — fail-closed."""
        tenant_a, _ = await create_two_tenants(db)
        await _clear_provider_rows(db, "user")
        db.add(_provider_row("user", None, f"https://shared-{TAG}.example.com"))
        await db.commit()

        registry = await _fresh_registry(db, True)
        assert registry.get_user_provider(tenant_id=tenant_a.id) is None
        assert all(
            p.tenant_id is not None for p in registry.list_providers()
        ), "shared (NULL-tenant) rows never load"
        import app.middleware.auth as auth_module

        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _IssuersAwareOIDCClient
        ):
            assert await auth_module._try_oidc_token("any", _ctx(tenant_a)) is None

    async def test_tenancy_off_resolves_root_slot_only(self, db):
        """Switch OFF: ONLY the ROOT tenant's (root_id, scope) slot loads —
        other tenants' rows and shared rows never enter the map; the root
        slot serves as the default (single-tenant) provider."""
        tenant_a, _ = await create_two_tenants(db)
        await _clear_provider_rows(db, "user")
        root = await _get_or_create_root(db)
        issuer_root = f"https://root-{TAG}.example.com"
        db.add(_provider_row("user", root.id, issuer_root))
        db.add(_provider_row("user", tenant_a.id, f"https://a-{TAG}.example.com"))
        await db.commit()

        registry = await _fresh_registry(db, False)
        assert registry.multi_tenancy_enabled is False
        loaded = registry.list_providers()
        assert [p.issuer_url for p in loaded] == [issuer_root], (
            "tenancy OFF ⇒ ONLY the root tenant's row loads"
        )
        # Tenant-less and any tenant argument resolve the ROOT slot
        # (the root tenant IS the default tenant when the switch is off).
        assert registry.get_user_provider(tenant_id=None).issuer_url == issuer_root
        assert registry.get_provider_candidates("user", None) == [loaded[0]]


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 4 — INTERNAL ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════


def _internal_app(db):
    from app.api.deps import require_internal_tenant_context
    from app.db.session import get_db

    app = FastAPI()

    @app.get("/probe")
    async def probe(tenant_ctx=Depends(require_internal_tenant_context)):
        return {"tenant_id": str(tenant_ctx.tenant_id), "slug": tenant_ctx.slug}

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return app


class TestInternalEndpoints:
    @pytest.fixture
    def mt_on(self, monkeypatch):
        import app.services.tenancy.platform_settings_service as pss

        monkeypatch.setattr(pss, "get_platform_settings_service", lambda: _FakeSettings(True))

    @pytest.fixture
    async def client(self, db, mt_on):
        import time as _time

        transport = ASGITransport(app=_internal_app(db))
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            c._time = _time
            yield c

    async def test_signed_headers_accepted_and_bind_tenant(self, client, db):
        """A correct signed set (matching tenant + fresh timestamp) is
        accepted and binds the signed tenant context."""
        tenant_a, _ = await create_two_tenants(db)
        headers = build_tenant_signature_headers(_ctx(tenant_a))
        response = await client.get("/probe", headers=headers)
        assert response.status_code == 200
        assert response.json()["slug"] == tenant_a.slug

    async def test_headerless_fail_closed_401(self, client, db):
        """Tenancy ON, no headers at all → 401 BEFORE any data access."""
        response = await client.get("/probe")
        assert response.status_code == 401

    async def test_tampered_headers_401(self, client, db):
        """A flipped signature byte (tampered/forged set) → 401."""
        tenant_a, _ = await create_two_tenants(db)
        headers = build_tenant_signature_headers(_ctx(tenant_a))
        headers[TENANT_SIGNATURE_HEADER] = "f" * 64
        response = await client.get("/probe", headers=headers)
        assert response.status_code == 401

    async def test_stale_timestamp_401(self, client, db):
        """A correctly signed but STALE set (replay outside the window) → 401."""
        tenant_a, _ = await create_two_tenants(db)
        stale = build_tenant_signature_headers(
            _ctx(tenant_a), timestamp=client._time.time() - 600
        )
        response = await client.get("/probe", headers=stale)
        assert response.status_code == 401

    async def test_wrong_tenant_binding_rejected(self, db):
        """When the expected binding is tenant B, a VALID signature for
        tenant A must be rejected (session tenant containment)."""
        tenant_a, tenant_b = await create_two_tenants(db)
        headers = build_tenant_signature_headers(_ctx(tenant_a))
        import app.core.tenant_signature as ts

        with pytest.raises(ts.TenantSignatureError):
            verify_tenant_signature_headers(
                headers, expected_tenant_id=tenant_b.id
            )

    def test_receiver_trees_are_forward_only(self):
        """Structural guard: Agent Runtime and Communication Hub trees never
        sign tenant contexts — the signing capability stays CC-only (plus
        the WS session signer in app/api/ws/chat.py by design)."""
        import pathlib

        backend = pathlib.Path(__file__).resolve().parents[2]
        signing_symbols = (
            "build_tenant_signature_headers",
            "sign_context_for_authenticated_session",
            "tenant_context_headers(",
        )
        for tree in ("app/agent_runtime", "app/communication_hub"):
            for path in (backend / tree).rglob("*.py"):
                source = path.read_text()
                for symbol in signing_symbols:
                    assert symbol not in source, (
                        f"{path} must not sign tenant contexts ({symbol})"
                    )
        # CH data client stays forward-only (via the internal_http egress hook).
        data_client = (backend / "app/communication_hub/data_client.py").read_text()
        assert "internal_httpx_client(" in data_client
        assert "forward_tenant_headers()" not in data_client
        assert "build_tenant_signature_headers" not in data_client


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 5 — WS CHAT
# ═════════════════════════════════════════════════════════════════════════════


class _FakeOIDCGateway:
    """Fake module-level OIDC gateway for the WS handler."""

    def __init__(self, accept: bool):
        self._accept = accept

    async def validate_token(self, token):
        if not self._accept:
            raise OIDCError("invalid token")
        return {"sub": "ws-user", "email": "ws@example.test"}


@pytest.fixture
def ws_app(monkeypatch):
    """Chat WS app with the global session factory pointed at parthenon_test.

    The TestClient drives the app on its OWN event loop, so the patched
    factory builds a fresh engine PER CALL — connections always bind to
    whichever loop is running the handler.
    """
    import app.db.session as db_session_module

    def _factory():
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        engine = create_async_engine(TEST_DB_URL)
        return async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )()

    monkeypatch.setattr(db_session_module, "AsyncSessionLocal", _factory)
    app = FastAPI()
    from app.api.ws.chat import ws_router

    app.include_router(ws_router)
    return app


class TestWsChatAuth:
    def test_oidc_token_accepted(self, ws_app, monkeypatch):
        """The chat WebSocket accepts an OIDC token (tier: registry/IdP)."""
        from app.api.ws import chat

        monkeypatch.setattr(
            chat, "get_oidc_client", lambda: _FakeOIDCGateway(accept=True)
        )
        with TestClient(ws_app) as client:
            with client.websocket_connect(
                f"/ws/sessions/{uuid.uuid4()}?token=oidc-token"
            ):
                pass  # connect succeeding = accepted (reject would close 1008)

    @pytest.mark.asyncio
    async def test_platform_account_token_accepted(self, ws_app, monkeypatch, db):
        """The chat WebSocket accepts a platform-account token too (the
        fixed bug: platform-issued users could never connect)."""
        from app.api.ws import chat
        from app.services.tenancy.platform_account_auth_service import (
            create_platform_account_token,
        )

        tenant, _second = await create_two_tenants(db)
        token = create_platform_account_token(
            user=SimpleNamespace(
                sub=f"platform_account:{uuid.uuid4()}",
                email="ws@example.test",
                display_name="WS",
            ),
            tenant=tenant,
        )
        monkeypatch.setattr(
            chat, "get_oidc_client", lambda: _FakeOIDCGateway(accept=False)
        )
        with TestClient(ws_app) as client:
            with client.websocket_connect(
                f"/ws/sessions/{uuid.uuid4()}?token={token}"
            ):
                pass

    @pytest.mark.asyncio
    async def test_unknown_tenant_slug_claim_closes_4003(
        self, ws_app, monkeypatch, db
    ):
        """A token whose tenant slug claim matches no tenant closes the
        connection with 4003 — never an unscoped connection."""
        import anyio

        from app.api.ws import chat
        from app.services.tenancy.platform_account_auth_service import (
            create_platform_account_token,
        )

        token = create_platform_account_token(
            user=SimpleNamespace(
                sub=f"platform_account:{uuid.uuid4()}",
                email="ghost@example.test",
                display_name="Ghost",
            ),
            tenant=SimpleNamespace(slug=f"ghost-tenant-{TAG}", id=uuid.uuid4()),
        )
        monkeypatch.setattr(
            chat, "get_oidc_client", lambda: _FakeOIDCGateway(accept=False)
        )
        with TestClient(ws_app) as client:
            with client.websocket_connect(
                f"/ws/sessions/{uuid.uuid4()}?token={token}"
            ) as ws:
                with pytest.raises(WebSocketDisconnect) as excinfo:
                    await anyio.to_thread.run_sync(ws.receive_text)
        assert excinfo.value.code == 4003

    @pytest.mark.asyncio
    async def test_valid_token_binds_tenant_context_for_connection(
        self, ws_app, monkeypatch, db
    ):
        """A valid token with a real tenant slug claim binds that tenant as
        the connection's tenant context (verified via the real resolution
        service against parthenon_test)."""
        import anyio

        from app.api.ws import chat
        from app.services.tenancy.platform_account_auth_service import (
            create_platform_account_token,
        )

        tenant, _second = await create_two_tenants(db)
        token = create_platform_account_token(
            user=SimpleNamespace(
                sub=f"platform_account:{uuid.uuid4()}",
                email="bind@example.test",
                display_name="Bind",
            ),
            tenant=tenant,
        )
        monkeypatch.setattr(
            chat, "get_oidc_client", lambda: _FakeOIDCGateway(accept=False)
        )

        import app.core.tenant_context as tenant_ctx_module

        captured: list[TenantContext] = []
        real_set = tenant_ctx_module.set_current_tenant_context

        def _capturing_set(context):
            captured.append(context)
            return real_set(context)

        monkeypatch.setattr(
            tenant_ctx_module, "set_current_tenant_context", _capturing_set
        )

        with TestClient(ws_app) as client:
            with client.websocket_connect(
                f"/ws/sessions/{uuid.uuid4()}?token={token}"
            ) as ws:
                # Let the handler finish the connect-time tenant binding.
                with anyio.fail_after(5):
                    await anyio.to_thread.run_sync(
                        lambda: ws.send_json({"message": ""})
                    )
                await anyio.sleep(0.5)
        assert captured, "tenant context must be bound at connect time"
        assert captured[0].slug == tenant.slug
        assert str(captured[0].tenant_id) == str(tenant.id)

    def test_unauthenticated_closes_1008(self, ws_app, monkeypatch):
        """No token / an invalid token → policy-violation close (1008)."""
        from app.api.ws import chat

        monkeypatch.setattr(
            chat, "get_oidc_client", lambda: _FakeOIDCGateway(accept=False)
        )
        with TestClient(ws_app) as client:
            with pytest.raises(WebSocketDisconnect) as excinfo:
                with client.websocket_connect(
                    f"/ws/sessions/{uuid.uuid4()}"
                ):
                    pass
        assert excinfo.value.code == 1008


# ═════════════════════════════════════════════════════════════════════════════
# Scenario 6 — AGENT OAUTH
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def discovery_stub(monkeypatch):
    """Stub OIDC discovery so endpoint resolution needs no network."""

    async def fake_test_connection(self, *, issuer_url):
        return {
            "ok": True,
            "discovery_doc": {
                "authorization_endpoint": f"{issuer_url.rstrip('/')}/auth",
                "token_endpoint": f"{issuer_url.rstrip('/')}/token",
            },
        }

    import app.services.oidc_config_service as config_service_module

    monkeypatch.setattr(
        config_service_module.OIDCConfigService,
        "test_connection",
        fake_test_connection,
    )


@pytest.fixture
def db_session_factory_patch(monkeypatch):
    """Point the service-layer global session factory at parthenon_test."""
    import sqlalchemy.ext.asyncio as sa_asyncio

    import app.db.session as db_session_module

    engine = sa_asyncio.create_async_engine(TEST_DB_URL)
    SessionLocal = sa_asyncio.async_sessionmaker(
        engine, class_=sa_asyncio.AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(db_session_module, "AsyncSessionLocal", SessionLocal)
    yield
    import asyncio

    asyncio.new_event_loop().run_until_complete(engine.dispose())


class TestAgentOAuth:
    async def test_authorize_resolves_own_tenant_agent_provider_only(
        self, db, monkeypatch, discovery_stub, db_session_factory_patch
    ):
        """With tenant A's context bound, the OAuth authorize URL is built
        from A's OWN agent provider slot — never B's, never the root's."""
        tenant_a, tenant_b = await create_two_tenants(db)
        await _clear_provider_rows(db, "agent")
        root = await _get_or_create_root(db)
        issuer_a = f"https://agent-a-{TAG}.example.com"
        db.add_all([
            _provider_row("agent", tenant_a.id, issuer_a),
            _provider_row("agent", tenant_b.id, f"https://agent-b-{TAG}.example.com"),
            _provider_row("agent", root.id, f"https://agent-root-{TAG}.example.com"),
        ])
        await db.commit()

        token = set_current_tenant_context(_ctx(tenant_a))
        try:
            from app.services.agents.identity_service import AgentIdentityService

            url = await AgentIdentityService().get_oauth_authorize_url(
                "state-1", "https://front/callback"
            )
        finally:
            reset_current_tenant_context(token)

        assert f"client-a" in url or f"agent-a-{TAG}" in url
        assert url.startswith(f"https://agent-a-{TAG}.example.com/auth"), (
            "authorize URL must come from tenant A's OWN agent slot"
        )
        assert f"agent-b-{TAG}" not in url
        assert f"agent-root-{TAG}" not in url

    async def test_authorize_tenant_less_resolves_root_slot(
        self, db, monkeypatch, discovery_stub, db_session_factory_patch
    ):
        """Bootstrap/tenant-less path (tenancy-off legacy semantics): with
        no bound context, authorize resolves the ROOT tenant's agent slot —
        never another tenant's, never the retired shared row."""
        tenant_a, _ = await create_two_tenants(db)
        await _clear_provider_rows(db, "agent")
        root = await _get_or_create_root(db)
        db.add_all([
            _provider_row("agent", root.id, f"https://agent-root-{TAG}.example.com"),
            _provider_row("agent", tenant_a.id, f"https://agent-a-{TAG}.example.com"),
        ])
        await db.commit()

        assert get_current_tenant_context() is None
        from app.services.agents.identity_service import AgentIdentityService

        url = await AgentIdentityService().get_oauth_authorize_url(
            "state-2", "https://front/callback"
        )
        assert url.startswith(f"https://agent-root-{TAG}.example.com/auth")
        assert f"agent-a-{TAG}" not in url
        assert f"shared-agent-{TAG}" not in url

    async def test_authorize_without_config_clear_error(self, db, monkeypatch, discovery_stub, db_session_factory_patch):
        """A tenant with NO agent provider config produces a clear,
        actionable error (never a silent mis-route to another slot)."""
        tenant_a, _ = await create_two_tenants(db)
        await _clear_provider_rows(db, "agent")
        root = await _get_or_create_root(db)
        # Only the ROOT slot configured — tenant A has NO agent provider.
        db.add(_provider_row("agent", root.id, f"https://agent-root-{TAG}.example.com"))
        await db.commit()

        token = set_current_tenant_context(_ctx(tenant_a))
        try:
            from app.services.agents.identity_service import (
                AgentIdentityService,
                AgentOAuthError,
            )

            with pytest.raises(AgentOAuthError) as excinfo:
                await AgentIdentityService().get_oauth_authorize_url(
                    "state-3", "https://front/callback"
                )
        finally:
            reset_current_tenant_context(token)
        assert "No agent identity provider configured" in str(excinfo.value)

    async def test_token_refresh_uses_identity_tenant_slot_strictly(
        self, db, monkeypatch, discovery_stub
    ):
        """Refreshing an identity's token hits the token endpoint of the
        identity's OWN tenant slot — even with other tenants' and the
        root's agent providers configured.  Stored tokens stay encrypted;
        the new pair must decrypt to what the IdP returned."""
        import app.services.agents.identity_service as identity_module
        from app.db.models.agents import AgentIdentity, AgentIdentityType

        tenant_a, tenant_b = await create_two_tenants(db)
        await _clear_provider_rows(db, "agent")
        root = await _get_or_create_root(db)
        issuer_a = f"https://agent-a-{TAG}.example.com"
        db.add_all([
            _provider_row("agent", tenant_a.id, issuer_a),
            _provider_row("agent", tenant_b.id, f"https://agent-b-{TAG}.example.com"),
            _provider_row("agent", root.id, f"https://agent-root-{TAG}.example.com"),
        ])
        await db.flush()

        identity = AgentIdentity(
            tenant_id=tenant_a.id,
            name=f"bot-{TAG}",
            identity_type=AgentIdentityType.realm_user,
            realm_name="ai_agents",
            realm_username=f"bot-{TAG}",
        )
        db.add(identity)
        await db.flush()
        identity.refresh_token = identity_module.get_vault().encrypt("refresh-token")
        await db.commit()

        captured: dict = {}

        class _FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 300,
                }

        class _FakeAsyncClient:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, **kwargs):
                captured["url"] = url
                captured["data"] = kwargs.get("data")
                return _FakeResponse()

        monkeypatch.setattr(
            identity_module.httpx, "AsyncClient", _FakeAsyncClient
        )

        from app.services.agents.identity_service import AgentIdentityService

        updated = await AgentIdentityService().refresh_token(identity.id, db)
        assert identity_module.get_vault().decrypt(updated.access_token) == (
            "new-access"
        )
        assert updated.encrypted_refresh_token is not None
        assert identity_module.get_vault().decrypt(updated.encrypted_refresh_token) == (
            "new-refresh"
        )
        assert captured["url"] == f"{issuer_a}/token", (
            "refresh must use the identity's OWN tenant slot endpoint"
        )
        assert captured["data"]["refresh_token"] == "refresh-token"
