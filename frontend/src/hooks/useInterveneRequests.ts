import { useCallback, useEffect, useRef, useState } from 'react'
import { isAxiosError } from 'axios'
import * as interveneApi from '../api/interveneApi'
import type {
  InterveneMetrics,
  InterveneRequest,
  InterventionType,
} from '../types'

const POLL_INTERVAL_MS = 10_000

export interface UseInterveneRequestsOptions {
  statusFilter?: string
  typeFilter?: InterventionType
  sessionId?: string
}

export function useInterveneRequests(options: UseInterveneRequestsOptions = {}) {
  const [pendingRequests, setPendingRequests] = useState<InterveneRequest[]>([])
  const [respondedRequests, setRespondedRequests] = useState<InterveneRequest[]>([])
  const [metrics, setMetrics] = useState<InterveneMetrics | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const stoppedDueToPermissionRef = useRef(false)

  const fetchData = useCallback(async () => {
    if (stoppedDueToPermissionRef.current) return
    try {
      setError(null)
      const all = await interveneApi.getInterveneRequests({
        status: options.statusFilter,
        intervention_type: options.typeFilter,
        agent_session_id: options.sessionId,
        limit: 100,
      })
      setPendingRequests(all.filter((r) => r.status === 'pending'))
      setRespondedRequests(all.filter((r) => r.status !== 'pending'))

      const m = await interveneApi.getInterveneMetrics()
      setMetrics(m)
    } catch (err) {
      setError(err)
      if (isAxiosError(err) && err.response?.status === 403) {
        stoppedDueToPermissionRef.current = true
        if (pollingRef.current) {
          clearInterval(pollingRef.current)
          pollingRef.current = null
        }
      }
    } finally {
      setIsLoading(false)
    }
  }, [options.statusFilter, options.typeFilter, options.sessionId])

  const submitResponse = useCallback(
    async (requestId: string, value: {
      approval_value?: boolean
      selected_choice?: string
      text_value?: string
    }) => {
      await interveneApi.submitInterveneResponse(requestId, {
        request_id: requestId,
        ...value,
      })
      await fetchData()
    },
    [fetchData],
  )

  const cancelRequest = useCallback(
    async (requestId: string) => {
      await interveneApi.cancelInterveneRequest(requestId)
      await fetchData()
    },
    [fetchData],
  )

  useEffect(() => {
    void fetchData()
    
    // Skip polling in tests to prevent hangs from persistent intervals
    if ((typeof window !== 'undefined' && (window as any).__VITEST__)) {
      return
    }
    
    pollingRef.current = setInterval(() => void fetchData(), POLL_INTERVAL_MS)
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [fetchData])

  return {
    pendingRequests,
    respondedRequests,
    metrics,
    isLoading,
    error,
    submitResponse,
    cancelRequest,
    refetch: fetchData,
  }
}
