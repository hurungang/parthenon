import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import { ConversationDialog } from '../components/agents/ConversationDialog'
import type { ChatMessage } from '../hooks/useChatSession'

// ── Mocks ─────────────────────────────────────────────────────────────────────

let mockMessages: ChatMessage[] = []
let mockChatStatus: unknown = null

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
    delegationCycles: [],
    activeDelegationCycleId: null,
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
    recoveryEpoch: 0,
    chatError: null,
    interventionRequest: null,
    interventionQueueLength: 0,
    sendInterventionResponse: vi.fn(),
    cancelIntervention: vi.fn(),
  })),
}))

const endSessionSpy = vi.fn()

vi.mock('../hooks/useConversationSessions', () => ({
  useConversationSessionsPage: vi.fn(() => ({
    data: {
      items: [
        {
          id: 'session-1',
          title: 'Current session',
          status: 'active',
          updated_at: '2026-11-01T10:00:00Z',
        },
        {
          id: 'session-2',
          title: 'Older session',
          status: 'active',
          updated_at: '2026-10-31T10:00:00Z',
        },
      ],
      total: 2,
      page: 1,
      page_size: 10,
      default_window_days: 7,
    },
    isLoading: false,
    error: null,
  })),
  useEndConversationSession: vi.fn(() => ({
    mutateAsync: endSessionSpy,
    isPending: false,
  })),
  useConversationSessions: vi.fn(() => ({
    data: [
      {
        id: 'session-1',
        title: 'Current session',
        status: 'active',
        updated_at: '2026-11-01T10:00:00Z',
      },
      {
        id: 'session-2',
        title: 'Older session',
        status: 'active',
        updated_at: '2026-10-31T10:00:00Z',
      },
    ],
    isLoading: false,
    error: null,
  })),
  useArchiveConversationSession: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
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
  default: () => null,
}))

vi.mock('../components/conversations/InlineInterventionDialog', () => ({
  InlineInterventionDialog: () => null,
}))
vi.mock('../components/conversations/InterventionPendingIndicator', () => ({
  InterventionPendingIndicator: () => null,
}))
vi.mock('../hooks/useConversationIntervention', () => ({
  useConversationIntervention: () => ({
    dialogError: null,
    isSubmitting: false,
    respondToIntervention: vi.fn(),
    cancelIntervention: vi.fn(),
  }),
}))
vi.mock('../components/ContentRenderer', () => ({
  ContentRenderer: (props: { content: string }) => props.content,
}))
vi.mock('../components/MaximizableContent', () => ({
  MaximizableContent: (props: { children: React.ReactNode }) => props.children,
}))
vi.mock('../components/agents/AgentExecutionDetailsDialog', () => ({
  AgentExecutionDetailsDialog: () => null,
}))
vi.mock('../hooks/useSessionExecutionLogStream', () => ({
  useSessionExecutionLogStream: () => ({ entries: [] }),
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

/** Resume session-1 first so the dialog has an active session + messages. */
async function renderWithResumedSession(props: Partial<Parameters<typeof ConversationDialog>[0]> = {}) {
  vi.mocked(apiClient.post).mockImplementation(async (url: string) => {
    if (String(url) === '/conversations/session-1/resume') {
      return {
        data: {
          id: 'session-1',
          status: 'active',
          guardrail_usage: null,
          turns: [
            {
              id: 'turn-1',
              role: 'user',
              content: 'Hello there',
              created_at: '2026-11-01T10:00:00Z',
              tool_calls: [],
            },
          ],
        },
      } as never
    }
    return { data: { id: 'brand-new-session' } } as never
  })
  const utils = renderDialog({ sessionId: 'session-1', ...props })
  await waitFor(() => {
    expect(screen.getByText('Hello there')).toBeDefined()
  })
  return utils
}

beforeEach(() => {
  mockMessages = []
  mockChatStatus = null
  endSessionSpy.mockClear()
  localStorage.clear()
  vi.mocked(apiClient.post).mockReset()
  vi.mocked(apiClient.post).mockResolvedValue({ data: { id: 'brand-new-session' } } as never)
})

describe('ConversationDialog — action bar', () => {
  it('renders the 4-option action bar (View All Sessions, New Session, End Session, Exit)', async () => {
    await renderWithResumedSession()
    expect(screen.getByText('conversations.sessions.viewAllSessions')).toBeDefined()
    expect(screen.getByText('conversations.sessions.newSession')).toBeDefined()
    expect(screen.getByText('conversations.sessions.end')).toBeDefined()
    expect(screen.getByText('conversations.sessions.exit')).toBeDefined()
  })

  it('New Session starts a FRESH session without ending/archiving the current one', async () => {
    await renderWithResumedSession()

    fireEvent.click(screen.getByText('conversations.sessions.newSession'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/conversations', {
        agent_type_id: 'agent-type-1',
      })
    })
    const postedUrls = vi.mocked(apiClient.post).mock.calls.map((c) => String(c[0]))
    expect(postedUrls).not.toContain('/conversations/session-1/end')
    expect(postedUrls).not.toContain('/conversations/session-1/archive')
    expect(endSessionSpy).not.toHaveBeenCalled()
    // Force-new flag must NOT be set: the current session stays active and
    // must remain resumable via View All Sessions.
    expect(localStorage.getItem('parthenon_assistant_force_new_agent-type-1')).toBeNull()

    // Message state resets to an empty new session (history cleared).
    await waitFor(() => {
      expect(screen.queryByText('Hello there')).toBeNull()
    })
  })

  it('View All Sessions lists sessions and switching resumes the chosen one', async () => {
    await renderWithResumedSession()

    fireEvent.click(screen.getByText('conversations.sessions.viewAllSessions'))

    await waitFor(() => {
      expect(screen.getByText('Older session')).toBeDefined()
    })
    expect(screen.getByText('Current session')).toBeDefined()

    // Switch to session-2 → resume endpoint called for it
    fireEvent.click(screen.getByTestId('conversation-dialog-switch-session-session-2'))
    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/conversations/session-2/resume')
    })
    // Switching must never end/archive the previous session
    const postedUrls = vi.mocked(apiClient.post).mock.calls.map((c) => String(c[0]))
    expect(postedUrls).not.toContain('/conversations/session-1/end')
    expect(postedUrls).not.toContain('/conversations/session-1/archive')
  })

  it('End Session still calls the end mutation and sets the force-new flag', async () => {
    endSessionSpy.mockResolvedValue({})
    await renderWithResumedSession()

    fireEvent.click(screen.getByText('conversations.sessions.end'))
    const confirmButtons = screen.getAllByText('conversations.sessions.end')
    fireEvent.click(confirmButtons[confirmButtons.length - 1])

    await waitFor(() => {
      expect(endSessionSpy).toHaveBeenCalledWith('session-1')
    })
    expect(localStorage.getItem('parthenon_assistant_force_new_agent-type-1')).toBe('1')
  })

  it('Exit closes the dialog without any API call', async () => {
    const onCloseSpy = vi.fn()
    await renderWithResumedSession({ onClose: onCloseSpy })
    vi.mocked(apiClient.post).mockClear()

    fireEvent.click(screen.getByText('conversations.sessions.exit'))

    expect(onCloseSpy).toHaveBeenCalled()
    expect(vi.mocked(apiClient.post).mock.calls.length).toBe(0)
  })

  it('action bar actions are disabled while a turn is streaming', async () => {
    mockChatStatus = { kind: 'thinking', timestamp: '2026-11-01T10:00:00Z' }
    await renderWithResumedSession()

    const newButton = screen
      .getByText('conversations.sessions.newSession')
      .closest('button') as HTMLButtonElement
    expect(newButton.disabled).toBe(true)
  })
})
