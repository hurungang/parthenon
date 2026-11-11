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
 * Persistent-activity-state hydration (persistent-agent-activity-state).
 *
 * The backend (CH) pushes an `activity_state` snapshot on every WebSocket
 * connect and returns the persisted state in `status_pong`. The hook must:
 * - accept all seven persisted states (including waiting_for_human + terminals),
 * - hydrate chatStatus / turnInFlight / pendingIntervention from the snapshot,
 * - never leave a blank window or a stuck spinner after a reconnect.
 */
describe('useChatSession — persisted activity hydration', () => {
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

  describe('parseActivityState', () => {
    it('maps every persisted state to a ChatStatus', async () => {
      const { parseActivityState } = await import('../hooks/useChatSession')
      for (const state of [
        'thinking',
        'using_tool',
        'delegating',
        'waiting_for_human',
        'finished',
        'failed',
        'timed_out',
      ]) {
        const parsed = parseActivityState({ type: 'activity_state', state })
        expect(parsed?.kind).toBe(state)
      }
    })

    it('returns null for a null/idle state', async () => {
      const { parseActivityState } = await import('../hooks/useChatSession')
      expect(parseActivityState({ type: 'activity_state', state: null })).toBeNull()
    })

    it('returns null for a non-activity message', async () => {
      const { parseActivityState } = await import('../hooks/useChatSession')
      expect(parseActivityState({ type: 'chat_status', state: 'thinking' })).toBeNull()
    })

    it('carries pending_intervention and context fields', async () => {
      const { parseActivityState } = await import('../hooks/useChatSession')
      const parsed = parseActivityState({
        type: 'activity_state',
        state: 'waiting_for_human',
        pending_intervention: true,
        agent_type: 'assistant',
        tool_name: 'human_intervene',
      })
      expect(parsed?.kind).toBe('waiting_for_human')
      expect(parsed?.pendingIntervention).toBe(true)
      expect(parsed?.agentType).toBe('assistant')
      expect(parsed?.toolName).toBe('human_intervene')
    })
  })

  describe('connect-time hydration', () => {
    it('hydrates a non-terminal state and keeps the turn in flight', async () => {
      const { useChatSession } = await import('../hooks/useChatSession')
      const { result } = renderHook(() => useChatSession('hydrate-thinking'))

      sendWsMessage(sockets[0], {
        type: 'activity_state',
        state: 'using_tool',
        tool_name: 'cc____list_agents',
        is_terminal: false,
      })

      expect(result.current.chatStatus?.kind).toBe('using_tool')
      expect(result.current.chatStatus?.toolName).toBe('cc____list_agents')
      expect(result.current.turnInFlight).toBe(true)
    })

    it('re-surfaces a pending intervention after reload', async () => {
      const { useChatSession } = await import('../hooks/useChatSession')
      const { result } = renderHook(() => useChatSession('hydrate-waiting'))

      sendWsMessage(sockets[0], {
        type: 'activity_state',
        state: 'waiting_for_human',
        pending_intervention: true,
        is_terminal: false,
      })

      expect(result.current.chatStatus?.kind).toBe('waiting_for_human')
      expect(result.current.pendingIntervention).toBe(true)
      expect(result.current.turnInFlight).toBe(true)
    })

    it('a terminal hydration clears the spinner / in-flight window', async () => {
      const { useChatSession } = await import('../hooks/useChatSession')
      const { result } = renderHook(() => useChatSession('hydrate-terminal'))

      sendWsMessage(sockets[0], {
        type: 'activity_state',
        state: 'finished',
        is_terminal: true,
      })

      expect(result.current.chatStatus?.kind).toBe('finished')
      expect(result.current.turnInFlight).toBe(false)
      expect(result.current.pendingIntervention).toBe(false)
    })

    it('a null (idle) hydration clears any lingering status', async () => {
      const { useChatSession } = await import('../hooks/useChatSession')
      const { result } = renderHook(() => useChatSession('hydrate-idle'))

      sendWsMessage(sockets[0], { type: 'activity_state', state: null })

      expect(result.current.chatStatus).toBeNull()
      expect(result.current.turnInFlight).toBe(false)
    })
  })

  describe('status_pong reconciliation', () => {
    it('reads the persisted state from status_pong rather than the booleans', async () => {
      const { useChatSession } = await import('../hooks/useChatSession')
      const { result } = renderHook(() => useChatSession('pong-persisted'))

      sendWsMessage(sockets[0], {
        type: 'status_pong',
        turn_in_flight: true,
        intervention_pending: false,
        state: 'using_tool',
        tool_name: 'cc____list_agents',
        is_terminal: false,
      })

      expect(result.current.chatStatus?.kind).toBe('using_tool')
      expect(result.current.turnInFlight).toBe(true)
    })

    it('closes the window from a terminal persisted state', async () => {
      const { useChatSession } = await import('../hooks/useChatSession')
      const { result } = renderHook(() => useChatSession('pong-terminal'))

      sendWsMessage(sockets[0], {
        type: 'status_pong',
        turn_in_flight: false,
        intervention_pending: false,
        state: 'timed_out',
        is_terminal: true,
      })

      expect(result.current.chatStatus?.kind).toBe('timed_out')
      expect(result.current.turnInFlight).toBe(false)
    })
  })
})
