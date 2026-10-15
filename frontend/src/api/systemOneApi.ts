/**
 * Typed API client functions for System One provider configuration
 * and decision execution results.
 *
 * The API key is write-only: it is accepted on create/update and never
 * returned in any response payload.
 */
import apiClient from './apiClient'

// ── Types ──────────────────────────────────────────────────────────────────

/** Vendor type — extensible backend enum (GET /system-one/provider-types). */
export type SystemOneProviderType = 'typesafe' | (string & {})

/** Preset FULL endpoint URL (create-form default), used verbatim. */
export const SYSTEM_ONE_PRESET_BASE_URL = 'https://api.typesafe.ai/v1/systemone'

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
  /** Editable per tenant; defaults to the preset base URL server-side. */
  base_url?: string
  default_model?: string
  api_key: string
  enabled?: boolean
  enabled_models?: string[] | null
}

export interface SystemOneProviderUpdate {
  display_name?: string
  /** Editable per tenant — required by the form on update. */
  base_url?: string
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

/** One selectable vendor type served by GET /system-one/provider-types. */
export interface SystemOneProviderTypeOption {
  value: string
  label: string
}

/** Model ids discovered from the vendor's OpenAI-compatible /models endpoint. */
export interface VendorModelSyncResult {
  models: string[]
}

export interface SystemOneStatus {
  configured: boolean
  provider_type?: SystemOneProviderType | null
  provider_id?: string | null
  model?: string | null
  provider_count?: number
}

// ── Decision model catalogue (provider/model hierarchy + toggles) ──────────

export type DecisionModelDisabledReason = 'manual' | 'vendor_cascaded'

/** Per-model availability entry within the provider hierarchy. */
export interface DecisionModelAvailabilityEntry {
  availability_id: string | null
  model_name: string
  effective_is_disabled: boolean
  disabled_reason: DecisionModelDisabledReason | null
}

/** One provider with its model catalogue in the hierarchy listing. */
export interface DecisionModelHierarchyEntry {
  provider_id: string
  display_name: string
  provider_type: SystemOneProviderType
  default_model: string
  is_disabled: boolean
  models: DecisionModelAvailabilityEntry[]
}

/** Flat enabled-models entry feeding the authoring selector. */
export interface DecisionEnabledModel {
  availability_id: string
  provider_id: string
  provider_type: SystemOneProviderType
  provider_display_name: string
  model_name: string
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
    /** Provider/model identity recorded by the decision engine (audit). */
    provider?: {
      provider_id: string
      provider_type: string
      provider_display_name: string
      model_name: string
      usage?: Record<string, unknown>
    } | null
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

/**
 * Selectable vendor (provider) types — served by the backend enum, never
 * hardcoded client-side.
 */
export async function listSystemOneProviderTypes(): Promise<
  SystemOneProviderTypeOption[]
> {
  const { data } = await apiClient.get<SystemOneProviderTypeOption[]>(
    '/system-one/provider-types',
  )
  return data
}

/**
 * Discover the vendor's model catalogue via its OpenAI-compatible
 * /models endpoint (with the stored key). Returns model ids only.
 */
export async function listVendorModels(
  providerId: string,
): Promise<VendorModelSyncResult> {
  const { data } = await apiClient.get<VendorModelSyncResult>(
    `/system-one/providers/${providerId}/vendor-models`,
  )
  return data
}

/** Import vendor model ids as availability rows (enabled by default). */
export async function importVendorModels(
  providerId: string,
  models: string[],
): Promise<SystemOneProvider> {
  const { data } = await apiClient.post<SystemOneProvider>(
    `/system-one/providers/${providerId}/import-models`,
    { models },
  )
  return data
}

// ── Decision model catalogue API ───────────────────────────────────────────

/** Provider → model hierarchy with effective availability state. */
export async function listDecisionModelHierarchy(): Promise<
  DecisionModelHierarchyEntry[]
> {
  const { data } = await apiClient.get<DecisionModelHierarchyEntry[]>(
    '/system-one/models',
  )
  return data
}

/** Vendor-level enable/disable — cascades to the provider's models. */
export async function setProviderAvailability(
  providerId: string,
  isDisabled: boolean,
): Promise<SystemOneProvider> {
  const { data } = await apiClient.put<SystemOneProvider>(
    `/system-one/providers/${providerId}/availability`,
    { is_disabled: isDisabled },
  )
  return data
}

/** Per-model manual disable/enable. */
export async function setDecisionModelAvailability(
  availabilityId: string,
  isDisabled: boolean,
): Promise<void> {
  await apiClient.put(`/system-one/models/${availabilityId}/availability`, {
    is_disabled: isDisabled,
  })
}

/** Flat enabled-models list (provider enabled + model enabled). */
export async function listEnabledDecisionModels(): Promise<
  DecisionEnabledModel[]
> {
  const { data } = await apiClient.get<DecisionEnabledModel[]>(
    '/system-one/enabled-models',
  )
  return data
}

// ── Decision guardrails (FIX-20261014-003000) ──────────────────────────────
// Guardrail management embedded in the Decision Model Providers module.
// Reuses the model-usage guardrail stack (same tables); rows are keyed via
// decision_provider_id and NEVER mixed with LLM model-config guardrails.

export interface DecisionGuardrail {
  id: string
  decision_provider_id: string | null
  model_id: string | null
  model_name: string
  period: 'hour' | 'day' | 'week' | 'month'
  limit_value: number
  unit: 'k' | 'tokens'
  enforcement_posture: 'terminate' | 'observe_only'
  is_active: boolean
  details: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface DecisionGuardrailCreatePayload {
  model_name: string
  period: DecisionGuardrail['period']
  limit_value: number
  unit: DecisionGuardrail['unit']
  enforcement_posture: DecisionGuardrail['enforcement_posture']
  is_active: boolean
}

export interface DecisionGuardrailUpdatePayload {
  limit_value?: number
  unit?: DecisionGuardrail['unit']
  enforcement_posture?: DecisionGuardrail['enforcement_posture']
  is_active?: boolean
}

/** Guardrails configured for one decision provider's models. */
export async function listDecisionGuardrails(
  providerId: string,
): Promise<DecisionGuardrail[]> {
  const { data } = await apiClient.get<DecisionGuardrail[]>(
    `/system-one/providers/${providerId}/guardrails`,
  )
  return data
}

/** Create one per-period guardrail for a decision provider model. */
export async function createDecisionGuardrail(
  providerId: string,
  payload: DecisionGuardrailCreatePayload,
): Promise<DecisionGuardrail> {
  const { data } = await apiClient.post<DecisionGuardrail>(
    `/system-one/providers/${providerId}/guardrails`,
    payload,
  )
  return data
}

/** Partially update one decision guardrail (period is immutable). */
export async function updateDecisionGuardrail(
  guardrailId: string,
  payload: DecisionGuardrailUpdatePayload,
): Promise<DecisionGuardrail> {
  const { data } = await apiClient.put<DecisionGuardrail>(
    `/system-one/guardrails/${guardrailId}`,
    payload,
  )
  return data
}

/** Hard-delete one decision guardrail (LLM rows are not reachable). */
export async function deleteDecisionGuardrail(guardrailId: string): Promise<void> {
  await apiClient.delete(`/system-one/guardrails/${guardrailId}`)
}

/** Usage posture snapshots for one decision provider's guardrails. */
export async function getDecisionGuardrailPosture(
  providerId: string,
  refresh = true,
): Promise<import('../types').ModelUsagePosture[]> {
  const { data } = await apiClient.get<import('../types').ModelUsagePosture[]>(
    `/system-one/providers/${providerId}/guardrails/posture`,
    { params: { refresh } },
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
