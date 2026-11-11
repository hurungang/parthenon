import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import { ConversationDialog } from '../components/agents/ConversationDialog'
import type { ChatMessage, ChatStatus, DelegationCycle } from '../hooks/useChatSession'

// ── Mocks ─────────────────────────────────────────────────────────────────────

let mockMessages: ChatMessage[] = []
let mockChatStatus: ChatStatus | null = null
let mockDelegationCycles: DelegationCycle[] = []
let mockActiveDelegationCycleId: string | null = null
let mockTurnInFlight = false

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

vi.mock('../hooks/useChatSession', () => ({
  useChatSession: vi.fn(() => ({
    messages: mockMessages,
    connected: true,
    pendingQuestion: null,
    sessionTitle: null,
    guardrailUsage: null,
    chatStatus: mockChatStatus,
    delegationCycles: mockDelegationCycles,
    activeDelegationCycleId: mockActiveDelegationCycleId,
    delegationSnippets: [],
    delegationSnippetsCollapsed: true,
    delegationCompleted: false,
    delegationExecutionLogAvailable: false,
    delegationExecutionSessionId: null,
    setDelegationSnippetsCollapsed: vi.fn(),
    toggleDelegationSnippetsCollapsed: vi.fn(),
    hydrateDelegationFromHistory: vi.fn(),
    sendMessage: vi.fn(() => true),
    clearMessages: vi.fn(),
    chatError: null,
    interventionRequest: null,
    interventionQueueLength: 0,
    sendInterventionResponse: vi.fn(),
    cancelIntervention: vi.fn(),
    recoveryEpoch: 0,
    turnInFlight: mockTurnInFlight,
  })),
}))

const endSessionSpy = vi.fn()

vi.mock('../hooks/useConversationSessions', () => ({
  useConversationSessionsPage: vi.fn(() => ({ data: undefined, isLoading: false, error: null })),
  useEndConversationSession: vi.fn(() => ({
    mutateAsync: endSessionSpy,
    isPending: false,
  })),
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

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ fallbackMessage }: { error: unknown; fallbackMessage?: string }) => (
    <div>{fallbackMessage ?? 'error'}</div>
  ),
}))

function renderDialog(props: Partial<Parameters<typeof ConversationDialog>[0]> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onClose = props.onClose ?? vi.fn()
  const utils = render(
    <QueryClientProvider client={qc}>
      <ConversationDialog
        open
        sessionId={null}
        agentTypeId="agent-type-1"
        agentTypeName="Assistant"
        onClose={onClose}
        {...props}
      />
    </QueryClientProvider>,
  )
  return { ...utils, onClose }
}

beforeEach(() => {
  mockMessages = []
  mockChatStatus = null
  mockDelegationCycles = []
  mockActiveDelegationCycleId = null
  mockTurnInFlight = false
  endSessionSpy.mockClear()
  vi.mocked(apiClient.post).mockReset()
  vi.mocked(apiClient.post).mockResolvedValue({ data: {} } as never)
})

describe('ConversationDialog — assistant content rendering', () => {
  it('renders an assistant markdown reply as formatted markdown (heading, code, link)', () => {
    mockMessages = [
      {
        id: 'm1',
        role: 'agent',
        content:
          '## Deployment Summary\n\nRun `npm run build` and see [the docs](https://example.com).',
        timestamp: '2026-01-01T00:00:00Z',
      },
    ]
    renderDialog()

    const heading = document.querySelectorAll('h2')
    const contentHeading = Array.from(heading).find((el) =>
      el.textContent?.includes('Deployment Summary'),
    )
    expect(contentHeading).toBeDefined()
    expect(document.querySelector('code')?.textContent).toContain('npm run build')
    const link = document.querySelector('a')
    expect(link?.getAttribute('href')).toBe('https://example.com')
    // Raw markdown syntax must not be visible
    expect(screen.queryByText(/## Deployment Summary/)).toBeNull()
  })

  it('renders assistant HTML content as sanitized HTML', () => {
    mockMessages = [
      {
        id: 'm2',
        role: 'agent',
        content: '<p>Report ready</p><script>alert(1)</script>',
        timestamp: '2026-01-01T00:00:00Z',
      },
    ]
    renderDialog()

    expect(screen.getByText(/Report ready/)).toBeDefined()
    expect(screen.queryByText('alert(1)')).toBeNull()
  })

  it('keeps user messages as plain text bubbles (raw markdown visible)', () => {
    mockMessages = [
      {
        id: 'm3',
        role: 'user',
        content: 'Summarize **this** for me',
        timestamp: '2026-01-01T00:00:00Z',
      },
    ]
    renderDialog()

    expect(screen.getByText(/Summarize \*\*this\*\* for me/)).toBeDefined()
    expect(document.querySelector('strong')).toBeNull()
  })
})

describe('ConversationDialog — close vs end session semantics', () => {
  it('closing the dialog does NOT call end or archive APIs', async () => {
    const onCloseSpy = vi.fn()
    renderDialog({ sessionId: 'session-1', onClose: onCloseSpy })

    // Wait for resume to complete
    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/conversations/session-1/resume')
    })

    fireEvent.click(screen.getByText('conversations.sessions.exit'))

    await waitFor(() => {
      expect(onCloseSpy).toHaveBeenCalled()
    })
    // Exit must not archive or end the session
    const postedUrls = vi.mocked(apiClient.post).mock.calls.map((c) => String(c[0]))
    expect(postedUrls).not.toContain('/conversations/session-1/end')
    expect(postedUrls).not.toContain('/conversations/session-1/archive')
    expect(endSessionSpy).not.toHaveBeenCalled()
  })

  it('explicit end-session action calls the end mutation', async () => {
    endSessionSpy.mockResolvedValue({})
    vi.mocked(apiClient.post).mockImplementation(async (url: string) => {
      if (String(url) === '/conversations/session-1/resume') {
        return { data: { id: 'session-1', turns: [] } } as never
      }
      return { data: {} } as never
    })
    const onCloseSpy = vi.fn()
    renderDialog({ sessionId: 'session-1', onClose: onCloseSpy })

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/conversations/session-1/resume')
    })

    fireEvent.click(screen.getByText('conversations.sessions.end'))
    // Confirm in the end-session dialog (two buttons share the key; take the one in the confirm dialog)
    const confirmButtons = screen.getAllByText('conversations.sessions.end')
    fireEvent.click(confirmButtons[confirmButtons.length - 1])

    await waitFor(() => {
      expect(endSessionSpy).toHaveBeenCalledWith('session-1')
    })
    expect(onCloseSpy).toHaveBeenCalled()
  })

  it('resume loads full prior history into the dialog', async () => {
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
                content: 'What is the status?',
                created_at: '2026-01-01T00:00:00Z',
                tool_calls: [],
              },
              {
                id: 'turn-2',
                role: 'agent',
                content: 'All systems operational.',
                created_at: '2026-01-01T00:01:00Z',
                tool_calls: [],
              },
            ],
          },
        } as never
      }
      return { data: {} } as never
    })

    renderDialog({ sessionId: 'session-1' })

    await waitFor(() => {
      expect(screen.getByText('What is the status?')).toBeDefined()
    })
    expect(screen.getByText('All systems operational.')).toBeDefined()
  })
})

describe('ConversationDialog — in-flight activity indicator invariant', () => {
  // FIX-20261109-BUG: reproduction for the blank chat window. On a resumed
  // assistant session, `hydrateDelegationFromHistory` synthesizes delegation
  // cycles from persisted `using_tool` tool_calls. When a new turn is in
  // flight (`turnInFlight === true`) with `chatStatus.kind === 'using_tool'`
  // and NO toolName, the standalone delegation status line is suppressed
  // (cycles exist) and the in-cycle live status line is suppressed (statusLine
  // is null without a toolName) — leaving the window completely blank until
  // the next event arrives. The thinking bubble must render instead.
  it('shows the thinking bubble during an in-flight turn when no delegation status indicator renders', async () => {
    mockMessages = [
      {
        id: 'm1',
        role: 'user',
        content: 'Do the thing',
        timestamp: '2026-01-01T00:00:00Z',
      },
    ]
    // Hydrated cycle from history (non-empty → suppresses the standalone line)
    mockDelegationCycles = [
      {
        id: 'cycle-1',
        startedAt: '2026-01-01T00:00:05Z',
        snippets: [
          {
            id: 's1',
            kind: 'using_tool',
            agentType: null,
            toolName: 'read_file',
            logTitle: null,
            timestamp: '2026-01-01T00:00:05Z',
          },
        ],
        snippetsCollapsed: true,
        completed: false,
        executionLogAvailable: false,
        executionSessionId: null,
      },
    ]
    mockActiveDelegationCycleId = 'cycle-1'
    // LLM-inference phase: last event was using_tool with no tool name
    mockChatStatus = {
      kind: 'using_tool',
      agentType: null,
      toolName: null,
      receiverSessionId: null,
      timestamp: '2026-01-01T00:00:10Z',
    }
    mockTurnInFlight = true

    renderDialog({ sessionId: 'session-1' })

    await waitFor(() => {
      expect(screen.getByText('Do the thing')).toBeDefined()
    })

    // Some activity indicator must be visible: the thinking bubble renders
    // under the shared chat-status-indicator testid with the statusThinking text.
    const indicators = screen.getAllByTestId('conversation-dialog-chat-status-indicator')
    expect(indicators.length).toBeGreaterThan(0)
    expect(screen.getByText('conversations.sessions.statusThinking')).toBeDefined()
  })
})
