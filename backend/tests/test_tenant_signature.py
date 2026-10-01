"""Unit tests for signed tenant context propagation (Phase 9.4, CS-19/CS-20).

Covers ``app.core.tenant_signature``:

- sign/verify round trip (happy path)
- tampered id/slug/signature rejection
- stale (replayed) and future timestamps rejection
- unsigned / partial header-set rejection (all-or-nothing)
- malformed id / timestamp rejection
- expected-tenant binding mismatch rejection
- ``tenant_context_headers`` returns {} when no context is active
  (single-tenant traffic byte-for-byte unchanged)
- ``verify_request_tenant_context`` verify-if-present semantics (None
  for headerless traffic) and no-widening guarantees for receivers
- case-insensitive header handling
- wrong-key signatures never verify (AR/CH cannot forge CC signatures)
"""
from __future__ import annotations

import time
import uuid

import pytest

from app.core.tenant_context import TenantContext
from app.core.tenant_signature import (
    DEFAULT_MAX_AGE_SECONDS,
    TENANT_ID_HEADER,
    TENANT_SIGNATURE_HEADER,
    TENANT_SIGNATURE_HEADERS,
    TENANT_SLUG_HEADER,
    TENANT_TIMESTAMP_HEADER,
    TenantSignatureError,
    build_tenant_signature_headers,
    tenant_context_headers,
    verify_request_tenant_context,
    verify_tenant_signature_headers,
)


def _ctx() -> TenantContext:
    return TenantContext(
        tenant_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        slug="acme",
        name="Acme Corp",
    )


class TestSignVerifyRoundTrip:
    def test_round_trip_verifies(self):
        headers = build_tenant_signature_headers(_ctx())
        verified = verify_tenant_signature_headers(headers)
        assert str(verified.tenant_id) == "11111111-1111-1111-1111-111111111111"
        assert verified.slug == "acme"

    def test_to_tenant_context_no_widening(self):
        """The verified context never carries name or system-tenant flag
        from the wire — receivers cannot fabricate richer contexts."""
        headers = build_tenant_signature_headers(_ctx())
        verified = verify_tenant_signature_headers(headers)
        ctx = verified.to_tenant_context()
        assert ctx.slug == "acme"
        assert ctx.name == ""  # NOT propagated
        assert ctx.is_system_tenant is False  # NOT propagated

    def test_all_four_headers_present(self):
        headers = build_tenant_signature_headers(_ctx())
        for header in TENANT_SIGNATURE_HEADERS:
            assert header in headers

    def test_case_insensitive_lookup(self):
        headers = {k.lower(): v for k, v in build_tenant_signature_headers(_ctx()).items()}
        verified = verify_tenant_signature_headers(headers)
        assert verified.slug == "acme"

    def test_starlette_style_headers_objects(self):
        """Headers-like objects (items() API) work."""
        class FakeHeaders(dict):
            pass

        headers = FakeHeaders(build_tenant_signature_headers(_ctx()))
        verified = verify_tenant_signature_headers(headers)
        assert verified.slug == "acme"


class TestTamperRejection:
    def test_tampered_slug_rejected(self):
        headers = build_tenant_signature_headers(_ctx())
        headers[TENANT_SLUG_HEADER] = "evil-tenant"
        with pytest.raises(TenantSignatureError, match="tampered|invalid"):
            verify_tenant_signature_headers(headers)

    def test_tampered_tenant_id_rejected(self):
        headers = build_tenant_signature_headers(_ctx())
        headers[TENANT_ID_HEADER] = str(uuid.uuid4())
        with pytest.raises(TenantSignatureError):
            verify_tenant_signature_headers(headers)

    def test_tampered_signature_rejected(self):
        headers = build_tenant_signature_headers(_ctx())
        headers[TENANT_SIGNATURE_HEADER] = "0" * 128
        with pytest.raises(TenantSignatureError):
            verify_tenant_signature_headers(headers)

    def test_tampered_timestamp_rejected(self):
        headers = build_tenant_signature_headers(_ctx())
        headers[TENANT_TIMESTAMP_HEADER] = str(int(time.time()) + 7)
        # The timestamp changed without re-signing → signature mismatch.
        with pytest.raises(TenantSignatureError):
            verify_tenant_signature_headers(headers)


class TestReplayRejection:
    def test_stale_timestamp_rejected(self):
        old = time.time() - (DEFAULT_MAX_AGE_SECONDS + 30)
        headers = build_tenant_signature_headers(_ctx(), timestamp=old)
        with pytest.raises(TenantSignatureError, match="stale"):
            verify_tenant_signature_headers(headers)

    def test_future_timestamp_beyond_window_rejected(self):
        future = time.time() + (DEFAULT_MAX_AGE_SECONDS + 30)
        headers = build_tenant_signature_headers(_ctx(), timestamp=future)
        with pytest.raises(TenantSignatureError, match="stale"):
            verify_tenant_signature_headers(headers)

    def test_explicit_now_honored_for_determinism(self):
        signed_at = 1_000_000
        headers = build_tenant_signature_headers(_ctx(), timestamp=signed_at)
        # Verify "now" far later than the window → stale.
        with pytest.raises(TenantSignatureError, match="stale"):
            verify_tenant_signature_headers(headers, now=signed_at + DEFAULT_MAX_AGE_SECONDS + 1)


class TestUnsignedAndPartial:
    def test_empty_header_set_rejected(self):
        with pytest.raises(TenantSignatureError, match="missing"):
            verify_tenant_signature_headers({})

    def test_partial_set_signature_only_rejected(self):
        with pytest.raises(TenantSignatureError, match="missing"):
            verify_tenant_signature_headers({TENANT_SIGNATURE_HEADER: "ab" * 32})

    def test_missing_signature_header_rejected(self):
        headers = build_tenant_signature_headers(_ctx())
        del headers[TENANT_SIGNATURE_HEADER]
        with pytest.raises(TenantSignatureError, match="missing"):
            verify_tenant_signature_headers(headers)

    def test_missing_slug_header_rejected(self):
        headers = build_tenant_signature_headers(_ctx())
        del headers[TENANT_SLUG_HEADER]
        with pytest.raises(TenantSignatureError, match="missing"):
            verify_tenant_signature_headers(headers)


class TestMalformedValues:
    def test_malformed_tenant_id_rejected(self):
        headers = build_tenant_signature_headers(_ctx())
        headers[TENANT_ID_HEADER] = "not-a-uuid"
        with pytest.raises(TenantSignatureError, match="malformed tenant id"):
            verify_tenant_signature_headers(headers)

    def test_malformed_timestamp_rejected(self):
        headers = build_tenant_signature_headers(_ctx())
        headers[TENANT_TIMESTAMP_HEADER] = "yesterday"
        with pytest.raises(TenantSignatureError, match="malformed timestamp"):
            verify_tenant_signature_headers(headers)

    def test_empty_slug_rejected(self):
        headers = build_tenant_signature_headers(_ctx())
        headers[TENANT_SLUG_HEADER] = "   "
        with pytest.raises(TenantSignatureError, match="empty"):
            verify_tenant_signature_headers(headers)


class TestExpectedTenantBinding:
    def test_matching_expected_tenant_passes(self):
        ctx = _ctx()
        headers = build_tenant_signature_headers(ctx)
        verified = verify_tenant_signature_headers(headers, expected_tenant_id=ctx.tenant_id)
        assert verified.slug == "acme"

    def test_mismatched_expected_tenant_rejected(self):
        headers = build_tenant_signature_headers(_ctx())
        other = uuid.uuid4()
        with pytest.raises(TenantSignatureError, match="does not match"):
            verify_tenant_signature_headers(headers, expected_tenant_id=other)


class TestSigningKeyIsolation:
    def test_signature_from_wrong_key_never_verifies(self, monkeypatch):
        """A signature produced under a different signing key (e.g. what a
        compromised AR/CH could fabricate) must never verify."""
        import app.core.tenant_signature as sig_module

        headers = build_tenant_signature_headers(_ctx())
        monkeypatch.setattr(
            sig_module, "_signing_key", lambda: b"attacker-controlled-key"
        )
        with pytest.raises(TenantSignatureError, match="tampered|invalid"):
            verify_tenant_signature_headers(headers)

    def test_forged_signature_with_wrong_key_rejected(self, monkeypatch):
        import app.core.tenant_signature as sig_module

        monkeypatch.setattr(
            sig_module, "_signing_key", lambda: b"attacker-key"
        )
        headers = {
            TENANT_ID_HEADER: str(_ctx().tenant_id),
            TENANT_SLUG_HEADER: "acme",
            TENANT_TIMESTAMP_HEADER: str(int(time.time())),
            TENANT_SIGNATURE_HEADER: "f" * 64,  # forged anywhere
        }
        with pytest.raises(TenantSignatureError):
            verify_tenant_signature_headers(headers)

    def test_receiver_services_never_import_signing_helper(self):
        """CS-20: no code path in AR or CH may import the CC-only signing
        helper — receivers forward what CC signed and never re-sign."""
        import pathlib
        import re

        backend_root = pathlib.Path(__file__).resolve().parents[1]
        receiver_trees = [
            backend_root / "app" / "agent_runtime",
            backend_root / "app" / "communication_hub",
        ]
        pattern = re.compile(r"tenant_context_headers|build_tenant_signature_headers")
        violations: list[str] = []
        for tree in receiver_trees:
            for py in tree.rglob("*.py"):
                source = py.read_text(encoding="utf-8")
                if pattern.search(source):
                    violations.append(str(py.relative_to(backend_root)))
        assert violations == [], (
            "AR/CH must forward (forward_tenant_headers), never sign: "
            f"{violations}"
        )


class TestClientHelpers:
    def test_tenant_context_headers_none_is_empty(self):
        """With no tenant context (switch off) clients attach NOTHING."""
        assert tenant_context_headers(None) == {}

    def test_tenant_context_headers_signed_when_active(self):
        headers = tenant_context_headers(_ctx())
        assert TENANT_SIGNATURE_HEADER in headers
        assert verify_tenant_signature_headers(headers).slug == "acme"

    def test_verify_request_no_headers_returns_none(self):
        """Headerless inbound traffic = single-tenant, passes through."""
        assert verify_request_tenant_context({}) is None
        assert verify_request_tenant_context({"Authorization": "Bearer x"}) is None

    def test_verify_request_partial_headers_raise(self):
        headers = {TENANT_ID_HEADER: str(uuid.uuid4())}  # present but incomplete
        with pytest.raises(TenantSignatureError):
            verify_request_tenant_context(headers)
