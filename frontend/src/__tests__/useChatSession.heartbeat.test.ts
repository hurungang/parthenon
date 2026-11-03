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

describe('useChatSession — thinking_heartbeat keepalive (FIX-20261031-091657)', () => {
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

  it('heartbeat refreshes the thinking status timestamp without changing kind', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('hb-session'))

    act(() => {
      result.current.sendMessage('Hello')
    })
    expect(result.current.chatStatus?.kind).toBe('thinking')

    const before = result.current.chatStatus?.timestamp
    expect(before).toBeTruthy()

    act(() => {
      sockets[0].onmessage?.call(
        sockets[0] as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({ type: 'chat_status', status: 'thinking_heartbeat' }),
        }),
      )
    })

    expect(result.current.chatStatus?.kind).toBe('thinking')
    expect(result.current.chatStatus?.timestamp).not.toBe(before)
    // No heartbeat content leaked into the message list
    expect(result.current.messages).toHaveLength(1)
  })

  it('timeout_or_failed status is surfaced for terminal error rendering', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('to-session'))

    act(() => {
      result.current.sendMessage('Hello')
    })

    act(() => {
      sockets[0].onmessage?.call(
        sockets[0] as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({ type: 'chat_status', status: 'timeout_or_failed' }),
        }),
      )
    })

    expect(result.current.chatStatus?.kind).toBe('timeout_or_failed')
  })
})
