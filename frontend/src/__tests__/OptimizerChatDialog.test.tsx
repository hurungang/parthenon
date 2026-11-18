import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import React from 'react'

/**
 * Optimization-mode chat chrome (7.2 / 7.3 / 7.4).
 *
 * The optimization conversation reuses the ordinary conversation experience
 * (multi-turn, activity, pause/resume, persisted history) with optimization
 * chrome: a mode/scope bar (identity parity, typed vs conversational scope,
 * replay-only / live-used chip), the optimizer-model alert with a System Config
 * shortcut and a disabled composer, the inline ask card, the live-test approval
 * card, decided live tests as inline chat history, and the replay-vs-live audit
 * block. Business and assistant conversations must be byte-identical — no
 * optimization chrome leaks.
 */

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // Key-echo translator; parameters are appended so assertions can prove the
    // subject name / model id / count the component actually passed in.
    t: (k: string, params?: Record<string, unknown>) => {
      const values = Object.entries(params ?? {}).filter(
        ([key]) => key !== 'defaultValue',
      )
      return values.length
        ? `${k} ${values.map(([key, value]) => `${key}=${String(value)}`).join(' ')}`
        : k
    },
  }),
}))

/** Mutable chat-hook state driven by the tests. */
const chat = {
  messages: [] as Array<Record<string, unknown>>,
  connected: false,
  pendingQuestion: null as string | null,
  sessionTitle: null as string | null,
  guardrailUsage: null,
  chatStatus: null as Record<string, unknown> | null,
  chatError: null as { code: string; message: string } | null,
  interventionRequest: null as Record<string, unknown> | null,
  pendingIntervention: false,
  interventionStatus: null,
  liveTestResults: {} as Record<string, unknown>,
  chatBlocked: null as Record<string, unknown> | null,
  activitySteps: [] as Array<Record<string, unknown>>,
  turnInFlight: false,
  statusStale: false,
  recoveryEpoch: 0,
}

const sendInterventionResponse = vi.fn(() => true)

vi.mock('../hooks/useChatSession', () => ({
  useChatSession: () => ({
    messages: chat.messages,
    connected: chat.connected,
    pendingQuestion: chat.pendingQuestion,
    sessionTitle: chat.sessionTitle,
    guardrailUsage: chat.guardrailUsage,
    chatStatus: chat.chatStatus,
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
    chatError: chat.chatError,
    interventionRequest: chat.interventionRequest,
    pendingIntervention: chat.pendingIntervention,
    interventionStatus: chat.interventionStatus,
    liveTestResults: chat.liveTestResults,
    chatBlocked: chat.chatBlocked,
    activitySteps: chat.activitySteps,
    interventionQueueLength: 0,
    sendInterventionResponse,
    cancelIntervention: vi.fn(() => true),
    sendTokenRefresh: vi.fn(),
    recoveryEpoch: chat.recoveryEpoch,
    turnInFlight: chat.turnInFlight,
    statusStale: chat.statusStale,
  }),
}))

const mockGet = vi.fn()
const mockPost = vi.fn()

vi.mock('../api/apiClient', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
  },
}))

import { ConversationDialog } from '../components/agents/ConversationDialog'

interface GatePayload {
  optimization_conversation_available?: boolean
  optimization_conversation_reason_code?: string | null
  is_conversational?: boolean
  optimizer_model_id?: string | null
  optimizer_model_reason_code?: string | null
}

interface DetailPayload {
  subjectName?: string
  isConversational?: boolean
  available?: boolean
  reasonCode?: string | null
  planPresent?: boolean
  optimizerModelReason?: string | null
  optimizerModelId?: string | null
  audit?: {
    replay_verifications: number
    live_operations: number
    last_live_at: string | null
    replay_only: boolean
  }
}

function mockBackend(
  gate: GatePayload = {},
  detail: DetailPayload | null = null,
  liveTests: Array<Record<string, unknown>> = [],
) {
  mockGet.mockImplementation(async (url: string) => {
    if (url.endsWith('/optimization-gate')) {
      return {
        data: { can_optimize: true, successful_executions: 1, ...gate },
      }
    }
    if (detail && url === '/conversations/conv-1/optimization') {
      return {
        data: {
          conversation: { id: 'conv-1', channel: 'optimization' },
          subject: {
            agent_type_id: 'at-1',
            name: detail.subjectName ?? 'Refund Agent',
            input_type: detail.isConversational ? 'conversation' : 'structured',
            is_conversational: detail.isConversational ?? false,
          },
          availability: {
            available: detail.available ?? true,
            reason_code: detail.reasonCode ?? null,
            reason: null,
            can_start_work: detail.available ?? true,
            plan_present: detail.planPresent ?? true,
            optimized_plan_status: detail.planPresent === false ? null : 'ready',
            successful_executions: 1,
            optimizer_model: {
              model_id: detail.optimizerModelId ?? null,
              effective_model_id: detail.optimizerModelId ?? 'gpt-4o',
              source: detail.optimizerModelId ? 'optimizer' : 'authoring',
              configured: !detail.optimizerModelReason,
              enabled: !detail.optimizerModelReason,
              reason_code: detail.optimizerModelReason ?? null,
            },
          },
          audit: detail.audit ?? {
            replay_verifications: 0,
            live_operations: 0,
            last_live_at: null,
            replay_only: true,
          },
        },
      }
    }
    if (url === '/conversations/conv-1/live-test-requests') return { data: liveTests }
    if (url === '/conversations/conv-1/interventions/pending') return { data: [] }
    if (url === '/conversations/conv-1/optimization') return { data: null }
    return { data: null }
  })

  mockPost.mockImplementation(async (url: string) => {
    if (url === '/conversations/conv-1/resume') {
      return { data: { id: 'conv-1', turns: [], guardrail_usage: null } }
    }
    if (url === '/conversations/optimization') {
      return {
        data: {
          conversation: { id: 'conv-new' },
          subject: { agent_type_id: 'at-1', name: 'Refund Agent' },
          availability: { available: true },
        },
      }
    }
    return { data: { id: 'conv-new' } }
  })
}

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

function renderDialog(props: {
  optimizationMode?: boolean
  sessionId?: string | null
  onOptimizationTurnSettled?: () => void
  onOptimizationTurnStateChange?: (inFlight: boolean) => void
} = {}) {
  const onClose = vi.fn()
  const utils = render(
    <ConversationDialog
      open
      sessionId={props.sessionId ?? null}
      agentTypeId="at-1"
      agentTypeName="Refund Agent"
      onClose={onClose}
      optimizationMode={props.optimizationMode ?? true}
      onOptimizationTurnSettled={props.onOptimizationTurnSettled}
      onOptimizationTurnStateChange={props.onOptimizationTurnStateChange}
    />,
    { wrapper },
  )
  return { ...utils, onClose }
}

function resetChat() {
  chat.messages = []
  chat.connected = false
  chat.pendingQuestion = null
  chat.sessionTitle = null
  chat.chatStatus = null
  chat.chatError = null
  chat.interventionRequest = null
  chat.pendingIntervention = false
  chat.interventionStatus = null
  chat.liveTestResults = {}
  chat.chatBlocked = null
  chat.activitySteps = []
  chat.turnInFlight = false
  chat.recoveryEpoch = 0
}

describe('ConversationDialog — optimization mode chrome', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    resetChat()
    mockBackend()
  })

  it('shows the subject agent identity in the title with an optimization-mode chip (no separate optimizer identity)', async () => {
    renderDialog()

    expect(await screen.findByTestId('conversation-dialog-optimization-mode-chip')).toBeDefined()
    expect(
      screen.getByTestId('conversation-dialog-optimization-mode-chip').textContent,
    ).toContain('agents.optimizer.modeOnAgent')
    // Identity parity moved out of the header: it is a tooltip on the chip now.
    expect(
      screen
        .getByTestId('conversation-dialog-optimization-identity')
        .getAttribute('title'),
    ).toBe('agents.optimizer.identityParity')
    // The dialog title is the SUBJECT agent, never an optimizer agent.
    expect(screen.getByText('Refund Agent')).toBeDefined()
    const body = document.body.textContent ?? ''
    expect(body).not.toMatch(/separate optimizer agent/i)
  })

  it('shows a compact, collapsed "What ran in this session" bar with the replay-only signal', async () => {
    mockBackend({ is_conversational: false })

    renderDialog()

    const bar = await screen.findByTestId('conversation-dialog-optimization-session-bar')
    expect(bar.getAttribute('data-expanded')).toBe('false')
    expect(
      screen.getByTestId('conversation-dialog-optimization-session-bar-live-chip').textContent,
    ).toBe('agents.optimizer.audit.noLive')
    expect(
      screen.getByTestId(
        'conversation-dialog-optimization-session-bar-replay-only-chip',
      ).textContent,
    ).toBe('agents.optimizer.replayOnly')
    // The full mode/scope header block is gone.
    expect(screen.queryByTestId('conversation-dialog-optimization-mode-bar')).toBeNull()
  })

  it('expands the bar to the typed subject scope and identity parity', async () => {
    mockBackend({ is_conversational: false })

    renderDialog()

    const toggle = await screen.findByTestId(
      'conversation-dialog-optimization-session-bar-toggle',
    )
    fireEvent.click(toggle)

    await waitFor(() => {
      expect(
        screen.getByTestId('conversation-dialog-optimization-session-bar-scope').textContent,
      ).toContain('agents.optimizer.scopePlan')
    })
    expect(
      screen.getByTestId('conversation-dialog-optimization-session-bar-identity').textContent,
    ).toBe('agents.optimizer.identityParity')
  })

  it('annotates a conversational subject scope (no optimized plan yet)', async () => {
    mockBackend({ is_conversational: true })

    renderDialog()

    fireEvent.click(
      await screen.findByTestId(
        'conversation-dialog-optimization-session-bar-toggle',
      ),
    )

    await waitFor(() => {
      expect(
        screen.getByTestId('conversation-dialog-optimization-session-bar-scope').textContent,
      ).toContain('agents.optimizer.scopeConversational')
    })
    expect(
      screen.getByTestId('conversation-dialog-optimization-session-bar-scope').textContent,
    ).not.toContain('agents.optimizer.scopePlan')
  })

  it('shows the live-used chip once an approved live test ran (single use)', async () => {
    mockBackend(
      {},
      {
        audit: {
          replay_verifications: 1,
          live_operations: 2,
          last_live_at: '2026-01-02T08:30:00.000Z',
          replay_only: false,
        },
      },
    )

    renderDialog({ sessionId: 'conv-1' })

    const chip = await screen.findByTestId(
      'conversation-dialog-optimization-session-bar-live-chip',
    )
    await waitFor(() => {
      expect(chip.textContent).toContain('agents.optimizer.audit.liveUsed')
    })
  })

  it('shows the optimizer-model alert with a System Config shortcut and disables the composer', async () => {
    mockBackend({
      optimization_conversation_available: false,
      optimization_conversation_reason_code: 'optimizer_model_not_configured',
      optimizer_model_reason_code: 'optimizer_model_not_configured',
    })

    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/']}>
          <Routes>
            <Route
              path="/"
              element={
                <ConversationDialog
                  open
                  sessionId={null}
                  agentTypeId="at-1"
                  agentTypeName="Refund Agent"
                  onClose={vi.fn()}
                  optimizationMode
                />
              }
            />
            <Route path="/system-config" element={<div data-testid="system-config-page" />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const alert = await screen.findByTestId('conversation-dialog-optimizer-model-alert')
    expect(alert.textContent).toContain('agents.optimizer.modelAlertBodyNotConfigured')

    // The composer is blocked: work must never start on an unapproved model.
    const composer = screen.getByPlaceholderText('agents.optimizer.inputBlockedModel')
    expect((composer as HTMLTextAreaElement).disabled).toBe(true)

    // The shortcut opens System Config.
    fireEvent.click(screen.getByTestId('conversation-dialog-optimizer-open-system-config'))
    expect(await screen.findByTestId('system-config-page')).toBeDefined()
  })

  it('names the stale optimizer model in the alert (no substitution)', async () => {
    mockBackend(
      {},
      {
        optimizerModelReason: 'optimizer_model_not_enabled',
        optimizerModelId: 'retired-model',
      },
    )

    renderDialog({ sessionId: 'conv-1' })

    const alert = await screen.findByTestId('conversation-dialog-optimizer-model-alert')
    expect(alert.textContent).toContain('agents.optimizer.modelAlertBodyNotEnabled')
    expect(alert.textContent).toContain('retired-model')
  })

  it('explains an out-of-scope chat_error in the conversation', async () => {
    chat.chatError = {
      code: 'optimization_out_of_scope',
      message: 'Nothing was changed.',
    }

    renderDialog()

    const alert = await screen.findByTestId('conversation-dialog-optimizer-chat-error')
    expect(alert.textContent).toBe('agents.optimizer.chatErrors.optimization_out_of_scope')
  })

  it('blocks input and explains why while a decision is pending', async () => {
    chat.chatBlocked = {
      reason: 'decision_pending',
      message: 'Answer the pending request first.',
      liveTestRequestId: 'ltr-1',
      expiresAt: null,
    }

    renderDialog({ sessionId: 'conv-1' })

    const blocked = await screen.findByTestId('conversation-dialog-optimization-decision-blocked')
    expect(blocked.textContent).toBe('agents.optimizer.blockedDecision')

    const composer = screen.getByPlaceholderText('agents.optimizer.inputBlockedDecision')
    expect((composer as HTMLTextAreaElement).disabled).toBe(true)
  })

  it('renders the inline ask card with choices and submits the chosen answer once', async () => {
    chat.interventionRequest = {
      type: 'intervene_request',
      request_id: 'req-ask-1',
      intervention_type: 'choice',
      reason: 'Which field should the script summarise?',
      choices: ['summary', 'raw_json'],
      delegation_depth: 0,
      conversation_session_id: 'conv-1',
      live_test: null,
    }
    chat.pendingIntervention = true

    renderDialog({ sessionId: 'conv-1' })

    const card = await screen.findByTestId('conversation-dialog-optimizer-ask')
    expect(card.textContent).toContain('Which field should the script summarise?')

    fireEvent.click(
      within(card).getByTestId('conversation-dialog-optimizer-ask-choice-summary'),
    )

    await waitFor(() => {
      expect(sendInterventionResponse).toHaveBeenCalledWith('req-ask-1', {
        selected_choice: 'summary',
      })
    })
    expect(sendInterventionResponse).toHaveBeenCalledTimes(1)
  })

  it('renders the script-based live-test approval card and approves once', async () => {
    chat.interventionRequest = {
      type: 'intervene_request',
      request_id: 'req-live-1',
      intervention_type: 'approval',
      reason: 'Run this live test?',
      delegation_depth: 0,
      conversation_session_id: 'conv-1',
      live_test: {
        live_test_request_id: 'ltr-1',
        status: 'pending',
        expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
        script_version_id: 'sv-3',
        script_name: 'search-flights',
        script_version_label: 'v3',
        operations: [
          {
            tool_name: 'crm____lookup_contact',
            arguments: { email: 'ada@example.com' },
            purpose: 'Confirm the contact exists',
          },
        ],
      },
    }
    chat.pendingIntervention = true

    renderDialog({ sessionId: 'conv-1' })

    const card = await screen.findByTestId('conversation-dialog-live-test-approval')
    // The script is the unit of approval; the tool is only a preview.
    expect(card.textContent).toContain('agents.optimizer.approval.runScriptTitle')
    expect(card.textContent).toContain('search-flights')
    expect(card.textContent).toContain('crm____lookup_contact')
    // The approval card IS the answer surface — no generic ask card.
    expect(screen.queryByTestId('conversation-dialog-optimizer-ask')).toBeNull()

    fireEvent.click(
      screen.getByTestId('conversation-dialog-live-test-approval-approve'),
    )

    await waitFor(() => {
      expect(sendInterventionResponse).toHaveBeenCalledWith('req-live-1', {
        approval_value: true,
      })
    })
  })

  it('sends the deny decision for a live test (nothing runs, replay-only stays)', async () => {
    chat.interventionRequest = {
      type: 'intervene_request',
      request_id: 'req-live-2',
      intervention_type: 'approval',
      reason: 'Run this live test?',
      delegation_depth: 0,
      conversation_session_id: 'conv-1',
      live_test: {
        live_test_request_id: 'ltr-2',
        status: 'pending',
        expires_at: null,
        operations: [{ tool_name: 'crm____lookup_contact', arguments: {} }],
      },
    }
    chat.pendingIntervention = true

    renderDialog({ sessionId: 'conv-1' })

    await screen.findByTestId('conversation-dialog-live-test-approval')
    fireEvent.click(screen.getByTestId('conversation-dialog-live-test-approval-deny'))

    await waitFor(() => {
      expect(sendInterventionResponse).toHaveBeenCalledWith('req-live-2', {
        approval_value: false,
      })
    })
    expect(sendInterventionResponse).not.toHaveBeenCalledWith(
      'req-live-2',
      expect.objectContaining({ approval_value: true }),
    )
  })

  it('renders a decided live test in its historical position and no activity block (single indicator)', async () => {
    chat.messages = [
      {
        id: 'm1',
        role: 'user',
        content: 'Tighten the refund verification loop',
        timestamp: '2026-01-01T10:00:00.000Z',
      },
      {
        id: 'm2',
        role: 'assistant',
        content: 'Verification results: 3 of 3 operations matched',
        timestamp: '2026-01-01T10:05:00.000Z',
      },
    ]
    chat.chatStatus = {
      kind: 'using_tool',
      toolName: 'execute_script',
      timestamp: '2026-01-01T10:03:00.000Z',
    }
    // The old "what it looked at" block is gone — the session bar covers it.
    chat.activitySteps = [
      {
        id: 's1',
        toolName: 'execute_script',
        state: 'running',
        timestamp: '2026-01-01T10:03:00.000Z',
      },
    ]
    chat.liveTestResults = {
      'ltr-1': {
        type: 'live_test_result',
        live_test_request_id: 'ltr-1',
        live_test_status: 'executed',
        executed_operations: [],
        script_run: {
          script_name: 'refund-flow',
          script_version_label: 'v2',
          success: true,
          result_summary: 'refunded once',
          error: null,
          duration_ms: 820,
          tool_calls: [],
          telemetry: {},
        },
      },
    }
    mockBackend(
      {},
      null,
      [
        {
          id: 'ltr-1',
          status: 'executed',
          target_agent_type_id: 'at-1',
          script_version_id: 'sv-2',
          script_name: 'refund-flow',
          script_version_label: 'v2',
          requested_operations: [
            { tool_name: 'crm____refund', arguments: {}, purpose: 'Refund once' },
          ],
          executed_operations: [],
          expires_at: null,
          execution_started_at: '2026-01-01T10:02:00.000Z',
          execution_finished_at: '2026-01-01T10:04:00.000Z',
          decision: {
            approval_value: true,
            operator_user_id: 'u-1',
            responded_at: '2026-01-01T10:02:00.000Z',
          },
          created_at: '2026-01-01T09:59:00.000Z',
        },
      ],
    )

    renderDialog({ sessionId: 'conv-1' })

    // The decided card is chat history, collapsed, expandable.
    const card = await screen.findByTestId('conversation-dialog-live-test-resolved-0')
    expect(card.getAttribute('data-state')).toBe('executed')
    expect(card.getAttribute('data-expanded')).toBe('false')
    expect(screen.queryByTestId('conversation-dialog-live-test-resolved-0-approve')).toBeNull()

    // It sits in the transcript (not appended after it): the assistant's
    // summary reply comes AFTER the card. (The ledger read may land a tick
    // later, so the position is asserted until the decision time is used.)
    await waitFor(() => {
      // Re-query both nodes: the card can re-sort (and be replaced) once the
      // ledger read lands, so a captured node would be detached (position 0).
      const liveCard = screen.getByTestId('conversation-dialog-live-test-resolved-0')
      const summary = screen.getByText('Verification results: 3 of 3 operations matched')
      expect(
        liveCard.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy()
    })

    // The separate activity/tool-call block is gone, and only the normal chat
    // status indicator spins.
    expect(screen.queryByTestId('conversation-dialog-optimizer-activity')).toBeNull()
    expect(
      document.querySelectorAll('.MuiCircularProgress-root'),
    ).toHaveLength(1)
  })

  it('renders the replay-vs-live audit block from the conversation read (expanded bar)', async () => {
    mockBackend(
      {},
      {
        audit: {
          replay_verifications: 4,
          live_operations: 0,
          last_live_at: null,
          replay_only: true,
        },
      },
    )

    renderDialog({ sessionId: 'conv-1' })

    // The audit detail lives behind the collapsed bar's chevron.
    fireEvent.click(
      await screen.findByTestId(
        'conversation-dialog-optimization-session-bar-toggle',
      ),
    )

    await screen.findByTestId(
      'conversation-dialog-optimization-session-bar-audit',
    )
    // One heading for the bar; the audit block itself is title-less here.
    expect(
      screen.getByTestId('conversation-dialog-optimization-session-bar').textContent,
    ).toContain('agents.optimizer.sessionBar.title')
    expect(
      screen.getByTestId('conversation-dialog-optimization-session-bar-audit-replay')
        .textContent,
    ).toContain('4')
    // Replay count is shown distinctly from approved live operations, with the
    // replay-only chip while nothing live ran.
    expect(
      screen.getByTestId('conversation-dialog-optimization-session-bar-audit-live')
        .textContent,
    ).toBe('agents.optimizer.audit.noLive')
    expect(
      screen.getByTestId(
        'conversation-dialog-optimization-session-bar-audit-replay-only',
      ),
    ).toBeDefined()
  })

  it('opens the optimization conversation through the subject-only endpoint (no client channel/scope)', async () => {
    renderDialog()

    const composer = await screen.findByPlaceholderText('agents.optimizer.inputPlaceholder')
    fireEvent.change(composer, { target: { value: 'Optimise the refund flow' } })
    fireEvent.click(screen.getByText('conversations.sessions.send'))

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/conversations/optimization', {
        agent_type_id: 'at-1',
      })
    })
    // Never the generic business-conversation create.
    expect(mockPost).not.toHaveBeenCalledWith('/conversations', expect.anything())
  })

  it('notifies the host to refresh the plan when a turn settles (7.5)', async () => {
    const onSettled = vi.fn()
    const onStateChange = vi.fn()
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    })

    const tree = () => (
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <ConversationDialog
            open
            sessionId={null}
            agentTypeId="at-1"
            agentTypeName="Refund Agent"
            onClose={vi.fn()}
            optimizationMode
            onOptimizationTurnSettled={onSettled}
            onOptimizationTurnStateChange={onStateChange}
          />
        </MemoryRouter>
      </QueryClientProvider>
    )

    chat.turnInFlight = true
    const { rerender } = render(tree())

    await waitFor(() => expect(onStateChange).toHaveBeenCalledWith(true))
    expect(onSettled).not.toHaveBeenCalled()

    chat.turnInFlight = false
    rerender(tree())

    await waitFor(() => {
      expect(onStateChange).toHaveBeenCalledWith(false)
      expect(onSettled).toHaveBeenCalledTimes(1)
    })
  })
})

describe('ConversationDialog — business / assistant mode is unchanged', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    resetChat()
    mockBackend()
  })

  it('renders no optimization chrome outside optimization mode', async () => {
    renderDialog({ optimizationMode: false })

    await waitFor(() => {
      expect(screen.getByText('Refund Agent')).toBeDefined()
    })

    expect(screen.queryByTestId('conversation-dialog-optimization-mode-chip')).toBeNull()
    expect(screen.queryByTestId('conversation-dialog-optimization-identity')).toBeNull()
    expect(screen.queryByTestId('conversation-dialog-optimization-session-bar')).toBeNull()
    expect(screen.queryByTestId('conversation-dialog-optimizer-model-alert')).toBeNull()
    expect(screen.queryByTestId('conversation-dialog-optimizer-activity')).toBeNull()

    // Business chat composer keeps its ordinary placeholder and is not blocked
    // by optimization state.
    const composer = screen.getByPlaceholderText('conversations.sessions.chatPlaceholder')
    expect((composer as HTMLTextAreaElement).disabled).toBe(false)
  })

  it('keeps a business intervention on the generic inline dialog, not the optimizer ask card', async () => {
    chat.interventionRequest = {
      type: 'intervene_request',
      request_id: 'req-biz-1',
      intervention_type: 'approval',
      reason: 'Approve this write?',
      delegation_depth: 0,
      conversation_session_id: 'conv-1',
      live_test: null,
    }
    chat.pendingIntervention = true

    renderDialog({ optimizationMode: false, sessionId: 'conv-1' })

    await screen.findByTestId('conversation-dialog-intervention-dialog')
    expect(screen.queryByTestId('conversation-dialog-optimizer-ask')).toBeNull()
    expect(screen.queryByTestId('conversation-dialog-live-test-approval')).toBeNull()
  })
})
