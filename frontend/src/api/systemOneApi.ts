/**
 * Typed API client functions for System One provider configuration
 * and decision execution results.
 *
 * The API key is write-only: it is accepted on create/update and never
 * returned in any response payload.
 */
import apiClient from './apiClient'

// ── Types ──────────────────────────────────────────────────────────────────

export type SystemOneProviderType = 'typesafe'

/** Preset provider base URL (non-editable for this release). */
export const SYSTEM_ONE_PRESET_BASE_URL = 'https://api.typesafe.ai/v1'

export interface SystemOneProvider {
  id: string
  provider_type: SystemOneProviderType
  display_name: string
  base_url: string
  default_model: string
  enabled: boolean
  enabled_models: string[] | null
  has_api_key: boolean
}

export interface SystemOneProviderCreate {
  provider_type?: SystemOneProviderType
  display_name: string
  /** Defaults to the preset base URL server-side; sent read-only. */
  base_url?: string
  default_model?: string
  api_key: string
  enabled?: boolean
  enabled_models?: string[] | null
}

export interface SystemOneProviderUpdate {
  display_name?: string
  /** Preset — not editable. */
  default_model?: string
  /** Omit to keep the existing key — never sent empty. */
  api_key?: string
  enabled?: boolean
  enabled_models?: string[] | null
}

/** Status-only Test-connection result — never carries key material. */
export interface SystemOneTestConnectionResult {
  ok: boolean
  message: string
  latency_ms?: number | null
}

export interface SystemOneStatus {
  configured: boolean
  provider_type?: SystemOneProviderType | null
  provider_id?: string | null
  model?: string | null
}

export type DecisionOutcome = 'act' | 'confirm' | 'escalate'
export type DecisionExecutionStatus = 'completed' | 'failed'
export type DecisionQuestionType = 'choice' | 'score' | 'noul'

/** One normalized per-question answer as persisted by the decision engine. */
export interface DecisionAnswer {
  type: DecisionQuestionType
  question_type: DecisionQuestionType
  value: unknown
  choice?: string
  score?: number
  noul?: number
  probabilities?: Record<string, number>
  confidence?: number
  legend?: string[]
  effective_confidence: number
}

/** Persisted decision execution result (auditable, no credentials). */
export interface DecisionExecutionResult {
  id: string
  tenant_id: string | null
  decision_tool_id: string
  conversation_session_id: string | null
  input_state_snapshot: Record<string, unknown> | null
  answers: {
    answers?: Record<string, DecisionAnswer>
    gate_confidence?: number
  } | null
  outcome: DecisionOutcome
  status: DecisionExecutionStatus
  provider_model: string | null
  error_message: string | null
  created_at: string
}

export interface DecisionResultsFilter {
  decision_tool_id?: string
  session_id?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}

// ── Provider config API ────────────────────────────────────────────────────

/** List all System One provider configs (never includes key material). */
export async function listSystemOneProviders(): Promise<SystemOneProvider[]> {
  const { data } = await apiClient.get<SystemOneProvider[]>('/system-one/providers')
  return data
}

/** Create a provider config (API key write-only). */
export async function createSystemOneProvider(
  body: SystemOneProviderCreate,
): Promise<SystemOneProvider> {
  const { data } = await apiClient.post<SystemOneProvider>('/system-one/providers', body)
  return data
}

/** Update a provider config; omit `api_key` to keep the existing key. */
export async function updateSystemOneProvider(
  providerId: string,
  body: SystemOneProviderUpdate,
): Promise<SystemOneProvider> {
  const { data } = await apiClient.patch<SystemOneProvider>(
    `/system-one/providers/${providerId}`,
    body,
  )
  return data
}

/** Delete a provider config. */
export async function deleteSystemOneProvider(providerId: string): Promise<void> {
  await apiClient.delete(`/system-one/providers/${providerId}`)
}

/**
 * Whether an enabled System One model is configured.
 * Used by the skill editor authoring gate.
 */
export async function getSystemOneStatus(): Promise<SystemOneStatus> {
  const { data } = await apiClient.get<SystemOneStatus>('/system-one/status')
  return data
}

/**
 * Test-connection: lightweight validation probe with the stored key.
 * Returns a status-only result — never key material.
 */
export async function testSystemOneProviderConnection(
  providerId: string,
): Promise<SystemOneTestConnectionResult> {
  const { data } = await apiClient.post<SystemOneTestConnectionResult>(
    `/system-one/providers/${providerId}/test`,
  )
  return data
}

// ── Decision results API ───────────────────────────────────────────────────

/** Query persisted decision execution results with optional filters. */
export async function getDecisionResults(
  filter: DecisionResultsFilter = {},
): Promise<DecisionExecutionResult[]> {
  const { data } = await apiClient.get<DecisionExecutionResult[]>('/results/decision', {
    params: {
      decision_tool_id: filter.decision_tool_id || undefined,
      session_id: filter.session_id || undefined,
      date_from: filter.date_from || undefined,
      date_to: filter.date_to || undefined,
      limit: filter.limit ?? 50,
      offset: filter.offset ?? 0,
    },
  })
  return data
}
