import { useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type {
  ModelGuardrailEnforcementPosture,
  ModelGuardrailPeriod,
  ModelUsageGuardrailLimit,
  ModelUsageUnit,
} from '../types'

export interface ModelUsageGuardrailCreatePayload {
  model_id: string
  model_name: string
  model_config_id?: string
  period: ModelGuardrailPeriod
  limit_value: number
  unit: ModelUsageUnit
  enforcement_posture: ModelGuardrailEnforcementPosture
  is_active: boolean
}

export interface ModelUsageGuardrailUpdatePayload {
  limit_value?: number
  unit?: ModelUsageUnit
  enforcement_posture?: ModelGuardrailEnforcementPosture
  is_active?: boolean
}

export function useCreateModelUsageLimit() {
  const queryClient = useQueryClient()
  return useMutation<ModelUsageGuardrailLimit, unknown, ModelUsageGuardrailCreatePayload>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post<ModelUsageGuardrailLimit>(
        '/agents/guardrails/model-usage-limits',
        payload,
      )
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents', 'guardrails', 'model-usage-limits'] })
      queryClient.invalidateQueries({ queryKey: ['agents', 'guardrails', 'model-usage-posture'] })
      queryClient.invalidateQueries({ queryKey: ['agents', 'model-availability'] })
    },
  })
}

export function useUpdateModelUsageLimit() {
  const queryClient = useQueryClient()
  return useMutation<ModelUsageGuardrailLimit, unknown, { limitId: string; payload: ModelUsageGuardrailUpdatePayload }>({
    mutationFn: async ({ limitId, payload }) => {
      const { data } = await apiClient.put<ModelUsageGuardrailLimit>(
        `/agents/guardrails/model-usage-limits/${limitId}`,
        payload,
      )
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents', 'guardrails', 'model-usage-limits'] })
      queryClient.invalidateQueries({ queryKey: ['agents', 'guardrails', 'model-usage-posture'] })
      queryClient.invalidateQueries({ queryKey: ['agents', 'model-availability'] })
    },
  })
}

export function useDeleteModelUsageLimit() {
  const queryClient = useQueryClient()
  return useMutation<void, unknown, string>({
    mutationFn: async (limitId) => {
      await apiClient.delete(`/agents/guardrails/model-usage-limits/${limitId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents', 'guardrails', 'model-usage-limits'] })
      queryClient.invalidateQueries({ queryKey: ['agents', 'guardrails', 'model-usage-posture'] })
      queryClient.invalidateQueries({ queryKey: ['agents', 'model-availability'] })
    },
  })
}
