/**
 * React Query hook for API Key Management.
 * Fetches API key list with loading/error state and exposes refresh().
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as api from '../api/apiKeysApi'
import type { ApiKeyCreateRequest } from '../types/apiKeys'

export const apiKeyQueryKeys = {
  all: ['api-keys'] as const,
  list: (status?: string) => ['api-keys', 'list', status ?? 'all'] as const,
  identitiesWithRoles: ['api-keys', 'identities-with-roles'] as const,
}

export function useApiKeys(status?: string) {
  return useQuery({
    queryKey: apiKeyQueryKeys.list(status),
    queryFn: () => api.fetchApiKeys(status),
  })
}

export function useCreateApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: ApiKeyCreateRequest) => api.createApiKey(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: apiKeyQueryKeys.all })
    },
  })
}

export function useRevokeApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (keyId: string) => api.revokeApiKey(keyId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: apiKeyQueryKeys.all })
    },
  })
}

export function useIdentitiesWithRoles() {
  return useQuery({
    queryKey: apiKeyQueryKeys.identitiesWithRoles,
    queryFn: () => api.fetchIdentitiesWithRoles(),
    staleTime: 60_000,
  })
}
