import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type { ModelUsageGuardrailLimit, ModelUsagePosture } from '../types'

export function useModelUsageLimits() {
  return useQuery<ModelUsageGuardrailLimit[]>({
    queryKey: ['agents', 'guardrails', 'model-usage-limits'],
    queryFn: async () => {
      const { data } = await apiClient.get<ModelUsageGuardrailLimit[]>(
        '/agents/guardrails/model-usage-limits',
      )
      return data
    },
    refetchInterval: 15000,
  })
}

export function useModelUsagePosture() {
  return useQuery<ModelUsagePosture[]>({
    queryKey: ['agents', 'guardrails', 'model-usage-posture'],
    queryFn: async () => {
      const { data } = await apiClient.get<ModelUsagePosture[]>(
        '/agents/guardrails/model-usage-posture?refresh=true',
      )
      return data
    },
    refetchInterval: 15000,
  })
}
