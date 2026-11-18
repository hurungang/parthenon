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

    it('carries the durable resume projection (id, state, reason, message)', async () => {
      // resumable-agent-turn-persistence 6.1 — hydration must not drop the
      // paused-turn projection, otherwise a reconnect cannot render the same
      // outcome as the live socket push.
      const { parseActivityState } = await import('../hooks/useChatSession')
      const parsed = parseActivityState({
        type: 'activity_state',
        state: 'failed',
        is_terminal: true,
        pending_intervention: false,
        active_resume_id: 'resume-42',
        resume_state: 'unresumable',
        terminal_reason_code: 'expired',
        terminal_message_key: 'conversation_turn_expired',
        message: 'This confirmation expired. Nothing was applied.',
        timestamp: '2026-01-02T03:04:05Z',
      })

      expect(parsed?.kind).toBe('failed')
      expect(parsed?.activeResumeId).toBe('resume-42')
      expect(parsed?.resumeState).toBe('unresumable')
      expect(parsed?.terminalReason).toBe('expired')
      expect(parsed?.message).toBe('This confirmation expired. Nothing was applied.')
      expect(parsed?.pendingIntervention).toBe(false)
      expect(parsed?.persisted).toBe(true)
    })

    it('keeps a live resume id for an answerable waiting pause', async () => {
      const { parseActivityState } = await import('../hooks/useChatSession')
      const parsed = parseActivityState({
        type: 'activity_state',
        state: 'waiting_for_human',
        pending_intervention: true,
        active_resume_id: 'resume-live',
        resume_state: 'waiting_for_human',
      })

      expect(parsed?.activeResumeId).toBe('resume-live')
      expect(parsed?.resumeState).toBe('waiting_for_human')
      expect(parsed?.terminalReason).toBeNull()
    })

    it('ignores unknown resume states instead of widening the vocabulary', async () => {
      const { parseActivityState } = await import('../hooks/useChatSession')
      const parsed = parseActivityState({
        type: 'activity_state',
        state: 'thinking',
        resume_state: 'not_a_real_state',
      })
      expect(parsed?.resumeState).toBeNull()
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

    it('survives the terminal message and live resume id into chatStatus', async () => {
      const { useChatSession } = await import('../hooks/useChatSession')
      const { result } = renderHook(() => useChatSession('hydrate-resume'))

      sendWsMessage(sockets[0], {
        type: 'activity_state',
        state: 'timed_out',
        is_terminal: true,
        active_resume_id: 'resume-7',
        resume_state: 'unresumable',
        terminal_reason_code: 'expired',
        message: 'The confirmation window closed. Nothing was applied.',
      })

      expect(result.current.chatStatus?.kind).toBe('timed_out')
      expect(result.current.chatStatus?.activeResumeId).toBe('resume-7')
      expect(result.current.chatStatus?.resumeState).toBe('unresumable')
      expect(result.current.chatStatus?.terminalReason).toBe('expired')
      expect(result.current.chatStatus?.message).toBe(
        'The confirmation window closed. Nothing was applied.',
      )
      expect(result.current.turnInFlight).toBe(false)
    })
  })

  describe('live chat_status projection', () => {
    it('keeps the optional resume fields on a live status event', async () => {
      const { useChatSession } = await import('../hooks/useChatSession')
      const { result } = renderHook(() => useChatSession('live-resume'))

      sendWsMessage(sockets[0], {
        type: 'chat_status',
        status: 'thinking',
        active_resume_id: 'resume-9',
        resume_state: 'resuming',
        timestamp: '2026-01-01T00:00:00Z',
      })

      expect(result.current.chatStatus?.kind).toBe('thinking')
      expect(result.current.chatStatus?.activeResumeId).toBe('resume-9')
      expect(result.current.chatStatus?.resumeState).toBe('resuming')
      expect(result.current.chatStatus?.persisted).toBe(false)
    })

    it('keeps a terminal reason + message on a live terminal status event', async () => {
      const { useChatSession } = await import('../hooks/useChatSession')
      const { result } = renderHook(() => useChatSession('live-terminal'))

      sendWsMessage(sockets[0], {
        type: 'chat_status',
        status: 'timed_out',
        terminal_reason_code: 'expired',
        message: 'Expired — nothing was applied.',
      })

      expect(result.current.chatStatus?.kind).toBe('timed_out')
      expect(result.current.chatStatus?.terminalReason).toBe('expired')
      expect(result.current.chatStatus?.message).toBe('Expired — nothing was applied.')
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
