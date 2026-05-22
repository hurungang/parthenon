import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'

describe('Service Segregation Security Audit - Frontend Boundary Checks', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('uses API-only base URL configuration (no direct database transport hints)', async () => {
    const { API_CONFIG } = await import('../api/API_CONFIG')

    expect(API_CONFIG.BASE_URL).toBeTruthy()
    expect(API_CONFIG.BASE_URL.toLowerCase()).not.toContain('postgres')
    expect(API_CONFIG.BASE_URL.toLowerCase()).not.toContain('supabase')
    expect(API_CONFIG.BASE_URL).not.toContain(':5432')
  })

  it('uses websocket endpoint config for chat transport', async () => {
    const { API_CONFIG } = await import('../api/API_CONFIG')

    expect(API_CONFIG.WS_BASE_URL).toBeTruthy()
    expect(API_CONFIG.WS_BASE_URL.toLowerCase()).toContain('ws')
    expect(API_CONFIG.WS_BASE_URL.toLowerCase()).not.toContain('postgres')
    expect(API_CONFIG.WS_BASE_URL).not.toContain(':5432')
  })

  it('builds websocket URL from configured ws base path and auth token only', async () => {
    class MockWebSocket {
      static instances: MockWebSocket[] = []

      url: string
      readyState = 0
      onopen: ((this: WebSocket, ev: Event) => any) | null = null
      onmessage: ((this: WebSocket, ev: MessageEvent) => any) | null = null
      onclose: ((this: WebSocket, ev: CloseEvent) => any) | null = null
      onerror: ((this: WebSocket, ev: Event) => any) | null = null

      constructor(url: string) {
        this.url = url
        MockWebSocket.instances.push(this)
      }

      send = vi.fn()
      close = vi.fn()
    }

    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket)
    localStorage.setItem('access_token', 'segregation-token')

    const { useChatSession } = await import('../hooks/useChatSession')
    renderHook(() => useChatSession('session-123', 'conv-999'))

    expect(MockWebSocket.instances).toHaveLength(1)
    const wsUrl = MockWebSocket.instances[0].url
    expect(wsUrl).toContain('/ws/sessions/session-123')
    expect(wsUrl).toContain('token=segregation-token')
    expect(wsUrl).toContain('conv_session_id=conv-999')
    expect(wsUrl.toLowerCase()).not.toContain('postgres')
    expect(wsUrl).not.toContain(':5432')
  })
})
