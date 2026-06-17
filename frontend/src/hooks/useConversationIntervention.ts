import { useCallback, useEffect, useState } from 'react'
import apiClient from '../api/apiClient'
import { useDialogErrorHandler } from './useDialogErrorHandler'
import type { InterveneRequest } from '../types'

/**
 * Manages intervention lifecycle state for a conversation session.
 *
 * Provides:
 * - Fetching pending interventions on mount (reconnect handling)
 * - Response submission via WebSocket (primary) with REST fallback
 * - Cancellation function
 * - Error handling using the standard useDialogErrorHandler pattern
 */
export function useConversationIntervention(
  sessionId: string | null,
  sendInterventionResponse?: (
    requestId: string,
    value: { approval_value?: boolean; selected_choice?: string; text_value?: string },
  ) => boolean,
  cancelIntervention?: (requestId: string) => boolean,
) {
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
  const [pendingInterventions, setPendingInterventions] = useState<InterveneRequest[]>([])
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Fetch pending interventions on mount (reconnect scenario)
  const fetchPending = useCallback(async () => {
    if (!sessionId) return
    try {
      const { data } = await apiClient.get<InterveneRequest[]>(
        `/conversations/${sessionId}/interventions/pending`,
      )
      setPendingInterventions(data ?? [])
    } catch {
      // Silently handle — the WebSocket path is primary
    }
  }, [sessionId])

  useEffect(() => {
    if (sessionId) {
      void fetchPending()
    }
  }, [sessionId, fetchPending])

  // Respond to an intervention request
  const respondToIntervention = useCallback(
    async (
      requestId: string,
      value: {
        approval_value?: boolean
        selected_choice?: string
        text_value?: string
      },
    ) => {
      clearDialogError()
      setIsSubmitting(true)
      try {
        // Try WebSocket first
        const wsSent = sendInterventionResponse?.(requestId, value)
        if (!wsSent) {
          // REST fallback
          await apiClient.post(
            `/conversations/${sessionId}/interventions/${requestId}/respond`,
            {
              request_id: requestId,
              ...value,
            },
          )
        }
        // Remove from pending list
        setPendingInterventions((prev) =>
          prev.filter((r) => r.id !== requestId),
        )
      } catch (err) {
        setDialogError(err)
      } finally {
        setIsSubmitting(false)
      }
    },
    [sessionId, sendInterventionResponse, clearDialogError, setDialogError],
  )

  // Cancel an intervention request
  const handleCancelIntervention = useCallback(
    async (requestId: string) => {
      clearDialogError()
      setIsSubmitting(true)
      try {
        const wsSent = cancelIntervention?.(requestId)
        if (!wsSent) {
          // REST fallback
          await apiClient.post(`/intervene/requests/${requestId}/cancel`)
        }
        setPendingInterventions((prev) =>
          prev.filter((r) => r.id !== requestId),
        )
      } catch (err) {
        setDialogError(err)
      } finally {
        setIsSubmitting(false)
      }
    },
    [sessionId, cancelIntervention, clearDialogError, setDialogError],
  )

  // Determine the current intervention from the pending list
  const currentIntervention: InterveneRequest | null =
    pendingInterventions.length > 0 ? pendingInterventions[0] : null

  return {
    pendingInterventions,
    currentIntervention,
    isSubmitting,
    dialogError,
    setDialogError,
    clearDialogError,
    respondToIntervention,
    cancelIntervention: handleCancelIntervention,
    fetchPending,
  }
}
