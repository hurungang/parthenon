"""Signed tenant context propagation — HMAC sign/verify utilities.

Control Center signs the resolved tenant context onto outbound calls to
Agent Runtime / Communication Hub as headers on the existing mTLS
channels.  The receiving services **verify** the signature and bind the
context read-only — they can never create or widen a tenant context
because only the shared signing key (held by the services, never by
agents or the frontend) produces valid signatures.

Headers (all-or-nothing; a partial set is invalid):
- ``X-Internal-Tenant-Id``        — tenant UUID
- ``X-Internal-Tenant-Slug``      — tenant slug
- ``X-Internal-Tenant-Timestamp`` — unix epoch seconds at signing
- ``X-Internal-Tenant-Signature`` — hex HMAC-SHA256 over the canonical
  string ``"<id>|<slug>|<timestamp>"``

Verification rejects: unsigned/incomplete sets, tampered values,
stale timestamps (replay outside the window), and mismatched
id/slug pairs.  The signing key comes from ``TENANT_CONTEXT_SIGNING_KEY``
(a development default keeps local/CI working; production must override).
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import logging
import time
import uuid
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.tenant_context import TenantContext

logger = logging.getLogger(__name__)

TENANT_ID_HEADER = "X-Internal-Tenant-Id"
TENANT_SLUG_HEADER = "X-Internal-Tenant-Slug"
TENANT_TIMESTAMP_HEADER = "X-Internal-Tenant-Timestamp"
TENANT_SIGNATURE_HEADER = "X-Internal-Tenant-Signature"

#: All tenant context headers — forwarded as a set by clients, verified
#: as a set by receivers.
TENANT_SIGNATURE_HEADERS: tuple[str, ...] = (
    TENANT_ID_HEADER,
    TENANT_SLUG_HEADER,
    TENANT_TIMESTAMP_HEADER,
    TENANT_SIGNATURE_HEADER,
)

#: Default maximum age of a signed context before it is treated as stale.
DEFAULT_MAX_AGE_SECONDS = 60.0


class TenantSignatureError(Exception):
    """Raised when a signed tenant context fails verification."""


def _signing_key() -> bytes:
    return get_settings().tenant_context_signing_key.encode()


def _canonical_message(tenant_id: str, slug: str, timestamp: str) -> bytes:
    return f"{tenant_id}|{slug}|{timestamp}".encode()


def _compute_signature(tenant_id: str, slug: str, timestamp: str) -> str:
    message = _canonical_message(tenant_id, slug, timestamp)
    return hmac.new(_signing_key(), message, hashlib.sha256).hexdigest()


def build_tenant_signature_headers(
    context: TenantContext,
    *,
    timestamp: float | None = None,
) -> dict[str, str]:
    """Sign a tenant context into the propagation header set (CC only)."""
    ts = timestamp if timestamp is not None else time.time()
    ts_str = str(int(ts))
    tenant_id = str(context.tenant_id)
    signature = _compute_signature(tenant_id, context.slug, ts_str)
    return {
        TENANT_ID_HEADER: tenant_id,
        TENANT_SLUG_HEADER: context.slug,
        TENANT_TIMESTAMP_HEADER: ts_str,
        TENANT_SIGNATURE_HEADER: signature,
    }


@dataclass(frozen=True, slots=True)
class VerifiedTenantContext:
    """Tenant context recovered from a verified signed header set."""

    tenant_id: uuid.UUID
    slug: str

    def to_tenant_context(self, name: str = "", *, is_system_tenant: bool = False) -> TenantContext:
        """Materialize as an immutable TenantContext (name only via CC)."""
        return TenantContext(
            tenant_id=self.tenant_id,
            slug=self.slug,
            name=name,
            is_system_tenant=is_system_tenant,
        )


def verify_tenant_signature_headers(
    headers,  # Mapping[str, str] — case-insensitive per HTTP semantics
    *,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    expected_tenant_id: uuid.UUID | str | None = None,
    now: float | None = None,
) -> VerifiedTenantContext:
    """Verify a signed tenant header set; raise on any failure.

    ``headers`` may be a Starlette ``Headers`` (case-insensitive) or any
    mapping; lookups are performed case-insensitively either way.

    Fails closed on: missing/partial header sets, tampered values,
    stale (replayed) timestamps, malformed ids, and — when
    ``expected_tenant_id`` is given — contexts not matching the expected
    tenant (e.g. a session's own binding).
    """
    values = _read_headers(headers)
    missing = [h for h in TENANT_SIGNATURE_HEADERS if h not in values]
    if missing:
        raise TenantSignatureError(f"missing tenant signature headers: {missing}")

    tenant_id_raw = values[TENANT_ID_HEADER].strip()
    slug = values[TENANT_SLUG_HEADER].strip()
    timestamp_raw = values[TENANT_TIMESTAMP_HEADER].strip()
    signature = values[TENANT_SIGNATURE_HEADER].strip()

    if not tenant_id_raw or not slug:
        raise TenantSignatureError("empty tenant id or slug in signed context")

    try:
        tenant_id = uuid.UUID(tenant_id_raw)
    except ValueError as exc:
        raise TenantSignatureError("malformed tenant id in signed context") from exc

    try:
        signed_at = float(timestamp_raw)
    except ValueError as exc:
        raise TenantSignatureError("malformed timestamp in signed context") from exc

    current = now if now is not None else time.time()
    if abs(current - signed_at) > max_age_seconds:
        raise TenantSignatureError(
            "stale tenant signature (replay outside the accepted window)"
        )

    expected_signature = _compute_signature(tenant_id_raw, slug, timestamp_raw)
    if not hmac.compare_digest(expected_signature, signature):
        raise TenantSignatureError("invalid tenant signature (tampered or forged)")

    if expected_tenant_id is not None and str(tenant_id) != str(expected_tenant_id):
        raise TenantSignatureError(
            "tenant signature does not match the expected tenant binding"
        )

    return VerifiedTenantContext(tenant_id=tenant_id, slug=slug)


def tenant_context_headers(context: TenantContext | None) -> dict[str, str]:
    """Signed headers for a tenant context — or ``{}`` when unset.

    Control Center's internal clients call this on every outbound request:
    with multi-tenancy off (or no resolved context) it adds nothing, so
    single-tenant traffic is byte-for-byte unchanged.

    CONTROL CENTER ONLY — this is the signing capability.  Agent Runtime
    and Communication Hub must never sign: they forward the header set
    they received and verified via :func:`forward_tenant_headers`.
    """
    if context is None:
        return {}
    return build_tenant_signature_headers(context)


# ── Receiver-side forwarding (AR/CH never re-sign) ───────────────────────────
#
# Agent Runtime / Communication Hub verify inbound signed headers and then
# FORWARD THE ORIGINAL SET VERBATIM when calling onward (AR→CC data
# resolves, CH→AR execution forwards).  Re-signing would hand the
# services the ability to mint valid context for ANY tenant (they hold
# the shared verification key), widening scope across tenants.  The
# forwarding contextvar below carries the verified original set instead.

_forwarded_tenant_headers: contextvars.ContextVar[dict[str, str] | None] = (
    contextvars.ContextVar("parthenon_forwarded_tenant_headers", default=None)
)


def extract_tenant_signature_headers(headers) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """Return the tenant signature headers present in *headers* (may be {})."""
    return _read_headers(headers)


def bind_forwarded_tenant_headers(headers: dict[str, str]) -> contextvars.Token:
    """Bind the verified original header set to the current async task.

    Called by the AR/CH middlewares right after a signature verifies, so
    downstream forwarding propagates EXACTLY what Control Center signed.
    """
    return _forwarded_tenant_headers.set(dict(headers))


def reset_forwarded_tenant_headers(token: contextvars.Token) -> None:
    _forwarded_tenant_headers.reset(token)


def forward_tenant_headers() -> dict[str, str]:
    """The verified original tenant header set to forward — or ``{}``.

    Receiver-side counterpart of :func:`tenant_context_headers`: AR/CH
    outbound calls attach this instead of signing anything themselves.
    No headers bound (single-tenant traffic) → ``{}``, byte-for-byte
    unchanged.
    """
    stored = _forwarded_tenant_headers.get()
    return dict(stored) if stored else {}


def verify_request_tenant_context(headers) -> TenantContext | None:  # type: ignore[no-untyped-def]
    """Verify signed tenant headers on an inbound service request.

    Receiver-side entry point for Agent Runtime / Communication Hub
    middlewares (they cannot read the platform switch — only Control
    Center touches the database — so the contract is verify-if-present):

    - **No tenant headers present** → returns ``None``; the request is
      single-tenant traffic and passes through unchanged.
    - **Any tenant header present** → the full signed set must verify;
      unsigned, partial, tampered, or stale sets raise
      :class:`TenantSignatureError`.

    The returned context is derived ONLY from values covered by the
    signature — receivers cannot widen it (the tenant ``name`` and the
    system-tenant flag are not propagated and stay empty/False).
    """
    if not _read_headers(headers):
        return None
    verified = verify_tenant_signature_headers(headers)
    return verified.to_tenant_context()


def _read_headers(headers) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """Case-insensitive header extraction for mappings and Starlette Headers."""
    result: dict[str, str] = {}
    lowered = {h.lower(): h for h in TENANT_SIGNATURE_HEADERS}
    try:
        items = list(headers.items())
    except AttributeError:
        items = list(headers)  # sequence of (key, value) pairs
    for key, value in items:
        canonical = lowered.get(str(key).lower())
        if canonical is not None:
            result[canonical] = str(value)
    return result
