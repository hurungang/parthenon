import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPut: vi.fn(),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: (...args: unknown[]) => shared.mockGet(...args),
    put: (...args: unknown[]) => shared.mockPut(...args),
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

const HIERARCHY = [
  {
    vendor_config_id: 'cfg-1',
    vendor_display_name: 'OpenAI',
    is_disabled: false,
    models: [
      {
        model_name: 'gpt-4.1',
        is_disabled: false,
        disabled_reason: null,
        guardrails: [],
      },
    ],
  },
] as const

beforeEach(() => {
  vi.clearAllMocks()
  shared.mockGet.mockResolvedValue({ data: HIERARCHY })
  shared.mockPut.mockResolvedValue({ data: {} })
})

describe('useModelAvailability', () => {
  it('queries /agents/model-availability and returns the hierarchy', async () => {
    const { useModelAvailability } = await import('../hooks/useModelAvailability')
    const wrapper = withQueryClient()
    const { result } = renderHook(() => useModelAvailability(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(shared.mockGet).toHaveBeenCalledWith('/agents/model-availability')
    expect(result.current.data).toEqual(HIERARCHY)
  })

  it('returns the API payload as-is so the dashboard can call .map() directly', async () => {
    // Regression: the backend previously wrapped the hierarchy as
    // `{ vendors: [...] }` which broke `hierarchy.map(...)` in
    // VendorModelGuardrailPanel. The contract is a flat array.
    const { useModelAvailability } = await import('../hooks/useModelAvailability')
    const wrapper = withQueryClient()
    const { result } = renderHook(() => useModelAvailability(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(Array.isArray(result.current.data)).toBe(true)
    expect(result.current.data).not.toHaveProperty('vendors')
  })
})

describe('useSetVendorDisabled', () => {
  it('PUTs to /agents/model-configs/{id}/disabled with the is_disabled flag', async () => {
    const { useSetVendorDisabled } = await import('../hooks/useModelAvailability')
    const wrapper = withQueryClient()
    const { result } = renderHook(() => useSetVendorDisabled(), { wrapper })

    await result.current.mutateAsync({
      configId: 'cfg-1',
      is_disabled: true,
    })

    expect(shared.mockPut).toHaveBeenCalledWith(
      '/agents/model-configs/cfg-1/disabled',
      expect.objectContaining({ is_disabled: true }),
    )
  })

  it('forwards an optional reason to the API', async () => {
    const { useSetVendorDisabled } = await import('../hooks/useModelAvailability')
    const wrapper = withQueryClient()
    const { result } = renderHook(() => useSetVendorDisabled(), { wrapper })

    await result.current.mutateAsync({
      configId: 'cfg-2',
      is_disabled: false,
      reason: 'maintenance complete',
    })

    expect(shared.mockPut).toHaveBeenCalledWith(
      '/agents/model-configs/cfg-2/disabled',
      expect.objectContaining({ is_disabled: false, reason: 'maintenance complete' }),
    )
  })
})

describe('useSetModelDisabled', () => {
  it('PUTs to /agents/model-configs/{id}/models/{name}/disabled with the is_disabled flag', async () => {
    const { useSetModelDisabled } = await import('../hooks/useModelAvailability')
    const wrapper = withQueryClient()
    const { result } = renderHook(() => useSetModelDisabled(), { wrapper })

    await result.current.mutateAsync({
      configId: 'cfg-1',
      modelName: 'gpt-4.1',
      is_disabled: true,
    })

    expect(shared.mockPut).toHaveBeenCalledWith(
      '/agents/model-configs/cfg-1/models/gpt-4.1/disabled',
      expect.objectContaining({ is_disabled: true }),
    )
  })

  it('URL-encodes the model name in the path', async () => {
    const { useSetModelDisabled } = await import('../hooks/useModelAvailability')
    const wrapper = withQueryClient()
    const { result } = renderHook(() => useSetModelDisabled(), { wrapper })

    await result.current.mutateAsync({
      configId: 'cfg-1',
      modelName: 'model with spaces',
      is_disabled: true,
    })

    expect(shared.mockPut).toHaveBeenCalledWith(
      '/agents/model-configs/cfg-1/models/model%20with%20spaces/disabled',
      expect.objectContaining({ is_disabled: true }),
    )
  })
})
