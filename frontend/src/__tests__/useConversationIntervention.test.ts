import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'

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

vi.mock('../hooks/useDialogErrorHandler', () => ({
  useDialogErrorHandler: () => ({
    dialogError: null,
    setDialogError: vi.fn(),
    clearDialogError: vi.fn(),
  }),
}))

describe('useConversationIntervention', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    shared.mockGet.mockReset()
    shared.mockPost.mockReset()
    shared.mockGet.mockResolvedValue({ data: [] })
  })

  it('fetches pending interventions on mount when sessionId is provided', async () => {
    const { useConversationIntervention } = await import('../hooks/useConversationIntervention')
    renderHook(() => useConversationIntervention('session-123'))

    await waitFor(() => {
      expect(shared.mockGet).toHaveBeenCalledWith(
        '/conversations/session-123/interventions/pending',
      )
    })
  })

  it('does not fetch when sessionId is null', async () => {
    const { useConversationIntervention } = await import('../hooks/useConversationIntervention')
    renderHook(() => useConversationIntervention(null))

    // Wait a tick to ensure no fetch happens
    await vi.waitFor(
      () => {
        expect(shared.mockGet).not.toHaveBeenCalled()
      },
      { timeout: 100 },
    )
  })

  it('handles empty pending state', async () => {
    shared.mockGet.mockResolvedValue({ data: [] })
    const { useConversationIntervention } = await import('../hooks/useConversationIntervention')
    const { result } = renderHook(() => useConversationIntervention('session-abc'))

    await waitFor(() => {
      expect(result.current.currentIntervention).toBeNull()
    })
    expect(result.current.pendingInterventions).toEqual([])
  })

  it('handles pending interventions from fetch', async () => {
    const mockInterventions = [
      {
        id: 'req-1',
        agent_session_id: 'sess-1',
        agent_type_id: 'at-1',
        intervention_type: 'approval',
        reason: 'Approve?',
        status: 'pending',
        delegation_depth: 0,
        created_at: '2026-01-01T00:00:00Z',
      },
    ]
    shared.mockGet.mockResolvedValue({ data: mockInterventions })
    const { useConversationIntervention } = await import('../hooks/useConversationIntervention')
    const { result } = renderHook(() => useConversationIntervention('session-abc'))

    await waitFor(() => {
      expect(result.current.pendingInterventions).toHaveLength(1)
    })
    expect(result.current.currentIntervention).toEqual(mockInterventions[0])
  })

  it('sends response via WebSocket when available', async () => {
    const sendInterventionResponse = vi.fn().mockReturnValue(true)
    const { useConversationIntervention } = await import('../hooks/useConversationIntervention')
    const { result } = renderHook(() =>
      useConversationIntervention('session-abc', sendInterventionResponse, vi.fn()),
    )

    await act(async () => {
      await result.current.respondToIntervention('req-1', { approval_value: true })
    })

    expect(sendInterventionResponse).toHaveBeenCalledWith('req-1', { approval_value: true })
    expect(shared.mockPost).not.toHaveBeenCalled()
  })

  it('falls back to REST when WebSocket is unavailable', async () => {
    const sendInterventionResponse = vi.fn().mockReturnValue(false)
    shared.mockPost.mockResolvedValue({ data: {} })
    const { useConversationIntervention } = await import('../hooks/useConversationIntervention')
    const { result } = renderHook(() =>
      useConversationIntervention('session-abc', sendInterventionResponse, vi.fn()),
    )

    await act(async () => {
      await result.current.respondToIntervention('req-2', { selected_choice: 'A' })
    })

    expect(sendInterventionResponse).toHaveBeenCalled()
    expect(shared.mockPost).toHaveBeenCalledWith(
      '/conversations/session-abc/interventions/req-2/respond',
      expect.objectContaining({
        request_id: 'req-2',
        selected_choice: 'A',
      }),
    )
  })

  it('cancels via WebSocket when available', async () => {
    const cancelIntervention = vi.fn().mockReturnValue(true)
    const { useConversationIntervention } = await import('../hooks/useConversationIntervention')
    const { result } = renderHook(() =>
      useConversationIntervention('session-abc', vi.fn(), cancelIntervention),
    )

    await act(async () => {
      await result.current.cancelIntervention('req-3')
    })

    expect(cancelIntervention).toHaveBeenCalledWith('req-3')
    expect(shared.mockPost).not.toHaveBeenCalled()
  })

  it('cancels via REST fallback when WebSocket unavailable', async () => {
    const cancelIntervention = vi.fn().mockReturnValue(false)
    shared.mockPost.mockResolvedValue({ data: {} })
    const { useConversationIntervention } = await import('../hooks/useConversationIntervention')
    const { result } = renderHook(() =>
      useConversationIntervention('session-abc', vi.fn(), cancelIntervention),
    )

    await act(async () => {
      await result.current.cancelIntervention('req-4')
    })

    expect(shared.mockPost).toHaveBeenCalledWith('/intervene/requests/req-4/cancel')
  })

  it('handles errors via useDialogErrorHandler', async () => {
    const sendInterventionResponse = vi.fn().mockReturnValue(false)
    shared.mockPost.mockRejectedValue(new Error('Network error'))
    const { useConversationIntervention } = await import('../hooks/useConversationIntervention')

    // Override the mock for this test
    const mockSetDialogError = vi.fn()
    vi.doMock('../hooks/useDialogErrorHandler', () => ({
      useDialogErrorHandler: () => ({
        dialogError: null,
        setDialogError: mockSetDialogError,
        clearDialogError: vi.fn(),
      }),
    }))

    const { result } = renderHook(() =>
      useConversationIntervention('session-abc', sendInterventionResponse, vi.fn()),
    )

    await act(async () => {
      await result.current.respondToIntervention('req-5', { text_value: 'test' })
    })

    // isSubmitting should be reset to false even on error
    expect(result.current.isSubmitting).toBe(false)
  })
})
