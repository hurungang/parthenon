import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

const { mockApiClient } = vi.hoisted(() => {
  return {
    mockApiClient: {
      get: vi.fn(),
      post: vi.fn(),
    },
  }
})

vi.mock('../../api/apiClient', () => ({ default: mockApiClient }))

import { useApiKeys, useIdentitiesWithRoles } from '../../hooks/useApiKeys'

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: qc }, children)
  }
}

describe('useApiKeys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches api keys successfully', async () => {
    const mockKeys = [
      {
        id: 'key-1',
        name: 'Test Key',
        key_prefix: 'phn_sk_',
        agent_identity_id: 'i-1',
        agent_identity_name: 'Agent X',
        agent_role_id: 'r-1',
        agent_role_name: 'Developer',
        status: 'active',
        created_at: '2026-01-01T00:00:00Z',
        last_used_at: null,
      },
    ]
    mockApiClient.get.mockResolvedValue({ data: mockKeys })

    const { result } = renderHook(() => useApiKeys(), { wrapper: createWrapper() })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    expect(result.current.data).toEqual(mockKeys)
  })

  it('handles loading state', () => {
    mockApiClient.get.mockImplementation(() => new Promise(() => {}))

    const { result } = renderHook(() => useApiKeys(), { wrapper: createWrapper() })

    expect(result.current.isLoading).toBe(true)
  })

  it('handles error state', async () => {
    mockApiClient.get.mockRejectedValue(new Error('Failed to fetch'))

    const { result } = renderHook(() => useApiKeys(), { wrapper: createWrapper() })

    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
    expect(result.current.error).toBeDefined()
  })

  it('fetches keys with status filter', async () => {
    const mockKeys = [{ id: 'key-1', name: 'Active Key', key_prefix: 'phn_sk_', agent_identity_id: 'i-1', agent_identity_name: 'Agent X', agent_role_id: 'r-1', agent_role_name: 'Developer', status: 'active', created_at: '2026-01-01T00:00:00Z', last_used_at: null }]
    mockApiClient.get.mockResolvedValue({ data: mockKeys })

    const { result } = renderHook(() => useApiKeys('active'), { wrapper: createWrapper() })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    expect(mockApiClient.get).toHaveBeenCalledWith('/api-keys', { params: { status: 'active' } })
  })
})

describe('useIdentitiesWithRoles', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches identities with roles', async () => {
    const mockData = [
      {
        identity_id: 'i-1',
        identity_name: 'Agent X',
        roles: [{ role_id: 'r-1', role_name: 'Developer' }],
      },
    ]
    mockApiClient.get.mockResolvedValue({ data: mockData })

    const { result } = renderHook(() => useIdentitiesWithRoles(), { wrapper: createWrapper() })

    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })

    expect(result.current.data).toEqual(mockData)
  })
})
