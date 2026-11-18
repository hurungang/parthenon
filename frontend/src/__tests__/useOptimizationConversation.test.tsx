import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: shared.mockGet,
    post: shared.mockPost,
  },
}))

import {
  invalidateOptimizedPlanQueries,
  liveTestCardStateFromStatus,
  liveTestScriptRun,
  liveTestRequestsQueryKey,
  optimizationConversationQueryKey,
  optimizedPlanQueryKey,
  resolveLiveTestCardState,
  useCreateOptimizationConversation,
  useLiveTestRequests,
  useOptimizationConversationDetail,
} from '../hooks/useOptimizationConversation'
import { optimizationGateQueryKey } from '../hooks/useOptimizationGate'
import type { LiveTestApprovalSummary } from '../types'

/**
 * Optimization-conversation data access.
 *
 * Creation goes through the subject-only endpoint (no client-supplied channel
 * or second agent type); the read exposes subject + availability + audit; the
 * ledger powers the approval card after a reconnect. Turn completion
 * invalidates the whole agent-type scope so the Optimized Plan tab and the gate
 * refresh without a page reload.
 */

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
}

function wrapperFor(client: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

describe('useOptimizationConversation — query keys', () => {
  it('scopes the conversation, ledger and plan keys by session/agent type', () => {
    expect(optimizationConversationQueryKey('conv-1')).toEqual([
      'conversations',
      'conv-1',
      'optimization',
    ])
    expect(liveTestRequestsQueryKey('conv-1')).toEqual([
      'conversations',
      'conv-1',
      'live-test-requests',
    ])
    expect(optimizedPlanQueryKey('at-1')).toEqual(['agents', 'types', 'at-1', 'optimized-plan'])
    // The plan key is a prefix of the whole agent-type scope, so invalidating
    // that scope refreshes the plan too.
    expect(optimizedPlanQueryKey('at-1').slice(0, 3)).toEqual(['agents', 'types', 'at-1'])
  })
})

describe('invalidateOptimizedPlanQueries (7.5 — plan auto-refresh)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('refetches the optimized plan AND the optimization gate after a terminal turn', async () => {
    const client = makeClient()
    const planFn = vi.fn().mockResolvedValue({ status: 'ready' })
    const gateFn = vi.fn().mockResolvedValue({ can_optimize: true })
    const otherAgentFn = vi.fn().mockResolvedValue({ status: 'ready' })

    await client.prefetchQuery({
      queryKey: optimizedPlanQueryKey('at-1'),
      queryFn: planFn,
    })
    await client.prefetchQuery({
      queryKey: optimizationGateQueryKey('at-1'),
      queryFn: gateFn,
    })
    await client.prefetchQuery({
      queryKey: optimizedPlanQueryKey('at-2'),
      queryFn: otherAgentFn,
    })

    expect(planFn).toHaveBeenCalledTimes(1)
    expect(gateFn).toHaveBeenCalledTimes(1)

    await invalidateOptimizedPlanQueries(client, 'at-1')

    // The subject's plan and gate re-read automatically — no reload.
    expect(planFn).toHaveBeenCalledTimes(2)
    expect(gateFn).toHaveBeenCalledTimes(2)
    // A DIFFERENT subject's cached state is untouched (scope inherent).
    expect(otherAgentFn).toHaveBeenCalledTimes(1)
  })

  it('does nothing without an agent type id', async () => {
    const client = makeClient()
    const planFn = vi.fn().mockResolvedValue({ status: 'ready' })
    await client.prefetchQuery({ queryKey: optimizedPlanQueryKey('at-1'), queryFn: planFn })

    await invalidateOptimizedPlanQueries(client, null)
    await invalidateOptimizedPlanQueries(client, undefined)

    expect(planFn).toHaveBeenCalledTimes(1)
  })
})

describe('useCreateOptimizationConversation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('creates the conversation with the subject agent type only (no channel, no second agent type)', async () => {
    shared.mockPost.mockResolvedValue({
      data: {
        conversation: { id: 'conv-new' },
        subject: { agent_type_id: 'at-1', name: 'Refund Agent' },
        availability: { available: true },
      },
    })
    const client = makeClient()
    const { result } = renderHook(() => useCreateOptimizationConversation('at-1'), {
      wrapper: wrapperFor(client),
    })

    const created = await result.current.mutateAsync()

    expect(shared.mockPost).toHaveBeenCalledWith('/conversations/optimization', {
      agent_type_id: 'at-1',
    })
    expect(created.conversation.id).toBe('conv-new')
  })
})

describe('useOptimizationConversationDetail / useLiveTestRequests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('reads subject, availability and audit for the session', async () => {
    shared.mockGet.mockResolvedValue({
      data: {
        conversation: { id: 'conv-1', channel: 'optimization' },
        subject: {
          agent_type_id: 'at-1',
          name: 'Refund Agent',
          input_type: 'conversation',
          is_conversational: true,
        },
        availability: {
          available: false,
          reason_code: 'no_successful_execution',
          reason: null,
          can_start_work: false,
          plan_present: false,
          optimized_plan_status: null,
          successful_executions: 0,
          optimizer_model: {
            model_id: null,
            effective_model_id: 'gpt-4o',
            source: 'authoring',
            configured: true,
            enabled: true,
            reason_code: null,
          },
        },
        audit: {
          replay_verifications: 2,
          live_operations: 0,
          last_live_at: null,
          replay_only: true,
        },
      },
    })
    const client = makeClient()
    const { result } = renderHook(() => useOptimizationConversationDetail('conv-1'), {
      wrapper: wrapperFor(client),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(shared.mockGet).toHaveBeenCalledWith('/conversations/conv-1/optimization')
    expect(result.current.data?.subject.name).toBe('Refund Agent')
    expect(result.current.data?.audit.replay_only).toBe(true)
    expect(result.current.data?.availability.plan_present).toBe(false)
  })

  it('does not read when the session id is absent (opening starts no work)', async () => {
    const client = makeClient()
    const detail = renderHook(() => useOptimizationConversationDetail(null), {
      wrapper: wrapperFor(client),
    })
    const ledger = renderHook(() => useLiveTestRequests(null), {
      wrapper: wrapperFor(client),
    })

    expect(detail.result.current.fetchStatus).toBe('idle')
    expect(ledger.result.current.fetchStatus).toBe('idle')
    expect(shared.mockGet).not.toHaveBeenCalled()
  })

  it('reads the session ledger', async () => {
    shared.mockGet.mockResolvedValue({
      data: [
        {
          id: 'ltr-1',
          status: 'denied',
          target_agent_type_id: 'at-1',
          requested_operations: [],
          executed_operations: null,
          expires_at: null,
          execution_started_at: null,
          execution_finished_at: null,
          decision: { approval_value: false, operator_user_id: 'user-1', responded_at: null },
          created_at: null,
        },
      ],
    })
    const client = makeClient()
    const { result } = renderHook(() => useLiveTestRequests('conv-1'), {
      wrapper: wrapperFor(client),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(shared.mockGet).toHaveBeenCalledWith('/conversations/conv-1/live-test-requests')
    expect(result.current.data?.[0].status).toBe('denied')
  })
})

describe('live-test card state projection', () => {
  function proposal(overrides: Partial<LiveTestApprovalSummary> = {}): LiveTestApprovalSummary {
    return {
      live_test_request_id: 'ltr-1',
      status: 'pending',
      expires_at: null,
      operations: [],
      executed_operations: null,
      target_agent_type_id: 'at-1',
      ...overrides,
    }
  }

  it('maps every ledger status to a card state (approved reads as running)', () => {
    expect(liveTestCardStateFromStatus('pending')).toBe('pending')
    expect(liveTestCardStateFromStatus('approved')).toBe('running')
    expect(liveTestCardStateFromStatus('executed')).toBe('executed')
    expect(liveTestCardStateFromStatus('failed')).toBe('failed')
    expect(liveTestCardStateFromStatus('denied')).toBe('denied')
    expect(liveTestCardStateFromStatus('expired')).toBe('expired')
    expect(liveTestCardStateFromStatus('cancelled')).toBe('cancelled')
    // Unknown/absent → the safe default (still answerable).
    expect(liveTestCardStateFromStatus(null)).toBe('pending')
    expect(liveTestCardStateFromStatus('nonsense')).toBe('pending')
  })

  it('prefers the result chunk, then local state, then the ledger status', () => {
    expect(
      resolveLiveTestCardState(proposal(), {
        result: {
          type: 'live_test_result',
          live_test_request_id: 'ltr-1',
          live_test_status: 'failed',
          executed_operations: [],
        },
      }),
    ).toBe('failed')

    expect(
      resolveLiveTestCardState(proposal(), {
        result: {
          type: 'live_test_result',
          live_test_request_id: 'ltr-1',
          live_test_status: 'executed',
          executed_operations: [],
        },
      }),
    ).toBe('executed')

    expect(resolveLiveTestCardState(proposal(), { localState: 'running' })).toBe('running')
    expect(resolveLiveTestCardState(proposal({ status: 'denied' }))).toBe('denied')
  })

  it('takes the script run record from the result chunk when present', () => {
    const ledger = proposal({
      executed_operations: [
        {
          kind: 'script_run',
          script_version_id: 'sv-1',
          script_name: 'search-flights',
          script_version_label: 'v2',
          status: 'success',
          result_summary: 'ledger',
          error: null,
          duration_ms: 900,
          tool_calls: [],
          telemetry: {},
        },
      ],
    })
    const result = {
      type: 'live_test_result' as const,
      live_test_request_id: 'ltr-1',
      live_test_status: 'executed' as const,
      executed_operations: [
        {
          kind: 'script_run',
          script_version_id: 'sv-1',
          script_name: 'search-flights',
          script_version_label: 'v3',
          status: 'success',
          result_summary: 'result',
          error: null,
          duration_ms: 1200,
          tool_calls: [],
          telemetry: {},
        },
      ],
    }

    expect(liveTestScriptRun(ledger)?.result_summary).toBe('ledger')
    expect(liveTestScriptRun(ledger, result)?.result_summary).toBe('result')
    expect(liveTestScriptRun(proposal())).toBeNull()
  })
})
