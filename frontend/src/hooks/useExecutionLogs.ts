import { useEffect, useState } from 'react'
import apiClient from '../api/apiClient'
import type { ExecutionLogRead } from '../types'

/**
 * Fetches the system instruction and user prompt captured before the first LLM
 * call for a given agent session.
 *
 * Returns an empty array when `sessionId` is null or while the request is in
 * flight.  On error, the hook returns an empty array and exposes the error.
 */
export function useExecutionLogs(sessionId: string | null): {
  logs: ExecutionLogRead[]
  loading: boolean
  error: unknown
} {
  const [logs, setLogs] = useState<ExecutionLogRead[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (!sessionId) {
      setLogs([])
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)

    apiClient
      .get<ExecutionLogRead[]>(`/agents/sessions/${sessionId}/execution-logs`)
      .then(({ data }) => {
        if (!cancelled) {
          setLogs(data)
          setLoading(false)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err)
          setLogs([])
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [sessionId])

  return { logs, loading, error }
}
