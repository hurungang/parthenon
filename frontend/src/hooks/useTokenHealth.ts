/**
 * React Query hook for dashboard token health (expired / expiring tokens).
 * Fetched per page load — no global store (consistent with the dashboard
 * metrics data-fetching pattern).
 */
import { useQuery } from '@tanstack/react-query'
import { getTokenHealth } from '../api/tokenHealthApi'
import type { TokenHealthSummary } from '../types/tokenHealth'

export function useTokenHealth(): {
  data: TokenHealthSummary | undefined
  isLoading: boolean
  isError: boolean
} {
  const query = useQuery<TokenHealthSummary, Error>({
    queryKey: ['dashboard', 'token-health'],
    queryFn: getTokenHealth,
  })
  return {
    data: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
  }
}
