"""Tenant Quota Service — effective limits + the three quota checks.

Resolves the limits a tenant is governed by (active license, else the
free-tier defaults owned by :class:`TenantLicensingService`) and
evaluates:

- **users** — live count of ACTIVE memberships (never counter rows);
- **agent_types** — live count of tenant agent-type records;
- **monthly_executions** — maintained via ``TenantQuotaUsage``: one
  calendar-month bucket per tenant, get-or-created and incremented once
  per ACCEPTED execution at the Control Center enforcement point.  A new
  month starts a fresh bucket (implicit reset); usage is never refunded.

Derived counts can never drift from the records; the executions counter
keeps high-volume metering off the execution history.  Reaching one
quota never blocks the unrelated quotas.

Every refusal raises :class:`QuotaExceededError` carrying the structured
:class:`~app.schemas.tenant_quota.QuotaBlockedPayload` (single shared
contract, single HTTP mapping → 403) and records a ``quota_exhausted``
audit event.  With the tenancy switch OFF every check is inert
(allowed) — the service is a no-op in single-tenant mode.

Singleton accessor mirrors the neighbouring tenancy services.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agents import AgentType
from app.db.models.tenant_audit_event import (
    TenantAuditActorType,
    TenantAuditEventType,
)
from app.db.models.tenant_membership import (
    TenantUserMembership,
    TenantUserMembershipStatus,
)
from app.db.models.tenant_quota_usage import QuotaType, TenantQuotaUsage
from app.schemas.tenant_quota import QuotaBlockedPayload
from app.services.tenancy.licensing_service import (
    EffectiveLimits,
    TenantLicensingService,
    get_tenant_licensing_service,
)
from app.services.tenancy.platform_settings_service import (
    get_platform_settings_service,
)
from app.services.tenancy.tenant_audit_service import TenantAuditService

logger = logging.getLogger(__name__)

QuotaTypeLiteralAlias = Literal["users", "agent_types", "monthly_executions"]


class QuotaExceededError(Exception):
    """Raised by every enforcement gate when a quota is exhausted.

    Carries the structured payload consumed by the single HTTP mapping
    (app.main exception handler → 403 + ``quota_exhausted`` audit).
    """

    def __init__(self, payload: QuotaBlockedPayload) -> None:
        self.payload = payload
        super().__init__(
            f"quota_exhausted: {payload.quota_type} "
            f"({payload.used}/{payload.limit}, tier={payload.tier})"
        )


@dataclass(frozen=True)
class QuotaCheckResult:
    """Structured result of a quota check (never raises)."""

    allowed: bool
    used: int
    limit: int
    payload: QuotaBlockedPayload | None = None


def _current_period_start() -> date:
    """First day of the current UTC calendar month (the bucket key)."""
    now = datetime.now(timezone.utc)
    return now.date().replace(day=1)


class TenantQuotaService:
    """Evaluates the three quotas against a tenant's effective limits."""

    def __init__(
        self,
        licensing_service: TenantLicensingService | None = None,
        audit_service: TenantAuditService | None = None,
    ) -> None:
        self._licensing = licensing_service or get_tenant_licensing_service()
        self._audit = audit_service or TenantAuditService()

    # ── Usage summary ────────────────────────────────────────────────────────

    async def count_active_users(self, db: AsyncSession, tenant_id: uuid.UUID) -> int:
        """Live count of the tenant's ACTIVE memberships."""
        result = await db.execute(
            select(func.count())
            .select_from(TenantUserMembership)
            .where(
                TenantUserMembership.tenant_id == tenant_id,
                TenantUserMembership.status == TenantUserMembershipStatus.active,
            )
        )
        return int(result.scalar() or 0)

    async def count_agent_types(self, db: AsyncSession, tenant_id: uuid.UUID) -> int:
        """Live count of the tenant's agent-type records."""
        result = await db.execute(
            select(func.count())
            .select_from(AgentType)
            .where(AgentType.tenant_id == tenant_id)
        )
        return int(result.scalar() or 0)

    async def get_monthly_executions(
        self, db: AsyncSession, tenant_id: uuid.UUID
    ) -> int:
        """Executions consumed in the current calendar-month bucket."""
        bucket = await self._get_bucket(db, tenant_id)
        return bucket.used_count if bucket is not None else 0

    async def get_usage(
        self, db: AsyncSession, tenant_id: uuid.UUID
    ) -> dict[str, object]:
        """Tier + effective limits + current usage (for read APIs)."""
        limits = await self._licensing.get_effective_limits(db, tenant_id)
        return {
            "tier": limits.tier.value,
            "max_users": limits.max_users,
            "max_agent_types": limits.max_agent_types,
            "monthly_agent_executions": limits.monthly_agent_executions,
            "users": await self.count_active_users(db, tenant_id),
            "agent_types": await self.count_agent_types(db, tenant_id),
            "executions_this_month": await self.get_monthly_executions(db, tenant_id),
        }

    # ── Checks (structured result — never raise) ─────────────────────────────

    async def check_users(
        self, db: AsyncSession, tenant_id: uuid.UUID
    ) -> QuotaCheckResult:
        """Users quota: active membership count vs ``max_users``.

        Consulted at invitation creation and the member-creating
        acceptance path.  Inert (allowed) with the switch off.
        """
        if not await self._tenancy_enabled(db):
            return QuotaCheckResult(allowed=True, used=0, limit=0)
        limits = await self._licensing.get_effective_limits(db, tenant_id)
        used = await self.count_active_users(db, tenant_id)
        if used >= limits.max_users:
            return QuotaCheckResult(
                allowed=False, used=used, limit=limits.max_users,
                payload=self._payload(limits, "users", used, limits.max_users),
            )
        return QuotaCheckResult(allowed=True, used=used, limit=limits.max_users)

    async def check_agent_types(
        self, db: AsyncSession, tenant_id: uuid.UUID
    ) -> QuotaCheckResult:
        """Agent-types quota: tenant agent-type count vs ``max_agent_types``."""
        if not await self._tenancy_enabled(db):
            return QuotaCheckResult(allowed=True, used=0, limit=0)
        limits = await self._licensing.get_effective_limits(db, tenant_id)
        used = await self.count_agent_types(db, tenant_id)
        if used >= limits.max_agent_types:
            return QuotaCheckResult(
                allowed=False, used=used, limit=limits.max_agent_types,
                payload=self._payload(limits, "agent_types", used, limits.max_agent_types),
            )
        return QuotaCheckResult(allowed=True, used=used, limit=limits.max_agent_types)

    async def check_executions(
        self, db: AsyncSession, tenant_id: uuid.UUID
    ) -> QuotaCheckResult:
        """Monthly executions quota: current bucket vs the license limit."""
        if not await self._tenancy_enabled(db):
            return QuotaCheckResult(allowed=True, used=0, limit=0)
        limits = await self._licensing.get_effective_limits(db, tenant_id)
        used = await self.get_monthly_executions(db, tenant_id)
        if used >= limits.monthly_agent_executions:
            return QuotaCheckResult(
                allowed=False, used=used, limit=limits.monthly_agent_executions,
                payload=self._payload(
                    limits, "monthly_executions", used,
                    limits.monthly_agent_executions,
                ),
            )
        return QuotaCheckResult(
            allowed=True, used=used, limit=limits.monthly_agent_executions
        )

    # ── Enforcement gates (raise QuotaExceededError on refusal) ──────────────

    async def ensure_users(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        result = await self.check_users(db, tenant_id)
        if not result.allowed:
            await self._refuse(db, tenant_id, result)

    async def ensure_agent_types(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        result = await self.check_agent_types(db, tenant_id)
        if not result.allowed:
            await self._refuse(db, tenant_id, result)

    async def ensure_executions(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        result = await self.check_executions(db, tenant_id)
        if not result.allowed:
            await self._refuse(db, tenant_id, result)

    # ── Counter maintenance ──────────────────────────────────────────────────

    async def increment_executions(
        self, db: AsyncSession, tenant_id: uuid.UUID
    ) -> int:
        """Get-or-create the current month bucket and count one execution.

        Called EXACTLY ONCE per accepted execution, before any dispatch.
        A new month implicitly resets (fresh bucket); completed/failed
        executions never refund usage.
        """
        bucket = await self._get_bucket(db, tenant_id)
        if bucket is None:
            bucket = TenantQuotaUsage(
                tenant_id=tenant_id,
                quota_type=QuotaType.monthly_executions,
                period_start=_current_period_start(),
                used_count=0,
            )
            db.add(bucket)
        bucket.used_count += 1
        await db.flush()
        return bucket.used_count

    # ── Audit helper (for non-HTTP callers, e.g. the scheduler) ──────────────

    async def record_quota_exhausted(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        payload: QuotaBlockedPayload,
        *,
        actor_type: TenantAuditActorType | None = None,
        target_resource: str | None = None,
    ) -> None:
        """Persist a ``quota_exhausted`` audit event (caller commits)."""
        await self._audit.record_safe(
            db,
            TenantAuditEventType.quota_exhausted,
            tenant_id=tenant_id,
            actor_type=actor_type or TenantAuditActorType.system,
            target_resource=target_resource,
            detail=payload.model_dump(),
            is_security_relevant=False,
        )

    # ── Internals ────────────────────────────────────────────────────────────

    async def _tenancy_enabled(self, db: AsyncSession) -> bool:
        return await get_platform_settings_service().is_multi_tenancy_enabled(db)

    async def _get_bucket(
        self, db: AsyncSession, tenant_id: uuid.UUID
    ) -> TenantQuotaUsage | None:
        result = await db.execute(
            select(TenantQuotaUsage).where(
                TenantQuotaUsage.tenant_id == tenant_id,
                TenantQuotaUsage.quota_type == QuotaType.monthly_executions,
                TenantQuotaUsage.period_start == _current_period_start(),
            )
        )
        return result.scalar_one_or_none()

    async def _refuse(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        result: QuotaCheckResult,
    ) -> None:
        """Log the refusal and raise the shared contract error.

        The audit write itself happens in the single HTTP mapping (fresh
        session — the request session rolls back when the gate raises);
        the scheduler calls :meth:`record_quota_exhausted` explicitly.
        """
        assert result.payload is not None
        logger.warning(
            "Quota exhausted: tenant=%s type=%s used=%d limit=%d",
            tenant_id, result.payload.quota_type, result.used, result.limit,
        )
        raise QuotaExceededError(result.payload)

    @staticmethod
    def _payload(
        limits: EffectiveLimits,
        quota_type: QuotaTypeLiteralAlias,
        used: int,
        limit: int,
    ) -> QuotaBlockedPayload:
        return QuotaBlockedPayload(
            quota_type=quota_type,
            tier=limits.tier.value,
            limit=limit,
            used=used,
        )


# ── Singleton ────────────────────────────────────────────────────────────────

_service: TenantQuotaService | None = None


def get_tenant_quota_service() -> TenantQuotaService:
    """Return the module-level TenantQuotaService singleton."""
    global _service
    if _service is None:
        _service = TenantQuotaService()
    return _service
