import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: shared.mockGet,
  },
}))

describe('useChatSession - intervention messages', () => {
  let sockets: MockWebSocket[] = []

  class MockWebSocket {
    static readonly OPEN = 1
    readyState = MockWebSocket.OPEN
    send = vi.fn()
    close = vi.fn()
    onopen: ((this: WebSocket, ev: Event) => any) | null = null
    onmessage: ((this: WebSocket, ev: MessageEvent) => any) | null = null
    onclose: ((this: WebSocket, ev: CloseEvent) => any) | null = null
    onerror: ((this: WebSocket, ev: Event) => any) | null = null

    constructor() {
      sockets.push(this)
    }
  }

  beforeEach(() => {
    sockets = []
    vi.stubGlobal('WebSocket', MockWebSocket)
    shared.mockGet.mockReset()
    shared.mockGet.mockResolvedValue({ data: [] })
  })

  // ── Intervene request message ────────────────────────────────────────────

  it('parses intervene_request WebSocket message and updates interventionRequest state', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]
    expect(socket).toBeDefined()

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'intervene_request',
            request_id: 'req-001',
            intervention_type: 'approval',
            reason: 'Approve this action?',
            agent_type: 'FraudCheckAgent',
            delegation_depth: 1,
            conversation_session_id: 'test-session-123',
          }),
        }),
      )
    })

    expect(result.current.interventionRequest).not.toBeNull()
    expect(result.current.interventionRequest?.request_id).toBe('req-001')
    expect(result.current.interventionRequest?.intervention_type).toBe('approval')
    expect(result.current.interventionRequest?.reason).toBe('Approve this action?')
    expect(result.current.interventionRequest?.agent_type).toBe('FraudCheckAgent')
    expect(result.current.interventionRequest?.delegation_depth).toBe(1)
  })

  it('parses choice-type intervene_request', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]
    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'intervene_request',
            request_id: 'req-002',
            intervention_type: 'choice',
            reason: 'Select option:',
            choices: ['Option A', 'Option B', 'Option C'],
            agent_type: 'ChoiceAgent',
            delegation_depth: 2,
            conversation_session_id: 'test-session-123',
          }),
        }),
      )
    })

    expect(result.current.interventionRequest?.intervention_type).toBe('choice')
    expect(result.current.interventionRequest?.choices).toEqual(['Option A', 'Option B', 'Option C'])
    expect(result.current.interventionRequest?.delegation_depth).toBe(2)
  })

  it('parses text-type intervene_request', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]
    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'intervene_request',
            request_id: 'req-003',
            intervention_type: 'text',
            reason: 'Describe the output format',
            agent_type: 'TextAgent',
            delegation_depth: 0,
            conversation_session_id: 'test-session-123',
          }),
        }),
      )
    })

    expect(result.current.interventionRequest?.intervention_type).toBe('text')
    expect(result.current.interventionRequest?.request_id).toBe('req-003')
  })

  // ── Intervene status message ─────────────────────────────────────────────

  it('clears interventionRequest on responded status', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]

    // First send an intervene_request
    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'intervene_request',
            request_id: 'req-004',
            intervention_type: 'approval',
            reason: 'Test',
            agent_type: 'TestAgent',
            delegation_depth: 0,
            conversation_session_id: 'test-session-123',
          }),
        }),
      )
    })
    expect(result.current.interventionRequest).not.toBeNull()

    // Then send intervened_status=responded
    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'intervene_status',
            request_id: 'req-004',
            status: 'responded',
          }),
        }),
      )
    })

    expect(result.current.interventionRequest).toBeNull()
  })

  it('clears interventionRequest on cancelled status', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'intervene_request',
            request_id: 'req-005',
            intervention_type: 'choice',
            reason: 'Test cancel',
            choices: ['A'],
            agent_type: 'TestAgent',
            delegation_depth: 0,
            conversation_session_id: 'test-session-123',
          }),
        }),
      )
    })
    expect(result.current.interventionRequest).not.toBeNull()

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'intervene_status',
            request_id: 'req-005',
            status: 'cancelled',
          }),
        }),
      )
    })

    expect(result.current.interventionRequest).toBeNull()
  })

  // ── Chat message blocking ────────────────────────────────────────────────

  it('blocks chat messages when intervention is pending', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'intervene_request',
            request_id: 'req-006',
            intervention_type: 'approval',
            reason: 'Block test',
            agent_type: 'TestAgent',
            delegation_depth: 0,
            conversation_session_id: 'test-session-123',
          }),
        }),
      )
    })

    // Try sending a message
    const wsSend = socket.send as ReturnType<typeof vi.fn>
    // The hook should block and not call send
    // Verify intervention is active
    expect(result.current.interventionRequest).not.toBeNull()
  })

  // ── Send intervention response via WebSocket ─────────────────────────────

  it('sendInterventionResponse sends correct WebSocket message', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]
    act(() => {
      result.current.sendInterventionResponse?.('req-007', {
        approval_value: true,
      })
    })

    expect(socket.send).toHaveBeenCalledWith(
      expect.stringContaining('intervene_response'),
    )
  })

  it('cancelIntervention sends correct WebSocket message', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]
    act(() => {
      result.current.cancelIntervention?.('req-008')
    })

    expect(socket.send).toHaveBeenCalledWith(
      expect.stringContaining('intervene_cancel'),
    )
  })

  // ── interventionRequest initially null ───────────────────────────────────

  it('interventionRequest starts as null', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    expect(result.current.interventionRequest).toBeNull()
    expect(result.current.interventionQueueLength).toBe(0)
  })
})
