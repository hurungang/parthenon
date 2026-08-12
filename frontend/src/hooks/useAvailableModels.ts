import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type { ModelConfig } from '../types'
import type { AvailableModel } from '../components/agents/AvailableModel'

/**
 * Fetches the flat union of `enabled_models` across all configured model
 * configs. Each entry carries both the model name and the `model_config_id`
 * so callers (e.g. AddGuardrailForm) can post the `(config_id, model_name)`
 * pair to the per-guardrail API.
 */
export function useAvailableModels() {
  return useQuery<AvailableModel[]>({
    queryKey: ['agents', 'model-configs', 'available-models'],
    queryFn: async () => {
      const { data } = await apiClient.get<ModelConfig[]>('/agents/model-configs')
      const models: AvailableModel[] = []
      for (const config of data) {
        for (const modelId of config.enabled_models) {
          models.push({
            model_id: modelId,
            model_name: modelId,
            model_config_id: config.id,
            config_id: config.id,
            config_display_name: config.display_name,
            provider_type: config.provider_type,
          })
        }
      }
      return models
    },
  })
}
