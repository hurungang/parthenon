"""Pydantic v2 schemas for Dashboard operational metrics."""
from pydantic import BaseModel


class AgentExecutionsBreakdown(BaseModel):
    """Completed / failed breakdown for agent executions."""
    completed: int = 0
    failed: int = 0


class SnapshotCounts(BaseModel):
    """Non-time-filtered snapshot count fields."""
    agent_types: int = 0
    agent_types_active: int = 0
    agent_types_running: int = 0
    pending_interventions: int = 0
    model_configs: int = 0
    model_counts: int = 0
    active_schedules: int = 0
    agent_identities: int = 0
    agent_roles: int = 0
    mcp_servers: int = 0
    pending_access_requests: int = 0


class TimeSensitiveCounts(BaseModel):
    """Time-filtered count fields with date range applied."""
    guardrail_breaches: int = 0
    agent_executions: AgentExecutionsBreakdown = AgentExecutionsBreakdown()
    posture_breaches: int = 0
    notification_delivered: int = 0
    notification_failed: int = 0


class CardPermissionFlags(BaseModel):
    """Per-card boolean flags where True indicates permission is **denied**."""
    agent_types: bool = False
    interventions: bool = False
    model_configs: bool = False
    schedules: bool = False
    identities: bool = False
    roles: bool = False
    mcp_servers: bool = False
    permission_requests: bool = False
    guardrail_breaches: bool = False
    executions: bool = False
    posture_breaches: bool = False
    notifications: bool = False


class DashboardSummary(BaseModel):
    """Top-level aggregation response for the dashboard."""
    snapshot_counts: SnapshotCounts = SnapshotCounts()
    time_sensitive: TimeSensitiveCounts = TimeSensitiveCounts()
    permission_flags: CardPermissionFlags = CardPermissionFlags()
