/**
 * Types for third-party agent-integration clients.
 *
 * A client is an access grant bound to one agent type (input-interface only),
 * distinct from an API key (identity credential).
 */

export type AgentClientKeyType = 'secret' | 'publishable'
export type AgentClientStatus = 'active' | 'inactive' | 'revoked'
export type AgentClientRateLimitWindow = 'per_minute' | 'per_hour' | 'per_day'

export interface AgentClient {
  id: string
  name: string
  slug: string
  agent_type_id: string
  agent_type_name: string | null
  key_type: AgentClientKeyType
  key_prefix: string
  status: AgentClientStatus
  white_label_theme: Record<string, unknown> | null
  allowed_origins: string[] | null
  rate_limit: number | null
  rate_limit_window: AgentClientRateLimitWindow | null
  created_at: string
  last_used_at: string | null
  expires_at: string | null
}

export interface AgentClientCreateRequest {
  name: string
  agent_type_id: string
  key_type: AgentClientKeyType
  slug?: string
  white_label_theme?: Record<string, unknown>
  allowed_origins?: string[]
  rate_limit?: number
  rate_limit_window?: AgentClientRateLimitWindow
}

export interface AgentClientCredentialResponse {
  id: string
  name: string
  key_type: AgentClientKeyType
  key_prefix: string
  client_key: string
  agent_type_id: string
  agent_type_name: string
  created_at: string
}
