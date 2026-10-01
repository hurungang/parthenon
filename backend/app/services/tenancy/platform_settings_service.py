"""Platform Settings Service — cached reads/writes of tenant-agnostic settings.

Home of the ``multi_tenancy_enabled`` switch (default ``false``).  Every
tenant feature branches on the cached read — the flag is never queried
from the database per request.  Reads are served from an in-process cache
with a short TTL (bounding cross-worker staleness); writes are
write-through with immediate local invalidation and are audited to
``TenantAuditEvent`` via :class:`TenantAuditService`.

Failure semantics: any read error (including a database without the
platform_settings table) yields the built-in default (tenancy off), so
the platform stays completely inert rather than half-enabled.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.platform_setting import (
    PlatformSetting,
    PlatformSettingCategory,
)
from app.db.models.tenant_audit_event import (
    TenantAuditActorType,
    TenantAuditEventType,
)
from app.services.tenancy.tenant_audit_service import TenantAuditService

logger = logging.getLogger(__name__)

#: The platform tenancy switch — the single gate for every tenant feature.
MULTI_TENANCY_ENABLED_KEY = "multi_tenancy_enabled"

#: How long a cached setting value may be served before re-reading the DB.
_CACHE_TTL_SECONDS = 30.0

#: Built-in defaults applied when a setting row is absent or unreadable.
_DEFAULTS: dict[str, Any] = {
    MULTI_TENANCY_ENABLED_KEY: False,
}

_DESCRIPTIONS: dict[str, str] = {
    MULTI_TENANCY_ENABLED_KEY: (
        "Platform tenancy switch. When false (default) the platform behaves "
        "exactly as the single-tenant product; when true, tenants with hard "
        "logical isolation are enforced."
    ),
}


def _encode_bool(value: Any) -> dict[str, Any]:
    """Wrap a JSON value in the canonical ``{"enabled": bool}`` payload."""
    return {"enabled": bool(value)}


def _decode_bool(payload: dict[str, Any] | None) -> bool:
    """Read a boolean out of a setting payload, tolerating raw-bool shapes."""
    if payload is None:
        return False
    if isinstance(payload, bool):
        return payload
    if isinstance(payload, dict):
        value = payload.get("enabled")
        if isinstance(value, bool):
            return value
    return False


class PlatformSettingsService:
    """Cached platform setting reads/writes; seeds the tenancy switch."""

    def __init__(self, audit_service: TenantAuditService | None = None) -> None:
        self._audit = audit_service or TenantAuditService()
        # key -> (payload, cached_at_monotonic)
        self._cache: dict[str, tuple[dict[str, Any] | None, float]] = {}
        self._lock = asyncio.Lock()

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_setting(
        self, db: AsyncSession, key: str
    ) -> dict[str, Any] | None:
        """Return the setting payload (cached); None when the row is absent."""
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None:
            payload, cached_at = cached
            if now - cached_at < _CACHE_TTL_SECONDS:
                return payload

        async with self._lock:
            # Double-checked: another caller may have refreshed while we
            # waited on the lock.
            cached = self._cache.get(key)
            if cached is not None and time.monotonic() - cached[1] < _CACHE_TTL_SECONDS:
                return cached[0]

            try:
                result = await db.execute(
                    select(PlatformSetting).where(PlatformSetting.key == key)
                )
                row = result.scalar_one_or_none()
            except Exception:
                # Database without the row/table — fail safe to the default.
                logger.warning(
                    "Platform setting %s unreadable; serving built-in default", key
                )
                payload = self._default_payload(key)
                self._cache[key] = (payload, time.monotonic())
                return payload

            payload = row.value if row is not None else None
            self._cache[key] = (payload, time.monotonic())
            return payload

    async def is_multi_tenancy_enabled(self, db: AsyncSession) -> bool:
        """Cached tenancy-switch read; false by default and on any error.

        This is the single gate for all tenant features: middleware,
        scoping helpers, registry keying, and frontend-facing discovery
        all branch here.
        """
        payload = await self.get_setting(db, MULTI_TENANCY_ENABLED_KEY)
        if payload is None:
            return False
        return _decode_bool(payload)

    async def get_bool(
        self, db: AsyncSession, key: str, *, default: bool = False
    ) -> bool:
        """Cached boolean read of a platform setting."""
        payload = await self.get_setting(db, key)
        if payload is None:
            return default
        return _decode_bool(payload)

    # ── writes ───────────────────────────────────────────────────────────────

    async def set_setting(
        self,
        db: AsyncSession,
        key: str,
        value: dict[str, Any] | bool,
        *,
        category: PlatformSettingCategory = PlatformSettingCategory.tenancy,
        actor_id: uuid.UUID | None = None,
        actor_ip: str | None = None,
    ) -> PlatformSetting:
        """Upsert a platform setting; invalidates the cache and audits.

        The caller owns the surrounding transaction (commit on success).
        """
        if isinstance(value, bool):
            value = _encode_bool(value)

        result = await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == key)
        )
        row = result.scalar_one_or_none()
        previous: dict[str, Any] | None = row.value if row is not None else None

        if row is None:
            row = PlatformSetting(
                key=key,
                value=value,
                description=_DESCRIPTIONS.get(key),
                category=category,
                is_tenant_agnostic=True,
            )
            db.add(row)
        else:
            row.value = value
            if _DESCRIPTIONS.get(key):
                row.description = _DESCRIPTIONS[key]
        await db.flush()

        # Invalidate before auditing so the local worker immediately serves
        # the new value even if the audit write fails afterwards.
        self.invalidate(key)

        await self._audit.record_safe(
            db,
            TenantAuditEventType.platform_setting_updated,
            tenant_id=None,  # platform-level event
            actor_type=(
                TenantAuditActorType.platform_admin
                if actor_id is not None
                else TenantAuditActorType.system
            ),
            actor_id=actor_id,
            actor_ip=actor_ip,
            target_resource=f"platform_setting:{key}",
            detail={"previous": previous, "new": value},
            is_security_relevant=(key == MULTI_TENANCY_ENABLED_KEY),
        )
        logger.info("Platform setting %s updated to %s", key, value)
        return row

    # ── bootstrap ────────────────────────────────────────────────────────────

    async def seed_defaults(self, db: AsyncSession) -> None:
        """Idempotently seed the tenancy switch row as false on startup.

        Existing rows are never overwritten — only absent rows are created
        with their built-in defaults.
        """
        result = await db.execute(
            select(PlatformSetting).where(
                PlatformSetting.key == MULTI_TENANCY_ENABLED_KEY
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            db.add(
                PlatformSetting(
                    key=MULTI_TENANCY_ENABLED_KEY,
                    value=_encode_bool(False),
                    description=_DESCRIPTIONS[MULTI_TENANCY_ENABLED_KEY],
                    category=PlatformSettingCategory.tenancy,
                    is_tenant_agnostic=True,
                )
            )
            await db.flush()
            logger.info(
                "Seeded platform setting %s=false", MULTI_TENANCY_ENABLED_KEY
            )
        self.invalidate()

    # ── cache ────────────────────────────────────────────────────────────────

    def invalidate(self, key: str | None = None) -> None:
        """Drop one key (or the whole cache) so the next read hits the DB."""
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

    def _default_payload(self, key: str) -> dict[str, Any] | None:
        """Built-in payload for a key that cannot be read from the DB."""
        default = _DEFAULTS.get(key)
        if default is None:
            return None
        return _encode_bool(default)


_service: PlatformSettingsService | None = None


def get_platform_settings_service() -> PlatformSettingsService:
    """Return the module-level PlatformSettingsService singleton.

    The cache must be shared process-wide so every request (and the
    tenant resolution middleware) observes the same switch state.
    """
    global _service
    if _service is None:
        _service = PlatformSettingsService()
    return _service
