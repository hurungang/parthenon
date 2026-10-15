/**
 * Typed API client functions for decision tools.
 *
 * Decision tools are user-definable tools behaving like system tools:
 * input/output contracts reference AgentDataType records, descriptions are
 * auto-generated, names are unique within the caller's tenant, and tools
 * are exposed as `decision____<name>` MCP tools.
 */
import apiClient from './apiClient'
import type { DecisionEnabledModel } from './systemOneApi'

export type DecisionToolStatus = 'draft' | 'active' | 'disabled'
export type DecisionQuestionType = 'choice' | 'score' | 'noul'
/** State maps from the execution input only (agent_data is retired). */
export type StatePresetSource = 'input'

/** Read-only summary of a referenced AgentDataType. */
export interface AgentDataTypeSummary {
  id: string
  name: string
  slug: string
  fields: { name: string; type?: string; description?: string }[]
}

export interface DecisionToolQuestion {
  id?: string
  ordering: number
  question_key: string
  question_type: DecisionQuestionType
  instructions: string | null
  /** choice: option key → description; score: ordered rubric legend; noul: null. */
  criteria_options: Record<string, string> | string[] | null
  is_required: boolean
}

export interface StatePresetMapping {
  source: StatePresetSource
  key: string
}

export interface DecisionTool {
  id: string
  tenant_id: string | null
  name: string
  purpose: string | null
  /** Auto-generated from the definition — what skills/agents/MCP clients see. */
  description: string | null
  input_data_type_id: string | null
  output_data_type_id: string | null
  input_data_type: AgentDataTypeSummary | null
  output_data_type: AgentDataTypeSummary | null
  state_preset: Record<string, StatePresetMapping> | null
  act_threshold: number
  confirm_threshold: number
  provider_model: string
  /** Selected enabled decision model (replaces legacy provider_model). */
  decision_model_availability_id: string | null
  provider_type: string | null
  provider_display_name: string | null
  model_name: string | null
  status: DecisionToolStatus
  enabled: boolean
  /** Readiness: both input and output data types are configured. */
  ready: boolean
  is_system: boolean
  created_at: string
  updated_at: string
  questions: DecisionToolQuestion[]
}

export interface DecisionToolCreate {
  name: string
  purpose?: string
  input_data_type_id?: string | null
  output_data_type_id?: string | null
  state_preset?: Record<string, StatePresetMapping> | null
  act_threshold?: number
  confirm_threshold?: number
  provider_model?: string
  decision_model_availability_id?: string | null
  status?: DecisionToolStatus
  enabled?: boolean
  questions: DecisionToolQuestion[]
}

export interface DecisionToolUpdate {
  purpose?: string
  input_data_type_id?: string | null
  output_data_type_id?: string | null
  state_preset?: Record<string, StatePresetMapping> | null
  act_threshold?: number
  confirm_threshold?: number
  provider_model?: string
  decision_model_availability_id?: string | null
  status?: DecisionToolStatus
  enabled?: boolean
  questions?: DecisionToolQuestion[]
}

export interface DecisionToolDescription {
  tool_id: string
  name: string
  description: string
}

// ── CRUD ───────────────────────────────────────────────────────────────────

/** List decision tools within the caller's tenant (filterable by status). */
export async function listDecisionTools(
  status?: DecisionToolStatus,
): Promise<DecisionTool[]> {
  const { data } = await apiClient.get<DecisionTool[]>('/decision-tools', {
    params: { status: status || undefined },
  })
  return data
}

/** Create a decision tool (per-tenant name uniqueness enforced server-side). */
export async function createDecisionTool(
  body: DecisionToolCreate,
): Promise<DecisionTool> {
  const { data } = await apiClient.post<DecisionTool>('/decision-tools', body)
  return data
}

/** Fetch one decision tool with questions, schemas, and generated description. */
export async function getDecisionTool(id: string): Promise<DecisionTool> {
  const { data } = await apiClient.get<DecisionTool>(`/decision-tools/${id}`)
  return data
}

/** Update a decision tool; the stored description is regenerated server-side. */
export async function updateDecisionTool(
  id: string,
  body: DecisionToolUpdate,
): Promise<DecisionTool> {
  const { data } = await apiClient.put<DecisionTool>(`/decision-tools/${id}`, body)
  return data
}

/** Delete a decision tool and its questions. */
export async function deleteDecisionTool(id: string): Promise<void> {
  await apiClient.delete(`/decision-tools/${id}`)
}

/** Fetch the auto-generated tool description (also included in reads). */
export async function getDecisionToolDescription(
  id: string,
): Promise<DecisionToolDescription> {
  const { data } = await apiClient.get<DecisionToolDescription>(
    `/decision-tools/${id}/description`,
  )
  return data
}

// ── Enabled decision models (authoring selector) ───────────────────────────

/**
 * Enabled decision models for the authoring selector (provider enabled AND
 * model enabled within the caller's tenant).
 */
export async function listEnabledModelsForAuthoring(): Promise<
  DecisionEnabledModel[]
> {
  const { data } = await apiClient.get<DecisionEnabledModel[]>(
    '/decision-tools/enabled-models',
  )
  return data
}

// ── AI-assisted authoring ──────────────────────────────────────────────────

export interface DecisionToolGenerateRequest {
  description: string
  input_data_type_id?: string | null
  output_data_type_id?: string | null
  existing_questions?: DecisionToolQuestion[] | null
}

export interface DecisionToolGenerateResponse {
  questions: DecisionToolQuestion[]
  state_preset: Record<string, StatePresetMapping> | null
  detected_state_paths: string[]
  model_id: string
}

/** AI-draft questions + state mapping from description + chosen data types. */
export async function generateDecisionToolDraft(
  body: DecisionToolGenerateRequest,
): Promise<DecisionToolGenerateResponse> {
  const { data } = await apiClient.post<DecisionToolGenerateResponse>(
    '/decision-tools/generate',
    body,
  )
  return data
}
