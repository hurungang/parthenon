import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

describe('useChatSession', () => {
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
  })

  it('starts disconnected when sessionId is null', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession(null))
    expect(result.current.connected).toBe(false)
    expect(result.current.messages).toHaveLength(0)
  })

  it('initializes with empty messages', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))
    expect(result.current.messages).toHaveLength(0)
  })

  it('sendMessage adds a user message to the queue', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))
    act(() => {
      result.current.sendMessage('Hello agent!')
    })
    expect(result.current.chatStatus?.kind).toBe('thinking')
    expect(typeof result.current.sendMessage).toBe('function')
  })

  it('clearMessages resets messages array', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))
    act(() => {
      result.current.clearMessages()
    })
    expect(result.current.messages).toHaveLength(0)
  })

  it('applies delegating and waiting status from websocket events', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]
    expect(socket).toBeDefined()

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'delegating',
            agent_type: 'agent____research-agent',
          }),
        }),
      )
    })

    expect(result.current.chatStatus?.kind).toBe('delegating')
    expect(result.current.chatStatus?.agentType).toBe('research-agent')

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'waiting',
            agent_type: 'agent__research-agent',
          }),
        }),
      )
    })

    expect(result.current.chatStatus?.kind).toBe('waiting')
    expect(result.current.chatStatus?.agentType).toBe('research-agent')
  })

  it('applies using_tool status from websocket events', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'using_tool',
            tool_name: 'send_notification',
          }),
        }),
      )
    })

    expect(result.current.chatStatus?.kind).toBe('using_tool')
    expect(result.current.chatStatus?.toolName).toBe('send_notification')
  })

  it('preserves timeout_or_failed status after agent reply', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'timeout_or_failed',
          }),
        }),
      )
    })

    expect(result.current.chatStatus?.kind).toBe('timeout_or_failed')

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            sender_role: 'agent',
            content: 'An error occurred while processing your message. Please try again.',
          }),
        }),
      )
    })

    expect(result.current.chatStatus?.kind).toBe('timeout_or_failed')
  })

  it('clears non-terminal status after agent reply', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'waiting',
            agent_type: 'agent__research-agent',
          }),
        }),
      )
    })

    expect(result.current.chatStatus?.kind).toBe('waiting')

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            sender_role: 'agent',
            content: 'Delegated work complete.',
          }),
        }),
      )
    })

    expect(result.current.chatStatus).toBeNull()
  })
})
