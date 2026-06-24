import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

/**
 * Simplified intervention integration tests for ConversationDialog.
 * The full ConversationDialog component is too large for JSDOM (MUI + hooks OOM).
 * Full integration is covered by E2E Playwright tests.
 *
 * These tests validate the intervention state integration at the hook level.
 */

describe('ConversationDialog - intervention state integration', () => {
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

  it('useChatSession exposes interventionRequest and interventionQueueLength', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    expect(typeof useChatSession).toBe('function')

    const { result } = renderHook(() => useChatSession('test-session-int'))

    expect(result.current).toHaveProperty('interventionRequest')
    expect(result.current).toHaveProperty('interventionQueueLength')
    expect(result.current.interventionRequest).toBeNull()
    expect(result.current.interventionQueueLength).toBe(0)
  })

  it('useChatSession exposes sendInterventionResponse and cancelIntervention', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('test-session-int'))

    expect(typeof result.current.sendInterventionResponse).toBe('function')
    expect(typeof result.current.cancelIntervention).toBe('function')
  })

  it('useConversationIntervention returns expected interface', async () => {
    const { useConversationIntervention } = await import('../hooks/useConversationIntervention')
    const { result } = renderHook(() => useConversationIntervention('test-session-int'))

    expect(result.current).toHaveProperty('pendingInterventions')
    expect(result.current).toHaveProperty('currentIntervention')
    expect(result.current).toHaveProperty('isSubmitting')
    expect(result.current).toHaveProperty('dialogError')
    expect(result.current).toHaveProperty('respondToIntervention')
    expect(result.current).toHaveProperty('cancelIntervention')
    expect(result.current).toHaveProperty('fetchPending')
  })
})
