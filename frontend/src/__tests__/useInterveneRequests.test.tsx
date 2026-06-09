import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'

const shared = vi.hoisted(() => ({
  mockGetInterveneRequests: vi.fn(),
  mockGetInterveneMetrics: vi.fn(),
  mockSubmitInterveneResponse: vi.fn(),
  mockCancelInterveneRequest: vi.fn(),
}))

vi.mock('../api/interveneApi', () => ({
  getInterveneRequests: shared.mockGetInterveneRequests,
  getInterveneMetrics: shared.mockGetInterveneMetrics,
  submitInterveneResponse: shared.mockSubmitInterveneResponse,
  cancelInterveneRequest: shared.mockCancelInterveneRequest,
}))

const mockPendingRequest = {
  id: 'req-1',
  agent_session_id: 'sess-abc',
  agent_type_id: 'agent-1',
  intervention_type: 'approval',
  reason: 'Approve?',
  status: 'pending',
  created_at: '2026-06-01T00:00:00Z',
}

const mockRespondedRequest = {
  id: 'req-2',
  agent_session_id: 'sess-abc',
  agent_type_id: 'agent-1',
  intervention_type: 'text',
  reason: 'Enter text',
  status: 'responded',
  created_at: '2026-06-01T00:00:00Z',
  responded_at: '2026-06-01T00:01:00Z',
  response: {
    id: 'resp-1',
    request_id: 'req-2',
    operator_user_id: 'user-1',
    text_value: 'done',
    responded_at: '2026-06-01T00:01:00Z',
  },
}

describe('useInterveneRequests', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    shared.mockGetInterveneRequests.mockReset()
    shared.mockGetInterveneMetrics.mockReset()
    shared.mockSubmitInterveneResponse.mockReset()
    shared.mockCancelInterveneRequest.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('fetches requests and metrics on mount', async () => {
    shared.mockGetInterveneRequests.mockResolvedValue([mockPendingRequest])
    shared.mockGetInterveneMetrics.mockResolvedValue({
      pending_count: 1,
      avg_response_time_seconds: 0,
      resolution_rate: 0,
    })

    const { useInterveneRequests } = await import('../hooks/useInterveneRequests')
    const { result } = renderHook(() => useInterveneRequests())

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })
    expect(shared.mockGetInterveneRequests).toHaveBeenCalledTimes(1)
    expect(shared.mockGetInterveneMetrics).toHaveBeenCalledTimes(1)
    expect(result.current.pendingRequests).toHaveLength(1)
    expect(result.current.pendingRequests[0].id).toBe('req-1')
    expect(result.current.respondedRequests).toHaveLength(0)
    expect(result.current.metrics?.pending_count).toBe(1)
  })

  it('splits requests into pending and responded', async () => {
    shared.mockGetInterveneRequests.mockResolvedValue([
      mockPendingRequest,
      mockRespondedRequest,
    ])
    shared.mockGetInterveneMetrics.mockResolvedValue({
      pending_count: 1,
      avg_response_time_seconds: 120,
      resolution_rate: 0.5,
    })

    const { useInterveneRequests } = await import('../hooks/useInterveneRequests')
    const { result } = renderHook(() => useInterveneRequests())

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })
    expect(result.current.pendingRequests).toHaveLength(1)
    expect(result.current.respondedRequests).toHaveLength(1)
    expect(result.current.pendingRequests[0].status).toBe('pending')
    expect(result.current.respondedRequests[0].status).toBe('responded')
  })

  it('sets error when fetch fails', async () => {
    shared.mockGetInterveneRequests.mockRejectedValue(new Error('Network error'))

    const { useInterveneRequests } = await import('../hooks/useInterveneRequests')
    const { result } = renderHook(() => useInterveneRequests())

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })
    expect(result.current.error).toBeTruthy()
    expect(result.current.pendingRequests).toHaveLength(0)
  })

  it('submits response and refetches', async () => {
    shared.mockGetInterveneRequests.mockResolvedValue([mockPendingRequest])
    shared.mockGetInterveneMetrics.mockResolvedValue({
      pending_count: 1, avg_response_time_seconds: 0, resolution_rate: 0,
    })
    shared.mockSubmitInterveneResponse.mockResolvedValue({
      id: 'resp-1',
      request_id: 'req-1',
      operator_user_id: 'user-1',
      approval_value: true,
      responded_at: '2026-06-01T00:01:00Z',
    })

    const { useInterveneRequests } = await import('../hooks/useInterveneRequests')
    const { result } = renderHook(() => useInterveneRequests())

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })
    expect(shared.mockGetInterveneRequests).toHaveBeenCalledTimes(1)

    await act(async () => {
      await result.current.submitResponse('req-1', { approval_value: true })
    })

    expect(shared.mockSubmitInterveneResponse).toHaveBeenCalledWith('req-1', {
      request_id: 'req-1',
      approval_value: true,
    })
    // Refetch after submit
    expect(shared.mockGetInterveneRequests).toHaveBeenCalledTimes(2)
  })

  it('cancels request and refetches', async () => {
    shared.mockGetInterveneRequests.mockResolvedValue([mockPendingRequest])
    shared.mockGetInterveneMetrics.mockResolvedValue({
      pending_count: 1, avg_response_time_seconds: 0, resolution_rate: 0,
    })
    shared.mockCancelInterveneRequest.mockResolvedValue({
      ...mockPendingRequest,
      status: 'cancelled',
    })

    const { useInterveneRequests } = await import('../hooks/useInterveneRequests')
    const { result } = renderHook(() => useInterveneRequests())

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    await act(async () => {
      await result.current.cancelRequest('req-1')
    })

    expect(shared.mockCancelInterveneRequest).toHaveBeenCalledWith('req-1')
    expect(shared.mockGetInterveneRequests).toHaveBeenCalledTimes(2)
  })

  it('polls periodically', async () => {
    shared.mockGetInterveneRequests.mockResolvedValue([])
    shared.mockGetInterveneMetrics.mockResolvedValue({
      pending_count: 0, avg_response_time_seconds: 0, resolution_rate: 1,
    })

    const { useInterveneRequests } = await import('../hooks/useInterveneRequests')
    renderHook(() => useInterveneRequests())

    await waitFor(() => {
      expect(shared.mockGetInterveneRequests).toHaveBeenCalledTimes(1)
    })

    // Advance 10 seconds to trigger polling interval
    await act(async () => {
      vi.advanceTimersByTime(10_000)
    })

    expect(shared.mockGetInterveneRequests).toHaveBeenCalledTimes(2)
  })

  it('filters requests by status and type', async () => {
    shared.mockGetInterveneRequests.mockResolvedValue([])
    shared.mockGetInterveneMetrics.mockResolvedValue({
      pending_count: 0, avg_response_time_seconds: 0, resolution_rate: 1,
    })

    const { useInterveneRequests } = await import('../hooks/useInterveneRequests')
    renderHook(() => useInterveneRequests({
      statusFilter: 'pending',
      typeFilter: 'approval',
      sessionId: 'sess-abc',
    }))

    await waitFor(() => {
      expect(shared.mockGetInterveneRequests).toHaveBeenCalledTimes(1)
    })
    expect(shared.mockGetInterveneRequests).toHaveBeenCalledWith({
      status: 'pending',
      intervention_type: 'approval',
      agent_session_id: 'sess-abc',
      limit: 100,
    })
  })

  it('cleans up interval on unmount', async () => {
    shared.mockGetInterveneRequests.mockResolvedValue([])
    shared.mockGetInterveneMetrics.mockResolvedValue({
      pending_count: 0, avg_response_time_seconds: 0, resolution_rate: 1,
    })

    const { useInterveneRequests } = await import('../hooks/useInterveneRequests')
    const { unmount } = renderHook(() => useInterveneRequests())

    await waitFor(() => {
      expect(shared.mockGetInterveneRequests).toHaveBeenCalledTimes(1)
    })

    unmount()

    // Advance time — should NOT trigger another fetch
    await act(async () => {
      vi.advanceTimersByTime(10_000)
    })

    expect(shared.mockGetInterveneRequests).toHaveBeenCalledTimes(1)
  })
})
