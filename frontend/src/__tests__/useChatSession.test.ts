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
    shared.mockGet.mockReset()
    shared.mockGet.mockResolvedValue({ data: [] })
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
    expect(result.current.delegationSnippetsCollapsed).toBe(true)
    expect(result.current.delegationSnippets).toHaveLength(1)

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'waiting',
            agent_type: 'agent__research-agent',
            receiver_session_id: 'delegated-session-123',
          }),
        }),
      )
    })

    expect(result.current.chatStatus?.kind).toBe('waiting')
    expect(result.current.chatStatus?.agentType).toBe('research-agent')
    expect(result.current.chatStatus?.receiverSessionId).toBe('delegated-session-123')
    expect(result.current.delegationExecutionSessionId).toBe('delegated-session-123')
    expect(result.current.delegationSnippets).toHaveLength(2)
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
    expect(result.current.delegationSnippets).toHaveLength(1)
    expect(result.current.delegationSnippets[0]?.toolName).toBe('send_notification')
  })

  it('toggles folded delegation snippet state from true to false', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    expect(result.current.delegationSnippetsCollapsed).toBe(true)

    act(() => {
      result.current.toggleDelegationSnippetsCollapsed()
    })

    expect(result.current.delegationSnippetsCollapsed).toBe(false)
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
            receiver_session_id: 'delegated-session-123',
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
    expect(result.current.delegationCompleted).toBe(true)
    expect(result.current.delegationExecutionLogAvailable).toBe(true)
  })

  it('streams execution log title snippets while delegation is active', async () => {
    shared.mockGet.mockResolvedValue({
      data: [
        {
          id: 'log-1',
          timestamp: new Date().toISOString(),
          message: 'Delegation tool call started',
        },
      ],
    })

    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'delegating',
            agent_type: 'agent__research-agent',
            receiver_session_id: 'delegated-session-123',
          }),
        }),
      )
    })

    await waitFor(() => {
      expect(result.current.delegationSnippets.some((s) => s.kind === 'log_title')).toBe(true)
    })

    const latest = result.current.delegationSnippets[result.current.delegationSnippets.length - 1]
    expect(latest?.kind).toBe('log_title')
    expect(latest?.logTitle).toBe('Delegation tool call started')
  })

  it('starts a fresh delegation snippet cycle after a new user message', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'delegating',
            agent_type: 'agent__research-agent',
            timestamp: '2020-01-01T00:00:00.000Z',
          }),
        }),
      )
    })

    expect(result.current.delegationSnippets).toHaveLength(1)
    expect(result.current.delegationSnippets[0]?.agentType).toBe('research-agent')

    act(() => {
      result.current.sendMessage('Please check another project id')
    })

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'delegating',
            agent_type: 'agent__supabase-agent',
            timestamp: '2030-01-01T00:00:00.000Z',
          }),
        }),
      )
    })

    expect(result.current.delegationSnippets).toHaveLength(1)
    expect(result.current.delegationSnippets[0]?.agentType).toBe('supabase-agent')
  })

  it('starts a fresh active delegation cycle after completion when user sends a new message', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'delegating',
            agent_type: 'agent__research-agent',
            timestamp: '2020-01-01T00:00:00.000Z',
          }),
        }),
      )
    })

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'waiting',
            agent_type: 'agent__research-agent',
            receiver_session_id: 'delegated-session-1',
            timestamp: '2020-01-01T00:00:10.000Z',
          }),
        }),
      )
    })

    expect(result.current.delegationSnippets).toHaveLength(2)

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            sender_role: 'agent',
            content: 'First delegation completed.',
            timestamp: '2020-01-01T00:00:20.000Z',
          }),
        }),
      )
    })

    act(() => {
      result.current.sendMessage('Run another delegated task')
    })

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'delegating',
            agent_type: 'agent__supabase-agent',
            timestamp: '2020-01-01T00:01:00.000Z',
          }),
        }),
      )
    })

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'waiting',
            agent_type: 'agent__supabase-agent',
            receiver_session_id: 'delegated-session-2',
            timestamp: '2020-01-01T00:01:10.000Z',
          }),
        }),
      )
    })

    const snippetSummaries = result.current.delegationSnippets
      .filter((snippet) => snippet.kind === 'delegating' || snippet.kind === 'waiting')
      .map((snippet) => `${snippet.kind}:${snippet.agentType}`)

    // Expected behavior: active cycle should start fresh and not reuse previous cycle snippet state.
    expect(snippetSummaries).toEqual([
      'delegating:supabase-agent',
      'waiting:supabase-agent',
    ])
  })

  it('keeps rapid consecutive delegation statuses in a single cycle for one user turn', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-123'))

    const socket = sockets[0]
    const sharedTimestamp = '2040-01-01T00:00:00.000Z'

    act(() => {
      result.current.sendMessage('Run delegated analysis now')
    })

    act(() => {
      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'delegating',
            agent_type: 'agent__research-agent',
            timestamp: sharedTimestamp,
          }),
        }),
      )

      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'waiting',
            agent_type: 'agent__research-agent',
            receiver_session_id: 'delegated-session-race',
            timestamp: sharedTimestamp,
          }),
        }),
      )

      socket.onmessage?.call(
        socket as unknown as WebSocket,
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'chat_status',
            status: 'delegating',
            agent_type: 'agent__research-agent',
            timestamp: sharedTimestamp,
          }),
        }),
      )
    })

    expect(result.current.delegationCycles).toHaveLength(1)
    expect(result.current.activeDelegationCycleId).toBe(result.current.delegationCycles[0]?.id)
    expect(result.current.delegationSnippets).toHaveLength(3)
    expect(result.current.delegationSnippets.map((snippet) => snippet.kind)).toEqual([
      'delegating',
      'waiting',
      'delegating',
    ])
    expect(result.current.delegationSnippets.every((snippet) => snippet.timestamp === sharedTimestamp)).toBe(true)
    expect(result.current.delegationExecutionSessionId).toBe('delegated-session-race')
  })
})
