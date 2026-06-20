/**
 * Typed API client functions for the Intervene (human-in-the-loop) module.
 * All functions use the shared apiClient with centralized base URL.
 */
import apiClient from './apiClient'
import type {
  InterveneMetrics,
  InterveneRequest,
  InterveneResponse,
} from '../types'

export interface InterveneRequestFilters {
  status?: string
  intervention_type?: string
  agent_session_id?: string
  conversation_session_id?: string
  limit?: number
  offset?: number
}

export interface InterveneResponsePayload {
  request_id: string
  approval_value?: boolean
  selected_choice?: string
  text_value?: string
}

export async function getInterveneRequests(
  filters?: InterveneRequestFilters,
): Promise<InterveneRequest[]> {
  const response = await apiClient.get<InterveneRequest[]>('/intervene/requests', {
    params: filters,
  })
  return response.data
}

export async function getInterveneRequest(id: string): Promise<InterveneRequest> {
  const response = await apiClient.get<InterveneRequest>(`/intervene/requests/${id}`)
  return response.data
}

export async function submitInterveneResponse(
  requestId: string,
  response: InterveneResponsePayload,
): Promise<InterveneResponse> {
  const result = await apiClient.post<InterveneResponse>(
    `/intervene/requests/${requestId}/respond`,
    response,
  )
  return result.data
}

export async function cancelInterveneRequest(requestId: string): Promise<InterveneRequest> {
  const result = await apiClient.post<InterveneRequest>(
    `/intervene/requests/${requestId}/cancel`,
  )
  return result.data
}

export async function getInterveneMetrics(): Promise<InterveneMetrics> {
  const response = await apiClient.get<InterveneMetrics>('/intervene/metrics')
  return response.data
}

/**
 * Terminate an agent session via the Runtime Control termination endpoint.
 * Triggers a cascade shutdown of the session and any sub-agents.
 */
export async function terminateSession(
  sessionId: string,
  reason?: string,
): Promise<void> {
  await apiClient.post('/agents/runtime/terminate', {
    target_session_id: sessionId,
    termination_scope: 'cascade_subtree',
    operator_reason: reason ?? 'Operator terminated via intervention dialog',
  })
}

/**
 * Fetch the currently pending intervention request for a given agent session (parent agent job).
 * This queries the dedicated endpoint for non-conversational delegation context.
 * Falls back to the generic filter-based approach if the new endpoint is not available (404).
 */
export async function getPendingInterventionForSession(sessionId: string): Promise<InterveneRequest | null> {
  try {
    const response = await apiClient.get<InterveneRequest>(`/agent-jobs/${sessionId}/interventions/pending`)
    return response.data
  } catch {
    // Fall back to the existing filter-based approach
    try {
      const requests = await getInterveneRequests({
        agent_session_id: sessionId,
        status: 'pending',
      })
      return requests.length > 0 ? requests[0] : null
    } catch {
      return null
    }
  }
}
