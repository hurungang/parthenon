/** Token expiry alerting — TypeScript types mirroring the backend Pydantic schemas. */

/** Computed token health state (mirrors backend TokenHealthState enum). */
export enum TokenHealthState {
  Healthy = 'healthy',
  Expiring = 'expiring',
  Expired = 'expired',
  Unknown = 'unknown',
}

/** Which kind of token-bearing entity the item describes. */
export type TokenHealthRemediationTarget = 'agent_identity' | 'mcp_session'

export interface TokenHealthItem {
  id: string
  name: string
  health_state: TokenHealthState
  expires_at: string | null
  refresh_expires_at: string | null
  last_refresh_outcome: string | null
  last_refresh_at: string | null
  remediation_target: TokenHealthRemediationTarget
  remediation_path: string
}

export interface TokenHealthCategorySummary {
  expired_count: number
  expiring_count: number
  healthy_count: number
  unknown_count: number
  items: TokenHealthItem[]
}

export interface TokenHealthPermissionFlags {
  /** True when the caller lacks permission for that category (placeholder shown). */
  identities: boolean
  mcp_sessions: boolean
}

export interface TokenHealthSummary {
  identities: TokenHealthCategorySummary
  mcp_sessions: TokenHealthCategorySummary
  permission_flags: TokenHealthPermissionFlags
}
