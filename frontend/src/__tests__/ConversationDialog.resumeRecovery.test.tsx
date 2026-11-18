import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConversationDialog } from '../components/agents/ConversationDialog'
import type { ChatMessage, ChatStatus, DelegationCycle } from '../hooks/useChatSession'
import type { InterveneRequest, InterveneRequestMessage } from '../types'

/**
 * resumable-agent-turn-persistence — Phase 6.2 / 6.3.
 *
 * Four-state recovery vocabulary in the conversation dialog:
 * - waiting for your input (only with a live resume id),
 * - resumed — thinking / using a tool (visually distinct from a fresh turn),
 * - resolved,
 * - no longer resumable (terminal card with next step + dismiss).
 *
 * Plus the degraded case (a stale hydrated `waiting_for_human` without a live
 * resume id) and the duplicate-approval guard against a terminal turn.
 */

const I18N: Record<string, string> = {
  'conversations.sessions.statusThinking': 'Thinking…',
  'conversations.sessions.statusWaiting': 'Waiting for delegated response…',
  'conversations.sessions.chatPlaceholder': 'Type a message…',
  'conversations.sessions.intervention.inputBlocked': 'Respond to the confirmation above…',
  'conversations.sessions.resumeState.waiting': 'Waiting for your input',
  'conversations.sessions.resumeState.resumed': 'Resumed · continuing',
  'conversations.sessions.resumeState.resolved': 'Resolved',
  'conversations.sessions.resumeState.unresumable': 'No longer resumable',
  'conversations.sessions.terminalCard.title': 'This confirmation can no longer be resumed',
  'conversations.sessions.terminalCard.subtitle': 'resolved without changes',
  'conversations.sessions.terminalCard.bodyExpired': 'EXPIRED-BODY Nothing was written.',
  'conversations.sessions.terminalCard.bodyLostPausePoint': 'LOST-PAUSE-POINT-BODY Nothing was written.',
  'conversations.sessions.terminalCard.bodyUnexpectedlyTerminated':
    'UNEXPECTEDLY-TERMINATED-BODY Nothing was applied.',
  'conversations.sessions.terminalCard.nextStepLabel': 'Next step',
  'conversations.sessions.terminalCard.nextStep': 'Ask again to generate a fresh preview.',
  'conversations.sessions.terminalCard.askAgain': 'Ask again',
  'conversations.sessions.terminalCard.dismiss': 'Dismiss',
  'conversations.sessions.terminalCard.nothingToReplay':
    'This turn ended without a decision — nothing to replay.',
  'conversations.sessions.intervention.approve': 'Approve',
  'conversations.sessions.intervention.deny': 'Deny',
}

let mockChatStatus: ChatStatus | null = null
let mockTurnInFlight = false
let mockPendingIntervention = false
let mockInterventionRequest: InterveneRequestMessage | null = null
let mockFetchedPendingIntervention: InterveneRequest | null = null
let mockMessages: ChatMessage[] = []
let mockDelegationCycles: DelegationCycle[] = []
let mockActiveDelegationCycleId: string | null = null

const { mockRespondToIntervention, mockCancelInterventionRequest, mockSendInterventionResponse, mockSendMessage } =
  vi.hoisted(() => ({
    mockRespondToIntervention: vi.fn(async () => undefined),
    mockCancelInterventionRequest: vi.fn(async () => undefined),
    mockSendInterventionResponse: vi.fn(() => true),
    mockSendMessage: vi.fn(() => true),
  }))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { agentType?: string; toolName?: string }) => {
      if (key === 'conversations.sessions.statusUsingTool') {
        return `Using tool ${String(options?.toolName ?? '')}`
      }
      if (key === 'conversations.sessions.statusDelegatingToAgent') {
        return `Delegating to agent ${String(options?.agentType ?? '')}`
      }
      return I18N[key] ?? key
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
    recoveryEpoch: 0,
    turnInFlight: mockTurnInFlight,
    statusStale: false,
    pendingIntervention: mockPendingIntervention,
    setDelegationSnippetsCollapsed: vi.fn(),
    toggleDelegationSnippetsCollapsed: vi.fn(),
    hydrateDelegationFromHistory: vi.fn(),
    sendMessage: mockSendMessage,
    clearMessages: vi.fn(),
    chatError: null,
    interventionRequest: mockInterventionRequest,
    interventionQueueLength: 0,
    sendInterventionResponse: mockSendInterventionResponse,
    cancelIntervention: vi.fn(),
    sendTokenRefresh: vi.fn(),
  })),
}))

vi.mock('../hooks/useConversationIntervention', () => ({
  useConversationIntervention: vi.fn(() => ({
    dialogError: null,
    isSubmitting: false,
    respondToIntervention: mockRespondToIntervention,
    cancelIntervention: mockCancelInterventionRequest,
    currentIntervention: mockFetchedPendingIntervention,
    pendingInterventions: mockFetchedPendingIntervention ? [mockFetchedPendingIntervention] : [],
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
  mockChatStatus = null
  mockTurnInFlight = false
  mockPendingIntervention = false
  mockInterventionRequest = null
  mockFetchedPendingIntervention = null
  mockMessages = []
  mockDelegationCycles = []
  mockActiveDelegationCycleId = null
  mockRespondToIntervention.mockClear()
  mockCancelInterventionRequest.mockClear()
  mockSendInterventionResponse.mockClear()
})

describe('ConversationDialog — resume recovery vocabulary', () => {
  it('renders "waiting for your input" when a live resume id backs the pause', () => {
    mockChatStatus = status('waiting_for_human', {
      activeResumeId: 'resume-1',
      resumeState: 'waiting_for_human',
      pendingIntervention: true,
    })
    mockTurnInFlight = true
    renderDialog()

    expect(screen.getByTestId('conversation-dialog-intervention-pending-indicator')).toBeTruthy()
    const chip = screen.getByTestId('conversation-dialog-resume-state-chip')
    expect(chip.textContent).toContain('Waiting for your input')
    // A waiting turn never also renders the thinking bubble.
    expect(screen.queryAllByTestId('conversation-dialog-chat-status-indicator').length).toBe(0)
  })

  it('a stale hydrated waiting_for_human without a live resume id is NOT rendered as waiting', () => {
    // 6.2 degraded case: persisted activity says waiting, but no live resume
    // record backs it (and no pending_intervention flag).
    mockChatStatus = status('waiting_for_human', {
      activeResumeId: null,
      resumeState: null,
      pendingIntervention: false,
      persisted: true,
    })
    mockTurnInFlight = true
    renderDialog()

    expect(screen.queryByTestId('conversation-dialog-intervention-pending-indicator')).toBeNull()
    expect(screen.queryByTestId('conversation-dialog-resume-state-chip')).toBeNull()
  })

  it('renders a resumed turn distinctly from a fresh turn', () => {
    mockChatStatus = status('thinking', {
      activeResumeId: 'resume-1',
      resumeState: 'resuming',
    })
    mockTurnInFlight = true
    const { unmount } = renderDialog()

    const badge = screen.getByTestId('conversation-dialog-resume-badge')
    expect(badge.textContent).toContain('Resumed · continuing')
    expect(
      screen.getByTestId('conversation-dialog-resume-state-chip').textContent,
    ).toContain('Resumed · continuing')
    unmount()

    // A fresh (never-paused) turn renders the thinking bubble WITHOUT the
    // resume badge/chip.
    mockChatStatus = status('thinking')
    renderDialog()
    expect(screen.queryByTestId('conversation-dialog-resume-badge')).toBeNull()
    expect(screen.queryByTestId('conversation-dialog-resume-state-chip')).toBeNull()
  })

  it('renders the resumed vocabulary for a resumed tool call', () => {
    mockChatStatus = status('using_tool', {
      toolName: 'cc____create_skill',
      activeResumeId: 'resume-1',
      resumeState: 'resuming',
    })
    mockTurnInFlight = true
    renderDialog()

    const indicators = screen.getAllByTestId('conversation-dialog-chat-status-indicator')
    expect(indicators[0].textContent).toContain('Using tool cc____create_skill')
    expect(screen.queryByTestId('conversation-dialog-resume-badge')).not.toBeNull()
  })

  it('renders the resolved state for a resumed turn that finished', () => {
    mockChatStatus = status('finished', {
      activeResumeId: null,
      resumeState: 'resolved',
    })
    renderDialog()

    expect(
      screen.getByTestId('conversation-dialog-resume-state-chip').textContent,
    ).toContain('Resolved')
    // Resolved is not a failure banner.
    expect(screen.queryByTestId('conversation-dialog-chat-status-terminal')).toBeNull()
  })
})

describe('ConversationDialog — no longer resumable terminal card', () => {
  it('renders the expired body, keeps the input enabled, and offers both actions', () => {
    mockChatStatus = status('timed_out', {
      resumeState: 'unresumable',
      terminalReason: 'expired',
      activeResumeId: 'resume-9',
      message: 'server rendered message',
    })
    renderDialog()

    expect(screen.getByTestId('conversation-dialog-terminal-card')).toBeTruthy()
    expect(screen.getByTestId('conversation-dialog-terminal-card-body').textContent).toContain(
      'EXPIRED-BODY',
    )
    expect(screen.getByTestId('conversation-dialog-terminal-card-next-step')).toBeTruthy()
    expect(screen.getByTestId('conversation-dialog-terminal-card-ask-again')).toBeTruthy()
    expect(screen.getByTestId('conversation-dialog-terminal-card-dismiss')).toBeTruthy()
    // The legacy generic terminal alert is replaced by the card.
    expect(screen.queryByTestId('conversation-dialog-chat-status-terminal')).toBeNull()
    // Input re-enabled while the card is visible.
    const input = screen.getByPlaceholderText('Type a message…') as HTMLTextAreaElement
    expect(input.disabled).toBe(false)
  })

  it('renders a different body for a lost pause point', () => {
    mockChatStatus = status('failed', {
      resumeState: 'unresumable',
      terminalReason: 'checkpoint_unavailable',
    })
    renderDialog()

    expect(screen.getByTestId('conversation-dialog-terminal-card-body').textContent).toContain(
      'LOST-PAUSE-POINT-BODY',
    )
  })

  it('renders the unexpectedly-terminated body for a turn the watchdog stopped', () => {
    // A crashed/restarted in-progress turn: the reaper resolves it as
    // `failed` + `unexpectedly_terminated`, and the card must explain that
    // nothing was applied and offer to resend.
    mockChatStatus = status('failed', {
      resumeState: 'unresumable',
      terminalReason: 'unexpectedly_terminated',
    })
    renderDialog()

    const card = screen.getByTestId('conversation-dialog-terminal-card')
    expect(card.getAttribute('data-terminal-reason')).toBe('unexpectedly_terminated')
    expect(screen.getByTestId('conversation-dialog-terminal-card-body').textContent).toContain(
      'UNEXPECTEDLY-TERMINATED-BODY',
    )
    expect(screen.getByTestId('conversation-dialog-terminal-card-ask-again')).toBeTruthy()
    // Input re-enabled so the operator can resend.
    const input = screen.getByPlaceholderText('Type a message…') as HTMLTextAreaElement
    expect(input.disabled).toBe(false)
  })

  it('"Ask again" replays the request after an unexpectedly-terminated turn', () => {
    mockChatStatus = status('failed', {
      resumeState: 'unresumable',
      terminalReason: 'unexpectedly_terminated',
    })
    mockMessages = [
      {
        id: 'u2',
        role: 'user',
        content: 'create the flight-search agent',
        timestamp: '2026-01-01T00:00:00Z',
      },
    ]
    renderDialog()

    fireEvent.click(screen.getByTestId('conversation-dialog-terminal-card-ask-again'))
    expect(screen.queryByTestId('conversation-dialog-terminal-card')).toBeNull()
    expect(mockSendMessage).toHaveBeenCalledWith('create the flight-search agent')
  })

  it('dismisses the card and keeps the input enabled', () => {
    mockChatStatus = status('timed_out', {
      resumeState: 'unresumable',
      terminalReason: 'expired',
    })
    renderDialog()

    fireEvent.click(screen.getByTestId('conversation-dialog-terminal-card-dismiss'))
    expect(screen.queryByTestId('conversation-dialog-terminal-card')).toBeNull()
    const input = screen.getByPlaceholderText('Type a message…') as HTMLTextAreaElement
    expect(input.disabled).toBe(false)
  })

  it('"Ask again" retires the card and re-enables the input', () => {
    mockChatStatus = status('timed_out', {
      resumeState: 'unresumable',
      terminalReason: 'expired',
    })
    renderDialog()

    fireEvent.click(screen.getByTestId('conversation-dialog-terminal-card-ask-again'))
    expect(screen.queryByTestId('conversation-dialog-terminal-card')).toBeNull()
    const input = screen.getByPlaceholderText('Type a message…') as HTMLTextAreaElement
    expect(input.disabled).toBe(false)
  })

  it('"Ask again" replays the last user message to start a fresh turn', () => {
    mockChatStatus = status('timed_out', {
      resumeState: 'unresumable',
      terminalReason: 'expired',
    })
    mockMessages = [
      { id: 'u1', role: 'user', content: 'create the flight-search agent', timestamp: '2026-01-01T00:00:00Z' },
    ]
    renderDialog()

    fireEvent.click(screen.getByTestId('conversation-dialog-terminal-card-ask-again'))
    expect(mockSendMessage).toHaveBeenCalledWith('create the flight-search agent')
  })
})

describe('ConversationDialog — terminal turn folds the confirmation read-only', () => {
  it('renders the confirmation read-only (no actions, input enabled) when the turn is terminal', () => {
    // A late/lingering confirmation on a turn that already ended.
    mockChatStatus = status('timed_out', {
      resumeState: 'unresumable',
      terminalReason: 'expired',
    })
    mockInterventionRequest = {
      type: 'intervene_request',
      request_id: 'req-1',
      intervention_type: 'approval',
      reason: 'Create skill triage-inbox',
      agent_type: 'assistant',
      delegation_depth: 0,
      conversation_session_id: 'conv-1',
    }
    renderDialog()

    // No actionable dialog / approve button on a terminal turn.
    expect(screen.queryByTestId('conversation-dialog-intervention-dialog')).toBeNull()
    expect(screen.queryByText('Approve')).toBeNull()
    // Folded grey read-only block is shown instead.
    expect(screen.getByTestId('conversation-dialog-intervention-closed')).toBeTruthy()
    // Input stays enabled so the operator can ask again / retype.
    const input = screen.getByPlaceholderText('Type a message…') as HTMLTextAreaElement
    expect(input.disabled).toBe(false)
    // Nothing is ever dispatched.
    expect(mockRespondToIntervention).not.toHaveBeenCalled()
    expect(mockSendInterventionResponse).not.toHaveBeenCalled()
  })

  it('still dispatches an approval while the turn is live', () => {
    mockChatStatus = status('waiting_for_human', {
      activeResumeId: 'resume-1',
      resumeState: 'waiting_for_human',
      pendingIntervention: true,
    })
    mockInterventionRequest = {
      type: 'intervene_request',
      request_id: 'req-2',
      intervention_type: 'approval',
      reason: 'Create skill triage-inbox',
      agent_type: 'assistant',
      delegation_depth: 0,
      conversation_session_id: 'conv-1',
    }
    renderDialog()

    fireEvent.click(screen.getByText('Approve'))
    expect(mockRespondToIntervention).toHaveBeenCalledWith('req-2', { approval_value: true })
    expect(screen.queryByTestId('conversation-dialog-nothing-to-replay')).toBeNull()
  })
})

describe('ConversationDialog — a confirmation is actionable only during a live pause', () => {
  const fetchedPending: InterveneRequest = {
    id: 'req-fetched',
    agent_session_id: null,
    agent_type_id: 'agent-type-1',
    conversation_session_id: 'conv-1',
    intervention_type: 'approval',
    reason: 'Create skill triage-inbox',
    status: 'pending',
    delegation_depth: 0,
    created_at: '2026-01-01T00:00:00Z',
    agent_name: 'assistant',
  }

  it('folds a stale using_tool confirmation read-only and renders NO spinner', () => {
    // Production symptom: a turn emitted `using_tool` then stopped, while a
    // REST-fetched confirmation was still pending. The stale `using_tool` must
    // not render a progressing bubble next to a live-looking dialog.
    mockChatStatus = status('using_tool', { toolName: 'cc____invoke_management_tool' })
    mockTurnInFlight = true
    mockFetchedPendingIntervention = fetchedPending
    renderDialog()

    expect(screen.queryByTestId('conversation-dialog-intervention-dialog')).toBeNull()
    expect(screen.queryByTestId('conversation-dialog-chat-status-indicator')).toBeNull()
    expect(screen.getByTestId('conversation-dialog-intervention-closed')).toBeTruthy()
    // Input is usable so the operator can retype / ask again.
    const input = screen.getByPlaceholderText('Type a message…') as HTMLTextAreaElement
    expect(input.disabled).toBe(false)
    expect(mockRespondToIntervention).not.toHaveBeenCalled()
  })

  it('folds a stale thinking confirmation read-only and renders NO spinner', () => {
    mockChatStatus = status('thinking')
    mockTurnInFlight = true
    mockFetchedPendingIntervention = fetchedPending
    renderDialog()

    expect(screen.queryByTestId('conversation-dialog-chat-status-indicator')).toBeNull()
    expect(screen.getByTestId('conversation-dialog-intervention-closed')).toBeTruthy()
  })

  it('never shows a spinner alongside a terminal turn with a lingering confirmation', () => {
    mockChatStatus = status('timed_out', {
      resumeState: 'unresumable',
      terminalReason: 'expired',
    })
    mockTurnInFlight = true
    mockFetchedPendingIntervention = fetchedPending
    renderDialog()

    expect(screen.queryByTestId('conversation-dialog-chat-status-indicator')).toBeNull()
    expect(screen.getByTestId('conversation-dialog-intervention-closed')).toBeTruthy()
  })

  it('keeps a REST-fetched confirmation actionable during a live pause', () => {
    mockChatStatus = status('waiting_for_human', {
      activeResumeId: 'resume-1',
      resumeState: 'waiting_for_human',
      pendingIntervention: true,
    })
    mockTurnInFlight = true
    mockFetchedPendingIntervention = fetchedPending
    renderDialog()

    expect(screen.getByTestId('conversation-dialog-intervention-dialog')).toBeTruthy()
    expect(screen.queryByTestId('conversation-dialog-intervention-closed')).toBeNull()

    fireEvent.click(screen.getByText('Approve'))
    expect(mockRespondToIntervention).toHaveBeenCalledWith('req-fetched', {
      approval_value: true,
    })
  })

  it('keeps the normal working bubble when no confirmation exists', () => {
    mockChatStatus = status('using_tool', { toolName: 'cc____list_agents' })
    mockTurnInFlight = true
    renderDialog()

    const indicators = screen.getAllByTestId('conversation-dialog-chat-status-indicator')
    expect(indicators[0].textContent).toContain('Using tool cc____list_agents')
    expect(screen.queryByTestId('conversation-dialog-intervention-closed')).toBeNull()
  })

  it('suppresses the in-cycle live status of a stale working status too', () => {
    mockDelegationCycles = [
      {
        id: 'cycle-1',
        startedAt: '2026-01-01T00:00:00Z',
        snippets: [
          {
            id: 'snippet-1',
            kind: 'delegating',
            agentType: 'researcher',
            toolName: null,
            logTitle: null,
            timestamp: '2026-01-01T00:00:00Z',
          },
        ],
        snippetsCollapsed: true,
        completed: false,
        executionLogAvailable: false,
        executionSessionId: null,
      },
    ]
    mockActiveDelegationCycleId = 'cycle-1'

    // Control: the live in-cycle status renders without a confirmation.
    mockChatStatus = status('using_tool', { toolName: 'cc____x' })
    mockTurnInFlight = true
    const first = renderDialog()
    expect(screen.getByTestId('conversation-dialog-delegation-inline-row')).toBeTruthy()
    expect(
      screen.getAllByTestId('conversation-dialog-chat-status-indicator').length,
    ).toBe(1)
    first.unmount()

    // With a stale confirmation the same line must disappear.
    mockFetchedPendingIntervention = fetchedPending
    renderDialog()
    expect(screen.getByTestId('conversation-dialog-delegation-inline-row')).toBeTruthy()
    expect(
      screen.queryAllByTestId('conversation-dialog-chat-status-indicator').length,
    ).toBe(0)
    expect(screen.getByTestId('conversation-dialog-intervention-closed')).toBeTruthy()
  })
})
