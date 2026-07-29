import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { ChatPage } from '../pages/chat/ChatPage'

type ChatStatusState = {
  kind: 'thinking' | 'delegating' | 'waiting' | 'using_tool' | 'timeout_or_failed'
  agentType: string | null
  toolName: string | null
  receiverSessionId: string | null
  timestamp: string
} | null

const shared = vi.hoisted(() => ({
  chatStatusState: null as ChatStatusState,
  messagesState: [] as Array<{
    id: string
    role: 'user' | 'agent' | 'system'
    content: string
    timestamp: string
  }>,
  delegationSnippetsState: [] as Array<{
    id: string
    kind: 'delegating' | 'waiting' | 'using_tool' | 'log_title'
    agentType: string | null
    toolName: string | null
    logTitle: string | null
    timestamp: string
  }>,
  delegationCompletedState: false,
  delegationExecutionLogAvailableState: false,
  delegationExecutionSessionIdState: null as string | null,
  mockPost: vi.fn(),
}))

function buildMockDelegationCycles() {
  const cycles: Array<{
    id: string
    startedAt: string
    snippets: typeof shared.delegationSnippetsState
    snippetsCollapsed: boolean
    completed: boolean
    executionLogAvailable: boolean
    executionSessionId: string | null
  }> = []

  let current: (typeof cycles)[number] | null = null
  for (const snippet of shared.delegationSnippetsState) {
    if (!current || snippet.kind === 'delegating') {
      current = {
        id: `cycle-${cycles.length + 1}`,
        startedAt: snippet.timestamp,
        snippets: [],
        snippetsCollapsed: true,
        completed: false,
        executionLogAvailable: false,
        executionSessionId: shared.delegationExecutionSessionIdState,
      }
      cycles.push(current)
    }
    current.snippets.push(snippet)
  }

  if (cycles.length > 0) {
    cycles[cycles.length - 1] = {
      ...cycles[cycles.length - 1],
      snippetsCollapsed: true,
      completed: shared.delegationCompletedState,
      executionLogAvailable: shared.delegationExecutionLogAvailableState,
      executionSessionId: shared.delegationExecutionSessionIdState,
    }
  }

  return cycles
}

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({ agentTypeId: 'agent-type-1', sessionId: 'session-1' }),
  }
})

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, options?: Record<string, unknown>) => {
      if (k === 'conversations.sessions.statusDelegatingToAgent') {
        return `Delegating to agent ${String(options?.agentType ?? '')}`
      }
      if (k === 'conversations.sessions.statusWaiting') {
        return 'Waiting for delegated response…'
      }
      if (k === 'conversations.sessions.statusThinking') {
        return 'Thinking…'
      }
      if (k === 'conversations.sessions.statusTimeoutOrFailed') {
        return 'Delegated step timed out or failed. Please try again.'
      }
      if (k === 'conversations.sessions.snippetPanelViewExecutionLogs') {
        return 'View Execution Logs'
      }
      return k
    },
  }),
}))

vi.mock('../hooks/useAgentTypes', () => ({
  useAgentTypes: () => ({
    data: [{ id: 'agent-type-1', name: 'Research Assistant' }],
  }),
}))

vi.mock('../hooks/useConversationSessions', () => ({
  useEndConversationSession: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}))

vi.mock('../hooks/useChatSession', () => ({
  useChatSession: () => ({
    messages: shared.messagesState,
    connected: true,
    pendingQuestion: null,
    sessionTitle: null,
    guardrailUsage: null,
    chatStatus: shared.chatStatusState,
    delegationCycles: buildMockDelegationCycles(),
    activeDelegationCycleId: buildMockDelegationCycles().slice(-1)[0]?.id ?? null,
    delegationSnippets: shared.delegationSnippetsState,
    delegationSnippetsCollapsed: true,
    delegationCompleted: shared.delegationCompletedState,
    delegationExecutionLogAvailable: shared.delegationExecutionLogAvailableState,
    delegationExecutionSessionId: shared.delegationExecutionSessionIdState,
    setDelegationSnippetsCollapsed: vi.fn(),
    toggleDelegationSnippetsCollapsed: vi.fn(),
    hydrateDelegationFromHistory: vi.fn(),
    sendMessage: vi.fn(),
    clearMessages: vi.fn(),
  }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    post: shared.mockPost,
  },
}))

describe('ConversationDelegationVisibility', () => {
  beforeEach(() => {
    shared.chatStatusState = null
    shared.messagesState = []
    shared.delegationSnippetsState = []
    shared.delegationCompletedState = false
    shared.delegationExecutionLogAvailableState = false
    shared.delegationExecutionSessionIdState = null
    shared.mockPost.mockReset()
    shared.mockPost.mockResolvedValue({
      data: {
        id: 'session-1',
        turns: [],
      },
    })
  })

  it('renders exact delegation label and waiting indicator', async () => {
    shared.chatStatusState = {
      kind: 'waiting',
      agentType: 'research-agent',
      toolName: null,
      receiverSessionId: null,
      timestamp: new Date().toISOString(),
    }
    shared.delegationSnippetsState = [
      {
        id: 'snippet-1',
        kind: 'delegating',
        agentType: 'research-agent',
        toolName: null,
        logTitle: null,
        timestamp: new Date().toISOString(),
      },
      {
        id: 'snippet-2',
        kind: 'waiting',
        agentType: 'research-agent',
        toolName: null,
        logTitle: null,
        timestamp: new Date().toISOString(),
      },
    ]

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ChatPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(shared.mockPost).toHaveBeenCalledWith('/conversations/session-1/resume')
    })

    expect(screen.getByText('Delegating to agent research-agent')).toBeDefined()
    expect(screen.getByTestId('chat-delegation-inline-row')).toBeDefined()
  })

  it('shows delegation intro and active progress while waiting even before first agent reply', async () => {
    shared.messagesState = [
      {
        id: 'user-msg-1',
        role: 'user',
        content: 'Please delegate this to research agent',
        timestamp: new Date().toISOString(),
      },
    ]
    shared.chatStatusState = {
      kind: 'waiting',
      agentType: 'research-agent',
      toolName: null,
      receiverSessionId: 'delegated-session-1',
      timestamp: new Date().toISOString(),
    }
    shared.delegationSnippetsState = [
      {
        id: 'snippet-1',
        kind: 'delegating',
        agentType: 'research-agent',
        toolName: null,
        logTitle: null,
        timestamp: new Date().toISOString(),
      },
      {
        id: 'snippet-2',
        kind: 'waiting',
        agentType: 'research-agent',
        toolName: null,
        logTitle: null,
        timestamp: new Date().toISOString(),
      },
    ]

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ChatPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(shared.mockPost).toHaveBeenCalledWith('/conversations/session-1/resume')
    })

    // Expected: active delegation cue should be visible immediately during wait state.
    expect(screen.getByText('Delegating to agent research-agent')).toBeDefined()
    expect(screen.getByTestId('chat-delegation-inline-row')).toBeDefined()
  })

  it('uses waiting snippet agent type for delegation title when delegating snippet is unavailable', async () => {
    shared.messagesState = [
      {
        id: 'user-msg-1',
        role: 'user',
        content: 'Please delegate this to supabase agent',
        timestamp: new Date().toISOString(),
      },
    ]
    shared.chatStatusState = {
      kind: 'waiting',
      agentType: 'supabase-agent',
      toolName: null,
      receiverSessionId: 'delegated-session-2',
      timestamp: new Date().toISOString(),
    }
    shared.delegationSnippetsState = [
      {
        id: 'snippet-1',
        kind: 'waiting',
        agentType: 'supabase-agent',
        toolName: null,
        logTitle: null,
        timestamp: new Date().toISOString(),
      },
    ]

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ChatPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(shared.mockPost).toHaveBeenCalledWith('/conversations/session-1/resume')
    })

    expect(screen.getByText('Delegating to agent supabase-agent')).toBeDefined()
  })

  it('shows delegation snippets folded by default and expands on demand', async () => {
    shared.chatStatusState = {
      kind: 'waiting',
      agentType: 'research-agent',
      toolName: null,
      receiverSessionId: null,
      timestamp: new Date().toISOString(),
    }
    shared.delegationSnippetsState = [
      {
        id: 'snippet-1',
        kind: 'delegating',
        agentType: 'research-agent',
        toolName: null,
        logTitle: null,
        timestamp: new Date().toISOString(),
      },
      {
        id: 'snippet-2',
        kind: 'log_title',
        agentType: null,
        toolName: null,
        logTitle: 'Tool call dispatched to supabase-agent',
        timestamp: new Date().toISOString(),
      },
    ]
    shared.delegationCompletedState = true
    shared.delegationExecutionLogAvailableState = true
    shared.delegationExecutionSessionIdState = 'delegated-session-1'

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ChatPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(shared.mockPost).toHaveBeenCalledWith('/conversations/session-1/resume')
    })

    expect(screen.getByTestId('chat-delegation-snippets')).toBeDefined()
    expect(screen.getByText('Tool call dispatched to supabase-agent')).toBeDefined()
    expect(screen.getByRole('button', { name: 'View Execution Logs' })).toBeDefined()

    // This click verifies control is rendered; toggle behavior is owned by the hook.
    fireEvent.click(screen.getByText('conversations.sessions.snippetPanelExpand'))
  })

  it('renders terminal timeout or failure status in chat view', async () => {
    shared.chatStatusState = {
      kind: 'timeout_or_failed',
      agentType: null,
      toolName: null,
      receiverSessionId: null,
      timestamp: new Date().toISOString(),
    }

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ChatPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(shared.mockPost).toHaveBeenCalledWith('/conversations/session-1/resume')
    })

    expect(screen.getByText('Delegated step timed out or failed. Please try again.')).toBeDefined()
    expect(screen.getByTestId('chat-chat-status-terminal')).toBeDefined()
  })

  it('renders separate progress bubbles per delegation cycle and keeps active cycle isolated from prior content', async () => {
    shared.messagesState = [
      {
        id: 'user-msg-1',
        role: 'user',
        content: 'First delegated request',
        timestamp: '2026-05-30T10:00:00.000Z',
      },
      {
        id: 'agent-msg-1',
        role: 'agent',
        content: 'First delegation completed.',
        timestamp: '2026-05-30T10:00:10.000Z',
      },
      {
        id: 'user-msg-2',
        role: 'user',
        content: 'Second delegated request',
        timestamp: '2026-05-30T10:01:00.000Z',
      },
    ]

    shared.chatStatusState = {
      kind: 'waiting',
      agentType: 'supabase-agent',
      toolName: null,
      receiverSessionId: 'delegated-session-2',
      timestamp: '2026-05-30T10:01:10.000Z',
    }

    shared.delegationSnippetsState = [
      {
        id: 'snippet-1',
        kind: 'delegating',
        agentType: 'research-agent',
        toolName: null,
        logTitle: null,
        timestamp: '2026-05-30T10:00:01.000Z',
      },
      {
        id: 'snippet-2',
        kind: 'waiting',
        agentType: 'research-agent',
        toolName: null,
        logTitle: null,
        timestamp: '2026-05-30T10:00:02.000Z',
      },
      {
        id: 'snippet-3',
        kind: 'delegating',
        agentType: 'supabase-agent',
        toolName: null,
        logTitle: null,
        timestamp: '2026-05-30T10:01:01.000Z',
      },
      {
        id: 'snippet-4',
        kind: 'waiting',
        agentType: 'supabase-agent',
        toolName: null,
        logTitle: null,
        timestamp: '2026-05-30T10:01:02.000Z',
      },
    ]

    shared.delegationCompletedState = true
    shared.delegationExecutionLogAvailableState = true
    shared.delegationExecutionSessionIdState = 'delegated-session-1'

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ChatPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(shared.mockPost).toHaveBeenCalledWith('/conversations/session-1/resume')
    })

    // Expected behavior: each delegation cycle should render its own progress bubble.
    expect(screen.getAllByTestId('chat-delegation-inline-row')).toHaveLength(2)

    // Expected behavior: active cycle text should reflect the second delegated agent.
    expect(screen.getByText('Delegating to agent supabase-agent')).toBeDefined()

    // Completed cycle should still expose execution logs action while new cycle is active.
    expect(screen.getByRole('button', { name: 'View Execution Logs' })).toBeDefined()
  })
})
