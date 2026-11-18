import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPut: vi.fn(),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: shared.mockGet,
    put: shared.mockPut,
  },
}))

import {
  OPTIMIZER_MODEL_CONFIG_QUERY_KEY,
  OPTIMIZER_MODEL_INHERIT_VALUE,
  isOptimizerModelBlocked,
  isOptimizerSelectionUnavailable,
  useOptimizerModelConfig,
  useSetOptimizerModel,
} from '../hooks/useOptimizerModelConfig'
import type { OptimizerModelConfig } from '../types'

/**
 * Workspace optimizer-model configuration (System Config data layer).
 *
 * `selected_model_id` echoes the RAW stored value so a stale selection stays
 * visible; `effective_model_id` / `source` describe what optimization would
 * actually use (explicit choice or inherit-from-authoring). Saving with `null`
 * clears back to inherit.
 */

const CONFIG: OptimizerModelConfig = {
  selected_model_id: 'gpt-4o',
  effective_model_id: 'gpt-4o',
  source: 'optimizer',
  configured: true,
  enabled: true,
  reason_code: null,
  options: [
    {
      model_id: 'gpt-4o',
      config_id: 'cfg-1',
      config_display_name: 'OpenAI Prod',
      provider_type: 'openai',
    },
  ],
}

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

describe('useOptimizerModelConfig', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('reads the tenant-scoped optimizer-model endpoint', async () => {
    shared.mockGet.mockResolvedValue({ data: CONFIG })
    const client = makeClient()
    const { result } = renderHook(() => useOptimizerModelConfig(), {
      wrapper: wrapperFor(client),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(shared.mockGet).toHaveBeenCalledWith('/agents/model-configs/optimizer-model')
    expect(result.current.data?.effective_model_id).toBe('gpt-4o')
    expect(OPTIMIZER_MODEL_CONFIG_QUERY_KEY).toEqual([
      'agents',
      'model-configs',
      'optimizer-model',
    ])
  })

  it('does not read when disabled (e.g. the section is not rendered)', () => {
    const client = makeClient()
    const { result } = renderHook(() => useOptimizerModelConfig(false), {
      wrapper: wrapperFor(client),
    })

    expect(result.current.fetchStatus).toBe('idle')
    expect(shared.mockGet).not.toHaveBeenCalled()
  })

  it('saves a selection and a null clear-to-inherit through the same endpoint', async () => {
    shared.mockPut.mockResolvedValue({ data: CONFIG })
    shared.mockGet.mockResolvedValue({ data: CONFIG })
    const client = makeClient()
    const { result } = renderHook(() => useSetOptimizerModel(), {
      wrapper: wrapperFor(client),
    })

    await act(async () => {
      await result.current.mutateAsync({ model_id: 'gpt-4o' })
    })
    expect(shared.mockPut).toHaveBeenCalledWith('/agents/model-configs/optimizer-model', {
      model_id: 'gpt-4o',
    })

    await act(async () => {
      await result.current.mutateAsync({ model_id: null })
    })
    // `null` clears the setting → optimization inherits the authoring model.
    expect(shared.mockPut).toHaveBeenCalledWith('/agents/model-configs/optimizer-model', {
      model_id: null,
    })
  })

  it('surfaces a 422 rejection to the caller (previous selection unchanged)', async () => {
    shared.mockPut.mockRejectedValue({
      response: { status: 422, data: { detail: 'Model is not enabled in this workspace' } },
    })
    const client = makeClient()
    const { result } = renderHook(() => useSetOptimizerModel(), {
      wrapper: wrapperFor(client),
    })

    let caught: unknown = null
    await act(async () => {
      try {
        await result.current.mutateAsync({ model_id: 'not-enabled' })
      } catch (err) {
        caught = err
      }
    })

    expect(caught).not.toBeNull()
  })
})

describe('optimizer config helpers', () => {
  it('exposes an explicit inherit sentinel that cannot collide with a model id', () => {
    expect(OPTIMIZER_MODEL_INHERIT_VALUE).toBe('__inherit__')
    expect(CONFIG.options.some((o) => o.model_id === OPTIMIZER_MODEL_INHERIT_VALUE)).toBe(false)
  })

  it('flags a stored value that is no longer in this workspace catalogue', () => {
    expect(
      isOptimizerSelectionUnavailable({ ...CONFIG, selected_model_id: 'retired-model' }),
    ).toBe(true)
    // Unset / inherit is never "unavailable".
    expect(isOptimizerSelectionUnavailable({ ...CONFIG, selected_model_id: null })).toBe(false)
    // A stored value present in the catalogue is fine.
    expect(isOptimizerSelectionUnavailable(CONFIG)).toBe(false)
    expect(isOptimizerSelectionUnavailable(null)).toBe(false)
  })

  it('reports "blocked" when disabled or carrying an optimizer-model reason code', () => {
    expect(isOptimizerModelBlocked(CONFIG)).toBe(false)
    expect(isOptimizerModelBlocked({ ...CONFIG, enabled: false })).toBe(true)
    expect(
      isOptimizerModelBlocked({ ...CONFIG, reason_code: 'optimizer_model_not_configured' }),
    ).toBe(true)
    expect(
      isOptimizerModelBlocked({ ...CONFIG, reason_code: 'optimizer_model_not_enabled' }),
    ).toBe(true)
    // An authoring-model reason is not an optimizer-model reason: the
    // availability projection reports the optimizer reason, not the raw
    // authoring cause.
    expect(
      isOptimizerModelBlocked({ ...CONFIG, reason_code: 'authoring_model_not_enabled' }),
    ).toBe(false)
    expect(isOptimizerModelBlocked(null)).toBe(false)
  })
})
