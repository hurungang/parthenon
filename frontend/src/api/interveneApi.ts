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
