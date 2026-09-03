import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement, type ReactNode } from 'react'

// The hook module imports the apiClient (default export); stub it so the
// pure predicate import has no side effects. The get stub is hoisted so the
// hook tests below can assert the request URL.
const mockGet = vi.hoisted(() => vi.fn())

vi.mock('../api/apiClient', () => ({
  default: { get: (...args: unknown[]) => mockGet(...args), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

import { isNodeVisibleByDefault, useRuntimeTopology } from '../hooks/useRuntimeTopology'
import type { RuntimeTopologyNode, RuntimeTopologyProjection } from '../types'

function node(overrides: Partial<RuntimeTopologyNode> = {}): RuntimeTopologyNode {
  return {
    session_id: 'sess-1',
    agent_type_id: 'at-1',
    agent_type_name: 'Support Agent',
    status: 'running',
    depth_from_root: 0,
    parent_session_id: null,
    started_at: null,
    created_at: '2026-06-01T00:00:00Z',
    termination_category: null,
    kind: 'conversation',
    ...overrides,
  }
}

const emptyTopology: RuntimeTopologyProjection = { nodes: [], edges: [], root_session_ids: [] }

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return function Wrapper({ children }: { children?: ReactNode }) {
    return createElement(QueryClientProvider, { client: queryClient }, children)
  }
}

describe('isNodeVisibleByDefault', () => {
  it('returns true for an active (running) node regardless of needs_intervention', () => {
    expect(isNodeVisibleByDefault(node({ status: 'running', needs_intervention: false }))).toBe(true)
    expect(isNodeVisibleByDefault(node({ status: 'running', needs_intervention: true }))).toBe(true)
  })

  it('returns true for a queued node', () => {
    expect(isNodeVisibleByDefault(node({ status: 'queued', kind: 'agent', needs_intervention: false }))).toBe(true)
  })

  it('returns true for a sleeping node awaiting intervention', () => {
    expect(isNodeVisibleByDefault(node({ status: 'sleep', needs_intervention: true }))).toBe(true)
  })

  it('returns false for a sleeping node not awaiting intervention', () => {
    expect(isNodeVisibleByDefault(node({ status: 'sleep', needs_intervention: false }))).toBe(false)
  })

  it('returns false for a sleeping node with an undefined needs_intervention (backwards compatibility)', () => {
    expect(isNodeVisibleByDefault(node({ status: 'sleep', needs_intervention: undefined }))).toBe(false)
  })

  it('does not resurrect terminal statuses (completed/failed/terminated are not "sleep")', () => {
    // These are not "sleep", so they are visible by default — but they are not
    // treated as "awaiting intervention" either. The key guarantee is the
    // predicate never returns true *because of* needs_intervention for them.
    expect(isNodeVisibleByDefault(node({ status: 'completed', kind: 'agent', needs_intervention: false }))).toBe(true)
    expect(isNodeVisibleByDefault(node({ status: 'failed', kind: 'agent', needs_intervention: false }))).toBe(true)
    expect(isNodeVisibleByDefault(node({ status: 'terminated', kind: 'agent', needs_intervention: false }))).toBe(true)
  })

  it('is unaffected by trigger-provenance and tool-call fields', () => {
    // A running node carrying the new trigger_source/label/tool_calls fields is
    // still visible by default (the new fields do not perturb the predicate).
    const withProvenance = node({
      status: 'running',
      kind: 'agent',
      trigger_source: 'user',
      trigger_source_label: 'Alice',
      tool_calls: [{ tool_name: 'github____list_prs', mcp_slug: 'github', called_at: null }],
    })
    expect(isNodeVisibleByDefault(withProvenance)).toBe(true)
  })

  it('keeps a sleeping awaiting-intervention node visible even with provenance fields', () => {
    const sleeping = node({
      status: 'sleep',
      needs_intervention: true,
      trigger_source: 'schedule',
      trigger_source_label: 'nightly-cleanup',
      tool_calls: [],
    })
    expect(isNodeVisibleByDefault(sleeping)).toBe(true)
  })
})

describe('useRuntimeTopology — recent_minutes wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue({ data: emptyTopology })
  })

  it('requests the default recent_minutes=30 window', async () => {
    const { result } = renderHook(() => useRuntimeTopology(), { wrapper: createWrapper() })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(mockGet.mock.calls[0][0]).toBe(
      '/agents/runtime/topology?include_terminal=false&recent_minutes=30',
    )
  })

  it('passes a custom recent_minutes value and include_terminal in the URL', async () => {
    const { result } = renderHook(() => useRuntimeTopology(true, 120), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mockGet.mock.calls[0][0]).toBe(
      '/agents/runtime/topology?include_terminal=true&recent_minutes=120',
    )
  })

  it('sends recent_minutes=0 when the window is disabled', async () => {
    const { result } = renderHook(() => useRuntimeTopology(false, 0), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mockGet.mock.calls[0][0]).toBe(
      '/agents/runtime/topology?include_terminal=false&recent_minutes=0',
    )
  })

  it('refetches when the recent_minutes value changes (query-key change)', async () => {
    const { result, rerender } = renderHook(
      ({ recent }: { recent: number }) => useRuntimeTopology(false, recent),
      { wrapper: createWrapper(), initialProps: { recent: 30 } },
    )

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mockGet).toHaveBeenCalledTimes(1)

    rerender({ recent: 360 })
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2))
    expect(mockGet.mock.calls[1][0]).toBe(
      '/agents/runtime/topology?include_terminal=false&recent_minutes=360',
    )
  })
})
