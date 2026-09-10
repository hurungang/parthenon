/**
 * Typed API client functions for API Key Management.
 * All functions use the shared apiClient with centralized base URL.
 */
import apiClient from './apiClient'
import type {
  ApiKey,
  ApiKeyCreateRequest,
  ApiKeyCreateResponse,
  ApiKeyDeleteResponse,
  ApiKeyRevokeResponse,
  IdentityWithRoles,
} from '../types/apiKeys'

export async function fetchApiKeys(status?: string): Promise<ApiKey[]> {
  const params: Record<string, string> = {}
  if (status) params.status = status
  const response = await apiClient.get<ApiKey[]>('/api-keys', { params })
  return response.data
}

export async function createApiKey(
  data: ApiKeyCreateRequest,
): Promise<ApiKeyCreateResponse> {
  const response = await apiClient.post<ApiKeyCreateResponse>('/api-keys', data)
  return response.data
}

export async function revokeApiKey(keyId: string): Promise<ApiKeyRevokeResponse> {
  const response = await apiClient.post<ApiKeyRevokeResponse>(`/api-keys/${keyId}/revoke`)
  return response.data
}

export async function deleteApiKey(keyId: string): Promise<ApiKeyDeleteResponse> {
  const response = await apiClient.delete<ApiKeyDeleteResponse>(`/api-keys/${keyId}`)
  return response.data
}

export async function fetchIdentitiesWithRoles(): Promise<IdentityWithRoles[]> {
  const response = await apiClient.get<IdentityWithRoles[]>('/api-keys/identities-with-roles')
  return response.data
}
