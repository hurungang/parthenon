import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type { AgentType, AgentInstance } from '../types'

const AGENT_TYPES_KEY = ['agents', 'types']

export function useAgentTypes(limit?: number, offset?: number) {
  const params: Record<string, number> = {}
  if (limit !== undefined) params.limit = limit
  if (offset !== undefined) params.offset = offset
  const hasPagination = limit !== undefined && offset !== undefined
  return useQuery<AgentType[]>({
    queryKey: hasPagination ? [...AGENT_TYPES_KEY, { limit, offset }] : AGENT_TYPES_KEY,
    queryFn: async () => {
      const { data } = await apiClient.get<AgentType[]>('/agents/types', { params })
      return data
    },
  })
}

export function useAgentType(typeId: string) {
  return useQuery<AgentType>({
    queryKey: ['agents', 'types', typeId],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentType>(`/agents/types/${typeId}`)
      return data
    },
    enabled: !!typeId,
  })
}

export function useAgentInstances(typeId: string) {
  return useQuery<AgentInstance[]>({
    queryKey: ['agents', 'types', typeId, 'instances'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentInstance[]>(`/agents/types/${typeId}/instances`)
      return data
    },
    enabled: !!typeId,
    refetchInterval: 10_000, // Poll every 10s for live status
  })
}

export function useTerminateInstance() {
  const queryClient = useQueryClient()
  return useMutation<void, Error, string>({
    mutationFn: async (instanceId) => {
      await apiClient.delete(`/agents/instances/${instanceId}`)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['agents', 'types'] })
    },
  })
}

export function useDeleteAgentType() {
  const queryClient = useQueryClient()
  return useMutation<void, Error, string>({
    mutationFn: async (typeId) => {
      await apiClient.delete(`/agents/types/${typeId}`)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['agents', 'types'] })
    },
  })
}
