/**
 * Decision-scope guardrail hooks (FIX-20261014-003000).
 *
 * Feed the reused VendorModelGuardrailPanel / AddGuardrailForm with data
 * from the decision-scoped `/system-one` guardrail endpoints (same
 * `model_guardrail_configurations` table, `config_source='decision_provider'`)
 * instead of the LLM `/agents/guardrails` endpoints.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createDecisionGuardrail,
  deleteDecisionGuardrail,
  getDecisionGuardrailPosture,
  listDecisionGuardrails,
  updateDecisionGuardrail,
  type DecisionGuardrail,
  type DecisionGuardrailCreatePayload,
  type DecisionGuardrailUpdatePayload,
} from '../api/systemOneApi'
import type { ModelUsagePosture } from '../types'

export function useDecisionGuardrails(providerId: string | null) {
  return useQuery<DecisionGuardrail[]>({
    queryKey: ['system-one', 'guardrails', providerId],
    queryFn: () => listDecisionGuardrails(providerId as string),
    enabled: providerId != null,
    refetchInterval: 15000,
  })
}

export function useDecisionGuardrailPosture(providerId: string | null) {
  return useQuery<ModelUsagePosture[]>({
    queryKey: ['system-one', 'guardrails', 'posture', providerId],
    queryFn: () => getDecisionGuardrailPosture(providerId as string, true),
    enabled: providerId != null,
    refetchInterval: 15000,
  })
}

export function useCreateDecisionGuardrail(providerId: string) {
  const queryClient = useQueryClient()
  return useMutation<DecisionGuardrail, unknown, DecisionGuardrailCreatePayload>({
    mutationFn: (payload) => createDecisionGuardrail(providerId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['system-one', 'guardrails'],
      })
      void queryClient.invalidateQueries({ queryKey: ['system-one', 'models'] })
    },
  })
}

export function useUpdateDecisionGuardrail() {
  const queryClient = useQueryClient()
  return useMutation<
    DecisionGuardrail,
    unknown,
    { guardrailId: string; payload: DecisionGuardrailUpdatePayload }
  >({
    mutationFn: ({ guardrailId, payload }) =>
      updateDecisionGuardrail(guardrailId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['system-one', 'guardrails'],
      })
    },
  })
}

export function useDeleteDecisionGuardrail() {
  const queryClient = useQueryClient()
  return useMutation<void, unknown, string>({
    mutationFn: (guardrailId) => deleteDecisionGuardrail(guardrailId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['system-one', 'guardrails'],
      })
    },
  })
}
