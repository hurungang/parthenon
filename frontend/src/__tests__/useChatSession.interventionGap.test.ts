import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

const shared = vi.hoisted(() => ({
  mockGet: vi.fn(),
}))

vi.mock('../api/apiClient', () => ({
  default: { get: shared.mockGet },
}))

describe('useChatSession — intervention gap reproduction', () => {
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
      this.send = (data: string) => { this.sent.push(data) }
      sockets.push(this)
    }
    send: (data: string) => void
    close = vi.fn()
  }

  function send(payload: unknown) {
    act(() => {
      sockets[0].onmessage?.call(
        sockets[0] as unknown as WebSocket,
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

  it('never blanks between thinking → using_tool → silence → intervene_request', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('gap-session'))

    act(() => { result.current.sendMessage('Create a new agent type') })
    expect(result.current.chatStatus?.kind).toBe('thinking')
    expect(result.current.turnInFlight).toBe(true)

    send({ type: 'chat_status', status: 'thinking' })
    expect(result.current.chatStatus?.kind).toBe('thinking')

    send({ type: 'chat_status', status: 'using_tool', tool_name: 'cc__list_management_tools' })
    console.log('after using_tool:', result.current.chatStatus, 'turnInFlight=', result.current.turnInFlight, 'cycles=', result.current.delegationCycles.length)
    expect(result.current.chatStatus?.kind).toBe('using_tool')
    expect(result.current.turnInFlight).toBe(true)

    send({ type: 'chat_status', status: 'using_tool', tool_name: 'cc__invoke_management_tool' })
    expect(result.current.chatStatus?.kind).toBe('using_tool')
    expect(result.current.turnInFlight).toBe(true)

    // 22s silence — heartbeat keeps the current status alive
    send({ type: 'chat_status', status: 'thinking_heartbeat' })
    expect(result.current.chatStatus?.kind).toBe('using_tool')
    expect(result.current.turnInFlight).toBe(true)

    // intervene_request arrives
    send({
      type: 'intervene_request',
      request_id: 'req-1',
      intervention_type: 'approval',
      reason: 'confirm?',
      conversation_session_id: 'gap-session',
    })
    expect(result.current.chatStatus?.kind).toBe('waiting_for_human')
    expect(result.current.turnInFlight).toBe(true)
  })
})
