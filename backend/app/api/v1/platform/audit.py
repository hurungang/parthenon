"""Platform security-audit read API — cross-tenant TenantAuditEvents.

Platform admin view of tenant lifecycle and security-relevant events
(including ``cross_tenant_access_denied`` / ``tenant_boundary_violation``)
across ALL tenants, with tenant attribution.  Tenant admins cannot see
platform-level or other tenants' audit events — this surface is
``/platform/*`` (base domain only).  Guarded by ``platform::audit``.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.resource_types import RT_PLATFORM_AUDIT
from app.db.models.tenant import Tenant
from app.db.models.tenant_audit_event import (
    TenantAuditActorType,
    TenantAuditEventType,
    TenantAuditEvent,
)
from app.db.session import DbSession

logger = logging.getLogger(__name__)

PlatformAuditRouter = APIRouter(prefix="/platform/audit-events", tags=["Platform: Audit"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class TenantAuditEventRead(BaseModel):
    id: str
    tenant_id: Optional[str] = None
    tenant_slug: Optional[str] = None
    event_type: str
    actor_type: str
    actor_id: Optional[str] = None
    actor_ip: Optional[str] = None
    target_resource: Optional[str] = None
    detail: Optional[dict] = None
    is_security_relevant: bool
    created_at: Optional[datetime] = None


class TenantAuditEventListResponse(BaseModel):
    items: list[TenantAuditEventRead]
    total: int


# ── Endpoint ─────────────────────────────────────────────────────────────────


@PlatformAuditRouter.get("", response_model=TenantAuditEventListResponse)
async def list_audit_events(
    db: DbSession,
    tenant_id: Optional[uuid.UUID] = Query(default=None),
    event_type: Optional[TenantAuditEventType] = Query(default=None),
    security_only: bool = Query(default=False),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_permission(RT_PLATFORM_AUDIT, "read")),
) -> TenantAuditEventListResponse:
    """Filterable cross-tenant audit events with tenant attribution."""
    conditions = []
    if tenant_id is not None:
        conditions.append(TenantAuditEvent.tenant_id == tenant_id)
    if event_type is not None:
        conditions.append(TenantAuditEvent.event_type == event_type)
    if security_only:
        conditions.append(TenantAuditEvent.is_security_relevant.is_(True))
    if date_from is not None:
        conditions.append(TenantAuditEvent.created_at >= date_from)
    if date_to is not None:
        conditions.append(TenantAuditEvent.created_at <= date_to)

    base = select(TenantAuditEvent, Tenant.slug).outerjoin(
        Tenant, Tenant.id == TenantAuditEvent.tenant_id
    )
    count_query = select(func.count()).select_from(TenantAuditEvent)
    if conditions:
        base = base.where(*conditions)
        count_query = count_query.where(*conditions)

    total = int((await db.execute(count_query)).scalar() or 0)
    rows = (
        await db.execute(
            base.order_by(TenantAuditEvent.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return TenantAuditEventListResponse(
        items=[
            TenantAuditEventRead(
                id=str(event.id),
                tenant_id=str(event.tenant_id) if event.tenant_id else None,
                tenant_slug=slug,
                event_type=event.event_type.value,
                actor_type=event.actor_type.value,
                actor_id=str(event.actor_id) if event.actor_id else None,
                actor_ip=event.actor_ip,
                target_resource=event.target_resource,
                detail=event.detail,
                is_security_relevant=bool(event.is_security_relevant),
                created_at=event.created_at,
            )
            for event, slug in rows
        ],
        total=total,
    )
