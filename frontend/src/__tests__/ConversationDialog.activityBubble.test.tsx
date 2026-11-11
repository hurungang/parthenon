import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConversationDialog } from '../components/agents/ConversationDialog'
import type { ChatMessage, ChatStatus } from '../hooks/useChatSession'

// ── Mocks ─────────────────────────────────────────────────────────────────────

let mockMessages: ChatMessage[] = []
let mockChatStatus: ChatStatus | null = null
let mockTurnInFlight = false
let mockPendingIntervention = false

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, options?: { agentType?: string; toolName?: string }) => {
      if (k === 'conversations.sessions.statusUsingTool') {
        return `Using tool ${String(options?.toolName ?? '')}`
      }
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
    recoveryEpoch: 0,
    turnInFlight: mockTurnInFlight,
    pendingIntervention: mockPendingIntervention,
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

function status(kind: ChatStatus['kind'], extra: Partial<ChatStatus> = {}): ChatStatus {
  return {
    kind,
    agentType: null,
    toolName: null,
    receiverSessionId: null,
    timestamp: '2026-01-01T00:00:00Z',
    ...extra,
  }
}

beforeEach(() => {
  mockMessages = []
  mockChatStatus = null
  mockTurnInFlight = false
  mockPendingIntervention = false
})

describe('ConversationDialog — activity bubble lifecycle', () => {
  it('renders the pending-intervention indicator continuously for waiting_for_human (no blank gap)', () => {
    mockChatStatus = status('waiting_for_human', { pendingIntervention: true })
    mockTurnInFlight = true
    renderDialog()

    expect(screen.getByTestId('conversation-dialog-intervention-pending-indicator')).toBeTruthy()
    // The thinking bubble must NOT also render while waiting.
    expect(screen.queryByTestId('conversation-dialog-chat-status-indicator')).toBeNull()
  })

  it('renders the pending indicator from the hydrated pendingIntervention flag alone', () => {
    mockChatStatus = null
    mockPendingIntervention = true
    renderDialog()

    expect(screen.getByTestId('conversation-dialog-intervention-pending-indicator')).toBeTruthy()
  })

  it('a finished terminal state clears the spinner silently', () => {
    mockChatStatus = status('finished')
    mockTurnInFlight = true
    renderDialog()

    expect(screen.queryByTestId('conversation-dialog-chat-status-indicator')).toBeNull()
    // `finished` clears silently (no per-reply "Turn completed." banner).
    expect(screen.queryByTestId('conversation-dialog-chat-status-terminal')).toBeNull()
  })

  it('a timed_out terminal state never leaves a stuck spinner', () => {
    mockChatStatus = status('timed_out')
    mockTurnInFlight = true
    renderDialog()

    expect(screen.getByTestId('conversation-dialog-chat-status-terminal')).toBeTruthy()
    expect(screen.queryByTestId('conversation-dialog-chat-status-indicator')).toBeNull()
  })

  it('a thinking state renders the thinking bubble', () => {
    mockChatStatus = status('thinking')
    mockTurnInFlight = true
    renderDialog()

    const indicators = screen.getAllByTestId('conversation-dialog-chat-status-indicator')
    expect(indicators.length).toBeGreaterThan(0)
  })
})
