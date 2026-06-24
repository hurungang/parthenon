import { useCallback, useState } from 'react'
import apiClient from '../api/apiClient'
import type { AgentOutputResponse, AgentJob } from '../types'

/**
 * Hook to manage typed output fetching lifecycle.
 * 
 * Extracts output_id from a session object and automatically fetches the corresponding typed output.
 * 
 * Usage:
 * ```tsx
 * const { outputId, typedOutput, outputLoading } = useTypedOutput(session)
 * ```
 */
export function useTypedOutput(_session: AgentJob | null) {
  const [outputId, setOutputId] = useState<string | undefined>(undefined)
  const [typedOutput, setTypedOutput] = useState<AgentOutputResponse | null>(null)
  const [outputLoading, setOutputLoading] = useState(false)

  // Extract output_id from session and update state
  const extractAndSetOutputId = useCallback(
    (sess: AgentJob | null) => {
      if (sess?.output_id) {
        setOutputId(sess.output_id)
      }
    },
    [],
  )

  // Fetch typed output from backend
  const fetchTypedOutput = useCallback(async (id: string) => {
    try {
      setOutputLoading(true)
      const { data } = await apiClient.get<AgentOutputResponse>(`/agent-outputs/${id}`)
      setTypedOutput(data)
    } catch {
      // Silently fail if typed output isn't available
    } finally {
      setOutputLoading(false)
    }
  }, [])

  // Reset state
  const reset = useCallback(() => {
    setOutputId(undefined)
    setTypedOutput(null)
    setOutputLoading(false)
  }, [])

  return {
    outputId,
    typedOutput,
    outputLoading,
    extractAndSetOutputId,
    fetchTypedOutput,
    reset,
  }
}
