import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import type { TFunction } from 'i18next'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: shared.mockGet,
  },
}))

import {
  GATE_REASON_AUTHORING_MODEL_NOT_CONFIGURED,
  GATE_REASON_AUTHORING_MODEL_NOT_ENABLED,
  GATE_REASON_CONVERSATIONAL_AGENT,
  GATE_REASON_NO_SUCCESSFUL_EXECUTION,
  GATE_REASON_OPTIMIZER_MODEL_NOT_CONFIGURED,
  GATE_REASON_OPTIMIZER_MODEL_NOT_ENABLED,
  isAuthoringModelReasonCode,
  localizeOptimizationConversationReason,
  localizeOptimizerModelReason,
  optimizationGateQueryKey,
  useOptimizationGate,
} from '../hooks/useOptimizationGate'

/**
 * Extended optimization gate (typed AND conversational entry).
 *
 * The gate now carries the optimizer-model state and the
 * optimization-CONVERSATION availability alongside the unchanged one-shot
 * `can_optimize` precondition. Every reason must localize through one shared
 * vocabulary so the Optimized Plan entry, the chat model alert and System Config
 * all read the SAME sentence for the SAME condition.
 */

/** Key-echo translator that records the key + params it was asked for. */
function makeT() {
  const calls: Array<{ key: string; params?: Record<string, unknown> }> = []
  const t = vi.fn(((key: string, params?: Record<string, unknown>) => {
    calls.push({ key, params })
    return key
  }) as unknown as TFunction)
  return { t, calls }
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
}

function wrapperFor(client: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

describe('useOptimizationGate — extended payload', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('reads the gate from the dedicated endpoint and exposes the additive fields', async () => {
    shared.mockGet.mockResolvedValue({
      data: {
        can_optimize: false,
        successful_executions: 0,
        reason: null,
        reason_code: GATE_REASON_NO_SUCCESSFUL_EXECUTION,
        is_conversational: true,
        can_generate_plan: false,
        optimization_conversation_available: true,
        optimization_conversation_reason_code: null,
        optimizer_model_configured: true,
        optimizer_model_id: 'gpt-4o',
        optimizer_model_source: 'authoring',
        optimizer_model_reason_code: null,
      },
    })
    const client = makeClient()
    const { result } = renderHook(() => useOptimizationGate('at-1'), {
      wrapper: wrapperFor(client),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(shared.mockGet).toHaveBeenCalledWith('/agents/types/at-1/optimization-gate')
    expect(optimizationGateQueryKey('at-1')).toEqual([
      'agents',
      'types',
      'at-1',
      'optimization-gate',
    ])
    // A conversational agent is NOT optimizable one-shot, but the
    // optimization CONVERSATION is available with the same safety rules.
    expect(result.current.data?.can_optimize).toBe(false)
    expect(result.current.data?.is_conversational).toBe(true)
    expect(result.current.data?.optimization_conversation_available).toBe(true)
    expect(result.current.data?.optimizer_model_source).toBe('authoring')
  })

  it('does not read without an agent type id', () => {
    const client = makeClient()
    const { result } = renderHook(() => useOptimizationGate(null), {
      wrapper: wrapperFor(client),
    })

    expect(result.current.fetchStatus).toBe('idle')
    expect(shared.mockGet).not.toHaveBeenCalled()
  })

  it('degrades gracefully when the payload is partial/legacy', async () => {
    shared.mockGet.mockResolvedValue({
      data: { can_optimize: false, successful_executions: 0, reason: 'Legacy reason.' },
    })
    const client = makeClient()
    const { result } = renderHook(() => useOptimizationGate('at-1'), {
      wrapper: wrapperFor(client),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    // Optional fields absent: callers must fall back to reason-only behaviour
    // (the entry stays open and the backend re-checks at request time).
    expect(result.current.data?.optimization_conversation_available).toBeUndefined()
    expect(result.current.data?.reason_code).toBeUndefined()
    expect(result.current.data?.reason).toBe('Legacy reason.')
  })
})

describe('localizeOptimizerModelReason', () => {
  it('maps each optimizer-model reason code to its shared copy', () => {
    const { t, calls } = makeT()

    expect(localizeOptimizerModelReason(t, GATE_REASON_OPTIMIZER_MODEL_NOT_CONFIGURED, 'raw')).toBe(
      'agents.optimizer.modelReasons.optimizer_model_not_configured',
    )
    expect(localizeOptimizerModelReason(t, GATE_REASON_OPTIMIZER_MODEL_NOT_ENABLED, 'raw')).toBe(
      'agents.optimizer.modelReasons.optimizer_model_not_enabled',
    )
    expect(calls.map((call) => call.key)).toEqual([
      'agents.optimizer.modelReasons.optimizer_model_not_configured',
      'agents.optimizer.modelReasons.optimizer_model_not_enabled',
    ])
  })

  it('falls back to the backend sentence for a non-optimizer reason', () => {
    const { t } = makeT()

    expect(
      localizeOptimizerModelReason(t, GATE_REASON_NO_SUCCESSFUL_EXECUTION, 'Needs a run.'),
    ).toBe('Needs a run.')
    expect(localizeOptimizerModelReason(t, null, 'Needs a run.')).toBe('Needs a run.')
    expect(localizeOptimizerModelReason(t, null, null)).toBeNull()
  })
})

describe('localizeOptimizationConversationReason', () => {
  it('never reports conversational_agent — the conversation works for both topologies', () => {
    const { t, calls } = makeT()

    // Even if a legacy backend sends it, the CONVERSATION entry does not show
    // conversational_agent as a reason (the one-shot gate still can).
    const out = localizeOptimizationConversationReason(t, GATE_REASON_CONVERSATIONAL_AGENT, null)
    expect(out).not.toBe('agents.optimize.gateReasons.conversational_agent')
    expect(calls.some((call) => call.key.includes('conversational_agent'))).toBe(false)
  })

  it('explains a missing reference execution in conversation language', () => {
    const { t } = makeT()
    expect(localizeOptimizationConversationReason(t, GATE_REASON_NO_SUCCESSFUL_EXECUTION, null)).toBe(
      'agents.optimizer.conversationReasonNoExecution',
    )
  })

  it('uses the shared optimizer-model vocabulary for model reasons', () => {
    const { t } = makeT()
    expect(
      localizeOptimizationConversationReason(t, GATE_REASON_OPTIMIZER_MODEL_NOT_CONFIGURED, null),
    ).toBe('agents.optimizer.modelReasons.optimizer_model_not_configured')
    expect(
      localizeOptimizationConversationReason(t, GATE_REASON_OPTIMIZER_MODEL_NOT_ENABLED, null),
    ).toBe('agents.optimizer.modelReasons.optimizer_model_not_enabled')
  })

  it('falls back to the backend sentence otherwise', () => {
    const { t } = makeT()
    expect(localizeOptimizationConversationReason(t, null, 'Permission denied.')).toBe(
      'Permission denied.',
    )
    expect(localizeOptimizationConversationReason(t, 'permission_denied', 'Denied.')).toBe(
      'Denied.',
    )
  })
})

describe('isAuthoringModelReasonCode', () => {
  it('detects every configuration-change reason (polling cannot fix these)', () => {
    expect(isAuthoringModelReasonCode(GATE_REASON_AUTHORING_MODEL_NOT_CONFIGURED)).toBe(true)
    expect(isAuthoringModelReasonCode(GATE_REASON_AUTHORING_MODEL_NOT_ENABLED)).toBe(true)
    expect(isAuthoringModelReasonCode(GATE_REASON_OPTIMIZER_MODEL_NOT_CONFIGURED)).toBe(true)
    expect(isAuthoringModelReasonCode(GATE_REASON_OPTIMIZER_MODEL_NOT_ENABLED)).toBe(true)
  })

  it('does not treat an execution-count or unknown reason as a configuration change', () => {
    expect(isAuthoringModelReasonCode(GATE_REASON_NO_SUCCESSFUL_EXECUTION)).toBe(false)
    expect(isAuthoringModelReasonCode(GATE_REASON_CONVERSATIONAL_AGENT)).toBe(false)
    expect(isAuthoringModelReasonCode(null)).toBe(false)
    expect(isAuthoringModelReasonCode('something_else')).toBe(false)
  })
})
