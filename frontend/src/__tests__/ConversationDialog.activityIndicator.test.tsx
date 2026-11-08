import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConversationDialog } from '../components/agents/ConversationDialog'
import type { ChatMessage, ChatStatus } from '../hooks/useChatSession'

// ── Mocks ─────────────────────────────────────────────────────────────────────

let mockMessages: ChatMessage[] = []
let mockChatStatus: ChatStatus | null = null
let mockTurnInFlight = false

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, options?: { agentType?: string; toolName?: string }) => {
      if (k === 'conversations.sessions.statusDelegatingToAgent') {
        return `Delegating to agent ${String(options?.agentType ?? '')}`
      }
      if (k === 'conversations.sessions.statusUsingTool') {
        return `Using tool ${String(options?.toolName ?? '')}`
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
    recoveryEpoch: 0,
    turnInFlight: mockTurnInFlight,
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
    sendTokenRefresh: vi.fn(),
  })),
}))

vi.mock('../hooks/useConversationSessions', () => ({
  useConversationSessionsPage: vi.fn(() => ({ data: undefined, isLoading: false, error: null })),
  useEndConversationSession: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn(async () => ({ data: [] })),
    post: vi.fn(async () => ({ data: {} })),
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

function renderDialog() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ConversationDialog
        open
        sessionId={null}
        agentTypeId="agent-type-1"
        agentTypeName="Assistant"
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  mockMessages = []
  mockChatStatus = null
  mockTurnInFlight = false
})

describe('ConversationDialog — activity indicator invariant mid-turn', () => {
  it('(a) delegation_resumed status renders a visible activity indicator', () => {
    mockChatStatus = {
      kind: 'delegation_resumed',
      agentType: 'worker',
      toolName: null,
      receiverSessionId: null,
      timestamp: '2026-01-01T00:00:00Z',
    }
    renderDialog()

    const indicators = screen.getAllByTestId('conversation-dialog-chat-status-indicator')
    expect(indicators.length).toBeGreaterThan(0)
    expect(indicators[0].textContent).toContain('Thinking')
  })

  it('(a2) using_tool status renders the "Using tool" indicator', () => {
    mockChatStatus = {
      kind: 'using_tool',
      agentType: null,
      toolName: 'cc____list_agents',
      receiverSessionId: null,
      timestamp: '2026-01-01T00:00:00Z',
    }
    renderDialog()

    const indicators = screen.getAllByTestId('conversation-dialog-chat-status-indicator')
    expect(indicators[0].textContent).toContain('Using tool cc____list_agents')
  })

  it('(b) turnInFlight with a null chatStatus falls back to the thinking bubble', () => {
    mockTurnInFlight = true
    mockChatStatus = null
    renderDialog()

    const indicators = screen.getAllByTestId('conversation-dialog-chat-status-indicator')
    expect(indicators[0].textContent).toContain('Thinking')
  })

  it('(b2) turnInFlight with an unrendered status kind falls back to the thinking bubble', () => {
    mockTurnInFlight = true
    mockChatStatus = {
      kind: 'timeout_or_failed' as ChatStatus['kind'],
      agentType: null,
      toolName: null,
      receiverSessionId: null,
      timestamp: '2026-01-01T00:00:00Z',
    }
    // timeout_or_failed renders its own terminal alert — fallback must not
    // double up; assert exactly one indicator (the terminal alert) renders.
    renderDialog()
    expect(screen.getByTestId('conversation-dialog-chat-status-terminal')).toBeTruthy()
    expect(screen.queryAllByTestId('conversation-dialog-chat-status-indicator').length).toBe(0)
  })

  it('(c) after the final reply (not in flight, null status) no indicator lingers', () => {
    mockTurnInFlight = false
    mockChatStatus = null
    renderDialog()

    expect(screen.queryAllByTestId('conversation-dialog-chat-status-indicator').length).toBe(0)
  })

  it('(c2) waiting_for_human keeps precedence over the fallback thinking bubble', () => {
    mockTurnInFlight = true
    mockChatStatus = {
      kind: 'waiting_for_human',
      agentType: 'worker',
      toolName: null,
      receiverSessionId: null,
      timestamp: '2026-01-01T00:00:00Z',
    }
    renderDialog()

    expect(screen.getByTestId('conversation-dialog-intervention-pending-indicator')).toBeTruthy()
    expect(screen.queryAllByTestId('conversation-dialog-chat-status-indicator').length).toBe(0)
  })

  it('(d) timeout_or_failed renders the terminal alert and turnStreaming covers turnInFlight', () => {
    mockTurnInFlight = true
    mockChatStatus = {
      kind: 'timeout_or_failed',
      agentType: null,
      toolName: null,
      receiverSessionId: null,
      timestamp: '2026-01-01T00:00:00Z',
    }
    renderDialog()

    expect(screen.getByTestId('conversation-dialog-chat-status-terminal')).toBeTruthy()
  })
})
