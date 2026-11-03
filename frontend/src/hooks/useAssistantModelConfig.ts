import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type { AssistantModelConfig } from '../types'

const ASSISTANT_MODEL_CONFIG_KEY = ['agents', 'model-configs', 'assistant-model']

/**
 * Resolves the tenant's configured assistant model via
 * GET /agents/model-configs/assistant-model. `selected_model_id` is null when
 * the tenant has not chosen a model for the Control Center Assistant yet —
 * callers use that to show setup guidance instead of a runtime error.
 *
 * Pass `enabled: false` to skip the query for non-assistant chat surfaces.
 */
export function useAssistantModelConfig(enabled: boolean) {
  return useQuery<AssistantModelConfig>({
    queryKey: ASSISTANT_MODEL_CONFIG_KEY,
    queryFn: async () => {
      const { data } = await apiClient.get<AssistantModelConfig>(
        '/agents/model-configs/assistant-model',
      )
      return data
    },
    enabled,
    staleTime: 30_000,
  })
}
