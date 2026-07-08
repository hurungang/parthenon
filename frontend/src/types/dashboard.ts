/** Dashboard operational metrics — TypeScript interfaces matching Pydantic v2 schemas. */

export interface AgentExecutionsBreakdown {
  completed: number
  failed: number
}

export interface SnapshotCounts {
  agent_types: number
  agent_types_active: number
  agent_types_running: number
  pending_interventions: number
  model_configs: number
  model_counts: number
  active_schedules: number
  agent_identities: number
  agent_roles: number
  mcp_servers: number
  pending_access_requests: number
}

export interface TimeSensitiveCounts {
  guardrail_breaches: number
  agent_executions: AgentExecutionsBreakdown
  posture_breaches: number
  notification_delivered: number
  notification_failed: number
}

export interface CardPermissionFlags {
  agent_types: boolean
  interventions: boolean
  model_configs: boolean
  schedules: boolean
  identities: boolean
  roles: boolean
  mcp_servers: boolean
  permission_requests: boolean
  guardrail_breaches: boolean
  executions: boolean
  posture_breaches: boolean
  notifications: boolean
}

export interface DashboardSummary {
  snapshot_counts: SnapshotCounts
  time_sensitive: TimeSensitiveCounts
  permission_flags: CardPermissionFlags
}
