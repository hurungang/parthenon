"""Shared FastAPI dependencies for the API layer."""
from collections.abc import Callable
import logging
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import DbSession, get_db
from app.schemas.errors import PermissionDeniedDetail, RequiredPermission

logger = logging.getLogger(__name__)

# Cache of (module, action) → _dep function so the same callable is returned
# for repeated calls with identical arguments.  This allows tests to use
# app.dependency_overrides with the result of require_permission().
_permission_dep_cache: dict[tuple[str, str], Callable] = {}

_CALLER_TYPE_MAP: dict[str, str] = {
    "agent-runtime": "agent_runtime",
    "communication-hub": "communication_hub",
}

_AR_ALLOWLIST: set[tuple[str, str]] = {
    ("GET", "/api/v1/internal/data/agent-types/{agent_type_id}/plan"),
    ("GET", "/api/v1/internal/data/agent-types/{agent_type_id}/context"),
    ("GET", "/api/v1/internal/data/model-configs/{model_config_id}"),
    ("GET", "/api/v1/internal/data/sessions/{session_id}"),
    ("POST", "/api/v1/internal/data/sessions/claim-queued"),
    ("PATCH", "/api/v1/internal/data/sessions/{session_id}/status"),
    ("POST", "/api/v1/internal/data/sessions/{session_id}/result"),
    ("POST", "/api/v1/internal/data/sessions/{session_id}/log"),
    ("POST", "/api/v1/internal/data/tool-calls"),
    ("GET", "/api/v1/internal/data/mcp-sessions/{server_slug}"),
    ("POST", "/api/v1/internal/data/preflight/availability"),
    # Typed output endpoints
    ("POST", "/api/v1/internal/validate-output"),
    ("POST", "/api/v1/internal/agent-outputs"),
    ("GET", "/api/v1/internal/agent-outputs"),
}

_CH_ALLOWLIST: set[tuple[str, str]] = {
    ("POST", "/api/v1/internal/certificates/validate"),
    ("POST", "/api/v1/internal/authorize/tool-call"),
    ("GET", "/api/v1/internal/data/sessions/{session_id}"),
    ("GET", "/api/v1/internal/data/sessions/{session_id}/history"),
    ("GET", "/api/v1/internal/data/users/{user_id}/permissions"),
    ("POST", "/api/v1/internal/data/conversations/{conv_session_id}/prepare-turn"),
    ("POST", "/api/v1/internal/data/conversations/{conv_session_id}/append-turn"),
    ("POST", "/api/v1/internal/data/conversations/{conv_session_id}/auto-name"),
    ("POST", "/api/v1/internal/data/a2a/request"),
    ("POST", "/api/v1/internal/data/a2a/sessions/{session_link_id}/disconnect"),
    ("POST", "/api/v1/internal/system-tools/save-data"),
    ("POST", "/api/v1/internal/system-tools/send-notification"),
    ("POST", "/api/v1/internal/system-tools/get-recipient-group"),
    ("POST", "/api/v1/internal/system-tools/human-intervene"),
    ("POST", "/api/v1/internal/system-tools/get-data"),
    ("POST", "/api/v1/internal/system-tools/get-output"),
    ("POST", "/api/v1/internal/system-tools/query-result"),
    ("POST", "/api/v1/internal/mcp/proxy-tool"),
    ("POST", "/api/v1/internal/data/intervene/respond"),
    ("POST", "/api/v1/internal/auth/validate-api-key"),
    ("POST", "/api/v1/internal/system-tools/skills/resolve"),
}

_INTERNAL_ALLOWLISTS: dict[str, set[tuple[str, str]]] = {
    "agent_runtime": _AR_ALLOWLIST,
    "communication_hub": _CH_ALLOWLIST,
}


def _normalize_internal_caller(service_name: str | None) -> str | None:
    """Normalize certificate service name to a stable internal caller type."""
    if not service_name:
        return None
    return _CALLER_TYPE_MAP.get(service_name.strip().lower())


def _resolve_route_template(request: Request) -> str:
    """Resolve canonical route template for policy checks and audit logs."""
    route = request.scope.get("route")
    if route is not None:
        route_path = getattr(route, "path", None) or getattr(route, "path_format", None)
        if isinstance(route_path, str) and route_path:
            return route_path
    return request.url.path


def _raise_internal_policy_deny(
    *,
    request: Request,
    caller_type: str | None,
    service_name: str | None,
    reason: str,
    endpoint: str,
) -> None:
    """Emit structured deny audit event and raise a deterministic 403."""
    deny_event = {
        "event": "internal.allowlist.denied",
        "caller_type": caller_type,
        "caller_identity": service_name,
        "certificate_type": "service",
        "method": request.method.upper(),
        "endpoint": endpoint,
        "deny_reason": reason,
        "path": request.url.path,
        "trace_id": request.headers.get("x-trace-id"),
        "correlation_id": request.headers.get("x-correlation-id"),
        "request_id": request.headers.get("x-request-id"),
    }
    logger.warning("%s", deny_event)
    raise HTTPException(
        status_code=403,
        detail={
            "error": "internal_endpoint_denied",
            "reason": reason,
            "caller_type": caller_type,
            "method": request.method.upper(),
            "endpoint": endpoint,
        },
    )


def get_current_claims(request: Request) -> dict[str, Any]:
    """Return the decoded JWT claims attached by the auth middleware."""
    claims: dict[str, Any] = getattr(request.state, "identity", {})
    return claims


def require_admin(request: Request) -> dict[str, Any]:
    """FastAPI dependency that enforces admin role.

    Raises HTTPException 403 if the caller does not have the 'admin' role.
    Returns the claims dict on success.

    Kept for backwards compatibility with non-permission-managed endpoints.
    New code should use require_permission() instead.
    """
    claims = get_current_claims(request)
    roles: list[str] = claims.get("roles", [])
    if "admin" not in roles:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return claims


#: Membership-based grants for the tenant self-service surfaces.
#: A user's ACTIVE TenantUserMembership in the request's tenant grants
#: these tenant:: permissions directly (the tenant workspace equivalent
#: of the platform-admin role).  Platform RBAC roles/policies continue to
#: apply on top, so wildcard policies (system_admin) still work.
_TENANT_MEMBERSHIP_GRANTS: dict[str, dict[str, set[str]]] = {
    "tenant::settings": {
        "read": {"member", "tenant_admin", "platform_admin"},
        "manage": {"tenant_admin", "platform_admin"},
    },
    "tenant::members": {
        "read": {"tenant_admin", "platform_admin"},
        "create": {"tenant_admin", "platform_admin"},
        "update": {"tenant_admin", "platform_admin"},
        "delete": {"tenant_admin", "platform_admin"},
        "manage": {"tenant_admin", "platform_admin"},
    },
}


async def _membership_grants(
    db: AsyncSession,
    user_id: Any,
    tenant_id: Any,
    module: str,
    action: str,
) -> bool:
    """True when the user's tenant membership grants module/action.

    ROOT blanket grant (10.21): an active ROOT membership grants EVERY
    module except the ``platform::*`` admin group — the root is the
    tenant owner.  The static legacy dict below then only governs
    NON-root membership roles (tenant_admin/member) on the tenant
    self-service surfaces; business modules (agent::*, integration::*,
    system::*) ride the seeded tenant RBAC roles for non-root members.
    """
    if tenant_id is None:
        return False
    membership = await _active_membership(db, user_id, tenant_id)
    if membership is None:
        return False
    return _membership_grants_from(membership, module, action)


def _membership_grants_from(
    membership: Any,
    module: str,
    action: str,
) -> bool:
    """Grant evaluation for an ALREADY-LOADED active membership.

    platform::* is the platform-admin domain (module group convention in
    resource_types.py) — memberships, root included, never grant it.
    Phase 10: the ROOT membership grants ALL tenant permissions inside
    its tenant — no additional role grants required (the root is the
    tenant owner; the slug-addressed workspace is theirs by creation).
    Checked BEFORE the static dict so modules missing from the dict
    (agent::*, integration::*, system::*) are granted to the root too.
    """
    # platform::* is the platform-admin domain (module group convention in
    # resource_types.py) — memberships, root included, never grant it.
    if module.startswith("platform::"):
        return False
    # Phase 10: the ROOT membership grants ALL tenant permissions inside
    # its tenant — no additional role grants required (the root is the
    # tenant owner; the slug-addressed workspace is theirs by creation).
    # Checked BEFORE the static dict so modules missing from the dict
    # (agent::*, integration::*, system::*) are granted to the root too.
    if getattr(membership, "is_root", False):
        return True
    allowed_roles = _TENANT_MEMBERSHIP_GRANTS.get(module, {}).get(action)
    if not allowed_roles:
        return False
    role = membership.tenant_role.value if hasattr(membership.tenant_role, "value") else str(membership.tenant_role)
    return role in allowed_roles


async def guard_non_root_membership(
    db: AsyncSession,
    membership: Any,
    *,
    request: Request | None = None,
    action: str = "mutate",
) -> None:
    """Reject any mutation targeting the ROOT membership (Phase 10).

    Shared guard used by the tenant self-service router AND every
    platform-admin path that could touch a membership: the root (owner)
    membership is immutable — it can never be demoted, suspended,
    removed or role-changed, regardless of the actor (delegated tenant
    admin or platform admin).  Rejections raise HTTP 403 and record a
    security-relevant ``root_protection_rejected`` TenantAuditEvent
    (fire-and-forget-safe; the audit failure never masks the 403).

    Raises:
        HTTPException 403 — when ``membership.is_root`` is true.
    """
    if membership is None or not getattr(membership, "is_root", False):
        return

    tenant_id = getattr(membership, "tenant_id", None)
    client_ip = getattr(getattr(request, "client", None), "host", None) if request is not None else None
    try:
        from app.db.models.tenant_audit_event import (
            TenantAuditActorType,
            TenantAuditEventType,
        )
        from app.services.tenancy.tenant_audit_service import TenantAuditService

        await TenantAuditService().record_safe(
            db,
            TenantAuditEventType.root_protection_rejected,
            tenant_id=tenant_id,
            actor_type=TenantAuditActorType.system,  # refined by callers below when known
            target_resource=f"tenant_membership:{membership.id}",
            detail={"action": action, "root_user_id": str(membership.user_id)},
            is_security_relevant=True,
        )
        # Commit NOW: this guard raises HTTPException immediately after,
        # and FastAPI throws that exception into the get_db generator,
        # whose handler ROLLS BACK the request session — a flushed-only
        # audit would be silently lost (the rejection must be audited per
        # PRD CS-30/CS-31).  At this point the only pending write is the
        # audit event itself, so committing is safe.
        await db.commit()
    except Exception:
        logger.exception("Failed to audit root protection rejection")

    logger.warning(
        "Root protection: rejected %s of root membership %s (tenant=%s)",
        action, membership.id, tenant_id,
    )
    raise HTTPException(
        status_code=403,
        detail=(
            "The organization owner (root) membership is immutable and "
            "cannot be changed or removed"
        ),
    )


async def _active_membership(
    db: AsyncSession,
    user_id: Any,
    tenant_id: Any,
) -> Any | None:
    """The user's ACTIVE TenantUserMembership in *tenant_id*, or None.

    Single membership lookup shared by the no-access gate and the
    membership grants path in :func:`authorize_identity`.
    """
    from sqlalchemy import select

    from app.db.models.tenant_membership import (
        TenantUserMembership,
        TenantUserMembershipStatus,
    )

    return (
        await db.execute(
            select(TenantUserMembership).where(
                TenantUserMembership.user_id == user_id,
                TenantUserMembership.tenant_id == tenant_id,
                TenantUserMembership.status == TenantUserMembershipStatus.active,
            )
        )
    ).scalar_one_or_none()


class NoWorkspaceAccessError(HTTPException):
    """Authenticated user WITHOUT an active membership in the resolved tenant.

    Authorization (membership) denial — explicitly NOT an authentication
    failure: clients must surface it as a permission error without
    clearing tokens or redirecting to login (no bounce loop;
    FIX-20260929-221449).

    Serialized FLAT by the app-level handler in ``app.main`` (registered
    for this subclass, so it takes precedence over FastAPI's default
    ``HTTPException`` envelope)::

        {"detail": "no_access_to_workspace", ...extra fields}

    ``detail`` is the machine-readable ``no_access_to_workspace`` marker;
    extra keyword arguments carry context (``required_permission`` for
    permission-gated calls, ``tenant_slug`` for membership dependencies).
    """

    def __init__(self, **extra: Any) -> None:
        super().__init__(status_code=403, detail="no_access_to_workspace")
        self.extra: dict[str, Any] = extra


def _no_access_to_workspace_detail(module: str, action: str) -> NoWorkspaceAccessError:
    """403 for a permission-gated call by a user with no membership in the
    resolved tenant — carries the structured ``required_permission`` payload
    so the frontend surfaces a targeted access-denied message."""
    return NoWorkspaceAccessError(
        required_permission=RequiredPermission(
            resource_type=module,
            action=action,
            resource_id=None,
        ).model_dump()
    )


async def _system_tenant_platform_admin(db: AsyncSession, user_id: Any) -> bool:
    """True when the user holds an ACTIVE ``platform_admin`` membership in
    the SYSTEM tenant (the platform console's membership-based gate,
    FIX-20260930-235927).

    Both lookups run through :func:`execute_unscoped` (identity plane):
    the platform console lives at the base domain where no tenant scope
    is bound, but these lookups must also stay correct if a scoped
    session ever reaches this path.
    """
    from sqlalchemy import select

    from app.db.models.tenant import Tenant
    from app.db.models.tenant_membership import (
        TenantUserMembership,
        TenantUserMembershipStatus,
    )
    from app.db.tenant_scoping import execute_unscoped

    system = (
        await execute_unscoped(
            db, select(Tenant.id).where(Tenant.is_system_tenant.is_(True))
        )
    ).scalar_one_or_none()
    if system is None:
        return False

    membership = (
        await execute_unscoped(
            db,
            select(TenantUserMembership).where(
                TenantUserMembership.user_id == user_id,
                TenantUserMembership.tenant_id == system,
                TenantUserMembership.status == TenantUserMembershipStatus.active,
                TenantUserMembership.tenant_role == "platform_admin",
            ),
        )
    ).scalar_one_or_none()
    return membership is not None


async def authorize_identity(
    db: AsyncSession,
    claims: dict[str, Any],
    module: str,
    action: str,
    *,
    is_super_admin: bool = False,
    tenant_id: Any = None,
) -> dict[str, Any]:
    """Enforce a permission-engine check for an already-validated identity.

    Shared permission gate used by BOTH auth paths:

    - ``require_permission()`` — requests authenticated by ``JWTAuthMiddleware``
      (claims come from ``request.state.identity``); and
    - self-authenticating endpoints that validate the JWT themselves — e.g. the
      SSE topology stream (``GET /agents/runtime/topology/stream``), which
      receives the token via the ``?token=`` query param because browser
      ``EventSource`` cannot set Authorization headers.

    Keeping one implementation guarantees the stream enforces EXACTLY the same
    permission semantics as the REST endpoint (permission parity).

    *tenant_id* — the request's resolved tenant id (multi-tenancy on); binds
    role collection to the tenant so identical role names in different tenants
    never collide.  None (switch off) leaves single-tenant behaviour unchanged.

    Identity-plane note (FIX-20260929-221449): the PlatformUser-by-sub
    lookup is an IDENTITY resolution — it runs tenant-scope-exempt
    (:func:`app.db.tenant_scoping.execute_unscoped`) so a user with no
    membership in the resolved tenant still RESOLVES.  Access is then
    decided by membership: without an ACTIVE membership in the resolved
    tenant the request is denied with the clean structured
    ``no_access_to_workspace`` 403 — never "user must re-authenticate".

    Raises:
        HTTPException 403 ``no_access_to_workspace`` — resolved tenant and
            the user holds no ACTIVE membership in it.
        HTTPException 403 — if the user has no matching allow policy.
        HTTPException 403 — if the user has no PlatformUser record yet.
    """
    from sqlalchemy import select

    from app.db.models.platform_user import PlatformUser
    from app.db.tenant_scoping import execute_unscoped
    from app.services.permissions.permission_engine import PermissionEngine

    # Super admin bypass — full access to all modules and actions
    if is_super_admin:
        return claims

    sub: str | None = claims.get("sub")
    realm_roles = claims.get("realm_access", {}).get("roles", [])
    client_roles: list[str] = []
    resource_access = claims.get("resource_access", {})
    for client_id, access in (resource_access or {}).items():
        if isinstance(access, dict):
            client_roles.extend(access.get("roles", []))
    logger.debug(
        "authorize_identity check: module=%s action=%s sub=%s realm_roles=%s client_roles=%s",
        module, action, sub, realm_roles, client_roles,
    )
    if not sub:
        logger.warning("authorize_identity: No identity claims found")
        raise HTTPException(status_code=403, detail="No identity claims found.")

    # Identity plane (FIX-20260929-221449): resolving WHO the request is
    # from is platform-level — exempt from the session's tenant scope so
    # the user row is visible without a membership in the resolved tenant.
    result = await execute_unscoped(
        db, select(PlatformUser).where(PlatformUser.sub == sub)
    )
    user = result.scalar_one_or_none()
    if user is None:
        logger.warning(
            "authorize_identity: PlatformUser not found for sub=%s — user must re-authenticate",
            sub,
        )
        raise HTTPException(
            status_code=403,
            detail="User not found in platform. Please re-authenticate.",
        )

    logger.debug(
        "authorize_identity: PlatformUser found — id=%s sub=%s",
        user.id, user.sub,
    )

    # No-membership gate (FIX-20260929-221449): an authenticated user
    # WITHOUT an active membership in the RESOLVED tenant gets the clean
    # structured no_access_to_workspace denial — the identity is valid
    # (no re-authentication), but the workspace grants them nothing.
    # Cross-tenant safety is preserved: membership + row-level scoping
    # still gate every piece of data.
    membership = None
    if tenant_id is not None:
        membership = await _active_membership(db, user.id, tenant_id)
        if membership is None:
            logger.warning(
                "authorize_identity: user_id=%s has no active membership in "
                "resolved tenant=%s — no_access_to_workspace",
                user.id, tenant_id,
            )
            raise _no_access_to_workspace_detail(module, action)

    # Tenant membership grants (multi-tenancy): the ROOT membership grants
    # every non-platform module directly (blanket tenant-owner grant);
    # non-root membership roles keep the legacy tenant self-service
    # grants (tenant::*).  Business modules (agent::*, integration::*,
    # system::*) reach this path too so a root tenant owner can use them
    # without any platform RBAC role.
    if membership is not None and not module.startswith("platform::"):
        if _membership_grants_from(membership, module, action):
            logger.debug(
                "authorize_identity ALLOWED via membership: user_id=%s module=%s action=%s",
                user.id, module, action,
            )
            return claims

    # Platform gating (FIX-20260930-235927): with multi-tenancy ON, the
    # ``platform::*`` admin group is satisfied ONLY by the super-admin
    # bypass (above) or an ACTIVE platform_admin membership in the SYSTEM
    # tenant.  The PermissionEngine collects GLOBAL tenant-less roles for
    # every module — legacy pre-tenancy ``system_admin`` wildcard holders
    # would otherwise unlock the whole platform console.  Global roles
    # remain effective for every non-platform module (legacy behaviour in
    # tenant workspaces unchanged); multi-tenancy OFF skips this gate
    # entirely (byte-for-byte legacy, no platform concept).
    if module.startswith("platform::"):
        from app.services.tenancy.platform_settings_service import (
            get_platform_settings_service,
        )

        if await get_platform_settings_service().is_multi_tenancy_enabled(db):
            if await _system_tenant_platform_admin(db, user.id):
                logger.debug(
                    "authorize_identity ALLOWED via system-tenant platform_admin "
                    "membership: user_id=%s module=%s action=%s",
                    user.id, module, action,
                )
                return claims
            logger.warning(
                "authorize_identity PLATFORM DENIED: user_id=%s module=%s action=%s "
                "— platform::* requires a system-tenant platform_admin membership "
                "when multi-tenancy is ON",
                user.id, module, action,
            )
            raise HTTPException(
                status_code=403,
                detail=PermissionDeniedDetail(
                    detail=(
                        "Platform administration requires a platform_admin "
                        "membership in the system tenant."
                    ),
                    required_permission=RequiredPermission(
                        resource_type=module,
                        action=action,
                        resource_id=None,
                    ),
                ).model_dump(),
            )

    auth = await PermissionEngine().authorize(
        db=db,
        user_id=user.id,
        module=module,
        action=action,
        resource_id="*",
        resource_tags={},
        tenant_id=tenant_id,
    )
    if not auth.allowed:
        logger.warning(
            "authorize_identity DENIED: user_id=%s module=%s action=%s reason=%s",
            user.id, module, action, auth.reason,
        )
        raise HTTPException(
            status_code=403,
            detail=PermissionDeniedDetail(
                detail=auth.reason,
                required_permission=RequiredPermission(
                    resource_type=module,
                    action=action,
                    resource_id=None,
                ),
            ).model_dump(),
        )
    logger.debug(
        "authorize_identity ALLOWED: user_id=%s module=%s action=%s",
        user.id, module, action,
    )

    return claims


def require_permission(module: str, action: str) -> Callable:
    """Dependency factory: returns a FastAPI dependency that enforces permission-engine access.

    The same callable is returned for identical (module, action) pairs so that
    app.dependency_overrides works correctly in tests.

    Uses the Permission Engine (policy-based) to check whether the calling user may
    perform *action* on *module*.  The system_admin role's wildcard policy grants access
    to all modules and actions automatically.

    Usage::

        @router.post("/something")
        async def create_something(
            _: dict = Depends(require_permission("permissions", "manage")),
        ):
            ...

    Raises:
        HTTPException 403 — if the user has no matching allow policy.
        HTTPException 403 — if the user has no PlatformUser record yet.
    """
    if (module, action) in _permission_dep_cache:
        return _permission_dep_cache[(module, action)]

    async def _dep(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> dict[str, Any]:
        claims: dict[str, Any] = getattr(request.state, "identity", {})
        # Tenant-bound RBAC (multi-tenancy on): collect the resolved tenant
        # so roles are evaluated within the request's tenant.  No-op (None)
        # when the switch is off.
        from app.core.tenant_context import get_tenant_context

        tenant_context = get_tenant_context(request)
        return await authorize_identity(
            db,
            claims,
            module,
            action,
            is_super_admin=bool(getattr(request.state, "is_super_admin", False)),
            tenant_id=(
                tenant_context.tenant_id if tenant_context.is_set else None
            ),
        )

    _permission_dep_cache[(module, action)] = _dep
    return _dep


async def require_service_certificate(
    request: Request,
    db: DbSession,
) -> dict:
    """Require a valid service certificate (for /internal/* endpoints).

    Extracts the client certificate from the ``X-Client-Certificate`` request
    header, validates it against the CA, and enforces that it is a *service*
    certificate (CN prefix ``service:``).

    Task 4.1: Returns **401 Unauthorized** when the certificate is absent or
    cryptographically invalid (expired, bad signature, revoked).

    Task 4.5: Returns **403 Forbidden** when the certificate is
    cryptographically valid but carries a ``CN=agent-instance:*`` subject,
    distinguishing an explicit capability boundary violation from a generic
    auth failure.  This prevents compromised agent containers from accessing
    internal Control Center APIs.

    Returns:
        Dict with ``cert_type`` and ``service_name`` on success.

    Raises:
        HTTPException 401 — certificate absent or invalid.
        HTTPException 403 — certificate is a valid agent-instance cert, which
            is explicitly blocked from ``/internal/*`` routes.
    """
    from app.services.certificate_authority import CertificateAuthorityService, CertificateType

    cert_pem = request.headers.get("X-Client-Certificate")
    if not cert_pem:
        raise HTTPException(
            status_code=401,
            detail="Service certificate required — no client certificate provided",
        )

    # Decode escaped newlines from HTTP header format
    cert_pem = cert_pem.replace("\\n", "\n")

    ca_service = CertificateAuthorityService()
    result = await ca_service.validate(cert_pem, db, "internal-api", "internal-access")
    if not result.valid:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid certificate: {result.reason}",
        )

    # Task 4.5: agent-instance certs are explicitly forbidden (403, not 401) so
    # that the distinction between "no credential" and "wrong credential type"
    # is visible in audit logs and client error handling.
    if result.cert_type == CertificateType.agent_instance:
        raise HTTPException(
            status_code=403,
            detail="Agent-instance certificates are not permitted on /internal/* endpoints",
        )

    if result.cert_type != CertificateType.service:
        raise HTTPException(
            status_code=401,
            detail=(
                f"Service certificate required — received "
                f"{result.cert_type or 'unknown'} certificate"
            ),
        )

    caller_type = _normalize_internal_caller(result.service_name)
    endpoint_template = _resolve_route_template(request)
    method = request.method.upper()

    if caller_type is None:
        _raise_internal_policy_deny(
            request=request,
            caller_type=None,
            service_name=result.service_name,
            reason="unknown_internal_caller",
            endpoint=endpoint_template,
        )

    allowlist = _INTERNAL_ALLOWLISTS.get(caller_type)
    if allowlist is None or (method, endpoint_template) not in allowlist:
        _raise_internal_policy_deny(
            request=request,
            caller_type=caller_type,
            service_name=result.service_name,
            reason="endpoint_not_allowlisted",
            endpoint=endpoint_template,
        )

    request.state.internal_caller_type = caller_type
    request.state.internal_caller_identity = result.service_name
    request.state.internal_cert_type = result.cert_type

    return {
        "cert_type": result.cert_type,
        "service_name": result.service_name,
        "caller_type": caller_type,
    }
