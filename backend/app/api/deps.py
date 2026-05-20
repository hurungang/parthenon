"""Shared FastAPI dependencies for the API layer."""
from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import DbSession, get_db
from app.schemas.errors import PermissionDeniedDetail, RequiredPermission

# Cache of (module, action) → _dep function so the same callable is returned
# for repeated calls with identical arguments.  This allows tests to use
# app.dependency_overrides with the result of require_permission().
_permission_dep_cache: dict[tuple[str, str], Callable] = {}


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
        sub: str | None = claims.get("sub")
        if not sub:
            raise HTTPException(status_code=403, detail="No identity claims found.")

        result = await db.execute(
            select(PlatformUser).where(PlatformUser.sub == sub)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=403,
                detail="User not found in platform. Please re-authenticate.",
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

    return {"cert_type": result.cert_type, "service_name": result.service_name}
