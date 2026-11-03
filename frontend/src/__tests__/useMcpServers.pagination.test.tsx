/**
 * FIX-20261102-062047 — "get everything" list hooks page the complete set.
 *
 * The backend caps a page at 200 and returns a short final page; the hooks
 * used by the tool pickers must page until exhausted instead of trusting a
 * single default window (which used to truncate at 50 and hide whole MCP
 * servers from the picker).
 */
import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useAllTools, useMcpServers } from '../hooks/useMcpServers'
import type { McpServer, McpTool } from '../types'

vi.mock('../api/apiClient', () => ({
  default: { get: vi.fn() },
}))

import apiClient from '../api/apiClient'

const getMock = apiClient.get as unknown as Mock

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

function tool(index: number): McpTool {
  return {
    id: `tool-${index}`,
    server_id: 'srv',
    server_slug: 'supabase',
    server_name: 'Supabase',
    name: `supabase____tool_${index}`,
    original_name: `tool_${index}`,
    description: null,
    input_schema: null,
    is_active: true,
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
  }
}

beforeEach(() => {
  getMock.mockReset()
})

describe('useAllTools complete listing (FIX-20261102-062047)', () => {
  it('pages until a short page so no tool is lost past the 200 cap', async () => {
    const firstPage = Array.from({ length: 200 }, (_, index) => tool(index))
    const secondPage = Array.from({ length: 5 }, (_, index) => tool(200 + index))
    getMock.mockImplementation(async (url: string, config: { params?: { offset?: number } }) => {
      expect(url).toBe('/mcp/tools')
      const offset = config?.params?.offset ?? 0
      return { data: offset === 0 ? firstPage : secondPage }
    })

    const { result } = renderHook(() => useAllTools(), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data).toHaveLength(205)
    expect(getMock).toHaveBeenCalledTimes(2)
    expect(getMock.mock.calls[0][1]).toMatchObject({ params: { limit: 200, offset: 0 } })
    expect(getMock.mock.calls[1][1]).toMatchObject({ params: { limit: 200, offset: 200 } })
  })

  it('keeps explicit paging callers on a single page request', async () => {
    getMock.mockResolvedValue({ data: [tool(1)] })
    const { result } = renderHook(() => useAllTools(10, 20), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(getMock).toHaveBeenCalledTimes(1)
    expect(getMock.mock.calls[0][1]).toMatchObject({ params: { limit: 10, offset: 20 } })
  })
})

describe('useMcpServers complete listing (FIX-20261102-062047)', () => {
  it('pages the full server catalogue', async () => {
    const server = (index: number): McpServer => ({
      id: `srv-${index}`,
      name: `server-${index}`,
      slug: `server-${index}`,
      description: null,
      base_url: 'http://example.test',
      status: 'active' as McpServer['status'],
      last_synced_at: null,
      session_count: 0,
      created_at: '2026-11-01T00:00:00Z',
      updated_at: '2026-11-01T00:00:00Z',
    })
    getMock.mockImplementation(async (_url: string, config: { params?: { offset?: number } }) => {
      const offset = config?.params?.offset ?? 0
      return {
        data:
          offset === 0
            ? Array.from({ length: 100 }, (_, index) => server(index))
            : [server(100), server(101)],
      }
    })

    const { result } = renderHook(() => useMcpServers(), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data).toHaveLength(102)
    expect(getMock).toHaveBeenCalledTimes(2)
    // /mcp/servers caps a page at 100 (unlike /mcp/tools' 200).
    expect(getMock.mock.calls[0][1]).toMatchObject({ params: { limit: 100, offset: 0 } })
  })
})
