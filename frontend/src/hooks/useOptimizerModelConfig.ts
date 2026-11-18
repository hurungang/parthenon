import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type { OptimizerModelConfig, OptimizerModelConfigUpdate } from '../types'
import { isOptimizerModelReasonCode } from '../utils/errorUtils'

/** Shared query key — invalidate after a save to re-read the derived state. */
export const OPTIMIZER_MODEL_CONFIG_QUERY_KEY = [
  'agents',
  'model-configs',
  'optimizer-model',
] as const

/** Value used by the Select for "inherit the plan authoring model". */
export const OPTIMIZER_MODEL_INHERIT_VALUE = '__inherit__'

/**
 * Reads the workspace optimizer-model configuration
 * (`GET /agents/model-configs/optimizer-model`).
 *
 * Options come only from the session tenant's enabled, non-disabled catalogue;
 * `selected_model_id` echoes the RAW stored value (a stale id stays visible)
 * while `effective_model_id` / `source` describe what optimization would use.
 */
export function useOptimizerModelConfig(enabled = true) {
  return useQuery<OptimizerModelConfig>({
    queryKey: OPTIMIZER_MODEL_CONFIG_QUERY_KEY,
    queryFn: async () => {
      const { data } = await apiClient.get<OptimizerModelConfig>(
        '/agents/model-configs/optimizer-model',
      )
      return data
    },
    enabled,
    staleTime: 30_000,
    retry: false,
  })
}

/**
 * Saves the workspace optimizer model (`PUT /agents/model-configs/optimizer-model`).
 * `null` clears the selection → optimization inherits the plan-authoring model.
 * The backend answers `422` for a model that is not enabled here.
 */
export function useSetOptimizerModel() {
  const queryClient = useQueryClient()
  return useMutation<OptimizerModelConfig, unknown, OptimizerModelConfigUpdate>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.put<OptimizerModelConfig>(
        '/agents/model-configs/optimizer-model',
        payload,
      )
      return data
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: OPTIMIZER_MODEL_CONFIG_QUERY_KEY })
    },
  })
}

/**
 * A saved optimizer model that is no longer in this workspace's catalogue.
 * The Select keeps showing the stale id (disabled) and Save stays blocked until
 * the operator re-selects — the state is never auto-cleared.
 */
export function isOptimizerSelectionUnavailable(
  config: OptimizerModelConfig | null | undefined,
): boolean {
  if (!config) return false
  const selected = config.selected_model_id
  if (!selected) return false
  return !config.options.some((option) => option.model_id === selected)
}

/**
 * True when no optimization work can start because no usable optimizer model
 * exists: nothing resolvable at all, or a stale/disabled explicit selection.
 */
export function isOptimizerModelBlocked(
  config: OptimizerModelConfig | null | undefined,
): boolean {
  if (!config) return false
  return config.enabled === false || isOptimizerModelReasonCode(config.reason_code)
}
