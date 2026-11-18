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
 * useChatSession — optimization-mode parsing and blocking.
 *
 * The optimization conversation reuses the existing chat transport. This suite
 * proves the additive parsing: the `live_test` block on an intervention (so the
 * approval card renders identically after a reconnect), the `live_test_result`
 * chunk (what actually ran), the optimizer `chat_error` codes, the
 * `chat_blocked` refusal while a decision is pending, and the visible activity
 * steps ("what it looked at") derived from the status stream.
 */
describe('useChatSession — optimization mode', () => {
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

  function emit(socket: MockWebSocket, payload: unknown) {
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

  // ── Pure parsers ─────────────────────────────────────────────────────────

  it('parseLiveTestApproval keeps the exact operation list, expiry and status', async () => {
    const { parseLiveTestApproval } = await import('../hooks/useChatSession')

    const parsed = parseLiveTestApproval({
      live_test_request_id: 'ltr-1',
      status: 'pending',
      expires_at: '2026-01-01T10:10:00.000Z',
      target_agent_type_id: 'at-1',
      operations: [
        { tool_name: 'crm____lookup', arguments: { email: 'a@b.c' }, purpose: 'lookup' },
        { tool_name: 'crm____tickets', arguments: {} },
      ],
    })

    expect(parsed).not.toBeNull()
    expect(parsed?.live_test_request_id).toBe('ltr-1')
    expect(parsed?.status).toBe('pending')
    expect(parsed?.expires_at).toBe('2026-01-01T10:10:00.000Z')
    expect(parsed?.target_agent_type_id).toBe('at-1')
    expect(parsed?.operations).toHaveLength(2)
    expect(parsed?.operations[0]).toEqual({
      tool_name: 'crm____lookup',
      arguments: { email: 'a@b.c' },
      purpose: 'lookup',
    })
    // A missing purpose degrades to null, never undefined-shaped output.
    expect(parsed?.operations[1].purpose).toBeNull()
  })

  it('parseLiveTestApproval refuses payloads without a request id (a plain ask)', async () => {
    const { parseLiveTestApproval } = await import('../hooks/useChatSession')

    expect(parseLiveTestApproval(null)).toBeNull()
    expect(parseLiveTestApproval({ operations: [] })).toBeNull()
    expect(parseLiveTestApproval({ live_test_request_id: '' })).toBeNull()
  })

  it('parseLiveTestResult reads the executed/failed outcome and defaults unknown statuses to executed', async () => {
    const { parseLiveTestResult } = await import('../hooks/useChatSession')

    const executed = parseLiveTestResult({
      type: 'live_test_result',
      live_test_request_id: 'ltr-1',
      live_test_status: 'executed',
      executed_operations: [
        { tool_name: 'crm____lookup', status: 'success', result_summary: '1 row' },
      ],
    })
    expect(executed?.live_test_status).toBe('executed')
    expect(executed?.executed_operations[0].result_summary).toBe('1 row')

    const failed = parseLiveTestResult({
      type: 'live_test_result',
      live_test_request_id: 'ltr-1',
      live_test_status: 'failed',
      live_test_error: 'permission denied',
      executed_operations: [],
    })
    expect(failed?.live_test_status).toBe('failed')
    expect(failed?.live_test_error).toBe('permission denied')

    expect(
      parseLiveTestResult({
        type: 'live_test_result',
        live_test_request_id: 'ltr-2',
        live_test_status: 'weird',
      })?.live_test_status,
    ).toBe('executed')

    // Wrong chunk type / missing id → null.
    expect(parseLiveTestResult({ type: 'chat_error' })).toBeNull()
    expect(parseLiveTestResult({ type: 'live_test_result' })).toBeNull()
  })

  // ── WS: approval proposal + result ───────────────────────────────────────

  it('hydrates the live_test proposal from an intervene_request', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('optimization-session-1'))
    const socket = sockets[0]

    emit(socket, {
      type: 'intervene_request',
      request_id: 'req-live-1',
      intervention_type: 'approval',
      reason: 'Run this live test?',
      agent_type: 'Refund Agent',
      delegation_depth: 0,
      conversation_session_id: 'optimization-session-1',
      live_test: {
        live_test_request_id: 'ltr-1',
        status: 'pending',
        expires_at: '2026-01-01T10:10:00.000Z',
        operations: [
          {
            tool_name: 'crm____lookup',
            arguments: { email: 'a@b.c' },
            purpose: 'lookup',
          },
        ],
      },
    })

    expect(result.current.interventionRequest?.live_test?.live_test_request_id).toBe('ltr-1')
    expect(result.current.interventionRequest?.live_test?.operations).toHaveLength(1)
    // The pause is live and the composer must block.
    expect(result.current.pendingIntervention).toBe(true)
    expect(result.current.chatStatus?.kind).toBe('waiting_for_human')
  })

  it('leaves live_test null for a plain ask (no approval payload)', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('optimization-session-1'))
    const socket = sockets[0]

    emit(socket, {
      type: 'intervene_request',
      request_id: 'req-ask-1',
      intervention_type: 'choice',
      reason: 'Which field?',
      choices: ['a', 'b'],
      delegation_depth: 0,
      conversation_session_id: 'optimization-session-1',
    })

    expect(result.current.interventionRequest?.live_test).toBeNull()
    expect(result.current.interventionRequest?.choices).toEqual(['a', 'b'])
  })

  it('stores the live_test_result chunk per request id', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('optimization-session-1'))
    const socket = sockets[0]

    emit(socket, {
      type: 'live_test_result',
      live_test_request_id: 'ltr-1',
      live_test_status: 'executed',
      script_run: {
        kind: 'script_run',
        script_version_id: 'sv-1',
        script_name: 'search-flights',
        script_version_label: 'v3',
        status: 'success',
        result_summary: '2 rows',
        error: null,
        duration_ms: 1200,
        tool_calls: [
          { tool_name: 'crm____lookup', status: 'success', result_summary: '1 row' },
        ],
        telemetry: {},
      },
    })

    expect(result.current.liveTestResults['ltr-1']?.live_test_status).toBe('executed')
    expect(result.current.liveTestResults['ltr-1']?.script_run?.script_name).toBe(
      'search-flights',
    )
    expect(
      result.current.liveTestResults['ltr-1']?.executed_operations[0].tool_calls[0].tool_name,
    ).toBe('crm____lookup')
  })

  // ── WS: errors, blocking, activity ───────────────────────────────────────

  it('parses the optimizer chat_error codes', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('optimization-session-1'))
    const socket = sockets[0]

    emit(socket, {
      type: 'chat_error',
      code: 'optimization_out_of_scope',
      message: 'That resource belongs to another agent type.',
    })

    expect(result.current.chatError).toEqual({
      code: 'optimization_out_of_scope',
      message: 'That resource belongs to another agent type.',
    })
  })

  it('parses chat_blocked so the composer is blocked while a decision is pending', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('optimization-session-1'))
    const socket = sockets[0]

    emit(socket, {
      type: 'chat_blocked',
      reason: 'decision_pending',
      message: 'Answer the pending request first.',
      live_test_request_id: 'ltr-1',
      expires_at: '2026-01-01T10:10:00.000Z',
    })

    expect(result.current.chatBlocked).toEqual({
      reason: 'decision_pending',
      message: 'Answer the pending request first.',
      liveTestRequestId: 'ltr-1',
      expiresAt: '2026-01-01T10:10:00.000Z',
    })
  })

  it('clears the blocked state once the pending decision is delivered/resolved', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('optimization-session-1'))
    const socket = sockets[0]

    emit(socket, { type: 'chat_blocked', reason: 'decision_pending', message: '' })
    expect(result.current.chatBlocked?.reason).toBe('decision_pending')

    emit(socket, {
      type: 'intervene_request',
      request_id: 'req-live-1',
      intervention_type: 'approval',
      reason: 'Run it?',
      delegation_depth: 0,
      conversation_session_id: 'optimization-session-1',
      live_test: {
        live_test_request_id: 'ltr-1',
        status: 'pending',
        operations: [],
      },
    })

    // The card is now displayed — the "blocked" notice is superseded.
    expect(result.current.chatBlocked).toBeNull()
  })

  it('turns every tool call into a visible activity step and closes it afterwards', async () => {
    const { useChatSession } = await import('../hooks/useChatSession')
    const { result } = renderHook(() => useChatSession('optimization-session-1'))
    const socket = sockets[0]

    emit(socket, {
      type: 'chat_status',
      status: 'using_tool',
      tool_name: 'execute_script',
      timestamp: '2026-01-01T10:00:00.000Z',
    })

    expect(result.current.activitySteps).toHaveLength(1)
    expect(result.current.activitySteps[0].toolName).toBe('execute_script')
    expect(result.current.activitySteps[0].state).toBe('running')

    emit(socket, {
      type: 'chat_status',
      status: 'using_tool',
      tool_name: 'get_execution_log',
      timestamp: '2026-01-01T10:00:05.000Z',
    })

    expect(result.current.activitySteps).toHaveLength(2)
    // Starting a new step closes the previous one.
    expect(result.current.activitySteps[0].state).toBe('done')
    expect(result.current.activitySteps[1].state).toBe('running')

    emit(socket, {
      type: 'chat_status',
      status: 'finished',
      timestamp: '2026-01-01T10:00:09.000Z',
    })

    expect(result.current.activitySteps.every((step) => step.state === 'done')).toBe(true)
  })
})
