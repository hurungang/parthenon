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
        from sqlalchemy import select

        from app.db.models.platform_user import PlatformUser
        from app.services.permissions.permission_engine import PermissionEngine

        claims: dict[str, Any] = getattr(request.state, "identity", {})

        # Super admin bypass — full access to all modules and actions
        if getattr(request.state, "is_super_admin", False):
            return claims

        sub: str | None = claims.get("sub")
        realm_roles = claims.get("realm_access", {}).get("roles", [])
        client_roles: list[str] = []
        resource_access = claims.get("resource_access", {})
        for client_id, access in (resource_access or {}).items():
            if isinstance(access, dict):
                client_roles.extend(access.get("roles", []))
        logger.debug(
            "require_permission check: module=%s action=%s sub=%s realm_roles=%s client_roles=%s",
            module, action, sub, realm_roles, client_roles,
        )
        if not sub:
            logger.warning("require_permission: No identity claims found in request.state.identity")
            raise HTTPException(status_code=403, detail="No identity claims found.")

        result = await db.execute(
            select(PlatformUser).where(PlatformUser.sub == sub)
        )
        user = result.scalar_one_or_none()
        if user is None:
            logger.warning(
                "require_permission: PlatformUser not found for sub=%s — user must re-authenticate",
                sub,
            )
            raise HTTPException(
                status_code=403,
                detail="User not found in platform. Please re-authenticate.",
            )

        logger.debug(
            "require_permission: PlatformUser found — id=%s sub=%s",
            user.id, user.sub,
        )

        auth = await PermissionEngine().authorize(
            db=db,
            user_id=user.id,
            module=module,
            action=action,
            resource_id="*",
            resource_tags={},
        )
        if not auth.allowed:
            logger.warning(
                "require_permission DENIED: user_id=%s module=%s action=%s reason=%s",
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
            "require_permission ALLOWED: user_id=%s module=%s action=%s",
            user.id, module, action,
        )

        return claims

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
