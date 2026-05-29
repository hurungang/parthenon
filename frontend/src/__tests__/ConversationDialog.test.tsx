import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import apiClient from '../api/apiClient'
import { ConversationDialog } from '../components/agents/ConversationDialog'

const sendMessageSpy = vi.fn(() => true)
const endSessionSpy = vi.fn()
let connectedState = false
let guardrailUsageState: Record<string, unknown> | null = null
let chatStatusState:
  | {
      kind: 'thinking' | 'delegating' | 'waiting' | 'using_tool' | 'timeout_or_failed'
      agentType: string | null
      toolName: string | null
      timestamp: string
    }
  | null = null

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, options?: { value?: string }) => (options?.value ? `${k} ${options.value}` : k),
  }),
}))

vi.mock('../hooks/useChatSession', () => ({
  useChatSession: vi.fn(() => ({
    messages: [],
    connected: connectedState,
    pendingQuestion: null,
    sessionTitle: null,
    guardrailUsage: guardrailUsageState,
    chatStatus: chatStatusState,
    sendMessage: sendMessageSpy,
    clearMessages: vi.fn(),
  })),
}))

vi.mock('../hooks/useConversationSessions', () => ({
  useEndConversationSession: vi.fn(() => ({
    mutateAsync: endSessionSpy,
    isPending: false,
  })),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    post: vi.fn(),
  },
}))

vi.mock('../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ fallbackMessage }: { error: unknown; fallbackMessage?: string }) => (
    <div>{fallbackMessage ?? 'error'}</div>
  ),
}))

describe('ConversationDialog', () => {
  beforeEach(() => {
    connectedState = false
    guardrailUsageState = null
    chatStatusState = null
    sendMessageSpy.mockClear()
    endSessionSpy.mockClear()
    vi.mocked(apiClient.post).mockReset()
    vi.mocked(apiClient.post).mockResolvedValue({ data: { id: 'conversation-session-1' } } as never)
  })

  it('waits for the WebSocket connection before sending the first message', async () => {
    const onClose = vi.fn()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <ConversationDialog
          open
          sessionId={null}
          agentTypeId="agent-type-1"
          agentTypeName="Conversational Agent"
          onClose={onClose}
        />
      </QueryClientProvider>,
    )

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hello agent' } })
    fireEvent.click(screen.getByText('conversations.sessions.send'))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/conversations', {
        agent_type_id: 'agent-type-1',
      })
    })

    expect(sendMessageSpy).not.toHaveBeenCalled()
    expect(screen.getByText('conversations.sessions.connecting')).toBeDefined()

    connectedState = true
    rerender(
      <QueryClientProvider client={queryClient}>
        <ConversationDialog
          open
          sessionId={null}
          agentTypeId="agent-type-1"
          agentTypeName="Conversational Agent"
          onClose={onClose}
        />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(sendMessageSpy).toHaveBeenCalledWith('Hello agent')
    })

    expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('')
  })

  it('keeps conversational guardrail details hidden by default and opens floating hint on demand', async () => {
    connectedState = true
    guardrailUsageState = {
      policySnapshotId: 'policy-123',
      tokenUsageCurrentSession: 4500,
      tokenBudget: 12000,
      cumulativeIterations: 2,
      maxIterations: 6,
      delegatedSteps: 1,
      maxDelegatedSteps: 8,
      delegationDepth: 0,
      maxDelegationDepth: 2,
    }

    const onClose = vi.fn()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <ConversationDialog
          open
          sessionId={null}
          agentTypeId="agent-type-1"
          agentTypeName="Conversational Agent"
          onClose={onClose}
        />
      </QueryClientProvider>,
    )

    expect(screen.getByText('conversations.sessions.guardrailHintOpen')).toBeDefined()
    expect(screen.queryByText('conversations.sessions.guardrailPanelTitle')).toBeNull()
    expect(screen.queryByText('policy-123')).toBeNull()

    fireEvent.click(screen.getByText('conversations.sessions.guardrailHintOpen'))

    expect(screen.getByText('conversations.sessions.guardrailPanelTitle')).toBeDefined()
    expect(screen.getByText('agents.sessions.logViewer.summary.policySnapshot')).toBeDefined()
    expect(screen.getByText('policy-123')).toBeDefined()
    expect(screen.getByText('4.5k tokens / 12k tokens')).toBeDefined()
    expect(screen.getByText('2 / 6')).toBeDefined()
    expect(screen.getByText('1 / 8')).toBeDefined()
    expect(screen.getByText('0 / 2')).toBeDefined()
  })

  it('restores guardrail hint values from resumed session payload', async () => {
    connectedState = true
    guardrailUsageState = null

    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        id: 'conversation-session-1',
        agent_type_id: 'agent-type-1',
        triggered_by_user_id: null,
        agent_job_id: null,
        title: 'Saved conversation',
        channel: 'web',
        status: 'active',
        turn_count: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        closed_at: null,
        guardrail_usage: {
          policy_snapshot_id: 'policy-resume-1',
          token_usage_current_session: 2100,
          token_budget: 10000,
          cumulative_iterations: 1,
          max_iterations: 6,
          delegated_steps: 0,
          max_delegated_steps: 8,
          delegation_depth: 0,
          max_delegation_depth: 2,
        },
        turns: [],
      },
    } as never)

    const onClose = vi.fn()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <ConversationDialog
          open
          sessionId="conversation-session-1"
          agentTypeId="agent-type-1"
          agentTypeName="Conversational Agent"
          onClose={onClose}
        />
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/conversations/conversation-session-1/resume')
    })

    fireEvent.click(screen.getByText('conversations.sessions.guardrailHintOpen'))

    expect(screen.getByText('policy-resume-1')).toBeDefined()
    expect(screen.getByText('2.1k tokens / 10k tokens')).toBeDefined()
  })

  it('renders delegation and waiting status in the dialog chat area', () => {
    connectedState = true
    chatStatusState = {
      kind: 'waiting',
      agentType: 'research-agent',
      toolName: null,
      timestamp: new Date().toISOString(),
    }

    const onClose = vi.fn()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <ConversationDialog
          open
          sessionId={null}
          agentTypeId="agent-type-1"
          agentTypeName="Conversational Agent"
          onClose={onClose}
        />
      </QueryClientProvider>,
    )

    expect(screen.getByText('conversations.sessions.statusDelegatingToAgent')).toBeDefined()
    expect(screen.getByText('conversations.sessions.statusWaiting')).toBeDefined()
    expect(screen.getByTestId('conversation-dialog-chat-status-indicator')).toBeDefined()
  })

  it('renders using_tool status in the dialog chat area', () => {
    connectedState = true
    chatStatusState = {
      kind: 'using_tool',
      agentType: null,
      toolName: 'send_notification',
      timestamp: new Date().toISOString(),
    }

    const onClose = vi.fn()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <ConversationDialog
          open
          sessionId={null}
          agentTypeId="agent-type-1"
          agentTypeName="Conversational Agent"
          onClose={onClose}
        />
      </QueryClientProvider>,
    )

    expect(screen.getByText('conversations.sessions.statusUsingTool')).toBeDefined()
    expect(screen.getByTestId('conversation-dialog-chat-status-indicator')).toBeDefined()
  })

  it('renders timeout_or_failed terminal status in the dialog chat area', () => {
    connectedState = true
    chatStatusState = {
      kind: 'timeout_or_failed',
      agentType: null,
      toolName: null,
      timestamp: new Date().toISOString(),
    }

    const onClose = vi.fn()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <ConversationDialog
          open
          sessionId={null}
          agentTypeId="agent-type-1"
          agentTypeName="Conversational Agent"
          onClose={onClose}
        />
      </QueryClientProvider>,
    )

    expect(screen.getByText('conversations.sessions.statusTimeoutOrFailed')).toBeDefined()
    expect(screen.getByTestId('conversation-dialog-chat-status-terminal')).toBeDefined()
  })
})
