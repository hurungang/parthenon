import { useMutation } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type { PreflightAvailabilityOutcome } from '../types'

export interface PreflightAvailabilityRequest {
  model_name: string
  vendor_config_id?: string
}

export function usePreflightAvailability() {
  return useMutation<PreflightAvailabilityOutcome, unknown, PreflightAvailabilityRequest>({
    mutationFn: async ({ model_name, vendor_config_id }) => {
      const { data } = await apiClient.post<PreflightAvailabilityOutcome>(
        '/agents/preflight/availability',
        { model_name, vendor_config_id },
      )
      return data
    },
  })
}
