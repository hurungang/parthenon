import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import type {
  LiveTestApprovalSummary,
  LiveTestCardState,
  LiveTestRequest,
  LiveTestResultMessage,
  OptimizationConversation,
  OptimizationConversationDetail,
  ScriptRunRecord,
} from '../types'
import { optimizationGateQueryKey } from './useOptimizationGate'

/** Conversation read (`GET /conversations/{id}/optimization`). */
export function optimizationConversationQueryKey(sessionId: string | null | undefined) {
  return ['conversations', sessionId, 'optimization'] as const
}

/** Ledger read (`GET /conversations/{id}/live-test-requests`). */
export function liveTestRequestsQueryKey(sessionId: string | null | undefined) {
  return ['conversations', sessionId, 'live-test-requests'] as const
}

/** Optimized-plan read for a subject agent type (owned by AgentOptimizedPlanTab). */
export function optimizedPlanQueryKey(agentTypeId: string | null | undefined) {
  return ['agents', 'types', agentTypeId, 'optimized-plan'] as const
}

/**
 * Refreshes everything the Optimized Plan tab and the gate show for a subject.
 *
 * A completed optimization turn may have authored a plan (`ready` /
 * `needs_feedback` / `failed`) and may unlock the gate (execution counts do not
 * change, but model/plan state does) — invalidate the WHOLE agent-type scope so
 * both surfaces re-read without a page reload.
 */
export async function invalidateOptimizedPlanQueries(
  queryClient: QueryClient,
  agentTypeId: string | null | undefined,
): Promise<void> {
  if (!agentTypeId) return
  await queryClient.invalidateQueries({
    queryKey: ['agents', 'types', agentTypeId],
    refetchType: 'all',
  })
  await queryClient.invalidateQueries({ queryKey: optimizationGateQueryKey(agentTypeId) })
  // The agent dialog's Sessions tab and any script views are part of the same
  // scope: a finished optimization creates a run and promotes authored scripts.
  await queryClient.invalidateQueries({ queryKey: ['agents', 'sessions'] })
  await queryClient.invalidateQueries({ queryKey: ['scripts'] })
}

/**
 * Opens an optimization conversation on the subject agent type
 * (`POST /conversations/optimization` with `{agent_type_id}` only).
 *
 * Creation writes one session and starts NO work — availability is computed and
 * returned so the chat can explain what is missing instead of failing to open.
 */
export function useCreateOptimizationConversation(agentTypeId: string) {
  const queryClient = useQueryClient()
  return useMutation<OptimizationConversation, unknown, void>({
    mutationFn: async () => {
      const { data } = await apiClient.post<OptimizationConversation>(
        '/conversations/optimization',
        { agent_type_id: agentTypeId },
      )
      return data
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['conversations', agentTypeId] })
    },
  })
}

/**
 * Subject + availability + replay-vs-live audit for an existing optimization
 * conversation. Used on open, resume and reconnect.
 */
export function useOptimizationConversationDetail(
  sessionId: string | null | undefined,
  enabled = true,
) {
  return useQuery<OptimizationConversationDetail>({
    queryKey: optimizationConversationQueryKey(sessionId),
    queryFn: async () => {
      const { data } = await apiClient.get<OptimizationConversationDetail>(
        `/conversations/${sessionId}/optimization`,
      )
      return data
    },
    enabled: enabled && !!sessionId,
    retry: false,
    staleTime: 0,
    refetchOnMount: 'always',
  })
}

/**
 * The session's live-test ledger, newest first. Powers the approval card
 * reconciliation after a reconnect, the "what ran" review and the audit block.
 */
export function useLiveTestRequests(
  sessionId: string | null | undefined,
  enabled = true,
) {
  return useQuery<LiveTestRequest[]>({
    queryKey: liveTestRequestsQueryKey(sessionId),
    queryFn: async () => {
      const { data } = await apiClient.get<LiveTestRequest[]>(
        `/conversations/${sessionId}/live-test-requests`,
      )
      return data
    },
    enabled: enabled && !!sessionId,
    retry: false,
    staleTime: 0,
  })
}

/** Maps a ledger status onto the approval-card state. */
export function liveTestCardStateFromStatus(status: string | null | undefined): LiveTestCardState {
  switch (status) {
    case 'executed':
      return 'executed'
    case 'failed':
      return 'failed'
    case 'denied':
      return 'denied'
    case 'expired':
      return 'expired'
    case 'cancelled':
      return 'cancelled'
    case 'approved':
      // Approved but not yet reported — the run is in flight.
      return 'running'
    default:
      return 'pending'
  }
}

/** The single status a card should show, preferring local live state. */
export function resolveLiveTestCardState(
  liveTest: LiveTestApprovalSummary,
  options: {
    result?: LiveTestResultMessage | null
    localState?: LiveTestCardState | null
  } = {},
): LiveTestCardState {
  if (options.result) {
    return options.result.live_test_status === 'failed' ? 'failed' : 'executed'
  }
  if (options.localState) return options.localState
  return liveTestCardStateFromStatus(liveTest.status)
}

/**
 * The single script run record of a live test (the script is the unit of
 * execution), preferring the `live_test_result` chunk over the ledger row.
 */
export function liveTestScriptRun(
  liveTest: LiveTestApprovalSummary | null | undefined,
  result?: LiveTestResultMessage | null,
): ScriptRunRecord | null {
  if (result) return result.script_run ?? result.executed_operations?.[0] ?? null
  return liveTest?.executed_operations?.[0] ?? null
}
