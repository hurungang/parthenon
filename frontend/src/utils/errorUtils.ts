export interface RequiredPermission {
  resource_type: string
  action: string
  resource_id?: string | null
}

export interface PermissionDeniedDetail {
  detail: string
  required_permission: RequiredPermission
}

/** One structured binding-validation failure (backend `BindingError`). */
export interface BindingErrorDetail {
  resource_type: 'role' | 'sop' | 'skill'
  resource_id?: string | null
  rule: string
  message: string
}

/** Backend 422 detail shape for `binding_validation_failed`. */
export interface BindingValidationFailureDetail {
  error: 'binding_validation_failed'
  messages: string[]
  errors: BindingErrorDetail[]
}

/**
 * Extracts structured binding-validation errors from a failed save response
 * (FastAPI 422 with `detail: {error: 'binding_validation_failed', messages,
 * errors}`). Returns the per-binding human-readable messages, or null when
 * the error is not a binding-validation failure (or carries no detail).
 */
export function extractBindingValidationErrors(error: unknown): string[] | null {
  if (!error || typeof error !== 'object') return null
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (!detail || typeof detail !== 'object') return null
  const obj = detail as Partial<BindingValidationFailureDetail>
  if (obj.error !== 'binding_validation_failed') return null
  const messages = Array.isArray(obj.messages)
    ? obj.messages.filter((m): m is string => typeof m === 'string' && m.length > 0)
    : []
  return messages.length > 0 ? messages : null
}

/**
 * Structured `412` failure emitted by the plan/optimize preconditions:
 * `detail: { error, reason_code, reason }`.
 *
 * - `optimize_gate_unmet` — `POST /agents/sessions/optimize`
 * - `plan_generation_unavailable` — `POST /agents/types/{id}/regenerate-plan`
 */
export interface StructuredGateFailure {
  error: 'optimize_gate_unmet' | 'plan_generation_unavailable'
  reason_code: string | null
  reason: string | null
}

/** Reads the nested `detail: { error, reason_code, reason }` payload. */
function extractStructuredGateFailure(
  error: unknown,
  expectedError: StructuredGateFailure['error'],
): StructuredGateFailure | null {
  if (!error || typeof error !== 'object') return null
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data
    ?.detail
  if (!detail || typeof detail !== 'object') return null
  const body = detail as { error?: unknown; reason_code?: unknown; reason?: unknown }
  if (body.error !== expectedError) return null
  return {
    error: expectedError,
    reason_code: typeof body.reason_code === 'string' && body.reason_code ? body.reason_code : null,
    reason: typeof body.reason === 'string' && body.reason ? body.reason : null,
  }
}

/**
 * Extracts the structured `412 optimize_gate_unmet` failure (reason code +
 * human-readable reason) from the dedicated Optimize trigger.
 *
 * The payload now carries `reason_code` (`conversational_agent`,
 * `authoring_model_not_configured`, `authoring_model_not_enabled`,
 * `no_successful_execution`) alongside `reason`; older payloads with only
 * `reason` are tolerated (`reason_code: null`).
 * Returns null for any other failure so standard dialog error handling applies.
 */
export function extractOptimizeGateFailure(error: unknown): StructuredGateFailure | null {
  return extractStructuredGateFailure(error, 'optimize_gate_unmet')
}

/**
 * Extracts the human-readable reason from a `412 optimize_gate_unmet`
 * response (`detail: { error: "optimize_gate_unmet", reason }`).
 * Kept for reason-only rendering; prefer `extractOptimizeGateFailure` when the
 * localized `reason_code` copy should be used.
 * Returns null for any other failure so standard dialog error handling applies.
 */
export function extractOptimizeGateReason(error: unknown): string | null {
  return extractOptimizeGateFailure(error)?.reason ?? null
}

/**
 * Extracts the structured `412 plan_generation_unavailable` failure from the
 * explicit plan-generation endpoint (conversational agent / authoring model
 * unset or no longer enabled).
 */
export function extractPlanGenerationReason(error: unknown): StructuredGateFailure | null {
  return extractStructuredGateFailure(error, 'plan_generation_unavailable')
}

// ── Conversational optimizer (optimization mode) ──────────────────────────────
//
// Optimization errors arrive in three shapes and all share the same reason
// vocabulary (`optimizer_model_not_configured`, `optimizer_model_not_enabled`,
// `no_successful_execution`, `out_of_scope`, `permission_denied`, …):
//   - conversation create/read: `422 {detail: {error, reason}}`
//   - internal agent context:   `412 {detail: {error: 'optimizer_model_unavailable', reason_code, reason}}`
//   - system-tool refusals:     `{status: 'refused', reason_code, reason}`
//   - WS chunks:                `chat_error {code, message}` / `chat_blocked {reason}`

/** `chat_error` codes that only exist for optimization conversations. */
export const OPTIMIZER_CHAT_ERROR_CODE_MODEL_NOT_CONFIGURED = 'optimizer_model_not_configured'
export const OPTIMIZER_CHAT_ERROR_CODE_MODEL_NOT_ENABLED = 'optimizer_model_not_enabled'
export const OPTIMIZER_CHAT_ERROR_CODE_OUT_OF_SCOPE = 'optimization_out_of_scope'
export const OPTIMIZER_CHAT_ERROR_CODE_PERMISSION_DENIED = 'optimization_permission_denied'

/** Reason codes shared with the availability projection / gate / System Config. */
export const OPTIMIZER_REASON_MODEL_NOT_CONFIGURED =
  OPTIMIZER_CHAT_ERROR_CODE_MODEL_NOT_CONFIGURED
export const OPTIMIZER_REASON_MODEL_NOT_ENABLED = OPTIMIZER_CHAT_ERROR_CODE_MODEL_NOT_ENABLED
export const OPTIMIZER_REASON_NO_SUCCESSFUL_EXECUTION = 'no_successful_execution'
export const OPTIMIZER_REASON_OUT_OF_SCOPE = 'out_of_scope'

/** `chat_blocked` reason raised while an optimization decision is pending. */
export const CHAT_BLOCKED_REASON_DECISION_PENDING = 'decision_pending'

/**
 * `request_live_test` / live-test-run refusal codes (the script is the unit of
 * approval — the tool-call preview is derived server-side and is not a run
 * list, so there is nothing to approve operation-by-operation).
 */
export const LIVE_TEST_REFUSAL_OUT_OF_SCOPE = 'out_of_scope'
export const LIVE_TEST_REFUSAL_INVALID_SCRIPT_VERSION = 'invalid_script_version'
export const LIVE_TEST_REFUSAL_SCRIPT_VERSION_NOT_FOUND = 'script_version_not_found'
export const LIVE_TEST_REFUSAL_NO_TOOL_CALLS = 'no_tool_calls'
export const LIVE_TEST_REFUSAL_OPERATION_NOT_PERMITTED = 'operation_not_permitted'
export const LIVE_TEST_REFUSAL_ALREADY_PENDING = 'live_test_already_pending'
export const LIVE_TEST_REFUSAL_QUOTA_EXHAUSTED = 'live_test_quota_exhausted'
export const LIVE_TEST_REFUSAL_NOT_APPROVED = 'live_test_not_approved'
export const LIVE_TEST_REFUSAL_EXPIRED = 'live_test_expired'
export const LIVE_TEST_REFUSAL_ALREADY_CONSUMED = 'live_test_already_consumed'
export const LIVE_TEST_REFUSAL_PERMISSION_DENIED = 'live_test_permission_denied'
export const LIVE_TEST_REFUSAL_RUN_TIMEOUT = 'live_test_run_timeout'
export const LIVE_TEST_REFUSAL_SCRIPT_UNAVAILABLE = 'live_test_script_unavailable'

const LIVE_TEST_REFUSAL_CODES: readonly string[] = [
  LIVE_TEST_REFUSAL_OUT_OF_SCOPE,
  LIVE_TEST_REFUSAL_INVALID_SCRIPT_VERSION,
  LIVE_TEST_REFUSAL_SCRIPT_VERSION_NOT_FOUND,
  LIVE_TEST_REFUSAL_NO_TOOL_CALLS,
  LIVE_TEST_REFUSAL_OPERATION_NOT_PERMITTED,
  LIVE_TEST_REFUSAL_ALREADY_PENDING,
  LIVE_TEST_REFUSAL_QUOTA_EXHAUSTED,
  LIVE_TEST_REFUSAL_NOT_APPROVED,
  LIVE_TEST_REFUSAL_EXPIRED,
  LIVE_TEST_REFUSAL_ALREADY_CONSUMED,
  LIVE_TEST_REFUSAL_PERMISSION_DENIED,
  LIVE_TEST_REFUSAL_RUN_TIMEOUT,
  LIVE_TEST_REFUSAL_SCRIPT_UNAVAILABLE,
]

/** True for a structured live-test refusal reason code. */
export function isLiveTestRefusalCode(code: string | null | undefined): boolean {
  return code != null && LIVE_TEST_REFUSAL_CODES.includes(code)
}

const OPTIMIZER_MODEL_REASON_CODES: readonly string[] = [
  OPTIMIZER_REASON_MODEL_NOT_CONFIGURED,
  OPTIMIZER_REASON_MODEL_NOT_ENABLED,
]

const OPTIMIZER_CHAT_ERROR_CODES: readonly string[] = [
  OPTIMIZER_CHAT_ERROR_CODE_MODEL_NOT_CONFIGURED,
  OPTIMIZER_CHAT_ERROR_CODE_MODEL_NOT_ENABLED,
  OPTIMIZER_CHAT_ERROR_CODE_OUT_OF_SCOPE,
  OPTIMIZER_CHAT_ERROR_CODE_PERMISSION_DENIED,
]

/** True when the code means "no usable optimizer model in this workspace". */
export function isOptimizerModelReasonCode(code: string | null | undefined): boolean {
  return code != null && OPTIMIZER_MODEL_REASON_CODES.includes(code)
}

/** True for the optimization-only `chat_error` codes. */
export function isOptimizerChatErrorCode(code: string | null | undefined): boolean {
  return code != null && OPTIMIZER_CHAT_ERROR_CODES.includes(code)
}

/** True when a `chat_blocked` chunk means a pending decision is blocking input. */
export function isDecisionPendingBlock(reason: string | null | undefined): boolean {
  return reason === CHAT_BLOCKED_REASON_DECISION_PENDING || reason === 'intervention_pending'
}

/**
 * Structured optimizer refusal extracted from any of the shapes above.
 * `code` is the raw discriminator (`optimizer_model_unavailable`,
 * `optimization_unavailable`, `out_of_scope`, …) when present.
 */
export interface OptimizerRefusal {
  code: string | null
  reason_code: string | null
  reason: string | null
}

function readOptimizerRefusalBody(body: unknown): OptimizerRefusal | null {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return null
  const obj = body as Record<string, unknown>
  const reasonCode = typeof obj.reason_code === 'string' && obj.reason_code ? obj.reason_code : null
  const reason = typeof obj.reason === 'string' && obj.reason ? obj.reason : null
  const code =
    (typeof obj.error === 'string' && obj.error) ||
    (typeof obj.code === 'string' && obj.code) ||
    (obj.status === 'refused' ? 'refused' : null)
  if (!code && !reasonCode && !reason) return null
  return { code, reason_code: reasonCode, reason }
}

/**
 * Extracts an optimizer refusal from a failed request body or a raw payload.
 *
 * Accepts an axios error (`response.data.detail` / `response.data`), a plain
 * detail object, or a WS `chat_error` / `chat_blocked` payload (mapped by the
 * caller into `{code, message}`). Returns null when nothing optimizer-shaped is
 * present so the Dialog Error Handling Standard fallback stays in charge.
 */
export function extractOptimizerRefusal(error: unknown): OptimizerRefusal | null {
  if (!error || typeof error !== 'object') return null
  const data = (error as { response?: { data?: unknown } })?.response?.data
  if (!data || typeof data !== 'object') {
    // A bare detail / refusal payload (no axios envelope).
    return readOptimizerRefusalBody(error)
  }
  const detail = (data as { detail?: unknown }).detail
  return readOptimizerRefusalBody(detail) ?? readOptimizerRefusalBody(data)
}

/**
 * Extracts a human-readable error message from an unknown error value.
 *
 * Priority:
 * 1. Axios error response body: `error.response.data.detail` (FastAPI standard error body)
 * 2. Generic Error object: `error.message`
 * 3. Provided `fallback` string
 */
export function extractErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object') {
    const axiosDetail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    if (typeof axiosDetail === 'string' && axiosDetail) return axiosDetail
    if (typeof axiosDetail === 'object' && axiosDetail) {
      const obj = axiosDetail as Record<string, unknown>
      if (typeof obj.summary === 'string' && obj.summary) return obj.summary
      if (typeof obj.error === 'string' && obj.error) return obj.error
      return JSON.stringify(obj)
    }
    const msg = (error as { message?: unknown })?.message
    if (typeof msg === 'string' && msg) return msg
  }
  return fallback
}

/**
 * Extracts structured permission denied details from a 403 error.
 * Returns null if the error is not a structured permission denial.
 */
export function extractPermissionError(error: unknown): PermissionDeniedDetail | null {
  if (error && typeof error === 'object') {
    const responseData = (error as { response?: { data?: unknown } })?.response?.data
    if (responseData && typeof responseData === 'object') {
      const detail = (responseData as { detail?: unknown }).detail
      if (detail && typeof detail === 'object') {
        const permDetail = detail as PermissionDeniedDetail
        if (permDetail.required_permission?.resource_type && permDetail.required_permission?.action) {
          return permDetail
        }
      }
    }
  }
  return null
}
