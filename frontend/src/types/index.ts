/**
 * Shared TypeScript type definitions for the Parthenon platform.
 */

// ── Identity & Auth ────────────────────────────────────────────────────────────

export type RoleType = 'user' | 'agent' | 'both'
export type IdentityType = 'user' | 'agent'

export interface Permission {
  id: string
  name: string
  resource: string
  action: string
  description: string | null
  created_at: string
}

export interface Role {
  id: string
  name: string
  description: string | null
  role_type: RoleType
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface Identity {
  id: string
  subject: string
  email: string | null
  display_name: string | null
  identity_type: IdentityType
  role_id: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

// ── MCP Hub ────────────────────────────────────────────────────────────────────

export type McpServerStatus = 'active' | 'inactive' | 'error'
export type McpSessionAuthType = 'api_key' | 'bearer_token' | 'basic_auth' | 'oauth2' | 'none'

export interface McpServer {
  id: string
  name: string
  slug: string
  description: string | null
  base_url: string
  status: McpServerStatus
  last_synced_at: string | null
  created_at: string
  updated_at: string
}

export interface McpSession {
  id: string
  server_id: string
  name: string
  description: string | null
  auth_type: McpSessionAuthType
  identity_subject: string | null
  is_active: boolean
  identity_binding: Record<string, unknown> | null
  credential_config: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface McpTool {
  id: string
  server_id: string
  name: string
  original_name: string
  description: string | null
  input_schema: Record<string, unknown> | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ToolPermission {
  id: string
  tool_id: string
  role_id: string
  created_at: string
}

export interface SyncResult {
  server_id: string
  tools_added: number
  tools_updated: number
  tools_deactivated: number
  total_active: number
}

// ── Skills & SOPs ──────────────────────────────────────────────────────────────

export type SopStepType = 'skill_invocation' | 'agent_delegation'

export interface Skill {
  id: string
  name: string
  description: string | null
  instructions: string | null
  is_active: boolean
  tool_ids: string[]
  created_at: string
  updated_at: string
}

export interface SopStep {
  id: string
  sop_id: string
  order: number
  step_type: SopStepType
  skill_id: string | null
  target_agent_type_id: string | null
  step_config: Record<string, unknown> | null
  name: string | null
  description: string | null
  created_at: string
}

export interface Sop {
  id: string
  name: string
  description: string | null
  instructions: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface SopDetail extends Sop {
  steps: SopStep[]
}

// ── Agents ─────────────────────────────────────────────────────────────────────

export type AgentInstanceStatus = 'created' | 'active' | 'closed' | 'error'
export type AgentIdentityType = 'realm_user'
export type AgentIdentityStatus = 'active' | 'suspended' | 'deprovisioned'
export type AgentJobStatus = 'queued' | 'running' | 'completed' | 'failed'
export type AgentInputType = 'none' | 'typed' | 'conversation'
export type AgentOutputType = 'auto' | 'typed' | 'markdown'

export interface AgentRole {
  id: string
  name: string
  description: string | null
  sop_ids: string[]
  skill_ids: string[]
  created_at: string
  updated_at: string
}

export interface AgentIdentity {
  id: string
  name: string
  identity_type: AgentIdentityType
  realm_name: string | null
  realm_username: string | null
  status: AgentIdentityStatus
  token_expires_at: string | null
  created_at: string
  updated_at: string
}

export interface AgentJob {
  id: string
  agent_type_id: string
  triggered_by_user_id: string | null
  input_data: Record<string, unknown> | null
  status: AgentJobStatus
  started_at: string | null
  completed_at: string | null
  output_data: Record<string, unknown> | null
  error_message: string | null
  created_at: string
}

export interface AgentType {
  id: string
  name: string
  description: string | null
  identity_id: string | null
  role_id: string | null
  llm_provider: string
  llm_model: string
  system_instruction: string | null
  input_type: AgentInputType
  input_schema: Record<string, unknown> | null
  output_type: AgentOutputType
  output_schema: Record<string, unknown> | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface AgentInstance {
  id: string
  agent_type_id: string
  status: AgentInstanceStatus
  session_handle: string
  initiator_subject: string | null
  created_at: string
  closed_at: string | null
}

// ── Scheduling ─────────────────────────────────────────────────────────────────

export type JobStatus = 'active' | 'paused' | 'deleted'
export type JobTargetType = 'agent' | 'sop'
export type ExecutionStatus = 'success' | 'failure' | 'running'

export interface ScheduledJob {
  id: string
  name: string
  description: string | null
  cron_expression: string
  target_type: JobTargetType
  target_id: string
  payload: Record<string, unknown> | null
  status: JobStatus
  scheduler_job_id: string | null
  created_at: string
  updated_at: string
}

export interface JobExecution {
  id: string
  job_id: string
  status: ExecutionStatus
  error: string | null
  result: Record<string, unknown> | null
  started_at: string
  finished_at: string | null
}

// ── Conversations ──────────────────────────────────────────────────────────────

export type ConversationStatus = 'active' | 'closed' | 'error'
export type TurnRole = 'user' | 'agent' | 'tool' | 'system'

export interface ToolCallRecord {
  id: string
  turn_id: string
  tool_name: string
  tool_input: Record<string, unknown> | null
  tool_output: Record<string, unknown> | null
  error: string | null
  duration_ms: number | null
  created_at: string
}

export interface ConversationTurn {
  id: string
  session_id: string
  role: TurnRole
  content: string
  token_count: number | null
  created_at: string
  tool_calls: ToolCallRecord[]
}

export interface ConversationSession {
  id: string
  agent_instance_id: string | null
  agent_type_id: string | null
  initiator_subject: string | null
  channel: string
  status: ConversationStatus
  turn_count: number
  created_at: string
  closed_at: string | null
}

export interface ConversationSessionDetail extends ConversationSession {
  turns: ConversationTurn[]
}

// ── Results ────────────────────────────────────────────────────────────────────

export interface ResultRecord {
  id: string
  agent_type_id: string | null
  agent_instance_id: string | null
  conversation_session_id: string | null
  title: string | null
  content_type: string
  payload: Record<string, unknown>
  tags: string[] | null
  created_at: string
}

// ── Notifications ──────────────────────────────────────────────────────────────

export type ChannelType = 'email' | 'slack' | 'teams' | 'webhook'
export type DeliveryStatus = 'pending' | 'delivered' | 'failed'

export interface NotificationChannel {
  id: string
  name: string
  channel_type: ChannelType
  description: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface NotificationEvent {
  id: string
  channel_id: string
  subject: string | null
  body: string
  recipient: string | null
  status: DeliveryStatus
  error: string | null
  created_at: string
  delivered_at: string | null
}

// ── Gateway ────────────────────────────────────────────────────────────────────

export interface GatewayRoute {
  id: string
  agent_type_id: string
  http_base_path: string
  created_at: string
}

export interface GatewayInitResponse {
  session_handle: string
  instance_id: string
  agent_type_id: string
}

export interface GatewayRequestResponse {
  response: string
  instance_id: string
  session_handle: string
  has_question: boolean
}

// ── Auth State ─────────────────────────────────────────────────────────────────

export interface AuthClaims {
  sub: string
  email?: string
  name?: string
  preferred_username?: string
  roles?: string[]
  exp: number
  iat: number
}

export interface AuthState {
  isAuthenticated: boolean
  isLoading: boolean
  token: string | null
  claims: AuthClaims | null
}
