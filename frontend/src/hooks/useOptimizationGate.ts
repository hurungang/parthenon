import { useQuery } from '@tanstack/react-query'
import type { TFunction } from 'i18next'
import apiClient from '../api/apiClient'
import type { OptimizerModelSource } from '../types'
import { isOptimizerModelReasonCode } from '../utils/errorUtils'

/**
 * Composed plan/optimize preconditions for an agent type.
 * Mirrors `OptimizationGateRead` (Control Center). The extended fields are
 * additive on the backend; they are optional here so an older/partial payload
 * degrades to the reason-only behaviour instead of blocking the UI.
 */
export interface OptimizationGate {
  can_optimize: boolean
  successful_executions: number
  reason: string | null
  /** Base-plan generation precondition (authoring model + non-conversational). */
  can_generate_plan?: boolean
  /** Derived "configured / re-select" state of the workspace authoring model. */
  workflow_model_configured?: boolean
  /** Raw stored authoring model id (echoed even when it is no longer enabled). */
  workflow_model_id?: string | null
  /** Agent types with `input_type === 'conversation'` have no plan at all. */
  is_conversational?: boolean
  /** First unmet precondition (conversational → model → executions). */
  reason_code?: string | null
  /**
   * Optimization-CONVERSATION entry: available for typed AND conversational
   * subjects. Independent of the one-shot `can_optimize` precondition.
   */
  optimization_conversation_available?: boolean
  optimization_conversation_reason_code?: string | null
  /** Derived optimizer-model state (explicit workspace choice or authoring inherit). */
  optimizer_model_configured?: boolean
  optimizer_model_id?: string | null
  optimizer_model_source?: OptimizerModelSource | null
  optimizer_model_reason_code?: string | null
}

/** Gate `reason_code` values shared with the backend copy. */
export const GATE_REASON_CONVERSATIONAL_AGENT = 'conversational_agent'
export const GATE_REASON_AUTHORING_MODEL_NOT_CONFIGURED = 'authoring_model_not_configured'
export const GATE_REASON_AUTHORING_MODEL_NOT_ENABLED = 'authoring_model_not_enabled'
export const GATE_REASON_NO_SUCCESSFUL_EXECUTION = 'no_successful_execution'
/** Optimizer-model reasons (availability / conversation entry / chat alert). */
export const GATE_REASON_OPTIMIZER_MODEL_NOT_CONFIGURED = 'optimizer_model_not_configured'
export const GATE_REASON_OPTIMIZER_MODEL_NOT_ENABLED = 'optimizer_model_not_enabled'

const LOCALIZED_GATE_REASON_CODES: readonly string[] = [
  GATE_REASON_CONVERSATIONAL_AGENT,
  GATE_REASON_AUTHORING_MODEL_NOT_CONFIGURED,
  GATE_REASON_AUTHORING_MODEL_NOT_ENABLED,
  GATE_REASON_NO_SUCCESSFUL_EXECUTION,
]

/** True when the reason code requires a System Config change (no polling helps). */
export function isAuthoringModelReasonCode(reasonCode: string | null | undefined): boolean {
  return (
    reasonCode === GATE_REASON_AUTHORING_MODEL_NOT_CONFIGURED ||
    reasonCode === GATE_REASON_AUTHORING_MODEL_NOT_ENABLED ||
    isOptimizerModelReasonCode(reasonCode)
  )
}

/**
 * Localized optimizer-model explanation (unset / stale selection).
 *
 * Kept separate from the gate copy so the Optimized Plan entry, the chat model
 * alert and System Config all read the SAME sentence for the SAME condition.
 */
export function localizeOptimizerModelReason(
  t: TFunction,
  reasonCode: string | null | undefined,
  reason: string | null | undefined,
): string | null {
  if (reasonCode && isOptimizerModelReasonCode(reasonCode)) {
    return t(`agents.optimizer.modelReasons.${reasonCode}`)
  }
  return reason ?? null
}


/**
 * Localized explanation of the first unmet gate precondition.
 *
 * Falls back to the backend `reason` string (older payloads carry no
 * `reason_code`), then to the generic unmet copy. Exported so callers (e.g. the
 * Plan Preview tab) can render the same reason inline, not only in a tooltip.
 */
export function localizeOptimizationGateReason(
  t: TFunction,
  reasonCode: string | null | undefined,
  reason: string | null | undefined,
): string | null {
  if (reasonCode && isOptimizerModelReasonCode(reasonCode)) {
    return t(`agents.optimizer.modelReasons.${reasonCode}`)
  }
  if (reasonCode && LOCALIZED_GATE_REASON_CODES.includes(reasonCode)) {
    return t(`agents.optimize.gateReasons.${reasonCode}`)
  }
  return reason ?? null
}

/**
 * Localized explanation of the optimization-CONVERSATION entry state.
 *
 * The conversation entry is available for typed and conversational agents, so
 * `conversational_agent` is never a reason here. Any reason code reduces to the
 * optimizer-model vocabulary (or the backend sentence).
 */
export function localizeOptimizationConversationReason(
  t: TFunction,
  reasonCode: string | null | undefined,
  reason: string | null | undefined,
): string | null {
  if (reasonCode && isOptimizerModelReasonCode(reasonCode)) {
    return t(`agents.optimizer.modelReasons.${reasonCode}`)
  }
  if (reasonCode === GATE_REASON_NO_SUCCESSFUL_EXECUTION) {
    return t('agents.optimizer.conversationReasonNoExecution')
  }
  return reason ?? null
}

/** Shared query key — invalidate this after a run completes to re-gate. */
export function optimizationGateQueryKey(agentTypeId: string | null | undefined) {
  return ['agents', 'types', agentTypeId, 'optimization-gate'] as const
}

/**
 * Reads `GET /agents/types/{id}/optimization-gate`.
 *
 * The gate is refetched on mount and while it is unmet so the action becomes
 * available as soon as a run lands, without a page reload. Polling only makes
 * sense for the execution-count blocker: a conversational agent or an
 * unset/disabled authoring model needs a configuration change instead, so those
 * states refetch on mount/focus only.
 */
export function useOptimizationGate(
  agentTypeId: string | null | undefined,
  enabled = true,
) {
  return useQuery<OptimizationGate>({
    queryKey: optimizationGateQueryKey(agentTypeId),
    queryFn: async () => {
      const { data } = await apiClient.get<OptimizationGate>(
        `/agents/types/${agentTypeId}/optimization-gate`,
      )
      return data
    },
    enabled: enabled && !!agentTypeId,
    retry: false,
    staleTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
    refetchInterval: (query) => {
      const gate = query.state.data
      if (!gate || gate.can_optimize) return false
      // Legacy/partial payloads have no reason_code — keep the gentle poll.
      if (!gate.reason_code) return 30_000
      // Only the execution-count blocker clears by itself.
      return gate.reason_code === GATE_REASON_NO_SUCCESSFUL_EXECUTION ? 30_000 : false
    },
  })
}
