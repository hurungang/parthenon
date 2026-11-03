"""Tenant-scoped settings store helpers.

Reads/writes rows in ``tenant_settings`` strictly scoped to the given
tenant id. Callers are responsible for resolving the SESSION tenant
(root tenant when multi-tenancy is off); this module never guesses.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenant_setting import TenantSetting


async def get_value(db: AsyncSession, tenant_id: uuid.UUID, key: str) -> Any | None:
    """Return the tenant's value for ``key``, or None when unset."""
    row = (
        await db.execute(
            select(TenantSetting).where(
                TenantSetting.tenant_id == tenant_id,
                TenantSetting.key == key,
            )
        )
    ).scalar_one_or_none()
    return row.value if row is not None else None


async def set_value(db: AsyncSession, tenant_id: uuid.UUID, key: str, value: Any) -> None:
    """Create or update the tenant's row for ``key`` (upsert)."""
    row = (
        await db.execute(
            select(TenantSetting).where(
                TenantSetting.tenant_id == tenant_id,
                TenantSetting.key == key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = TenantSetting(tenant_id=tenant_id, key=key, value=value)
        db.add(row)
    else:
        row.value = value
    await db.flush()
