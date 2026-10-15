"""Platform identity-provider API — manages the ROOT tenant's providers.

The shared (NULL-tenant) slot is RETIRED: every tenant uses ONLY its
own identity provider.  The platform surface manages the ROOT tenant's
``(root_id, scope)`` slots — platform admins are root-tenant users, so
they manage their own tenant's providers here.  These handlers call the
SAME ``OIDCConfigService`` with ``tenant_id=root_tenant_id`` every time
— a platform admin can never accidentally touch another tenant's own
``(tenant, scope)`` slot from here.

All routes are guarded by ``platform::settings`` (metadata-level platform
administration; no tenant business data is exposed).
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.deps import require_permission
from app.api.v1.system_config import (
    _config_to_response,
    _get_changed_by,
    _reload_registry,
)
from app.core.resource_types import RT_PLATFORM_SETTINGS
from app.db.session import DbSession
from app.schemas.system_config import (
    IdentityProviderConfigCreate,
    IdentityProviderConfigListResponse,
    IdentityProviderConfigResponse,
    IdentityProviderConfigToggle,
    IdentityProviderConfigUpdate,
)
from app.services.oidc_config_service import OIDCConfigError, OIDCConfigService

logger = logging.getLogger(__name__)

PlatformIdentityProvidersRouter = APIRouter(
    prefix="/platform/identity-providers", tags=["Platform: Identity Providers"]
)


async def _root_tenant_id(db: DbSession) -> uuid.UUID:
    """The ROOT tenant's id (``Tenant.is_system_tenant``), or 400."""
    from app.services.tenancy.root_tenant import get_root_tenant_id

    root_id = await get_root_tenant_id(db)
    if root_id is None:
        raise HTTPException(
            status_code=400,
            detail="Root tenant not initialized; complete setup first.",
        )
    return root_id


@PlatformIdentityProvidersRouter.get(
    "", response_model=IdentityProviderConfigListResponse
)
async def list_platform_identity_providers(
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_SETTINGS, "read")),
) -> IdentityProviderConfigListResponse:
    """List the ROOT tenant's provider configs (secrets masked)."""
    configs = await OIDCConfigService().list_providers(
        db, tenant_id=await _root_tenant_id(db)
    )
    items = [_config_to_response(cfg, mask_secret=True) for cfg in configs]
    return IdentityProviderConfigListResponse(items=items, total=len(items))


@PlatformIdentityProvidersRouter.get(
    "/{scope}", response_model=IdentityProviderConfigResponse
)
async def get_platform_identity_provider(
    scope: str,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_SETTINGS, "read")),
) -> IdentityProviderConfigResponse:
    """Get a ROOT-tenant provider config by scope (user or agent)."""
    try:
        config = await OIDCConfigService().get_by_scope(
            db, scope, tenant_id=await _root_tenant_id(db)
        )
    except OIDCConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if config is None:
        raise HTTPException(status_code=404, detail=f"No provider config for scope '{scope}'")
    return _config_to_response(config, mask_secret=False)


@PlatformIdentityProvidersRouter.post(
    "", response_model=IdentityProviderConfigResponse, status_code=201
)
async def create_platform_identity_provider(
    body: IdentityProviderConfigCreate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_SETTINGS, "manage")),
) -> IdentityProviderConfigResponse:
    """Create a provider config in the ROOT tenant's slot."""
    try:
        config = await OIDCConfigService().create_provider(
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
            default_tenant_role=body.default_tenant_role,
            changed_by=_get_changed_by(request),
            tenant_id=await _root_tenant_id(db),
        )
        await db.commit()
        await _reload_registry(db, scope=body.provider_scope)
        return _config_to_response(config, mask_secret=False)
    except OIDCConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@PlatformIdentityProvidersRouter.put(
    "/{scope}", response_model=IdentityProviderConfigResponse
)
async def update_platform_identity_provider(
    scope: str,
    body: IdentityProviderConfigUpdate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_SETTINGS, "manage")),
) -> IdentityProviderConfigResponse:
    """Update the ROOT tenant's provider config for a scope."""
    try:
        config = await OIDCConfigService().update_provider(
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
            default_tenant_role=body.default_tenant_role,
            changed_by=_get_changed_by(request),
            tenant_id=await _root_tenant_id(db),
        )
        await db.commit()
        await _reload_registry(db, scope=scope)
        return _config_to_response(config, mask_secret=False)
    except OIDCConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@PlatformIdentityProvidersRouter.delete("/{scope}", status_code=204)
async def delete_platform_identity_provider(
    scope: str,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_SETTINGS, "manage")),
) -> Response:
    """Delete the ROOT tenant's provider config for a scope."""
    try:
        await OIDCConfigService().delete_provider(
            db,
            scope,
            changed_by=_get_changed_by(request),
            tenant_id=await _root_tenant_id(db),
        )
        await db.commit()
        await _reload_registry(db, scope=scope)
    except OIDCConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(status_code=204)


@PlatformIdentityProvidersRouter.patch(
    "/{scope}/toggle", response_model=IdentityProviderConfigResponse
)
async def toggle_platform_identity_provider(
    scope: str,
    body: IdentityProviderConfigToggle,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_SETTINGS, "manage")),
) -> IdentityProviderConfigResponse:
    """Enable/disable the ROOT tenant's provider config for a scope."""
    try:
        config = await OIDCConfigService().toggle_provider(
            db,
            scope,
            is_enabled=body.is_enabled,
            changed_by=_get_changed_by(request),
            tenant_id=await _root_tenant_id(db),
        )
        await db.commit()
        await _reload_registry(db, scope=scope)
        return _config_to_response(config, mask_secret=False)
    except OIDCConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
