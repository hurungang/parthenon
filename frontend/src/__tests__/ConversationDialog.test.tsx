import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
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
      receiverSessionId: string | null
      timestamp: string
    }
  | null = null
let delegationSnippetsState: Array<{
  id: string
  kind: 'delegating' | 'waiting' | 'using_tool'
  agentType: string | null
  toolName: string | null
  timestamp: string
}> = []

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, options?: { value?: string; agentType?: string }) => {
      if (k === 'conversations.sessions.statusDelegatingToAgent') {
        return `Delegating to agent ${String(options?.agentType ?? '')}`
      }
      return options?.value ? `${k} ${options.value}` : k
    },
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
    delegationSnippets: delegationSnippetsState,
    delegationSnippetsCollapsed: true,
    delegationCompleted: false,
    delegationExecutionLogAvailable: false,
    delegationExecutionSessionId: null,
    setDelegationSnippetsCollapsed: vi.fn(),
    toggleDelegationSnippetsCollapsed: vi.fn(),
    hydrateDelegationFromHistory: vi.fn(),
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
    delegationSnippetsState = []
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

  it('shows policy snapshot id from resumed camelCase guardrail payload instead of unknown', async () => {
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
          policySnapshotId: 'policy-camel-1',
          tokenUsageCurrentSession: 2100,
          tokenBudget: 10000,
          cumulativeIterations: 1,
          maxIterations: 6,
          delegatedSteps: 0,
          maxDelegatedSteps: 8,
          delegationDepth: 0,
          maxDelegationDepth: 2,
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

    // Expected behavior: panel must render concrete policy snapshot id from resume payload.
    expect(screen.getByText('policy-camel-1')).toBeDefined()
  })

  it('renders delegation and waiting status in the dialog chat area', () => {
    connectedState = true
    chatStatusState = {
      kind: 'waiting',
      agentType: 'research-agent',
      toolName: null,
      receiverSessionId: null,
      timestamp: new Date().toISOString(),
    }
    delegationSnippetsState = [
      {
        id: 'snippet-1',
        kind: 'delegating',
        agentType: 'research-agent',
        toolName: null,
        timestamp: new Date().toISOString(),
      },
      {
        id: 'snippet-2',
        kind: 'waiting',
        agentType: 'research-agent',
        toolName: null,
        timestamp: new Date().toISOString(),
      },
    ]

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

    expect(screen.getByText('Delegating to agent research-agent')).toBeDefined()
    expect(within(screen.getByTestId('conversation-dialog-chat-status-indicator')).getByText('conversations.sessions.statusWaiting')).toBeDefined()
    expect(screen.getByTestId('conversation-dialog-delegation-inline-row')).toBeDefined()
  })

  it('uses waiting snippet agent type for delegation bubble title when delegating snippet is missing', () => {
    connectedState = true
    chatStatusState = {
      kind: 'waiting',
      agentType: 'supabase-agent',
      toolName: null,
      receiverSessionId: 'delegated-session-2',
      timestamp: new Date().toISOString(),
    }
    delegationSnippetsState = [
      {
        id: 'snippet-1',
        kind: 'waiting',
        agentType: 'supabase-agent',
        toolName: null,
        timestamp: new Date().toISOString(),
      },
    ]

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

    expect(screen.getByText('Delegating to agent supabase-agent')).toBeDefined()
    expect(within(screen.getByTestId('conversation-dialog-chat-status-indicator')).getByText('conversations.sessions.statusWaiting')).toBeDefined()
  })

  it('renders delegation log block in dialog chat area when delegation is active', () => {
    connectedState = true
    chatStatusState = {
      kind: 'waiting',
      agentType: 'research-agent',
      toolName: null,
      receiverSessionId: null,
      timestamp: new Date().toISOString(),
    }
    delegationSnippetsState = [
      {
        id: 'snippet-1',
        kind: 'delegating',
        agentType: 'research-agent',
        toolName: null,
        timestamp: new Date().toISOString(),
      },
    ]

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

    expect(screen.getByTestId('conversation-dialog-delegation-snippets')).toBeDefined()
  })

  it('renders using_tool status in the dialog chat area', () => {
    connectedState = true
    chatStatusState = {
      kind: 'using_tool',
      agentType: null,
      toolName: 'send_notification',
      receiverSessionId: null,
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

  it('does not render a duplicate progress indicator when active cycle is already delegating', () => {
    connectedState = true
    chatStatusState = {
      kind: 'delegating',
      agentType: 'research-agent',
      toolName: null,
      receiverSessionId: 'delegated-session-1',
      timestamp: new Date().toISOString(),
    }
    delegationSnippetsState = [
      {
        id: 'snippet-1',
        kind: 'delegating',
        agentType: 'research-agent',
        toolName: null,
        timestamp: new Date().toISOString(),
      },
    ]

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

    expect(screen.getByTestId('conversation-dialog-delegation-inline-row')).toBeDefined()
    expect(screen.queryAllByTestId('conversation-dialog-chat-status-indicator')).toHaveLength(1)
  })

  it('renders timeout_or_failed terminal status in the dialog chat area', () => {
    connectedState = true
    chatStatusState = {
      kind: 'timeout_or_failed',
      agentType: null,
      toolName: null,
      receiverSessionId: null,
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
