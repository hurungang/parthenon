import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type { ModelAvailabilityHierarchy } from '../types'

export function useModelAvailability() {
  return useQuery<ModelAvailabilityHierarchy>({
    queryKey: ['agents', 'model-availability'],
    queryFn: async () => {
      const { data } = await apiClient.get<ModelAvailabilityHierarchy>(
        '/agents/model-availability',
      )
      return data
    },
    refetchInterval: 15000,
  })
}

export interface SetVendorDisabledPayload {
  configId: string
  is_disabled: boolean
  reason?: string
}

export function useSetVendorDisabled() {
  const queryClient = useQueryClient()
  return useMutation<unknown, unknown, SetVendorDisabledPayload>({
    mutationFn: async ({ configId, is_disabled, reason }) => {
      const { data } = await apiClient.put<unknown>(
        `/agents/model-configs/${configId}/disabled`,
        { is_disabled, reason },
      )
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents', 'model-availability'] })
    },
  })
}

export interface SetModelDisabledPayload {
  configId: string
  modelName: string
  is_disabled: boolean
  reason?: string
}

export function useSetModelDisabled() {
  const queryClient = useQueryClient()
  return useMutation<unknown, unknown, SetModelDisabledPayload>({
    mutationFn: async ({ configId, modelName, is_disabled, reason }) => {
      const { data } = await apiClient.put<unknown>(
        `/agents/model-configs/${configId}/models/${encodeURIComponent(modelName)}/disabled`,
        { is_disabled, reason },
      )
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents', 'model-availability'] })
    },
  })
}
