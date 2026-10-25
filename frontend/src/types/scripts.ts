/**
 * Types for the Software 3.0 script registry — mirrors backend/app/schemas/scripts.py.
 */

export type ScriptLifecycleStatus = 'draft' | 'verified' | 'compiled' | 'retired'

export type ScriptHealthStatus = 'healthy' | 'degraded' | 'unhealthy'

export type VerificationComparisonOutcome =
  | 'match'
  | 'match_within_tolerance'
  | 'mismatch'

export type VerificationVerdict = 'promoted' | 'rejected'

export type FallbackTriggerReason =
  | 'execution_error'
  | 'tool_schema_mismatch'
  | 'output_validation_failure'

export type FallbackResultingAction =
  | 'llm_completed'
  | 'repaired_candidate_produced'
  | 'repair_not_produced'

export type RepairRetryOutcome = 'pending' | 'succeeded' | 'failed'

export type SandboxValidationStatus = 'pending' | 'passed' | 'failed'

export interface ScriptVersionResponse {
  id: string
  script_definition_id: string
  version_label: string
  lifecycle_status: ScriptLifecycleStatus
  declarative_step_graph: Record<string, unknown> | null
  /** Model-authored sandboxed Python source (sandboxed scripting). */
  python_source: string | null
  cpu_limit_seconds: number | null
  memory_limit_mb: number | null
  wall_time_limit_seconds: number | null
  sandbox_validation_status: SandboxValidationStatus
  sandbox_validation_reason: string | null
  parent_version_id: string | null
  repaired_from_id: string | null
  created_by: string | null
  created_at: string
}

export interface ScriptDefinitionResponse {
  id: string
  name: string
  description: string | null
  lifecycle_status: ScriptLifecycleStatus
  health_status: ScriptHealthStatus
  agent_type_id: string
  source_plan_id: string | null
  source_session_id: string | null
  current_version_id: string | null
  created_at: string
  updated_at: string
  versions: ScriptVersionResponse[]
}

export interface ScriptDefinitionListResponse {
  items: ScriptDefinitionResponse[]
  total: number
}

export interface VerificationRunResponse {
  id: string
  script_version_id: string
  reference_execution_id: string | null
  comparison_outcome: VerificationComparisonOutcome
  verdict: VerificationVerdict
  verdict_reason: string | null
  input_context: Record<string, unknown> | null
  expected_output: Record<string, unknown> | null
  actual_output: Record<string, unknown> | null
  created_at: string
}

export interface VerificationRunListResponse {
  items: VerificationRunResponse[]
  total: number
}

export interface FallbackEventResponse {
  id: string
  execution_record_id: string
  script_version_id: string | null
  trigger_reason: FallbackTriggerReason
  resulting_action: FallbackResultingAction
  failure_detail: string | null
  script_health_impact: number
  repaired_version_id: string | null
  created_at: string
}

export interface FallbackEventListResponse {
  items: FallbackEventResponse[]
  total: number
}

export interface HealthSummaryResponse {
  script_definition_id: string
  health_status: ScriptHealthStatus
  lifecycle_status: ScriptLifecycleStatus
  recent_fallback_count: number
  total_fallback_count: number
  latest_fallback: Record<string, unknown> | null
}

export interface RepairAttemptResponse {
  id: string
  fallback_event_id: string
  script_version_id: string | null
  repaired_version_id: string | null
  defect_diagnosis: string
  diff_applied: string | null
  retry_outcome: RepairRetryOutcome
  created_at: string
}

export interface RepairAttemptListResponse {
  items: RepairAttemptResponse[]
  total: number
}

export interface LifecycleTransitionRequest {
  target_status: ScriptLifecycleStatus
}
