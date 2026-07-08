"""System Config API — identity provider and super admin management.

All endpoints require super admin or admin authentication.
"""

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import DbSession
from app.schemas.system_config import (
    IdentityProviderConfigCreate,
    IdentityProviderConfigListResponse,
    IdentityProviderConfigResponse,
    IdentityProviderConfigToggle,
    IdentityProviderConfigUpdate,
    OIDCTestRequest,
    OIDCTestResponse,
    SuperAdminLoginRequest,
    SuperAdminLoginResponse,
    SuperAdminPasswordUpdateRequest,
    SuperAdminStatusResponse,
    SuperAdminToggleRequest,
)
from app.services.oidc_config_service import OIDCConfigError, OIDCConfigService
from app.services.super_admin_auth_service import (
    SuperAdminAuthError,
    SuperAdminAuthService,
)

logger = logging.getLogger(__name__)

SystemConfigRouter = APIRouter(prefix="/system", tags=["System Config"])
AuthRouter = APIRouter(prefix="/auth", tags=["Auth"])


# ──────────────────────────────────────────────────────────────────────────────
# Auth endpoints (public)
# ──────────────────────────────────────────────────────────────────────────────


@AuthRouter.post("/super-admin/login", response_model=SuperAdminLoginResponse)
async def super_admin_login(
    request: Request,
    body: SuperAdminLoginRequest,
    db: DbSession,
) -> SuperAdminLoginResponse:
    """Authenticate as the built-in super admin.

    Returns a short-lived internal JWT for platform access.
    Public endpoint — no prior auth required.
    """
    service = SuperAdminAuthService()
    try:
        token = await service.login(db, body.username, body.password)
        await db.commit()
        return SuperAdminLoginResponse(
            access_token=token,
            username=body.username,
        )
    except SuperAdminAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


@AuthRouter.post("/super-admin/refresh", response_model=SuperAdminLoginResponse)
async def super_admin_refresh(
    request: Request,
    db: DbSession,
) -> SuperAdminLoginResponse:
    """Refresh a super admin JWT.

    Requires a valid (non-expired) super admin token in the Authorization header.
    The identity attached to the request by the middleware is used to issue
    a new token for the same user.
    """
    identity = getattr(request.state, "identity", None)
    if not identity or not identity.get("is_super_admin"):
        raise HTTPException(status_code=401, detail="Not a valid super admin session")

    username = identity.get("username", "")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token identity")

    service = SuperAdminAuthService()
    try:
        # Re-issue token for the same user (validate they still exist & are enabled)
        creds = await service._get_credentials(db)  # noqa: SLF001
        if creds is None or creds.username != username or not creds.is_enabled:
            raise HTTPException(status_code=401, detail="Super admin account is no longer valid")

        token = service._issue_token(creds)  # noqa: SLF001
        return SuperAdminLoginResponse(
            access_token=token,
            username=username,
        )
    except SuperAdminAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# Identity Provider CRUD (System Config)
# ──────────────────────────────────────────────────────────────────────────────


def _get_changed_by(request: Request) -> str:
    """Extract the identity of the admin making the change."""
    identity = getattr(request.state, "identity", {})
    if identity.get("is_super_admin"):
        return identity.get("username", "super_admin")
    return identity.get("sub", "unknown")


@SystemConfigRouter.get(
    "/identity-providers", response_model=IdentityProviderConfigListResponse
)
async def list_identity_providers(
    request: Request,
    db: DbSession,
) -> IdentityProviderConfigListResponse:
    """List all configured identity providers (user + agent).

    Public endpoint — accessible before OIDC auth so the login page can
    discover available providers. Client secrets are masked.
    """
    service = OIDCConfigService()
    configs = await service.list_providers(db)

    items = []
    for cfg in configs:
        resp = _config_to_response(cfg, mask_secret=True)
        items.append(resp)

    return IdentityProviderConfigListResponse(items=items, total=len(items))


@SystemConfigRouter.get(
    "/identity-providers/{scope}", response_model=IdentityProviderConfigResponse
)
async def get_identity_provider(
    scope: str,
    request: Request,
    db: DbSession,
) -> IdentityProviderConfigResponse:
    """Get a single provider config by scope (user or agent).

    Requires super admin or admin auth.
    """
    _require_auth(request)
    service = OIDCConfigService()
    try:
        config = await service.get_by_scope(db, scope)
    except OIDCConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if config is None:
        raise HTTPException(status_code=404, detail=f"No provider config for scope '{scope}'")

    return _config_to_response(config, mask_secret=False)


@SystemConfigRouter.post(
    "/identity-providers", response_model=IdentityProviderConfigResponse, status_code=201
)
async def create_identity_provider(
    body: IdentityProviderConfigCreate,
    request: Request,
    db: DbSession,
) -> IdentityProviderConfigResponse:
    """Create a new identity provider config.

    Requires super admin or admin auth.
    Validates OIDC Discovery at the issuer URL before persisting.
    Rejects duplicate provider_scope entries.
    Triggers OIDCProviderRegistry hot-reload on success.
    """
    _require_auth(request)
    changed_by = _get_changed_by(request)
    service = OIDCConfigService()
    try:
        config = await service.create_provider(
            db,
            provider_scope=body.provider_scope,
            provider_type=body.provider_type,
            display_name=body.display_name,
            issuer_url=body.issuer_url,
            client_id=body.client_id,
            client_secret=body.client_secret,
            public_client_id=body.public_client_id,
            scopes=body.scopes,
            claim_mappings=body.claim_mappings,
            is_enabled=body.is_enabled,
            changed_by=changed_by,
        )
        await db.commit()
        await _reload_registry(db, scope=body.provider_scope)
        return _config_to_response(config, mask_secret=False)
    except OIDCConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@SystemConfigRouter.put(
    "/identity-providers/{scope}", response_model=IdentityProviderConfigResponse
)
async def update_identity_provider(
    scope: str,
    body: IdentityProviderConfigUpdate,
    request: Request,
    db: DbSession,
) -> IdentityProviderConfigResponse:
    """Update an existing identity provider config.

    Requires super admin or admin auth.
    Only non-None fields in the request body are updated.
    Triggers OIDCProviderRegistry hot-reload on success.
    """
    _require_auth(request)
    changed_by = _get_changed_by(request)
    service = OIDCConfigService()
    try:
        config = await service.update_provider(
            db,
            scope,
            provider_type=body.provider_type,
            display_name=body.display_name,
            issuer_url=body.issuer_url,
            client_id=body.client_id,
            client_secret=body.client_secret,
            public_client_id=body.public_client_id,
            scopes=body.scopes,
            claim_mappings=body.claim_mappings,
            is_enabled=body.is_enabled,
            changed_by=changed_by,
        )
        await db.commit()
        await _reload_registry(db, scope=scope)
        return _config_to_response(config, mask_secret=False)
    except OIDCConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@SystemConfigRouter.delete("/identity-providers/{scope}", status_code=204)
async def delete_identity_provider(
    scope: str,
    request: Request,
    db: DbSession,
) -> Response:
    """Delete an identity provider config.

    Requires super admin or admin auth.
    Triggers OIDCProviderRegistry hot-reload on success.
    """
    _require_auth(request)
    changed_by = _get_changed_by(request)
    service = OIDCConfigService()
    try:
        await service.delete_provider(db, scope, changed_by=changed_by)
        await db.commit()
        await _reload_registry(db, scope=scope)
    except OIDCConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(status_code=204)


@SystemConfigRouter.patch(
    "/identity-providers/{scope}/toggle", response_model=IdentityProviderConfigResponse
)
async def toggle_identity_provider(
    scope: str,
    body: IdentityProviderConfigToggle,
    request: Request,
    db: DbSession,
) -> IdentityProviderConfigResponse:
    """Enable or disable a provider without deleting its config.

    Requires super admin or admin auth.
    """
    _require_auth(request)
    changed_by = _get_changed_by(request)
    service = OIDCConfigService()
    try:
        config = await service.toggle_provider(
            db, scope, is_enabled=body.is_enabled, changed_by=changed_by
        )
        await db.commit()
        await _reload_registry(db, scope=scope)
        return _config_to_response(config, mask_secret=False)
    except OIDCConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# OIDC Testing (System Config)
# ──────────────────────────────────────────────────────────────────────────────


@SystemConfigRouter.post(
    "/identity-providers/test", response_model=OIDCTestResponse
)
async def test_oidc_connection(
    body: OIDCTestRequest,
    request: Request,
    db: DbSession,
) -> OIDCTestResponse:
    """Test OIDC connectivity for a given issuer URL.

    Performs step-by-step diagnostics: discovery fetch, issuer validation,
    JWKS verification, and token endpoint check.  Results are not persisted.

    Requires super admin or admin auth.
    """
    _require_auth(request)
    service = OIDCConfigService()
    result = await service.test_connection(
        issuer_url=body.issuer_url,
        client_id=body.client_id,
        client_secret=body.client_secret,
    )
    return OIDCTestResponse(**result)


@SystemConfigRouter.post("/identity-providers/test-login")
async def initiate_test_login(
    body: OIDCTestRequest,
    request: Request,
    db: DbSession,
) -> dict:
    """Initiate a test OIDC authorization code flow.

    Returns a redirect URL that the frontend should open for the user.

    Requires super admin or admin auth.
    """
    _require_auth(request)
    # Generate a test session ID and store in-memory or Redis for callback
    test_id = str(uuid4())

    # Build the authorization URL
    issuer_url = body.issuer_url.rstrip("/")
    service = OIDCConfigService()

    # Validate discovery first
    try:
        result = await service.test_connection(
            issuer_url=issuer_url,
            client_id=body.client_id,
            client_secret=body.client_secret,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    discovery = result.get("discovery_doc", {})
    auth_endpoint = discovery.get("authorization_endpoint", "")

    if not auth_endpoint:
        raise HTTPException(status_code=400, detail="No authorization_endpoint in discovery document")

    # Store test session (simple in-process dict for now)
    _test_sessions[test_id] = {
        "issuer_url": issuer_url,
        "client_id": body.client_id,
        "client_secret": body.client_secret,
        "redirect_uri": body.redirect_uri or _get_test_callback_url(request),
        "status": "initiated",
        "created_at": str(__import__("datetime").datetime.now()),
    }

    import urllib.parse

    redirect_url = (
        f"{auth_endpoint}?"
        f"response_type=code&"
        f"client_id={urllib.parse.quote(body.client_id or '')}&"
        f"redirect_uri={urllib.parse.quote(body.redirect_uri or _get_test_callback_url(request), safe='')}&"
        f"scope=openid profile email&"
        f"state={test_id}"
    )

    return {
        "test_id": test_id,
        "redirect_url": redirect_url,
        "status": "initiated",
    }


@SystemConfigRouter.get("/identity-providers/test-login/callback")
async def test_login_callback(
    code: str,
    state: str,
    request: Request,
    db: DbSession,
) -> dict:
    """OIDC callback for test login — exchanges code for tokens.

    Validates the authorization code against the configured provider's
    token endpoint and returns the decoded claims.
    """
    session = _test_sessions.get(state)
    if session is None:
        raise HTTPException(status_code=400, detail="Unknown or expired test session")

    issuer_url = session["issuer_url"]
    client_id = session["client_id"]
    client_secret = session.get("client_secret")
    redirect_uri = session.get("redirect_uri", _get_test_callback_url(request))

    # Fetch discovery to get token endpoint
    service = OIDCConfigService()
    result = await service.test_connection(issuer_url=issuer_url)
    discovery = result.get("discovery_doc", {})
    token_endpoint = discovery.get("token_endpoint", "")

    if not token_endpoint:
        raise HTTPException(status_code=400, detail="No token_endpoint in discovery document")

    # Exchange code for tokens
    import httpx
    from app.core.ssl_context import get_ssl_context

    try:
        async with httpx.AsyncClient(timeout=15.0, verify=get_ssl_context()) as http_client:
            resp = await http_client.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id or "",
                    "client_secret": client_secret or "",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            tokens = resp.json()
    except Exception as exc:
        _test_sessions[state]["status"] = "failed"
        _test_sessions[state]["error"] = str(exc)
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {exc}")

    # Decode ID token claims
    id_token = tokens.get("id_token", "")
    claims = {}
    if id_token:
        from jose import jwt as jwt_decode
        try:
            claims = jwt_decode.get_unverified_claims(id_token)
        except Exception:
            claims = {"error": "Could not decode ID token"}

    _test_sessions[state]["status"] = "completed"
    _test_sessions[state]["claims"] = claims

    return {
        "test_id": state,
        "status": "completed",
        "claims": claims,
        "token_response": {k: v for k, v in tokens.items() if k != "id_token"},
        "id_token_claims": claims,
    }


@SystemConfigRouter.get("/identity-providers/test-login/status/{test_id}")
async def test_login_status(
    test_id: str,
    request: Request,
    db: DbSession,
) -> dict:
    """Poll the status of a running test-login session."""
    session = _test_sessions.get(test_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Test session not found")
    return session


# ──────────────────────────────────────────────────────────────────────────────
# Super Admin Management (System Config)
# ──────────────────────────────────────────────────────────────────────────────


@SystemConfigRouter.get(
    "/super-admin/status", response_model=SuperAdminStatusResponse
)
async def get_super_admin_status(
    request: Request,
    db: DbSession,
) -> SuperAdminStatusResponse:
    """Return the current super admin status (public endpoint).

    Accessible without auth so the login page can determine whether to
    show the super admin login form.
    """
    service = SuperAdminAuthService()
    status = await service.get_status(db)
    if status is None:
        return SuperAdminStatusResponse(
            is_enabled=service.is_enabled(),
            username=None,
            last_login_at=None,
        )
    # Env-level disable overrides DB
    env_enabled = service.is_enabled()
    status["is_enabled"] = status["is_enabled"] and env_enabled
    return SuperAdminStatusResponse(**status)


@SystemConfigRouter.patch(
    "/super-admin/toggle", response_model=SuperAdminStatusResponse
)
async def toggle_super_admin(
    body: SuperAdminToggleRequest,
    request: Request,
    db: DbSession,
) -> SuperAdminStatusResponse:
    """Enable or disable the super admin account.

    Requires super admin auth.
    Disabling requires at least one active OIDC provider (guard rail).
    """
    _require_super_admin(request)
    service = SuperAdminAuthService()

    # Guard rail: before disabling, ensure at least one OIDC provider exists
    if not body.is_enabled:
        config_service = OIDCConfigService()
        providers = await config_service.list_providers(db)
        active_providers = [p for p in providers if p.is_enabled]
        if not active_providers:
            raise HTTPException(
                status_code=400,
                detail="Cannot disable super admin: no active OIDC provider configured. "
                       "Configure at least one OIDC provider before disabling the super admin.",
            )

    try:
        creds = await service.toggle(db, is_enabled=body.is_enabled)
        await db.commit()
        status = await service.get_status(db)
        if status is None:
            return SuperAdminStatusResponse(is_enabled=body.is_enabled)
        return SuperAdminStatusResponse(**status)
    except SuperAdminAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@SystemConfigRouter.put(
    "/super-admin/password", response_model=SuperAdminStatusResponse
)
async def update_super_admin_password(
    body: SuperAdminPasswordUpdateRequest,
    request: Request,
    db: DbSession,
) -> SuperAdminStatusResponse:
    """Update the super admin password.

    Requires super admin auth.
    """
    _require_super_admin(request)
    service = SuperAdminAuthService()
    try:
        await service.update_password(
            db, body.current_password, body.new_password
        )
        await db.commit()
        status = await service.get_status(db)
        if status is None:
            return SuperAdminStatusResponse(is_enabled=True)
        return SuperAdminStatusResponse(**status)
    except SuperAdminAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

# In-memory test session store for OIDC test-login flow
_test_sessions: dict[str, dict] = {}


def _get_test_callback_url(request: Request) -> str:
    """Build the test-login callback URL for the current server."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/system/identity-providers/test-login/callback"


def _config_to_response(
    config, *, mask_secret: bool = False
) -> IdentityProviderConfigResponse:
    """Convert a model instance to a response schema."""
    secret = config.encrypted_client_secret
    if mask_secret:
        secret = OIDCConfigService.mask_secret(secret)
    return IdentityProviderConfigResponse(
        id=str(config.id),
        provider_scope=config.provider_scope,
        provider_type=config.provider_type,
        display_name=config.display_name,
        issuer_url=config.issuer_url,
        client_id=config.client_id,
        encrypted_client_secret=secret,
        public_client_id=getattr(config, "ui_client_id", None),
        scopes=config.scopes,
        claim_mappings=config.claim_mappings,
        is_enabled=config.is_enabled,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _require_auth(request: Request) -> None:
    """Raise 401 if the request is not authenticated."""
    identity = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(status_code=401, detail="Authentication required")


def _require_super_admin(request: Request) -> None:
    """Raise 401/403 if the request is not from a super admin."""
    identity = getattr(request.state, "identity", None)
    if identity is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not identity.get("is_super_admin"):
        raise HTTPException(status_code=403, detail="Super admin access required")


async def _reload_registry(db: AsyncSession, scope: str) -> None:
    """Trigger a hot-reload of the OIDC Provider Registry."""
    try:
        from app.main import _get_registry
        registry = _get_registry()
        await registry.reload_single(db, scope)
        logger.info("SystemConfig: hot-reloaded provider registry for scope=%s", scope)
    except Exception:
        logger.exception("SystemConfig: failed to hot-reload registry")
