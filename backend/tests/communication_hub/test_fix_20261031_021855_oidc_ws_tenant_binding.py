"""FIX-20261031-021855 — OIDC WebSocket connections bind NO tenant context.

Defect 2 root cause (confirmed by code reading): ``WebSocketServer.authenticate``
validates OIDC tokens via ``OIDCClient.validate_token`` which returns claims
VERBATIM — no ``tenant`` claim is injected on this direct-validation path
(the REST auth middleware injects it from the resolved login context, but
WS bypasses that middleware).  ``websocket_chat`` bound the tenant context
ONLY when ``claims.get("tenant")`` was truthy, so an OIDC user's connection
ran context-less → ``_signed_tenant_forwarding`` yielded headerless → AR's
callback ``PATCH /internal/data/sessions/{id}/status`` → 401 "Signed tenant
context headers are required".

The fix: when the claims carry no ``tenant`` slug, the tenant is resolved
server-side from the user's active membership (the SAME mechanism REST
uses — ``PlatformUser`` by ``sub`` → active membership, default first),
via ``_bind_connection_tenant_context`` / ``_resolve_oidc_tenant_slug``.
Fail-closed: unresolvable tenant under multi-tenancy rejects the
connection.  Platform-account tokens and single-tenant mode are unchanged.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from app.api.ws import chat  # noqa: E402
from app.core.tenant_context import (  # noqa: E402
    TenantContext,
    get_current_tenant_context,
    reset_current_tenant_context,
)

CTX = TenantContext(
    tenant_id=uuid.UUID("88888888-8888-8888-8888-888888888888"),
    slug="oidc-ws-tenant",
    name="OIDC WS Tenant",
)

OIDC_CLAIMS = {
    "sub": "oidc-user-sub-123",
    "iss": "https://keycloak.example/realms/parthenon",
    # NOTE: no ``tenant`` claim — OIDC tokens are returned verbatim.
}


class FakeResult:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class FakeSession:
    """Minimal async session stub: first execute → PlatformUser lookup,
    second execute → membership slug lookup."""

    def __init__(self, user_row, slug) -> None:
        self.user_row = user_row
        self.slug = slug
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self.calls += 1
        if self.calls == 1:
            return FakeResult(scalar=self.user_row)
        return FakeResult(scalar=self.slug)


@pytest.fixture
def clean_context():
    token = None

    class _Guard:
        def reset(self):
            nonlocal token
            if token is not None:
                reset_current_tenant_context(token)
                token = None

    guard = _Guard()
    yield guard
    guard.reset()


def _patch_db_and_settings(multi_tenancy, user_row=SimpleNamespace(id=1), slug=CTX.slug):
    """Patch AsyncSessionLocal and the multi-tenancy switch for the helper."""
    session = FakeSession(user_row, slug)

    settings_svc = type("S", (), {})()
    settings_svc.is_multi_tenancy_enabled = AsyncMock(return_value=multi_tenancy)


    resolution_svc = type("R", (), {})()

    async def _resolve_slug(db, slug):
        if slug == CTX.slug:
            return CTX
        from app.services.tenancy.tenant_resolution_service import (
            TenantResolutionError,
        )

        raise TenantResolutionError("unknown", slug)

    resolution_svc.resolve_slug = _resolve_slug

    return (
        patch("app.db.session.AsyncSessionLocal", lambda: session)
    ), patch(
        "app.services.tenancy.platform_settings_service.get_platform_settings_service",
        lambda: settings_svc,
    ), patch(
        "app.services.tenancy.tenant_resolution_service.get_tenant_resolution_service",
        lambda: resolution_svc,
    ), session


class TestOidcWsTenantBinding:
    @pytest.mark.asyncio
    async def test_oidc_claims_without_tenant_resolve_membership_and_bind(
        self, clean_context
    ):
        """THE defect: OIDC claims with NO ``tenant`` claim must resolve the
        user's tenant server-side (active membership) and bind the context —
        otherwise ``_signed_tenant_forwarding`` goes headerless and AR's
        first CC callback 401s."""
        db_patch, settings_patch, resolution_patch, session = _patch_db_and_settings(
            multi_tenancy=True, user_row=SimpleNamespace(id=1), slug=CTX.slug
        )
        with db_patch, settings_patch, resolution_patch:
            error = await chat._bind_connection_tenant_context(OIDC_CLAIMS)

        assert error is None, f"connection must bind, got rejection: {error}"
        bound = get_current_tenant_context()
        assert bound is not None, (
            "OIDC WS connection bound NO tenant context — every hop goes out "
            "headerless and AR's status PATCH fails closed with 401"
        )
        assert bound.slug == CTX.slug
        assert str(bound.tenant_id) == str(CTX.tenant_id)
        clean_context.reset()

    @pytest.mark.asyncio
    async def test_oidc_no_membership_fails_closed(self, clean_context):
        """Multi-tenancy ON + no resolvable membership → fail closed with a
        clear reason (no headerless pipeline)."""
        db_patch, settings_patch, resolution_patch, _session = _patch_db_and_settings(
            multi_tenancy=True, user_row=None, slug=None
        )
        with db_patch, settings_patch, resolution_patch:
            error = await chat._bind_connection_tenant_context(OIDC_CLAIMS)

        assert error == "No active tenant membership"
        assert get_current_tenant_context() is None

    @pytest.mark.asyncio
    async def test_single_tenant_mode_stays_unbound(self, clean_context):
        """Multi-tenancy OFF → no binding, no error (root tenant, headerless
        traffic — unchanged behaviour)."""
        db_patch, settings_patch, resolution_patch, _session = _patch_db_and_settings(
            multi_tenancy=False
        )
        with db_patch, settings_patch, resolution_patch:
            error = await chat._bind_connection_tenant_context(OIDC_CLAIMS)

        assert error is None
        assert get_current_tenant_context() is None

    @pytest.mark.asyncio
    async def test_platform_token_native_tenant_claim_unchanged(
        self, clean_context
    ):
        """Platform-account JWTs carry a native ``tenant`` slug — behaviour
        must be unchanged (membership lookup never runs)."""
        db_patch, settings_patch, resolution_patch, session = _patch_db_and_settings(
            multi_tenancy=True, slug=CTX.slug
        )

        from unittest.mock import patch as _patch

        with _patch.object(
            chat, "_resolve_oidc_tenant_slug", AsyncMock(side_effect=AssertionError(
                "platform tokens must not use the membership fallback"
            ))
        ):
            # The native-slug path uses the resolution service for the slug;
            # patch the DB session it resolves through.
            with _patch("app.db.session.AsyncSessionLocal", lambda: session), \
                 _patch(
                     "app.services.tenancy.tenant_resolution_service.get_tenant_resolution_service",
                 ) as svc_cls:
                svc = svc_cls.return_value
                svc.resolve_slug = AsyncMock(return_value=CTX)
                error = await chat._bind_connection_tenant_context(
                    {"sub": "svc-cc", "tenant": CTX.slug}
                )

        assert error is None
        assert get_current_tenant_context() is not None
        clean_context.reset()

    @pytest.mark.asyncio
    async def test_resolved_context_feeds_signed_delegation_headers(
        self, clean_context
    ):
        """End-to-end shape: after the OIDC resolution binds the context, the
        delegation hop mints a VERIFIED signed header set (no 401)."""
        from app.core.tenant_signature import (
            TENANT_SIGNATURE_HEADERS,
            forward_tenant_headers,
            verify_tenant_signature_headers,
        )

        db_patch, settings_patch, resolution_patch, _session = _patch_db_and_settings(
            multi_tenancy=True, user_row=SimpleNamespace(id=1), slug=CTX.slug
        )
        with db_patch, settings_patch, resolution_patch:
            error = await chat._bind_connection_tenant_context(OIDC_CLAIMS)
        assert error is None

        with chat._signed_tenant_forwarding():
            headers = dict(forward_tenant_headers())
        assert set(headers) == set(TENANT_SIGNATURE_HEADERS)
        verified = verify_tenant_signature_headers(headers)
        assert verified.slug == CTX.slug
        clean_context.reset()
