import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: shared.mockGet,
  },
}))

/**
 * Invariant under test: while a conversational turn is in flight, the chat
 * status never lands on a kind that renders nothing — the window must always
 * show a visible activity indicator until the final agent reply.
 */
describe('useChatSession — activity indicator always visible mid-turn', () => {
  let sockets: MockWebSocket[] = []

  class MockWebSocket {
    static readonly OPEN = 1

    readyState = MockWebSocket.OPEN
    sent: string[] = []
    onopen: ((this: WebSocket, ev: Event) => any) | null = null
    onmessage: ((this: WebSocket, ev: MessageEvent) => any) | null = null
    onclose: ((this: WebSocket, ev: CloseEvent) => any) | null = null
    onerror: ((this: WebSocket, ev: Event) => any) | null = null

    constructor() {
      this.send = (data: string) => {
        this.sent.push(data)
      }
      sockets.push(this)
    }
    send: (data: string) => void
    close = vi.fn()
  }

  function sendWsMessage(socket: MockWebSocket, payload: unknown) {
    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', { data: JSON.stringify(payload) }),
      )
    })
  }

  beforeEach(() => {
    sockets = []
    vi.stubGlobal('WebSocket', MockWebSocket)
    shared.mockGet.mockReset()
    shared.mockGet.mockResolvedValue({ data: [] })
  })

  it('(a) mid-turn using_tool → delegation_resumed keeps a visible indicator', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('resumed-session'))

    act(() => {
      result.current.sendMessage('Hello')
    })
    expect(result.current.chatStatus?.kind).toBe('thinking')

    sendWsMessage(sockets[0], { type: 'chat_status', status: 'using_tool', tool_name: 'cc____list_agents' })
    expect(result.current.chatStatus?.kind).toBe('using_tool')

    sendWsMessage(sockets[0], { type: 'chat_status', status: 'delegation_resumed', agent_type: 'agent____worker' })
    // delegation_resumed has no dedicated rendering in the dialog — it must be
    // stored as a thinking-equivalent so the indicator stays visible.
    expect(result.current.chatStatus?.kind).toBe('thinking')
    expect(result.current.chatStatus?.agentType).toBe('worker')

    // heartbeat keeps the restored indicator alive
    const before = result.current.chatStatus?.timestamp
    sendWsMessage(sockets[0], { type: 'chat_status', status: 'thinking_heartbeat' })
    expect(result.current.chatStatus?.kind).toBe('thinking')
    expect(result.current.chatStatus?.timestamp).not.toBe(before)
  })

  it('(b) an ask-user agent message mid-turn does not blank the indicator', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('ask-session'))

    act(() => {
      result.current.sendMessage('Do the thing')
    })

    sendWsMessage(sockets[0], { type: 'chat_status', status: 'using_tool', tool_name: 'cc____preview' })
    expect(result.current.chatStatus?.kind).toBe('using_tool')

    sendWsMessage(sockets[0], {
      sender_role: 'agent',
      content: '? Which name should I use?',
      timestamp: '2026-01-01T00:00:00Z',
    })

    expect(result.current.pendingQuestion).toBe('? Which name should I use?')
    expect(result.current.chatStatus).not.toBeNull()
    expect(result.current.chatStatus?.kind).toBe('thinking')
  })

  it('(b2) the final agent reply clears the indicator', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('final-session'))

    act(() => {
      result.current.sendMessage('Hello')
    })
    sendWsMessage(sockets[0], { type: 'chat_status', status: 'using_tool', tool_name: 'cc____list' })

    sendWsMessage(sockets[0], {
      sender_role: 'agent',
      content: 'All done.',
      timestamp: '2026-01-01T00:00:00Z',
    })
    expect(result.current.chatStatus).toBeNull()
    expect(result.current.turnInFlight).toBe(false)
  })

  it('(b3) an intermediate agent message mid-delegation demotes to thinking, never null', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('intermediate-session'))

    act(() => {
      result.current.sendMessage('Run it')
    })
    expect(result.current.turnInFlight).toBe(true)

    // Delegation starts — a delegation cycle becomes active.
    sendWsMessage(sockets[0], { type: 'chat_status', status: 'delegating', agent_type: 'agent____worker' })

    // Intermediate sub-agent message while the delegated turn keeps running —
    // the indicator must NOT be cleared; it demotes to a thinking-equivalent.
    sendWsMessage(sockets[0], {
      sender_role: 'agent',
      content: 'Partial progress: step 1 complete.',
      timestamp: '2026-01-01T00:00:00Z',
    })
    expect(result.current.messages.length).toBe(2)
    expect(result.current.chatStatus).not.toBeNull()
    expect(result.current.chatStatus?.kind).toBe('thinking')
    expect(result.current.turnInFlight).toBe(true)

    // Heartbeats keep it alive during the continued delegation work.
    sendWsMessage(sockets[0], { type: 'chat_status', status: 'thinking_heartbeat' })
    expect(result.current.chatStatus?.kind).toBe('thinking')

    // The turn's actual final reply then clears the indicator exactly once.
    sendWsMessage(sockets[0], {
      sender_role: 'agent',
      content: 'Final reply.',
      timestamp: '2026-01-01T00:01:00Z',
    })
    expect(result.current.chatStatus).toBeNull()
    expect(result.current.turnInFlight).toBe(false)
  })

  it('(b4) a terminal timeout_or_failed status closes the in-flight window', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('terminal-session'))

    act(() => {
      result.current.sendMessage('Hello')
    })
    expect(result.current.turnInFlight).toBe(true)

    sendWsMessage(sockets[0], { type: 'chat_status', status: 'timeout_or_failed' })
    expect(result.current.chatStatus?.kind).toBe('timeout_or_failed')
    expect(result.current.turnInFlight).toBe(false)
  })

  it('(b5) heartbeats during a long gap preserve the in-flight indicator', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('heartbeat-session'))

    act(() => {
      result.current.sendMessage('Long task')
    })

    for (let i = 0; i < 5; i++) {
      sendWsMessage(sockets[0], { type: 'chat_status', status: 'thinking_heartbeat' })
    }
    expect(result.current.chatStatus).not.toBeNull()
    expect(result.current.chatStatus?.kind).toBe('thinking')
    expect(result.current.turnInFlight).toBe(true)
  })

  it('(c) reconnecting mid-turn restores a visible thinking indicator', async () => {
    vi.useFakeTimers()
    try {
      const { useChatSession } = await import('../hooks/useChatSession')
      const { result } = renderHook(() => useChatSession('reconnect-session'))

      act(() => {
        result.current.sendMessage('Hello')
      })
      sendWsMessage(sockets[0], { type: 'chat_status', status: 'using_tool', tool_name: 'cc____list' })

      // Unexpected disconnect mid-turn
      act(() => {
        sockets[0].onclose?.call(
          sockets[0] as unknown as WebSocket,
          new CloseEvent('close', { code: 1006, wasClean: false }),
        )
      })
      expect(result.current.connected).toBe(false)

      // Reconnect after the backoff timer fires
      act(() => {
        vi.advanceTimersByTime(1600)
      })
      expect(sockets.length).toBe(2)

      act(() => {
        sockets[1].onopen?.call(sockets[1] as unknown as WebSocket, new Event('open'))
      })

      expect(result.current.connected).toBe(true)
      expect(result.current.chatStatus).not.toBeNull()
      expect(result.current.chatStatus?.kind).toBe('thinking')
      expect(result.current.recoveryEpoch).toBe(1)
    } finally {
      vi.useRealTimers()
    }
  })
})
