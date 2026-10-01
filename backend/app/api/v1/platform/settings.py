"""Platform settings API — read/write tenant-agnostic platform settings.

Home of the ``multi_tenancy_enabled`` switch:

- ``GET /platform/settings`` — all settings (platform admin only).
- ``GET /platform/settings/{key}`` — one setting.
- ``PUT /platform/settings/{key}`` — upsert a setting.  Toggling the
  tenancy switch runs the guarded enable/disable flow (system-tenant
  adoption on enable), is audited, and invalidates the cached value in
  all workers via a Redis pub/sub notification (workers also converge
  within the cache TTL).

All routes are guarded by ``platform::settings``.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import require_permission
from app.core.config import get_settings
from app.core.resource_types import RT_PLATFORM_SETTINGS
from app.db.models.platform_setting import PlatformSetting, PlatformSettingCategory
from app.db.session import DbSession
from app.services.tenancy.platform_settings_service import (
    MULTI_TENANCY_ENABLED_KEY,
    PlatformSettingsService,
    get_platform_settings_service,
)

logger = logging.getLogger(__name__)

PlatformSettingsRouter = APIRouter(prefix="/platform/settings", tags=["Platform: Settings"])

#: Redis channel used to notify all workers of a settings change.
SETTINGS_INVALIDATION_CHANNEL = "parthenon:platform_settings:invalidate"


# ── Schemas ──────────────────────────────────────────────────────────────────


class PlatformSettingRead(BaseModel):
    key: str
    value: Optional[dict[str, Any]] = None
    description: Optional[str] = None
    category: str
    updated_at: Optional[str] = None


class PlatformSettingsListResponse(BaseModel):
    items: list[PlatformSettingRead]
    multi_tenancy_enabled: bool


class PlatformSettingUpdate(BaseModel):
    value: Any = Field(..., description="New setting value (boolean switch or JSON payload)")


class PlatformSettingUpdateResponse(BaseModel):
    key: str
    value: Optional[dict[str, Any]] = None
    multi_tenancy_enabled: bool
    adoption: Optional[dict[str, Any]] = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _to_read(row: PlatformSetting) -> PlatformSettingRead:
    return PlatformSettingRead(
        key=row.key,
        value=row.value,
        description=row.description,
        category=row.category.value if hasattr(row.category, "value") else str(row.category),
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def _actor_id(request: Request) -> Optional[uuid.UUID]:
    """PlatformUser id of the caller (set by the auth middleware sync)."""
    value = getattr(request.state, "platform_user_id", None)
    try:
        return uuid.UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


async def _publish_invalidation(key: str) -> None:
    """Best-effort Redis notify so OTHER workers drop their cached value.

    Local worker cache is invalidated by the write itself; remote workers
    converge immediately via this message, or within the cache TTL if
    the notification is lost.
    """
    try:
        import redis.asyncio as aioredis

        redis_url = get_settings().computed_redis_url
        client = aioredis.from_url(redis_url, socket_connect_timeout=2)
        try:
            await client.publish(
                SETTINGS_INVALIDATION_CHANNEL,
                f"{{\"invalidated\": \"{key}\"}}",
            )
        finally:
            await client.aclose()
    except Exception:
        logger.warning("Platform settings invalidation publish failed (non-fatal)")


async def _toggle_multi_tenancy(
    db: DbSession,
    request: Request,
    enabled: bool,
) -> dict[str, Any]:
    """Guarded enable/disable flow for the tenancy switch.

    Enable: system-tenant adoption MUST run first (backfill + platform
    admin membership) while the switch is still off, then the switch
    flips.  Disable: validates the transition and restores single-tenant
    behaviour (data is preserved).
    """
    from app.services.tenancy.tenant_adoption_service import TenantAdoptionService

    adoption_service = TenantAdoptionService()
    actor_id = _actor_id(request)
    if enabled:
        summary = await adoption_service.adopt_system_tenant(db, actor_id=actor_id)
        return {"action": "enabled", **summary}
    summary = await adoption_service.validate_disable(db)
    return {"action": "disabled", **summary}


# ── Endpoints ────────────────────────────────────────────────────────────────


@PlatformSettingsRouter.get("", response_model=PlatformSettingsListResponse)
async def list_platform_settings(
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_SETTINGS, "read")),
) -> PlatformSettingsListResponse:
    """Read all platform settings (platform admin only)."""
    from sqlalchemy import select

    result = await db.execute(
        select(PlatformSetting).order_by(PlatformSetting.key.asc())
    )
    rows = list(result.scalars().all())
    multi_tenancy_enabled = (
        await get_platform_settings_service().is_multi_tenancy_enabled(db)
    )
    return PlatformSettingsListResponse(
        items=[_to_read(row) for row in rows],
        multi_tenancy_enabled=multi_tenancy_enabled,
    )


@PlatformSettingsRouter.get("/{key}", response_model=PlatformSettingRead)
async def get_platform_setting(
    key: str,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_SETTINGS, "read")),
) -> PlatformSettingRead:
    """Read one platform setting by key."""
    from sqlalchemy import select

    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == key)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Setting not found")
    return _to_read(row)


@PlatformSettingsRouter.put("/{key}", response_model=PlatformSettingUpdateResponse)
async def update_platform_setting(
    key: str,
    body: PlatformSettingUpdate,
    request: Request,
    db: DbSession,
    _: dict = Depends(require_permission(RT_PLATFORM_SETTINGS, "manage")),
) -> PlatformSettingUpdateResponse:
    """Upsert a platform setting (platform admin only).

    Toggling ``multi_tenancy_enabled`` runs the guarded adoption/disable
    flow, is audited, and invalidates the settings cache cluster-wide.
    """
    service = get_platform_settings_service()

    if key == MULTI_TENANCY_ENABLED_KEY:
        enabled = body.value if isinstance(body.value, bool) else bool(
            (body.value or {}).get("enabled") if isinstance(body.value, dict) else body.value
        )
        adoption = await _toggle_multi_tenancy(db, request, enabled)
        await service.set_setting(
            db, key, bool(enabled),
            category=PlatformSettingCategory.tenancy,
            actor_id=_actor_id(request),
            actor_ip=request.client.host if request.client else None,
        )
        # Per-tenant provider registry follows the switch in THIS worker.
        try:
            from app.main import _get_registry

            registry = _get_registry()
            registry.set_tenancy_enabled(enabled)
            await registry.reload(db)
        except Exception:
            logger.exception("OIDC registry reload after tenancy toggle failed")
        await _publish_invalidation(key)
        await db.commit()
        return PlatformSettingUpdateResponse(
            key=key,
            value={"enabled": enabled},
            multi_tenancy_enabled=enabled,
            adoption=adoption,
        )

    # Generic setting upsert
    value = body.value
    if not isinstance(value, dict):
        value = {"value": value}
    row = await service.set_setting(
        db, key, value,
        category=PlatformSettingCategory.platform,
        actor_id=_actor_id(request),
        actor_ip=request.client.host if request.client else None,
    )
    await _publish_invalidation(key)
    await db.commit()
    return PlatformSettingUpdateResponse(
        key=key,
        value=row.value,
        multi_tenancy_enabled=await service.is_multi_tenancy_enabled(db),
    )
