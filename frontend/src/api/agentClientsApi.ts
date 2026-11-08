/**
 * Typed API client functions for third-party agent-integration clients.
 */
import apiClient from './apiClient'
import type {
  AgentClient,
  AgentClientCreateRequest,
  AgentClientCredentialResponse,
  AgentClientRateLimitWindow,
} from '../types/agentClients'

export interface AgentTypeOption {
  id: string
  name: string
}

export interface AgentClientUpdateRequest {
  allowed_origins?: string[] | null
  rate_limit?: number | null
  rate_limit_window?: AgentClientRateLimitWindow | null
}

export async function fetchAgentClients(agentTypeId?: string): Promise<AgentClient[]> {
  const params: Record<string, string> = {}
  if (agentTypeId) params.agent_type_id = agentTypeId
  const response = await apiClient.get<AgentClient[]>('/clients', { params })
  return response.data
}

export async function fetchAgentTypeOptions(): Promise<AgentTypeOption[]> {
  const response = await apiClient.get<Array<{ id: string; name: string }>>('/agents/types')
  return response.data.map((t) => ({ id: t.id, name: t.name }))
}

export async function createAgentClient(
  data: AgentClientCreateRequest,
): Promise<AgentClientCredentialResponse> {
  const response = await apiClient.post<AgentClientCredentialResponse>('/clients', data)
  return response.data
}

export async function updateAgentClientStatus(
  clientId: string,
  status: 'active' | 'inactive',
): Promise<AgentClient> {
  const response = await apiClient.patch<AgentClient>(`/clients/${clientId}/status`, { status })
  return response.data
}

export async function updateAgentClient(
  clientId: string,
  data: AgentClientUpdateRequest,
): Promise<AgentClient> {
  const response = await apiClient.patch<AgentClient>(`/clients/${clientId}`, data)
  return response.data
}

export async function revokeAgentClient(
  clientId: string,
): Promise<{ id: string; status: string; message: string }> {
  const response = await apiClient.delete(`/clients/${clientId}`)
  return response.data
}

export async function deleteAgentClient(
  clientId: string,
): Promise<{ id: string; status: string; message: string }> {
  const response = await apiClient.delete(`/clients/${clientId}`)
  return response.data
}

export async function rotateAgentClientCredential(
  clientId: string,
): Promise<AgentClientCredentialResponse> {
  const response = await apiClient.post<AgentClientCredentialResponse>(
    `/clients/${clientId}/credential`,
  )
  return response.data
}
