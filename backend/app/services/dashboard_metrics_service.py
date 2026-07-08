"""DashboardMetricsService — per-domain permission-checked count aggregation."""
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.resource_types import (
    RT_AGENT,
    RT_AGENT_HUMAN_INTERVENTION,
    RT_AGENT_IDENTITIES,
    RT_AGENT_MODEL_CONFIGS,
    RT_AGENT_ROLES,
    RT_AGENT_SCHEDULES,
    RT_AGENT_TRAILS,
    RT_INTEGRATION_MCP_HUB,
    RT_INTEGRATION_NOTIFICATIONS,
    RT_SYSTEM_PERMISSIONS,
)
from app.db.models.access_request import AccessRequest, AccessRequestStatus
from app.db.models.agents import AgentIdentity, AgentJob, AgentJobStatus, AgentRole, AgentType, ModelConfig
from app.db.models.guardrail_threshold_event import GuardrailThresholdEvent
from app.db.models.intervene import InterveneRequest, InterveneRequestStatus
from app.db.models.mcp_hub import McpServer
from app.db.models.model_availability import ModelAvailability
from app.db.models.model_usage_posture import ModelUsagePosture, ModelUsagePostureState
from app.db.models.notifications import DeliveryStatus, NotificationLog
from app.db.models.platform_user import PlatformUser
from app.db.models.scheduling import JobStatus, ScheduledJob
from app.schemas.dashboard import (
    AgentExecutionsBreakdown,
    CardPermissionFlags,
    DashboardSummary,
    SnapshotCounts,
    TimeSensitiveCounts,
)
from app.services.permissions.permission_engine import PermissionEngine

logger = logging.getLogger(__name__)

_PERMISSION_MAP: dict[str, tuple[str, str]] = {
    "agent_types": (RT_AGENT, "read"),
    "executions": (RT_AGENT, "read"),
    "interventions": (RT_AGENT_HUMAN_INTERVENTION, "view"),
    "model_configs": (RT_AGENT_MODEL_CONFIGS, "read"),
    "posture_breaches": (RT_AGENT_MODEL_CONFIGS, "read"),
    "schedules": (RT_AGENT_SCHEDULES, "read"),
    "identities": (RT_AGENT_IDENTITIES, "read"),
    "roles": (RT_AGENT_ROLES, "read"),
    "mcp_servers": (RT_INTEGRATION_MCP_HUB, "read"),
    "guardrail_breaches": (RT_AGENT_TRAILS, "read"),
    "permission_requests": (RT_SYSTEM_PERMISSIONS, "read"),
    "notifications": (RT_INTEGRATION_NOTIFICATIONS, "read"),
}


class DashboardMetricsService:

    def __init__(self, db: AsyncSession, claims: dict[str, Any]) -> None:
        self._db = db
        self._claims = claims
        self._user_id: uuid.UUID | None = None

    async def aggregate_metrics(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> DashboardSummary:
        await self._resolve_user_id()

        permission_flags = CardPermissionFlags()
        snapshot = SnapshotCounts()
        time_sensitive = TimeSensitiveCounts()

        # ── Agent Types ──
        if await self._check_permission("agent_types"):
            snapshot.agent_types = await self._count(select(func.count()).select_from(AgentType))
            snapshot.agent_types_active = await self._count(
                select(func.count()).select_from(AgentType).where(AgentType.is_active == True)
            )
            snapshot.agent_types_running = await self._count(
                select(func.count()).select_from(AgentJob).where(AgentJob.status == AgentJobStatus.running)
            )
        else:
            permission_flags.agent_types = True

        # ── Pending Interventions ──
        if await self._check_permission("interventions"):
            snapshot.pending_interventions = await self._count(
                select(func.count()).select_from(InterveneRequest).where(InterveneRequest.status == InterveneRequestStatus.pending)
            )
        else:
            permission_flags.interventions = True

        # ── Model Configs (vendors) + Model Counts (individual models) ──
        if await self._check_permission("model_configs"):
            result = await self._db.execute(
                select(ModelConfig).where(ModelConfig.is_disabled == False)
            )
            vendors = result.scalars().all()
            snapshot.model_configs = len(vendors)
            # Count individual enabled models from two sources:
            # 1. ModelAvailability table (canonical per-model tracking)
            avail_count = await self._count(
                select(func.count()).select_from(ModelAvailability).where(ModelAvailability.is_disabled == False)
            )
            # 2. Sum of enabled_models array lengths from vendor configs
            json_count = sum(len(vendor.enabled_models or []) for vendor in vendors)
            snapshot.model_counts = avail_count if avail_count > 0 else json_count
        else:
            permission_flags.model_configs = True

        # ── Active Schedules ──
        if await self._check_permission("schedules"):
            snapshot.active_schedules = await self._count(
                select(func.count()).select_from(ScheduledJob).where(ScheduledJob.status == JobStatus.active)
            )
        else:
            permission_flags.schedules = True

        # ── Agent Identities ──
        if await self._check_permission("identities"):
            snapshot.agent_identities = await self._count(select(func.count()).select_from(AgentIdentity))
        else:
            permission_flags.identities = True

        # ── Agent Roles ──
        if await self._check_permission("roles"):
            snapshot.agent_roles = await self._count(select(func.count()).select_from(AgentRole))
        else:
            permission_flags.roles = True

        # ── MCP Servers ──
        if await self._check_permission("mcp_servers"):
            snapshot.mcp_servers = await self._count(select(func.count()).select_from(McpServer))
        else:
            permission_flags.mcp_servers = True

        # ── Pending Permission Requests ──
        if await self._check_permission("permission_requests"):
            snapshot.pending_access_requests = await self._count(
                select(func.count()).select_from(AccessRequest).where(AccessRequest.status == AccessRequestStatus.pending)
            )
        else:
            permission_flags.permission_requests = True

        # ── Guardrail Breaches ──
        if await self._check_permission("guardrail_breaches"):
            time_sensitive.guardrail_breaches = await self._count(
                select(func.count()).select_from(GuardrailThresholdEvent).where(
                    GuardrailThresholdEvent.emitted_at >= start_time,
                    GuardrailThresholdEvent.emitted_at <= end_time,
                )
            )
        else:
            permission_flags.guardrail_breaches = True

        # ── Agent Executions ──
        if await self._check_permission("executions"):
            completed_count = await self._count(
                select(func.count()).select_from(AgentJob).where(
                    AgentJob.status == AgentJobStatus.completed,
                    AgentJob.created_at >= start_time,
                    AgentJob.created_at <= end_time,
                )
            )
            failed_count = await self._count(
                select(func.count()).select_from(AgentJob).where(
                    AgentJob.status == AgentJobStatus.failed,
                    AgentJob.created_at >= start_time,
                    AgentJob.created_at <= end_time,
                )
            )
            time_sensitive.agent_executions = AgentExecutionsBreakdown(completed=completed_count, failed=failed_count)
        else:
            permission_flags.executions = True

        # ── Posture Breaches ──
        if await self._check_permission("posture_breaches"):
            time_sensitive.posture_breaches = await self._count(
                select(func.count()).select_from(ModelUsagePosture).where(
                    ModelUsagePosture.posture_state == ModelUsagePostureState.breached,
                    ModelUsagePosture.observed_at >= start_time,
                    ModelUsagePosture.observed_at <= end_time,
                )
            )
        else:
            permission_flags.posture_breaches = True

        # ── Notifications ──
        if await self._check_permission("notifications"):
            time_sensitive.notification_delivered = await self._count(
                select(func.count()).select_from(NotificationLog).where(
                    NotificationLog.status == DeliveryStatus.delivered,
                    NotificationLog.created_at >= start_time,
                    NotificationLog.created_at <= end_time,
                )
            )
            time_sensitive.notification_failed = await self._count(
                select(func.count()).select_from(NotificationLog).where(
                    NotificationLog.status == DeliveryStatus.failed,
                    NotificationLog.created_at >= start_time,
                    NotificationLog.created_at <= end_time,
                )
            )
        else:
            permission_flags.notifications = True

        return DashboardSummary(
            snapshot_counts=snapshot,
            time_sensitive=time_sensitive,
            permission_flags=permission_flags,
        )

    async def _resolve_user_id(self) -> None:
        if self._claims.get("is_super_admin"):
            return
        sub: str | None = self._claims.get("sub")
        if not sub:
            logger.warning("DashboardMetricsService: No 'sub' in claims — all permissions denied.")
            return
        result = await self._db.execute(select(PlatformUser.id).where(PlatformUser.sub == sub))
        row = result.scalar_one_or_none()
        if row is not None:
            self._user_id = row
        else:
            logger.warning("DashboardMetricsService: PlatformUser not found for sub=%s — all permissions denied.", sub)

    async def _check_permission(self, domain: str) -> bool:
        if self._claims.get("is_super_admin"):
            return True
        if self._user_id is None:
            return False
        module, action = _PERMISSION_MAP[domain]
        auth = await PermissionEngine().authorize(
            db=self._db, user_id=self._user_id, module=module, action=action,
            resource_id="*", resource_tags={},
        )
        return auth.allowed

    async def _count(self, stmt) -> int:
        result = await self._db.execute(stmt)
        count = result.scalar_one_or_none()
        return count if count is not None else 0
