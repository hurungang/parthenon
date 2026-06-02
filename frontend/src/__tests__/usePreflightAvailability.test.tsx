import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

const shared = vi.hoisted(() => ({
  mockPost: vi.fn(),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    post: (...args: unknown[]) => shared.mockPost(...args),
  },
}))

function withQueryClient() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('usePreflightAvailability', () => {
  it('POSTs to /agents/preflight/availability with the model name and returns allowed=true', async () => {
    shared.mockPost.mockResolvedValue({
      data: { allowed: true, reason: null, blocked_by: null },
    })
    const { usePreflightAvailability } = await import('../hooks/usePreflightAvailability')
    const wrapper = withQueryClient()
    const { result } = renderHook(() => usePreflightAvailability(), { wrapper })

    const outcome = await result.current.mutateAsync({ model_name: 'gpt-4.1' })

    expect(shared.mockPost).toHaveBeenCalledWith(
      '/agents/preflight/availability',
      expect.objectContaining({ model_name: 'gpt-4.1' }),
    )
    expect(outcome.allowed).toBe(true)
  })

  it('forwards vendor_config_id when provided', async () => {
    shared.mockPost.mockResolvedValue({
      data: { allowed: true, reason: null, blocked_by: null },
    })
    const { usePreflightAvailability } = await import('../hooks/usePreflightAvailability')
    const wrapper = withQueryClient()
    const { result } = renderHook(() => usePreflightAvailability(), { wrapper })

    await result.current.mutateAsync({
      model_name: 'gpt-4.1',
      vendor_config_id: 'cfg-1',
    })

    expect(shared.mockPost).toHaveBeenCalledWith(
      '/agents/preflight/availability',
      expect.objectContaining({ model_name: 'gpt-4.1', vendor_config_id: 'cfg-1' }),
    )
  })

  it('returns a denial outcome with blocked_by=vendor_cascaded', async () => {
    shared.mockPost.mockResolvedValue({
      data: {
        allowed: false,
        reason: 'Vendor is disabled',
        blocked_by: 'vendor_cascaded',
      },
    })
    const { usePreflightAvailability } = await import('../hooks/usePreflightAvailability')
    const wrapper = withQueryClient()
    const { result } = renderHook(() => usePreflightAvailability(), { wrapper })

    const outcome = await result.current.mutateAsync({ model_name: 'gpt-4.1' })

    expect(outcome.allowed).toBe(false)
    expect(outcome.blocked_by).toBe('vendor_cascaded')
  })

  it('returns a denial outcome with blocked_by=manual', async () => {
    shared.mockPost.mockResolvedValue({
      data: {
        allowed: false,
        reason: 'Model is disabled',
        blocked_by: 'manual',
      },
    })
    const { usePreflightAvailability } = await import('../hooks/usePreflightAvailability')
    const wrapper = withQueryClient()
    const { result } = renderHook(() => usePreflightAvailability(), { wrapper })

    const outcome = await result.current.mutateAsync({ model_name: 'gpt-4.1' })

    expect(outcome.allowed).toBe(false)
    expect(outcome.blocked_by).toBe('manual')
  })

  it('propagates API errors back to the caller', async () => {
    shared.mockPost.mockRejectedValue(new Error('Network error'))
    const { usePreflightAvailability } = await import('../hooks/usePreflightAvailability')
    const wrapper = withQueryClient()
    const { result } = renderHook(() => usePreflightAvailability(), { wrapper })

    await waitFor(async () => {
      await expect(result.current.mutateAsync({ model_name: 'gpt-4.1' })).rejects.toThrow('Network error')
    })
  })
})
