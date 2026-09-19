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
