"""Per-tenant answerable-window (resume TTL) resolution — Control Center.

A paused conversational turn's ``ConversationTurnResume.expires_at`` is the
horizon inside which the operator's answer can still be applied. The window is
**tenant policy**: each tenant may pick its own value in the
``tenant_settings`` store under ``conversation_turn_resume_ttl_seconds``, with
the platform setting (``settings.conversation_turn_resume_ttl_seconds``,
default 900s / 15 minutes) as the fallback.

Control Center is the authority for the paused turn's expiry: both CC entry
points that create/refresh a resume record for a conversation
(``InterveneRequestStore.create_request`` and the internal
``PUT /conversations/{id}/resume`` relay) compute ``expires_at`` here and
ignore any client-supplied value, so Agent Runtime's platform-level setting can
never override tenant policy.

The same resolver backs the tenant settings API read/write
(``GET``/``PATCH /tenant/settings``).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.tenancy.tenant_settings_service import get_value, set_value

logger = logging.getLogger(__name__)

#: ``TenantSetting`` key holding the tenant's answerable-window override.
RESUME_TTL_SETTING_KEY = "conversation_turn_resume_ttl_seconds"

#: Lower bound for the answerable window (matches the platform setting clamp).
MIN_RESUME_TTL_SECONDS = 30


def platform_resume_ttl_seconds() -> int:
    """The platform default answerable window (clamped to the minimum)."""
    return max(
        MIN_RESUME_TTL_SECONDS,
        int(get_settings().conversation_turn_resume_ttl_seconds),
    )


def _coerce_seconds(value: Any) -> int | None:
    """Coerce a stored JSON value to whole seconds (``None`` when unusable)."""
    if isinstance(value, bool):  # bool is an int subclass — never a duration
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


async def resolve_resume_ttl_seconds(
    db: AsyncSession,
    tenant_id: uuid.UUID | None,
) -> int:
    """Resolve the answerable window for a tenant, in seconds.

    Reads the tenant's override, coercing and clamping it (minimum 30s); an
    unset, malformed or unreadable value falls back to the platform default
    (900s). ``tenant_id=None`` (single-tenant / pre-adoption rows) resolves to
    the platform default.
    """
    default = platform_resume_ttl_seconds()
    if tenant_id is None:
        return default

    raw = await get_value(db, tenant_id, RESUME_TTL_SETTING_KEY)
    seconds = _coerce_seconds(raw)
    if seconds is None:
        return default
    if seconds < MIN_RESUME_TTL_SECONDS:
        logger.info(
            "Tenant %s resume TTL %s is below the %ss minimum — clamping",
            tenant_id,
            seconds,
            MIN_RESUME_TTL_SECONDS,
        )
        return MIN_RESUME_TTL_SECONDS
    return seconds


async def set_resume_ttl_seconds(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    seconds: int,
) -> int:
    """Persist a tenant's answerable-window override (clamped, returns stored)."""
    value = max(MIN_RESUME_TTL_SECONDS, int(seconds))
    await set_value(db, tenant_id, RESUME_TTL_SETTING_KEY, value)
    logger.info(
        "Tenant %s resume TTL set to %ss (stored %ss)",
        tenant_id,
        seconds,
        value,
    )
    return value


async def resolve_resume_expiry(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None,
    now: datetime | None = None,
) -> datetime:
    """The paused turn's ``expires_at``: ``now + tenant answerable window``."""
    ttl = await resolve_resume_ttl_seconds(db, tenant_id)
    return (now or datetime.now(timezone.utc)) + timedelta(seconds=ttl)


__all__ = [
    "MIN_RESUME_TTL_SECONDS",
    "RESUME_TTL_SETTING_KEY",
    "platform_resume_ttl_seconds",
    "resolve_resume_expiry",
    "resolve_resume_ttl_seconds",
    "set_resume_ttl_seconds",
]
