"""Tenant Audit Service — single writer for TenantAuditEvent records.

Every tenancy lifecycle action (create/suspend/resume/delete), every
cross-tenant denial, and every security-relevant boundary violation is
written through this service so tenant attribution and security flagging
stay consistent across the platform.

Writes are "flush, not commit": events join the caller's transaction
wherever possible, and :meth:`TenantAuditService.record_safe` provides a
fire-and-forget-safe variant that never raises (per tech-spec: audit
writes must never break the request path, but security-relevant denials
are always attempted).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenant_audit_event import (
    TenantAuditActorType,
    TenantAuditEvent,
    TenantAuditEventType,
)

logger = logging.getLogger(__name__)


class TenantAuditService:
    """Writes tenant lifecycle and security-relevant audit events."""

    async def record(
        self,
        db: AsyncSession,
        event_type: TenantAuditEventType,
        *,
        tenant_id: uuid.UUID | None = None,
        actor_type: TenantAuditActorType = TenantAuditActorType.system,
        actor_id: uuid.UUID | None = None,
        actor_ip: str | None = None,
        target_resource: str | None = None,
        detail: dict[str, Any] | None = None,
        is_security_relevant: bool = False,
    ) -> TenantAuditEvent:
        """Create and flush (not commit) a TenantAuditEvent.

        The caller owns the surrounding transaction; flushing keeps the
        event atomic with the action it audits.
        """
        event = TenantAuditEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_ip=actor_ip,
            target_resource=target_resource,
            detail=detail,
            is_security_relevant=is_security_relevant,
        )
        db.add(event)
        await db.flush()
        return event

    async def record_safe(
        self,
        db: AsyncSession,
        event_type: TenantAuditEventType,
        *,
        tenant_id: uuid.UUID | None = None,
        actor_type: TenantAuditActorType = TenantAuditActorType.system,
        actor_id: uuid.UUID | None = None,
        actor_ip: str | None = None,
        target_resource: str | None = None,
        detail: dict[str, Any] | None = None,
        is_security_relevant: bool = False,
    ) -> None:
        """Fire-and-forget-safe audit write — never raises.

        Used from rejection/rejection paths (middleware, scoping helpers)
        where a failed audit write must not mask the primary error.  If
        the flush fails the event is rolled back locally and logged.
        """
        try:
            await self.record(
                db,
                event_type,
                tenant_id=tenant_id,
                actor_type=actor_type,
                actor_id=actor_id,
                actor_ip=actor_ip,
                target_resource=target_resource,
                detail=detail,
                is_security_relevant=is_security_relevant,
            )
        except Exception:
            logger.exception(
                "Failed to write tenant audit event type=%s tenant_id=%s "
                "target=%s — rolling back the audit write only",
                event_type,
                tenant_id,
                target_resource,
            )
            await db.rollback()
