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
export type McpSessionAuthType = 'api_key' | 'bearer_token' | 'basic_auth' | 'oauth2' | 'none' | 'passthrough'

export interface McpServer {
  id: string
  name: string
  slug: string
  description: string | null
  base_url: string
  status: McpServerStatus
  last_synced_at: string | null
  session_count: number
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
  is_default: boolean
  identity_binding: Record<string, unknown> | null
  credential_config: Record<string, unknown> | null
  oauth_expires_at: string | null
  oauth_refresh_expires_at: string | null
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
  warnings: string[]
}

// ── Skills & SOPs ──────────────────────────────────────────────────────────────

export type SopStepType = 'skill_invocation' | 'agent_delegation'

export interface Skill {
  id: string
  name: string
  description: string | null
  instructions?: string | null
  instructions_with_tools?: string | null
  is_active: boolean
  is_system: boolean
  tool_ids: string[]
  created_at: string
  updated_at: string
}

export interface SkillWorkflowToolInput {
  id?: string | null
  name: string
  description?: string | null
  input_schema?: Record<string, unknown> | null
}

export interface SkillWorkflowGenerateRequest {
  description: string
  selected_tools: SkillWorkflowToolInput[]
}

export interface SkillWorkflowGenerateResponse {
  workflow: string
  model_id: string
}

export interface SkillWorkflowPreviewRequest {
  workflow: string
  description?: string | null
  selected_tools: SkillWorkflowToolInput[]
}

export interface SkillWorkflowPreviewResponse {
  instruction_file: string
  model_id: string
  selected_tools: SkillWorkflowToolInput[]
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
  required_skill_ids?: string[]
}

export interface SopDetail extends Sop {
  steps: SopStep[]
}

export interface SopWorkflowStepInput {
  order: number
  step_type: SopStepType
  skill_id?: string | null
  target_agent_type_id?: string | null
  name?: string | null
  description?: string | null
}

export interface SopWorkflowGenerateRequest {
  description: string
  steps: SopWorkflowStepInput[]
}

export interface SopWorkflowGenerateResponse {
  workflow: string
  model_id: string
}

export interface SopWorkflowPreviewRequest {
  workflow: string
  description?: string | null
  steps: SopWorkflowStepInput[]
}

export interface SopWorkflowPreviewResponse {
  instruction_file: string
  model_id: string
  steps: SopWorkflowStepInput[]
}

// ── Agents ─────────────────────────────────────────────────────────────────────

export type AgentInstanceStatus = 'created' | 'active' | 'closed' | 'error'
export type AgentIdentityType = 'realm_user'
export type AgentIdentityStatus = 'active' | 'suspended' | 'deprovisioned'
export type AgentJobStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'terminated'
  | 'waiting_for_human'
export type AgentInputType = 'none' | 'typed' | 'conversation'
export type AgentOutputType = 'auto' | 'typed' | 'markdown'

export interface AgentRole {
  id: string
  name: string
  description: string | null
  sop_ids: string[]
  skill_ids: string[]
  allowed_identity_types: string[]
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
  has_refresh_token: boolean
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
  conversation_history: Array<{ role: string; content: string }> | null
  stop_category?: string | null
  stop_reason?: string | null
  stop_details?: Record<string, unknown> | null
  created_at: string
  agent_type_name?: string
  triggered_by_user_name?: string
  output_id?: string | null // FK to AgentOutput for typed outputs
  output_type?: AgentOutputType | null // Resolved from AgentType
}

export interface RuntimeTopologyNode {
  session_id: string
  agent_type_id: string
  agent_type_name: string | null
  // Phase 3.13/3.16: status is now a free-form string.  For
  // kind="agent" it carries the AgentJobStatus (queued/running/
  // completed/failed/terminated).  For kind="conversation" it
  // carries the runtime ConversationStatus (active/sleep/closed/
  // archived/error).  For kind="instance" it carries the
  // AgentInstanceStatus (created/active/closed/error).
  status: string
  depth_from_root: number
  parent_session_id: string | null
  started_at: string | null
  created_at: string
  termination_category: string | null
  // Phase 3.13/3.16: distinguishes agent runs ("agent"),
  // conversation sessions ("conversation"), and agent instances
  // ("instance").  Defaults to "agent" for backwards
  // compatibility with older payloads.
  kind?: 'agent' | 'conversation' | 'instance'
  // Phase 3.13: optional human-friendly title for conversation
  // nodes (auto-generated conversation name).
  title?: string | null
}

export interface RuntimeTopologyEdge {
  parent_session_id: string
  child_session_id: string
  depth_from_root: number
}

export interface RuntimeTopologyProjection {
  nodes: RuntimeTopologyNode[]
  edges: RuntimeTopologyEdge[]
  root_session_ids: string[]
}

export type TerminationScope = 'node_only' | 'cascade_subtree'
export type TerminationPermissionEvaluationOutcome = 'allowed' | 'denied'
export type TerminationRequestStatus =
  | 'accepted'
  | 'rejected'
  | 'completed'
  | 'partially_completed'
  | 'failed'
export type TerminationOutcome =
  | 'terminated'
  | 'already_completed'
  | 'not_found'
  | 'permission_denied'
  | 'failed'

export interface RuntimeTerminationRequestPayload {
  target_session_id: string
  termination_scope: TerminationScope
  operator_reason?: string
}

export interface RuntimeTerminationRequest {
  id: string
  requested_by_user_id: string
  target_agent_job_id: string
  termination_scope: TerminationScope
  permission_evaluation_outcome: TerminationPermissionEvaluationOutcome
  permission_evaluation_reason: string | null
  request_status: TerminationRequestStatus
  requested_at: string
  completed_at: string | null
}

export interface RuntimeTerminationCascadeOutcome {
  id: string
  termination_request_id: string
  affected_agent_job_id: string
  cascade_level: number
  termination_outcome: TerminationOutcome
  outcome_reason: string | null
  processed_at: string
}

export type ModelUsagePosturePeriod = 'hour' | 'day' | 'week' | 'month'
export type ModelGuardrailPeriod = ModelUsagePosturePeriod
export type ModelUsagePostureState = 'within_limit' | 'approaching_limit' | 'breached'
export type ModelGuardrailEnforcementPosture = 'terminate' | 'observe_only'
export type ModelUsageUnit = 'k' | 'tokens'

export interface ModelUsageGuardrailLimit {
  id: string
  model_config_id: string
  model_id: string
  model_name: string
  period: ModelGuardrailPeriod
  limit_value: number
  enforcement_posture: ModelGuardrailEnforcementPosture
  unit: ModelUsageUnit
  is_active: boolean
  details: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ModelUsagePosture {
  id: string
  model_guardrail_configuration_id: string
  model_id: string
  posture_period: ModelUsagePosturePeriod
  usage_value: number
  limit_value: number
  posture_state: ModelUsagePostureState
  observed_at: string
  details: Record<string, unknown>
}

export type ModelAvailabilityDisabledReason = 'manual' | 'vendor_cascaded'

export interface ModelAvailabilityEntry {
  model_name: string
  is_disabled: boolean
  disabled_reason: ModelAvailabilityDisabledReason | null
  guardrails: ModelUsageGuardrailLimit[]
}

export interface VendorAvailabilityNode {
  vendor_config_id: string
  vendor_display_name: string
  is_disabled: boolean
  models: ModelAvailabilityEntry[]
}

export type ModelAvailabilityHierarchy = VendorAvailabilityNode[]

export interface PreflightAvailabilityOutcome {
  allowed: boolean
  reason: string | null
  blocked_by: ModelAvailabilityDisabledReason | null
}

export type AgentPlanStatus = 'pending' | 'success' | 'failed'

export interface PlanStep {
  order: number
  type: string
  name: string
  description: string | null
}

export interface TopologyNode {
  id: string
  type: string
  label: string
  meta?: Record<string, unknown>
  usage?: string
}

export interface TopologyEdge {
  source: string
  target: string
  label?: string
  style?: string
}

export interface AgentPlan {
  id: string
  agent_type_id: string
  plan_steps: PlanStep[]
  topology_nodes: TopologyNode[]
  topology_edges: TopologyEdge[]
  generation_status: AgentPlanStatus
  generation_error: string | null
  agent_config_hash: string | null
  generated_at: string | null
}

export interface SopBinding {
  id: string
  sop_id: string
  sop_name: string
  order: number
  created_at: string
}

export interface SkillBinding {
  id: string
  skill_id: string
  skill_name: string
  order: number
  created_at: string
}

export interface SopBindingInput {
  sop_id: string
  order: number
}

export interface SkillBindingInput {
  skill_id: string
  order: number
}

export interface AgentType {
  id: string
  name: string
  description: string | null
  identity_id: string | null
  role_id: string | null
  model_id: string | null
  system_instruction: string | null
  input_type: AgentInputType
  input_schema: Record<string, unknown> | null
  output_type: AgentOutputType
  output_schema: Record<string, unknown> | null
  output_data_type_id: string | null
  output_data_type_name: string | null
  sop_bindings?: SopBinding[]
  skill_bindings?: SkillBinding[]
  guardrail_max_iterations?: number
  guardrail_max_delegation_depth?: number
  guardrail_max_delegated_steps?: number
  guardrail_execution_timeout_seconds?: number
  guardrail_token_budget?: number | null
  guardrail_token_enforcement_mode?: 'observe' | 'enforce'
  guardrail_token_fallback_mode?: 'observe_and_log' | 'stop_on_next_hard_guardrail'
  guardrail_conversational_token_visibility_mode?: 'enabled' | 'disabled'
  guardrail_conversational_continuation_policy?: 'allow'
  is_active: boolean
  created_at: string
  updated_at: string
  plan?: AgentPlan | null
}

export interface GuardrailUsage {
  policySnapshotId: string | null
  cumulativeIterations: number | null
  maxIterations: number | null
  delegatedSteps: number | null
  maxDelegatedSteps: number | null
  delegationDepth: number | null
  maxDelegationDepth: number | null
  elapsedSeconds: number | null
  tokenUsageCurrentSession: number | null
  tokenBudget: number | null
  executionTimeoutSeconds: number | null
}

export type ModelProviderType =
  | 'openai'
  | 'anthropic'
  | 'litellm_proxy'
  | 'azure_openai'
  | 'gemini'
  | 'mistral'
  | 'cohere'
  | 'groq'
  | 'together'
  | 'fireworks'
  | 'perplexity'
  | 'deepseek'

export interface ModelConfig {
  id: string
  display_name: string
  provider_type: ModelProviderType
  api_base_url: string | null
  has_credentials: boolean
  enabled_models: string[]
  created_at: string
  updated_at: string
}

export interface WorkflowGenerationModelOption {
  model_id: string
  config_id: string
  config_display_name: string
  provider_type: ModelProviderType
}

export interface WorkflowGenerationModelConfig {
  selected_model_id: string | null
  options: WorkflowGenerationModelOption[]
}

export interface ExecutionLogRead {
  id: string
  session_id: string
  system_instruction: string | null
  user_prompt: string | null
  logged_at: string
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
export type JobTargetType = 'agent'
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

export interface LinkedAgentSession {
  id: string
  status: AgentJobStatus
  output_data: Record<string, unknown> | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  agent_type_name: string | null
}

export interface JobExecution {
  id: string
  job_id: string
  status: ExecutionStatus
  error: string | null
  result: Record<string, unknown> | null
  started_at: string
  finished_at: string | null
  agent_session: LinkedAgentSession | null
}

// ── Conversations ──────────────────────────────────────────────────────────────

export type ConversationStatus = 'active' | 'closed' | 'archived' | 'error'
export type TurnRole = 'user' | 'agent' | 'tool' | 'system'
export type TurnType = 'message' | 'intervene_request' | 'intervene_response'

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
  turn_type: TurnType
  content: string
  intervene_request_id: string | null
  token_count: number | null
  created_at: string
  tool_calls: ToolCallRecord[]
}

export interface ConversationSessionCreate {
  agent_type_id: string
}

export interface ConversationSession {
  id: string
  agent_type_id: string | null
  triggered_by_user_id: string | null
  agent_job_id: string | null
  title: string | null
  channel: string
  status: ConversationStatus
  turn_count: number
  created_at: string
  updated_at: string
  closed_at: string | null
  guardrail_usage?: Record<string, unknown> | null
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

export type ChannelType = 'SMTP' | 'SENDGRID' | 'RESEND' | 'TEAMS_WEBHOOK' | 'SLACK_WEBHOOK'
export type DeliveryStatus = 'pending' | 'delivered' | 'failed'
export type SourceType = 'SOP' | 'AGENT' | 'MANUAL'

export interface ChannelPropertyRead {
  id: string
  key: string
  is_secret: boolean
  value?: string | null  // Only populated for non-secret properties
}

export interface ChannelPropertyWrite {
  key: string
  value: string
  is_secret: boolean
}

export interface NotificationChannel {
  id: string
  name: string
  channel_type: ChannelType
  description: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  properties: ChannelPropertyRead[]
}

export interface GroupChannelMappingRead {
  id: string
  channel_id: string
}

export interface RecipientGroup {
  id: string
  name: string
  slug: string
  description: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  channel_mappings: GroupChannelMappingRead[]
}

export interface NotificationLog {
  id: string
  group_id: string | null
  channel_id: string
  source_type: SourceType
  source_id: string | null
  subject: string | null
  body: string
  recipient: string | null
  status: DeliveryStatus
  error: string | null
  metadata_: Record<string, unknown> | null
  created_at: string
  delivered_at: string | null
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

// ── Agent Data Types ───────────────────────────────────────────────────────────

export type DataTypeFieldType = 'string' | 'number' | 'boolean' | 'date' | 'enum'

export interface AgentDataTypeField {
  name: string
  description?: string
  type: DataTypeFieldType
  enum_values?: string[] | null
  required?: boolean
  default?: string | number | boolean | null
}

export interface AgentDataType {
  id: string
  name: string
  slug: string
  description: string | null
  fields: AgentDataTypeField[]
  created_at: string
  updated_at: string
}

export interface ReferencingAgentType {
  id: string
  name: string
}

export interface DataTypeCreate {
  name: string
  slug: string
  description?: string | null
  fields: AgentDataTypeField[]
}

export interface DataTypeUpdate {
  name?: string
  slug?: string
  description?: string | null
  fields?: AgentDataTypeField[]
}

export interface DataTypeListResponse {
  items: AgentDataType[]
  total: number
  page: number
  page_size: number
  usage?: Record<string, number>
  referencing_agent_types?: Record<string, ReferencingAgentType[]>
}

// ── Agent Outputs ──────────────────────────────────────────────────────────────

export interface AgentOutputResponse {
  id: string
  data_type_id: string
  data_type_name: string
  agent_type_id: string
  agent_type_name: string
  execution_session_id: string
  field_values: Record<string, unknown> | null
  validation_status: 'valid' | 'validation_error'
  raw_output: string | null
  created_at: string
}

export interface AgentOutputQueryParams {
  data_type_id?: string
  agent_type_id?: string
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}

export interface AgentOutputListResponse {
  items: AgentOutputResponse[]
  total: number
  page: number
  page_size: number
}

export interface AgentOutputExportParams {
  data_type_id?: string
  agent_type_id?: string
  date_from?: string
  date_to?: string
}

// ── Auto Outputs (auto/markdown output_type, stored in AgentJob.output_data) ──

export interface AutoOutputItem {
  session_id: string
  agent_type_id: string
  agent_type_name: string | null
  output_preview: string | null
  created_at: string
}

// ── Agent Data ─────────────────────────────────────────────────────────────────

export interface AgentDataResponse {
  id: string
  agent_type_id: string | null
  session_id: string | null
  data_name: string
  data_value: unknown
  data_type: string
  is_active: boolean
  created_at: string
  agent_type_name: string | null
}

export interface AgentDataQueryParams {
  data_name?: string
  agent_type_id?: string
  session_id?: string
  page?: number
  page_size?: number
}

export interface AgentDataListResponse {
  items: AgentDataResponse[]
  total: number
  page: number
  page_size: number
}

export interface AutoOutputListResponse {
  items: AutoOutputItem[]
  total: number
  page: number
  page_size: number
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

// ── Log Viewer ─────────────────────────────────────────────────────────────────

export interface ExecutionLogEntry {
  id: string
  session_id?: string
  timestamp: string
  event_type: string
  log_level: string
  event_category?: 'functional' | 'guardrail' | 'posture' | 'termination' | 'validation'
  correlation_id?: string | null
  actor_type?: 'system' | 'user' | 'operator'
  message: string
  data: Record<string, unknown>
}

export type WorkingStepIconType = 'llm' | 'tool' | 'success' | 'error' | 'info' | 'delegating' | 'waiting'

export interface WorkingStepDetail {
  label: string
  content: string
  eventType?: string
}

export interface WorkingStep {
  id: string
  iconType: WorkingStepIconType
  message: string
  timestamp: string
  detail: WorkingStepDetail | null
}

export interface WorkingStepSpan {
  id: string
  title: string
  iconType: WorkingStepIconType
  children: (WorkingStep | WorkingStepSpan)[]
  collapsed: boolean
}

export interface LogSummary {
  identity: string | null
  role: string | null
  model: string | null
  inputType: AgentInputType | null
  sopsSkills: string[]
  planCompleted: number
  planTotal: number
  resultStatus: 'success' | 'failure' | 'terminated' | 'running' | 'unknown'
  startedAt: string | null
  completedAt: string | null
  durationMs: number | null
  guardrailUsage: GuardrailUsage | null
}

export interface StructuredLog {
  summary: LogSummary
  spans: WorkingStepSpan[]
  workingSteps: WorkingStep[]
  rawLog: string
}

export interface LogPresenterOptions {
  /** Actual session status from AgentJob — overrides inferred status from logs */
  sessionStatus?: AgentJobStatus
}

// ── Intervene ─────────────────────────────────────────────────────────────────

export type InterveneRequestStatus = 'pending' | 'responded' | 'cancelled' | 'expired'
export type InterventionType = 'approval' | 'choice' | 'text'

export interface InterveneRequest {
  id: string
  agent_session_id: string
  agent_type_id: string
  conversation_session_id?: string | null
  intervention_type: InterventionType
  reason: string
  choices?: string[]
  status: InterveneRequestStatus
  delegation_depth: number
  created_at: string
  responded_at?: string
  expires_at?: string
  response?: InterveneResponse
  agent_name?: string
  triggered_by_user_name?: string
}

export interface InterveneResponse {
  id: string
  request_id: string
  operator_user_id: string
  approval_value?: boolean
  selected_choice?: string
  text_value?: string
  responded_at: string
  operator_user_name?: string
}

export interface InterveneMetrics {
  pending_count: number
  avg_response_time_seconds: number
  resolution_rate: number
}

// ── Intervention WebSocket Messages ─────────────────────────────────────────────

export interface InterveneRequestMessage {
  type: 'intervene_request'
  request_id: string
  intervention_type: InterventionType
  reason: string
  choices?: string[]
  agent_type?: string
  delegation_depth: number
  conversation_session_id: string
}

export interface InterveneResponseMessage {
  type: 'intervene_response'
  request_id: string
  approval_value?: boolean
  selected_choice?: string
  text_value?: string
}

export interface InterveneCancelMessage {
  type: 'intervene_cancel'
  request_id: string
}

export interface InterveneStatusMessage {
  type: 'intervene_status'
  request_id: string
  status: 'pending' | 'responded' | 'cancelled' | 'expired' | 'error'
  message?: string
}

export interface ChatBlockedMessage {
  type: 'chat_blocked'
  reason: string
  message: string
}

export type InterventionWsMessage =
  | InterveneRequestMessage
  | InterveneStatusMessage
  | ChatBlockedMessage
