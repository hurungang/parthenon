/**
 * React Query hook for dashboard operational metrics.
 * Manages date range state and fetches aggregated counts from the backend.
 */
import { useCallback, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getDashboardSummary } from '../api/dashboardApi'
import type { DashboardSummary } from '../types/dashboard'

function defaultStartTime(): string {
  return new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
}

function defaultEndTime(): string {
  return new Date().toISOString()
}

export interface UseDashboardMetricsReturn {
  data: DashboardSummary | undefined
  isLoading: boolean
  isError: boolean
  error: Error | null
  startTime: string
  endTime: string
  setDateRange: (start: string, end: string) => void
  refetch: () => void
}

export function useDashboardMetrics(): UseDashboardMetricsReturn {
  const [startTime, setStartTime] = useState<string>(defaultStartTime)
  const [endTime, setEndTime] = useState<string>(defaultEndTime)

  const queryKey = ['dashboard', 'summary', startTime, endTime] as const

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } = useQuery<any, Error>({
    queryKey,
    queryFn: () => getDashboardSummary(startTime, endTime),
    staleTime: 30_000,
  })

  const setDateRange = useCallback((start: string, end: string) => {
    setStartTime(start)
    setEndTime(end)
  }, [])

  return {
    data: data as DashboardSummary | undefined,
    isLoading,
    isError,
    error,
    startTime,
    endTime,
    setDateRange,
    refetch,
  }
}
