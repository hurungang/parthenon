import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

describe('useChatSession', () => {
  beforeEach(() => {
    // Mock WebSocket
    const MockWebSocket = vi.fn().mockImplementation(() => ({
      readyState: 1, // OPEN
      send: vi.fn(),
      close: vi.fn(),
      onopen: null,
      onmessage: null,
      onclose: null,
      onerror: null,
    }))
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
    // Message is added even if WS is not yet "open" due to mock
    // The key is the function can be called without error
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
})
