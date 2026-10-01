"""FIX-20260929-043443 reproduction — OIDC tokens never carry the ``tenant`` claim.

Issue: OIDC sign-in succeeds, the dashboard renders and starts loading, then
the user is redirected back to /login mid-load.

Chain (verified in code):

1. A workspace-bound OIDC sign-in completes; dashboard calls go out with
   ``X-Tenant: <workspace>`` and the provider-issued Bearer token.
2. ``JWTAuthMiddleware`` validates the token against the tenant's own
   provider (``_try_oidc_token`` — this part works).
3. ``_check_tenant_claim`` (app/middleware/auth.py L362-373) then REQUIRES
   the token to carry a ``tenant`` claim equal to the resolved tenant.
4. **The OIDC path never provisions that claim.**  The only protocol mapper
   the platform ever creates is the ``groups`` membership mapper
   (identity/bootstrap_service.py, keycloak_admin_client.py); neither
   ``_try_oidc_token`` nor ``OIDCClient.validate_token`` injects a tenant
   claim; only ``create_platform_account_token`` (the password sign-in /
   sign-up path) embeds ``tenant``.  An external/tenant-scoped provider
   therefore issues tokens with NO tenant claim.
5. Result: EVERY authenticated request from an OIDC session in multi-tenant
   mode is rejected with 401 "Token is not valid for this tenant" → the
   frontend axios 401 interceptor wipes the tokens and redirects to
   /login — the reported symptom.

These tests run the exact middleware pipeline (validate → claim check) with
a token from the tenant's OWN provider, in the realistic claim shape an
OIDC provider issues (standard identity claims, no tenant claim).

Related suite: backend/tests/test_tenant_oidc_isolation.py covers the claim
check mechanics (missing/mismatch/match) with synthetic claims; the gap
demonstrated here is that the REAL OIDC claim shape never satisfies it.
"""
from __future__ import annotations

import os
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.tenant_context import TenantContext  # noqa: E402
from app.db.session import Base  # noqa: E402

TENANT_TESTCOM = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

CTX_TESTCOM = TenantContext(
    tenant_id=TENANT_TESTCOM, slug="test-com", name="Test Com"
)


@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory engine per test (audit writes need a DB)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def _fresh_settings_singleton():
    """Isolate the process-wide PlatformSettingsService cache per test."""
    import app.services.tenancy.platform_settings_service as settings_module

    settings_module._service = None
    yield
    settings_module._service = None


def _audit_patch(test_engine):
    """Point the audit writer's AsyncSessionLocal at the test DB."""
    import app.db.session as db_session_module

    SessionLocal = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    return patch.object(db_session_module, "AsyncSessionLocal", SessionLocal)


class _FakeRegistry:
    """Registry stub exposing provider resolution + secrets only."""

    def __init__(self, providers: dict, initialized: bool = True):
        self._providers = providers  # (tenant_key, scope) -> (issuer, client_id)
        self.initialized = initialized
        self._multi_tenancy_enabled = True

    def get_provider(self, scope, tenant_id=None, is_system_tenant=False):
        key = (str(tenant_id) if tenant_id else None, scope)
        if key not in self._providers and is_system_tenant:
            key = (None, scope)
        entry = self._providers.get(key)
        if entry is None:
            return None
        return SimpleNamespace(
            issuer_url=entry[0], client_id=entry[1], claim_mappings={}
        )

    def get_decrypted_secret(self, scope, tenant_id=None, is_system_tenant=False):
        return None

    def has_any_provider(self):
        return len(self._providers) > 0


def _patch_registry(registry):
    import app.main as main_module

    return patch.object(main_module, "_get_registry", lambda: registry)


class _FakeOIDCClient:
    """Stands in for the per-provider OIDCClient; returns REALISTIC claims.

    Built via :func:`_fake_oidc_client` so each instance returns the test's
    claim payload.  The claim shape mirrors what a real OIDC provider issues
    after a successful sign-in: standard identity claims only.  This is
    verified real-world behaviour, not an arbitrary choice — nothing in the
    platform provisions a ``tenant`` claim for OIDC clients (no mapper
    creation, no validation-time injection), so the provider CANNOT embed
    one.
    """

    _claims: dict = {}

    def __init__(self, **kwargs):
        # Accept the exact constructor surface _try_oidc_token uses
        # (issuer_url, client_id, claim_mappings, decrypted_client_secret).
        pass

    async def validate_token(self, token: str) -> dict:
        return dict(self._claims)


def _fake_oidc_client(claims: dict) -> type[_FakeOIDCClient]:
    """Build a FakeOIDCClient class returning *claims* from validate_token."""
    return type("FakeOIDCClient", (_FakeOIDCClient,), {"_claims": dict(claims)})


def _realistic_oidc_claims() -> dict:
    now = int(time.time())
    return {
        "sub": "alice-from-external-idp",
        "email": "alice@example.com",
        "name": "Alice Example",
        "preferred_username": "alice",
        "groups": ["employees"],
        "iat": now,
        "exp": now + 3600,
    }


class _FakeRequest:
    def __init__(self, context, path="/api/v1/dashboard/summary"):
        self.state = SimpleNamespace()
        if context is not None:
            self.state.tenant_context = context
        self.url = SimpleNamespace(path=path)
        self.method = "GET"
        self.client = SimpleNamespace(host="10.0.0.9")


def _middleware():
    from app.middleware.auth import JWTAuthMiddleware

    return JWTAuthMiddleware(app=None)  # check method needs no app


class TestOidcTokenTenantClaimGap:
    """The workspace-bound OIDC session must survive the middleware pipeline."""

    async def test_oidc_token_from_tenants_own_provider_is_accepted_for_that_tenant(
        self, engine
    ):
        """THE REPRODUCTION.

        A valid token issued by test-com's OWN provider (tenant context
        resolved from X-Tenant: test-com) must pass the full pipeline —
        validation + tenant claim check — so the dashboard load proceeds.
        Today the token has no ``tenant`` claim, the claim check rejects it
        with 401, and the frontend interceptor bounces the user to /login
        mid-load.
        """
        import app.middleware.auth as auth_module

        registry = _FakeRegistry(
            {(str(TENANT_TESTCOM), "user"): (
                "https://idp-test-com.example.com", "client-test-com"
            )}
        )
        claims = _realistic_oidc_claims()  # ← no 'tenant' claim, as issued

        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _fake_oidc_client(claims)
        ):
            validated, is_super_admin = await auth_module.validate_raw_token(
                "provider-issued-token", CTX_TESTCOM
            )

        # Sanity: validation against the tenant's own provider succeeds…
        assert validated is not None, (
            "token from the tenant's own provider must validate — if this "
            "fails the provider resolution itself is broken"
        )
        assert is_super_admin is False

        # …and the claim check must accept it for the same tenant.
        with _audit_patch(engine):
            claim_error = await _middleware()._check_tenant_claim(
                _FakeRequest(CTX_TESTCOM), validated, False
            )

        assert claim_error is None, (
            "OIDC TOKEN TENANT CLAIM GAP: a token issued by the tenant's own "
            f"provider is rejected in multi-tenant mode ({claim_error!r}) — "
            "'_check_tenant_claim' requires a 'tenant' claim that the OIDC "
            "path never provisions (no mapper creation, no validation-time "
            "injection), so EVERY dashboard request from an OIDC session "
            "returns 401 and the frontend interceptor redirects to /login "
            "mid-load (FIX-20260929-043443)"
        )

    async def test_oidc_token_carrying_matching_claim_is_accepted_control(self):
        """Control: an OIDC token WITH the matching claim passes — isolates
        the defect to claim provisioning, not the claim-check logic."""
        import app.middleware.auth as auth_module

        registry = _FakeRegistry(
            {(str(TENANT_TESTCOM), "user"): (
                "https://idp-test-com.example.com", "client-test-com"
            )}
        )
        claims = _realistic_oidc_claims()
        claims["tenant"] = "test-com"  # the claim nothing provisions today

        with _patch_registry(registry), patch.object(
            auth_module, "OIDCClient", _fake_oidc_client(claims)
        ):
            validated, _ = await auth_module.validate_raw_token(
                "provider-issued-token", CTX_TESTCOM
            )
        assert validated is not None
        claim_error = await _middleware()._check_tenant_claim(
            _FakeRequest(CTX_TESTCOM), validated, False
        )
        assert claim_error is None

    async def test_platform_account_token_control_passes_for_its_tenant(self):
        """Control: the password sign-in / sign-up path works end-to-end —
        ``create_platform_account_token`` embeds ``tenant`` (slug), so the
        same pipeline accepts it.  Proves the rig is correct and ONLY the
        OIDC path is broken."""
        from app.middleware.auth import validate_raw_token
        from app.services.tenancy.platform_account_auth_service import (
            create_platform_account_token,
            validate_platform_account_token,
        )

        user = SimpleNamespace(
            sub="platform-alice", email="alice@example.com", display_name="Alice"
        )
        tenant = SimpleNamespace(
            id=TENANT_TESTCOM, slug="test-com", name="Test Com"
        )
        token = create_platform_account_token(user=user, tenant=tenant)
        claims = validate_platform_account_token(token)
        assert claims is not None
        assert claims.get("tenant") == "test-com"

        validated, is_super_admin = await validate_raw_token(token, CTX_TESTCOM)
        assert validated is not None
        assert is_super_admin is False

        claim_error = await _middleware()._check_tenant_claim(
            _FakeRequest(CTX_TESTCOM), validated, False
        )
        assert claim_error is None
