import type { QuotaBlockedPayload } from '../types'

/**
 * Extracts the structured quota refusal payload from a failed API call
 * (backend quota contract: HTTP 403 with `detail` = QuotaBlockedPayload,
 * `code: 'quota_exhausted'`).  Returns null when the error is anything
 * else (permission denial, validation, network, …).
 */
export function extractQuotaBlocked(error: unknown): QuotaBlockedPayload | null {
  if (!error || typeof error !== 'object') return null
  const detail = (error as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail
  if (!detail || typeof detail !== 'object') return null
  const candidate = detail as Partial<QuotaBlockedPayload>
  if (candidate.code !== 'quota_exhausted') return null
  if (
    typeof candidate.quota_type !== 'string' ||
    typeof candidate.tier !== 'string' ||
    typeof candidate.limit !== 'number' ||
    typeof candidate.used !== 'number'
  ) {
    return null
  }
  return candidate as QuotaBlockedPayload
}
