import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConversationDialog } from '../components/agents/ConversationDialog'
import type { ChatMessage, ChatStatus, DelegationCycle } from '../hooks/useChatSession'

let mockMessages: ChatMessage[] = []
let mockChatStatus: ChatStatus | null = null
let mockTurnInFlight = false
let mockDelegationCycles: DelegationCycle[] = []
let mockActiveCycleId: string | null = null

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, options?: { agentType?: string; toolName?: string }) => {
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
    delegationCycles: mockDelegationCycles,
    activeDelegationCycleId: mockActiveCycleId,
    delegationSnippets: [],
    delegationSnippetsCollapsed: true,
    delegationCompleted: false,
    delegationExecutionLogAvailable: false,
    delegationExecutionSessionId: null,
    recoveryEpoch: 0,
    turnInFlight: mockTurnInFlight,
    pendingIntervention: false,
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
  default: { get: vi.fn(async () => ({ data: [] })), post: vi.fn(async () => ({ data: {} })) },
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
      <ConversationDialog open sessionId={null} agentTypeId="at-1" agentTypeName="Assistant" onClose={vi.fn()} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  mockMessages = []
  mockChatStatus = null
  mockTurnInFlight = false
  mockDelegationCycles = []
  mockActiveCycleId = null
})

describe('ConversationDialog — using_tool (management tool) rendering', () => {
  it('shows "Using tool" when a using_tool status is active with no delegation cycle', () => {
    mockChatStatus = { kind: 'using_tool', agentType: null, toolName: 'cc__invoke_management_tool', receiverSessionId: null, timestamp: '2026-01-01T00:00:00Z' }
    mockTurnInFlight = true
    renderDialog()
    expect(screen.getByText(/Using tool cc__invoke_management_tool/)).toBeTruthy()
  })

  it('shows "Using tool" even when a (real) empty using_tool delegation cycle exists', () => {
    mockChatStatus = { kind: 'using_tool', agentType: null, toolName: 'cc__invoke_management_tool', receiverSessionId: null, timestamp: '2026-01-01T00:00:00Z' }
    mockTurnInFlight = true
    mockDelegationCycles = [
      { id: 'c1', startedAt: '2026-01-01T00:00:00Z', snippets: [], snippetsCollapsed: true, completed: false, executionLogAvailable: false, executionSessionId: null },
    ]
    mockActiveCycleId = 'c1'
    renderDialog()
    expect(screen.getByText(/Using tool cc__invoke_management_tool/)).toBeTruthy()
  })

  it('shows "Using tool" when resumed delegation history exists but the active cycle was filtered (empty)', () => {
    // Reproduces the real-world gap: a resumed session already has delegation
    // cycles, and the current `using_tool` status creates an EMPTY cycle that
    // gets filtered out — the active-cycle id points at a non-rendered cycle.
    mockChatStatus = { kind: 'using_tool', agentType: null, toolName: 'cc__invoke_management_tool', receiverSessionId: null, timestamp: '2026-01-01T00:00:00Z' }
    mockTurnInFlight = true
    mockDelegationCycles = [
      {
        id: 'history-cycle',
        startedAt: '2026-01-01T00:00:00Z',
        snippets: [
          { id: 's1', kind: 'delegating', agentType: 'worker', toolName: null, logTitle: null, timestamp: '2026-01-01T00:00:00Z' },
        ],
        snippetsCollapsed: true,
        completed: true,
        executionLogAvailable: false,
        executionSessionId: null,
      },
    ]
    mockActiveCycleId = 'active-using-tool-cycle' // not present in delegationCycles (filtered out)
    renderDialog()
    expect(screen.getByText(/Using tool cc__invoke_management_tool/)).toBeTruthy()
  })
})
