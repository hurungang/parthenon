import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import { ConversationDialog } from '../components/agents/ConversationDialog'

/**
 * FIX-20261031-071721 (defect 1): resumed-session live delivery.
 *
 * Uses the REAL useChatSession hook (only collaborators mocked) with a mock
 * WebSocket to verify that an agent reply pushed over the WebSocket after a
 * send in a RESUMED session is appended to the rendered message list without
 * requiring dialog close/reopen.
 */

let sockets: MockWebSocket[] = []

class MockWebSocket {
  static readonly OPEN = 1
  static readonly CONNECTING = 0

  readyState = MockWebSocket.OPEN
  url = ''
  sent: string[] = []
  onopen: ((this: WebSocket, ev: Event) => unknown) | null = null
  onmessage: ((this: WebSocket, ev: MessageEvent) => unknown) | null = null
  onclose: ((this: WebSocket, ev: CloseEvent) => unknown) | null = null
  onerror: ((this: WebSocket, ev: Event) => unknown) | null = null

  constructor(url = '') {
    this.url = url
    sockets.push(this)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    this.readyState = 3
  }

  // Test helpers
  simulateOpen() {
    this.onopen?.call(this as unknown as WebSocket, new Event('open'))
  }

  simulateClose() {
    this.readyState = 3
    this.onclose?.call(
      this as unknown as WebSocket,
      new CloseEvent('close', { code: 1006, wasClean: false }),
    )
  }

  simulateMessage(payload: unknown) {
    this.onmessage?.call(
      this as unknown as WebSocket,
      new MessageEvent('message', { data: JSON.stringify(payload) }),
    )
  }
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, options?: { agentType?: string }) => {
      if (k === 'conversations.sessions.statusDelegatingToAgent') {
        return `Delegating to agent ${String(options?.agentType ?? '')}`
      }
      return k
    },
  }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn(async () => ({ data: [] })),
    post: vi.fn(),
  },
}))

vi.mock('../hooks/useAssistantModelConfig', () => ({
  useAssistantModelConfig: vi.fn(() => ({ data: null })),
}))

vi.mock('../hooks/useConversationSessions', () => ({
  useConversationSessionsPage: vi.fn(() => ({ data: undefined, isLoading: false, error: null })),
  useEndConversationSession: vi.fn(() => ({
    mutateAsync: vi.fn(),
    isPending: false,
  })),
}))

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ fallbackMessage }: { error: unknown; fallbackMessage?: string }) => (
    <div>{fallbackMessage ?? 'error'}</div>
  ),
}))

function renderResumedDialog(sessionId = 'session-1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <React.StrictMode>
      <QueryClientProvider client={qc}>
        <ConversationDialog
          open
          sessionId={sessionId}
          agentTypeId="agent-type-1"
          agentTypeName="Assistant"
          testIdPrefix="assistant-conversation"
          onClose={vi.fn()}
        />
      </QueryClientProvider>
    </React.StrictMode>,
  )
}

describe('ConversationDialog — resumed session live delivery (FIX-20261031-071721 defect 1)', () => {
  beforeEach(() => {
    sockets = []
    vi.stubGlobal('WebSocket', MockWebSocket)
    localStorage.setItem('access_token', 'test-token')
    vi.mocked(apiClient.post).mockReset()
    vi.mocked(apiClient.get).mockReset()
    vi.mocked(apiClient.get).mockResolvedValue({ data: [] } as never)
    vi.mocked(apiClient.post).mockImplementation(async (url: string) => {
      if (String(url) === '/conversations/session-1/resume') {
        return {
          data: {
            id: 'session-1',
            agent_type_id: 'agent-type-1',
            status: 'active',
            guardrail_usage: null,
            turns: [
              {
                id: 'turn-1',
                role: 'user',
                content: 'Earlier question',
                created_at: '2026-01-01T00:00:00Z',
                tool_calls: [],
              },
              {
                id: 'turn-2',
                role: 'agent',
                content: 'Earlier answer',
                created_at: '2026-01-01T00:01:00Z',
                tool_calls: [],
              },
            ],
          },
        } as never
      }
      return { data: {} } as never
    })
  })

  it('appends a live agent reply to the message list after sending in a resumed session', async () => {
    renderResumedDialog()

    // Resume completed: history rendered
    await waitFor(() => {
      expect(screen.getByText('Earlier question')).toBeDefined()
    })
    expect(screen.getByText('Earlier answer')).toBeDefined()

    // WS connected for the resumed session
    await waitFor(() => {
      expect(sockets.length).toBeGreaterThan(0)
    })
    const socket = sockets[sockets.length - 1]
    act(() => socket.simulateOpen())

    // Send a message in the resumed session
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'ping' } })
    fireEvent.click(screen.getByText('conversations.sessions.send'))

    // User message appears instantly (optimistic UI). Query must wait for
    // the async send to settle and match only the bubble (the input textarea
    // may transiently still contain the text while it clears).
    await waitFor(() => {
      expect(
        screen
          .getAllByText('ping')
          .some((el) => el.tagName === 'P'),
      ).toBe(true)
    })
    await waitFor(() => {
      expect(socket.sent.some((d) => d.includes('ping'))).toBe(true)
    })

    // Server pushes the agent reply over the SAME WebSocket
    act(() => {
      socket.simulateMessage({
        sender_role: 'agent',
        content: 'live reply 42',
        timestamp: new Date().toISOString(),
      })
    })

    // The reply MUST be visible in the live UI without exit/reopen
    await waitFor(() => {
      expect(screen.getByText('live reply 42')).toBeDefined()
    })
  })

  it('keeps the assistant reply visible after a chat_status event was also received', async () => {
    renderResumedDialog()

    await waitFor(() => {
      expect(screen.getByText('Earlier question')).toBeDefined()
    })
    await waitFor(() => {
      expect(sockets.length).toBeGreaterThan(0)
    })
    const socket = sockets[sockets.length - 1]
    act(() => socket.simulateOpen())

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'status ping' } })
    fireEvent.click(screen.getByText('conversations.sessions.send'))

    act(() => {
      socket.simulateMessage({
        type: 'chat_status',
        status: 'thinking',
        timestamp: new Date().toISOString(),
      })
    })
    act(() => {
      socket.simulateMessage({
        sender_role: 'agent',
        content: 'final live answer',
        timestamp: new Date().toISOString(),
      })
    })

    await waitFor(() => {
      expect(screen.getByText('final live answer')).toBeDefined()
    })
  })

  it('reconnects after an unexpected WS close mid-turn and recovers the persisted reply via history', async () => {
    // The resume endpoint is called once on dialog open; after the reconnect
    // recovery it is called again and now includes the agent reply (the turn
    // completed server-side while the socket was down).
    let resumeCalls = 0
    vi.mocked(apiClient.post).mockImplementation(async (url: string) => {
      if (String(url) === '/conversations/session-1/resume') {
        resumeCalls += 1
        const turns: Array<Record<string, unknown>> = [
          {
            id: 'turn-1',
            role: 'user',
            content: 'Earlier question',
            created_at: '2026-01-01T00:00:00Z',
            tool_calls: [],
          },
          {
            id: 'turn-2',
            role: 'agent',
            content: 'Earlier answer',
            created_at: '2026-01-01T00:01:00Z',
            tool_calls: [],
          },
        ]
        if (resumeCalls > 1) {
          turns.push(
            {
              id: 'turn-3',
              role: 'user',
              content: 'ping',
              created_at: '2026-01-01T00:02:00Z',
              tool_calls: [],
            },
            {
              id: 'turn-4',
              role: 'agent',
              content: 'recovered reply 77',
              created_at: '2026-01-01T00:03:00Z',
              tool_calls: [],
            },
          )
        }
        return {
          data: { id: 'session-1', agent_type_id: 'agent-type-1', status: 'active', guardrail_usage: null, turns },
        } as never
      }
      return { data: {} } as never
    })

    renderResumedDialog()

    await waitFor(() => {
      expect(screen.getByText('Earlier question')).toBeDefined()
    })
    await waitFor(() => {
      expect(sockets.length).toBeGreaterThan(0)
    })
    const socket = sockets[sockets.length - 1]
    act(() => socket.simulateOpen())

    // Send in the resumed session; the turn is in flight (thinking)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'ping' } })
    fireEvent.click(screen.getByText('conversations.sessions.send'))
    await waitFor(() => {
      expect(
        screen
          .getAllByText('ping')
          .some((el) => el.tagName === 'P'),
      ).toBe(true)
    })

    // Connection drops mid-turn; the reply never arrives on this socket
    act(() => socket.simulateClose())
    expect(screen.queryByText('recovered reply 77')).toBeNull()

    // The client must reconnect with the SAME session id...
    await waitFor(
      () => {
        expect(sockets.length).toBeGreaterThan(1)
      },
      { timeout: 8000 },
    )
    const reconnected = sockets[sockets.length - 1]
    expect(reconnected).not.toBe(socket)
    expect(reconnected.url).toContain('/sessions/session-1')

    // ...and after reconnecting, recover the persisted turn via history so the
    // reply appears live WITHOUT exit/reopen.
    act(() => reconnected.simulateOpen())
    await waitFor(
      () => {
        expect(screen.getByText('recovered reply 77')).toBeDefined()
      },
      { timeout: 8000 },
    )
    // The persisted user turn must not duplicate the optimistic message
    expect(screen.getAllByText('ping')).toHaveLength(1)
  })
})
