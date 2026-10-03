"""Immutable per-request tenant context.

The tenant context is established exactly once per request by
``TenantResolutionMiddleware`` (Control Center only), stored on
``request.state``, and treated as read-only by all consumers.  A single
accessor returns the :data:`TENANT_UNSET` sentinel when multi-tenancy is
off (or the context has not been resolved), so feature code can branch
cleanly without null checks:

    from app.core.tenant_context import get_tenant_context

    ctx = get_tenant_context(request)
    if ctx.is_set:
        ...  # tenant-scoped behaviour
    else:    # single-tenant mode — byte-for-byte legacy behaviour
        ...

Mutation attempts raise ``dataclasses.FrozenInstanceError`` — the context
may never be widened or altered mid-request.
"""
from __future__ import annotations

import contextvars
import dataclasses
import uuid
from dataclasses import dataclass

from fastapi import Request

__all__ = [
    "TenantContext",
    "TenantContextUnset",
    "TENANT_UNSET",
    "get_tenant_context",
    "is_tenancy_enabled",
    "require_tenant_context",
    "set_tenant_context",
]


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Immutable per-request tenant identity established at resolution time.

    Only tenant *metadata* rides on the context (never business data).
    ``is_system_tenant`` marks the implicit tenant that adopts pre-existing
    data on upgraded deployments.
    """

    tenant_id: uuid.UUID
    slug: str
    name: str
    is_system_tenant: bool = False

    @property
    def is_set(self) -> bool:
        return True


class TenantContextUnset:
    """Singleton sentinel returned when no tenant context is active.

    Multi-tenancy off (or unresolved) — feature code branches on
    ``is_set``.  The sentinel is falsy and read-safe: accessing tenant
    fields raises so accidental use in single-tenant mode is loud.
    """

    _instance: TenantContextUnset | None = None

    def __new__(cls) -> TenantContextUnset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def is_set(self) -> bool:
        return False

    @property
    def tenant_id(self) -> uuid.UUID:
        raise AttributeError(
            "No tenant context is active (single-tenant mode or unresolved)"
        )

    @property
    def slug(self) -> str:
        raise AttributeError(
            "No tenant context is active (single-tenant mode or unresolved)"
        )

    @property
    def name(self) -> str:
        raise AttributeError(
            "No tenant context is active (single-tenant mode or unresolved)"
        )

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "TENANT_UNSET"


#: Module-level unset sentinel (single-tenant mode / unresolved request).
TENANT_UNSET = TenantContextUnset()


def set_tenant_context(request: Request, context: TenantContext) -> None:
    """Attach the resolved tenant context to the request (middleware only).

    Overwriting an already-set context is rejected: the context is
    established exactly once per request and is immutable thereafter.
    """
    existing = getattr(request.state, "tenant_context", None)
    if isinstance(existing, TenantContext):
        raise RuntimeError(
            "Tenant context already set for this request — it must be "
            "resolved exactly once by TenantResolutionMiddleware"
        )
    request.state.tenant_context = context


def get_tenant_context(request: Request) -> TenantContext | TenantContextUnset:
    """Read the request's tenant context.

    Returns :data:`TENANT_UNSET` when multi-tenancy is off or the context
    has not been resolved (single-tenant mode).
    """
    context = getattr(request.state, "tenant_context", None)
    if isinstance(context, TenantContext):
        return context
    return TENANT_UNSET


def is_tenancy_enabled(request: Request) -> bool:
    """Whether the tenancy switch was ON when this request was resolved.

    Set by :class:`~app.middleware.tenant_resolution.TenantResolutionMiddleware`
    (``request.state.tenancy_enabled``).  Defaults to False when the
    middleware did not run (unit tests, internal service traffic) — the
    safe legacy default, so tenancy-gated features stay inert.

    Phase 11: a resolved context is no longer proof that multi-tenancy
    is active — the default context when the switch is OFF is the ROOT
    tenant.  Feature code must branch on THIS flag (not ``is_set``) to
    decide whether tenancy features apply.
    """
    return bool(getattr(request.state, "tenancy_enabled", False))


def require_tenant_context(request: Request) -> TenantContext:
    """Return the resolved tenant context or raise when unset.

    Used by code paths that only make sense in multi-tenant mode
    (platform admin APIs, tenant self-service endpoints).
    """
    context = get_tenant_context(request)
    if not isinstance(context, TenantContext):
        raise RuntimeError("This endpoint requires an active tenant context")
    return context


def tenant_id_or_none(
    context: TenantContext | TenantContextUnset,
) -> uuid.UUID | None:
    """Convenience: tenant id for scoping, or None in single-tenant mode."""
    if isinstance(context, TenantContext):
        return context.tenant_id
    return None


# ── Request-scoped propagation (context variable) ────────────────────────────

#: Current-request tenant context for code without access to ``request``
#: (outbound HTTP clients in AR/CH forwarding the context downstream, and
#: middleware-adjacent helpers).  Set by the tenant middlewares of all
#: three services; async tasks inherit it from their spawning request.
_current_tenant: contextvars.ContextVar[TenantContext | None] = contextvars.ContextVar(
    "parthenon_current_tenant", default=None
)


def set_current_tenant_context(context: TenantContext) -> contextvars.Token:
    """Bind the context to the current async task (middlewares only)."""
    return _current_tenant.set(context)


def reset_current_tenant_context(token: contextvars.Token) -> None:
    _current_tenant.reset(token)


def get_current_tenant_context() -> TenantContext | None:
    """The active tenant context for this async task, or None."""
    return _current_tenant.get()


# ── OTEL tenant attribution ──────────────────────────────────────────────────

#: Span attribute names — tenant attribution on every span in multi-tenant mode.
SPAN_TENANT_ID_ATTR = "parthenon.tenant.id"
SPAN_TENANT_SLUG_ATTR = "parthenon.tenant.slug"
SPAN_TENANCY_ATTR = "parthenon.tenancy"


def set_tenant_span_attributes(
    context: TenantContext | TenantContextUnset | None,
    *,
    tenancy_active: bool = False,
) -> None:
    """Attach tenant attribution to the current OTEL span.

    - Context resolved (multi-tenancy on): ``parthenon.tenant.id`` /
      ``parthenon.tenant.slug`` attributes plus ``parthenon.tenancy=tenant``.
    - Tenancy on but no context (platform surface, bypassed path):
      ``parthenon.tenancy=platform`` sentinel.
    - Tenancy off: NO attributes set — telemetry is byte-for-byte unchanged.

    Fail-safe: telemetry must never break request handling.
    """
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span is None or not span.is_recording():
            return
        if isinstance(context, TenantContext):
            span.set_attribute(SPAN_TENANT_ID_ATTR, str(context.tenant_id))
            span.set_attribute(SPAN_TENANT_SLUG_ATTR, context.slug)
            span.set_attribute(SPAN_TENANCY_ATTR, "tenant")
        elif tenancy_active:
            span.set_attribute(SPAN_TENANCY_ATTR, "platform")
    except Exception:
        pass


# Frozen-dataclass contract: mutation raises.  Kept as an executable
# assertion so a refactor that drops frozen=True fails fast in tests.
def _assert_frozen() -> None:  # pragma: no cover — contract check
    ctx = TenantContext(
        tenant_id=uuid.uuid4(), slug="check", name="check"
    )
    try:
        ctx.slug = "mutated"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("TenantContext must remain frozen (immutable)")
