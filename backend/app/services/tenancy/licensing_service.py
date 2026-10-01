"""Tenant Licensing Service — license assign/change/remove + effective limits.

Owns the ``TenantLicense`` lifecycle:

- **Assign/change** supersedes the previous active license (``is_active``
  set to false and ``unassigned_at`` stamped — history retained, the
  latest active row wins, enforced by the ``uq_tenant_license_single_active``
  partial unique index).
- **Remove** deactivates the active license; the tenant immediately falls
  back to the built-in free-tier default limits (constants owned HERE).
- **Effective limits** resolve to the active license when present, else
  the free-tier defaults.

Every change writes ``license_assigned`` / ``license_changed`` /
``license_removed`` audit events through :class:`TenantAuditService`.
Unknown tiers and non-positive limits are rejected before any write.

Singleton accessor mirrors the neighbouring tenancy services.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenant_audit_event import TenantAuditActorType, TenantAuditEventType
from app.db.models.tenant_license import LicenseTier, TenantLicense
from app.services.tenancy.tenant_audit_service import TenantAuditService

logger = logging.getLogger(__name__)


# ── Free-tier defaults (built-in fallback when no license is active) ─────────

FREE_TIER_MAX_USERS = 10
FREE_TIER_MAX_AGENT_TYPES = 5
FREE_TIER_MONTHLY_AGENT_EXECUTIONS = 100


@dataclass(frozen=True)
class EffectiveLimits:
    """The limits a tenant is governed by right now."""

    tier: LicenseTier
    max_users: int
    max_agent_types: int
    monthly_agent_executions: int

    def as_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier.value,
            "max_users": self.max_users,
            "max_agent_types": self.max_agent_types,
            "monthly_agent_executions": self.monthly_agent_executions,
        }


FREE_TIER_LIMITS = EffectiveLimits(
    tier=LicenseTier.free,
    max_users=FREE_TIER_MAX_USERS,
    max_agent_types=FREE_TIER_MAX_AGENT_TYPES,
    monthly_agent_executions=FREE_TIER_MONTHLY_AGENT_EXECUTIONS,
)


class TenantLicenseError(Exception):
    """Raised when license input fails validation or no license exists."""


class TenantLicensingService:
    """License assignment with supersede semantics and limits resolution."""

    def __init__(self, audit_service: TenantAuditService | None = None) -> None:
        self._audit = audit_service or TenantAuditService()

    # ── Queries ──────────────────────────────────────────────────────────────

    async def get_active_license(
        self, db: AsyncSession, tenant_id: uuid.UUID
    ) -> TenantLicense | None:
        """The tenant's current active license (None → free-tier fallback)."""
        result = await db.execute(
            select(TenantLicense)
            .where(
                TenantLicense.tenant_id == tenant_id,
                TenantLicense.is_active.is_(True),
            )
            .order_by(TenantLicense.assigned_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_effective_limits(
        self, db: AsyncSession, tenant_id: uuid.UUID
    ) -> EffectiveLimits:
        """Active-license limits, or the built-in free-tier defaults."""
        license_row = await self.get_active_license(db, tenant_id)
        if license_row is None:
            return FREE_TIER_LIMITS
        return EffectiveLimits(
            tier=license_row.tier,
            max_users=license_row.max_users,
            max_agent_types=license_row.max_agent_types,
            monthly_agent_executions=license_row.monthly_agent_executions,
        )

    # ── Mutations ────────────────────────────────────────────────────────────

    async def assign_license(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        tier: LicenseTier,
        max_users: int,
        max_agent_types: int,
        monthly_agent_executions: int,
        actor_id: uuid.UUID | None = None,
        actor_type: TenantAuditActorType = TenantAuditActorType.platform_admin,
    ) -> TenantLicense:
        """Assign a license (or change the existing one) — supersedes history.

        The previous active license is deactivated (``is_active = false``,
        ``unassigned_at`` stamped) so at most one active license remains.
        Writes ``license_assigned`` (first assignment) or
        ``license_changed`` (re-assignment) audit events.
        """
        self._validate(tier=tier, max_users=max_users,
                       max_agent_types=max_agent_types,
                       monthly_agent_executions=monthly_agent_executions)

        previous = await self.get_active_license(db, tenant_id)
        if previous is not None:
            previous.is_active = False
            from datetime import datetime, timezone

            previous.unassigned_at = datetime.now(timezone.utc)

        license_row = TenantLicense(
            tenant_id=tenant_id,
            tier=tier,
            max_users=max_users,
            max_agent_types=max_agent_types,
            monthly_agent_executions=monthly_agent_executions,
            is_active=True,
        )
        db.add(license_row)
        await db.flush()

        await self._audit.record_safe(
            db,
            (
                TenantAuditEventType.license_changed
                if previous is not None
                else TenantAuditEventType.license_assigned
            ),
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            target_resource=f"tenant_license:{license_row.id}",
            detail={
                "tier": tier.value,
                "max_users": max_users,
                "max_agent_types": max_agent_types,
                "monthly_agent_executions": monthly_agent_executions,
                "superseded_license_id": str(previous.id) if previous else None,
            },
        )
        logger.info(
            "License %s: tenant=%s tier=%s",
            "changed" if previous is not None else "assigned", tenant_id, tier.value,
        )
        return license_row

    async def remove_license(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
        actor_type: TenantAuditActorType = TenantAuditActorType.platform_admin,
    ) -> None:
        """Remove the active license — immediate free-tier fallback."""
        active = await self.get_active_license(db, tenant_id)
        if active is None:
            raise TenantLicenseError("Tenant has no active license to remove.")

        from datetime import datetime, timezone

        active.is_active = False
        active.unassigned_at = datetime.now(timezone.utc)
        await db.flush()

        await self._audit.record_safe(
            db,
            TenantAuditEventType.license_removed,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            target_resource=f"tenant_license:{active.id}",
            detail={
                "removed_tier": active.tier.value,
                "fallback": "free",
            },
        )
        logger.info("License removed: tenant=%s tier=%s → free tier", tenant_id, active.tier.value)

    # ── Validation ───────────────────────────────────────────────────────────

    @staticmethod
    def _validate(
        *,
        tier: LicenseTier,
        max_users: int,
        max_agent_types: int,
        monthly_agent_executions: int,
    ) -> None:
        if not isinstance(tier, LicenseTier):
            raise TenantLicenseError(
                f"Unknown license tier: {tier!r} (expected free/team/enterprise)"
            )
        for name, value in (
            ("max_users", max_users),
            ("max_agent_types", max_agent_types),
            ("monthly_agent_executions", monthly_agent_executions),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise TenantLicenseError(
                    f"{name} must be a positive integer (got {value!r})"
                )


_service: TenantLicensingService | None = None


def get_tenant_licensing_service() -> TenantLicensingService:
    """Return the module-level TenantLicensingService singleton."""
    global _service
    if _service is None:
        _service = TenantLicensingService()
    return _service
