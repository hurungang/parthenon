import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { ChatPage } from '../pages/chat/ChatPage'

type ChatStatusState = {
  kind: 'thinking' | 'delegating' | 'waiting' | 'using_tool' | 'timeout_or_failed'
  agentType: string | null
  toolName: string | null
  timestamp: string
} | null

const shared = vi.hoisted(() => ({
  chatStatusState: null as ChatStatusState,
  mockPost: vi.fn(),
}))

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
    messages: [],
    connected: true,
    pendingQuestion: null,
    sessionTitle: null,
    guardrailUsage: null,
    chatStatus: shared.chatStatusState,
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

    expect(screen.getByText('Delegating to agent research-agent')).toBeDefined()
    expect(screen.getByText('Waiting for delegated response…')).toBeDefined()
    expect(screen.getByTestId('chat-status-indicator')).toBeDefined()
  })

  it('renders terminal timeout or failure status in chat view', async () => {
    shared.chatStatusState = {
      kind: 'timeout_or_failed',
      agentType: null,
      toolName: null,
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
    expect(screen.getByTestId('chat-status-terminal')).toBeDefined()
  })
})
