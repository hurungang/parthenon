/**
 * Dashboard metrics API client functions.
 */
import apiClient from './apiClient'
import type { DashboardSummary } from '../types/dashboard'

/**
 * Fetch aggregated dashboard metrics with optional date range for time-sensitive cards.
 * The API never returns 403 for individual cards — permission denials are
 * reflected in the `permission_flags` fields.
 */
export async function getDashboardSummary(
  startTime: string,
  endTime: string,
): Promise<DashboardSummary> {
  const { data } = await apiClient.get<DashboardSummary>('/dashboard/summary', {
    params: { start_time: startTime, end_time: endTime },
  })
  return data
}
