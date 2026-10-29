/**
 * Token health API client functions (token-expiry-alerting).
 */
import apiClient from './apiClient'
import type { TokenHealthSummary } from '../types/tokenHealth'

/**
 * Fetch expired / expiring token counts and itemized details per category
 * (agent identities, MCP sessions). Categories the caller cannot read are
 * flagged in `permission_flags` — the API never returns 403 per category.
 */
export async function getTokenHealth(): Promise<TokenHealthSummary> {
  const { data } = await apiClient.get<TokenHealthSummary>('/dashboard/token-health')
  return data
}
