import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { OptimizedPlanView } from '../components/agents/AgentOptimizedPlanTab'

/**
 * "Talk to optimizer" entry on the Optimized Plan tab (7.1).
 *
 * The entry is a mode of THE agent type, offered for typed AND conversational
 * agents (the previous conversational-type restriction is gone). A missing plan
 * is an informational empty state — the conversation still opens, because that
 * is where the operator learns what is missing. Only a missing permission
 * disables the entry; a missing/unusable optimizer model keeps it open and shows
 * the reason plus the System Config shortcut.
 */

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, params?: Record<string, unknown>) => {
      let out = k
      if (params) {
        for (const [key, value] of Object.entries(params)) {
          out = out.split(`{{${key}}}`).join(String(value))
        }
      }
      return out
    },
  }),
}))

// The dialog itself is covered by OptimizerChatDialog.test.tsx; here we only
// prove the entry opens it and that a settled turn refreshes the plan. Stub the
// heavy transport so no socket is opened.
const chatState = vi.hoisted(() => ({ turnInFlight: false }))

vi.mock('../hooks/useChatSession', () => ({
  useChatSession: () => ({
    messages: [],
    connected: false,
    pendingQuestion: null,
    sessionTitle: null,
    guardrailUsage: null,
    chatStatus: null,
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
    chatError: null,
    interventionRequest: null,
    pendingIntervention: false,
    interventionStatus: null,
    liveTestResults: {},
    chatBlocked: null,
    activitySteps: [],
    interventionQueueLength: 0,
    sendInterventionResponse: vi.fn(() => true),
    cancelIntervention: vi.fn(() => true),
    sendTokenRefresh: vi.fn(),
    recoveryEpoch: 0,
    turnInFlight: chatState.turnInFlight,
    statusStale: false,
  }),
}))

const mockApiGet = vi.fn()
const mockApiPost = vi.fn()

vi.mock('../api/apiClient', () => ({
  default: {
    get: (...args: unknown[]) => mockApiGet(...args),
    post: (...args: unknown[]) => mockApiPost(...args),
  },
}))

import { AgentOptimizedPlanTab } from '../components/agents/AgentOptimizedPlanTab'

const PLAN: OptimizedPlanView = {
  id: 'op-1',
  agent_type_id: 'at-1',
  agent_plan_id: 'ap-1',
  status: 'ready',
  fully_scripted: true,
  error: null,
  steps: [],
  steps_count: 0,
  scripts_authored: 0,
  feedback_comments: [],
  generated_at: null,
}

interface GatePayload {
  can_optimize?: boolean
  successful_executions?: number
  reason?: string | null
  reason_code?: string | null
  is_conversational?: boolean
  optimization_conversation_available?: boolean
  optimization_conversation_reason_code?: string | null
  optimizer_model_configured?: boolean
  optimizer_model_id?: string | null
  optimizer_model_source?: 'optimizer' | 'authoring' | null
  optimizer_model_reason_code?: string | null
}

function mockGet(plan: OptimizedPlanView | null, gate: GatePayload) {
  mockApiGet.mockImplementation(async (url: string) => {
    if (url.endsWith('/optimization-gate')) {
      return { data: { can_optimize: true, successful_executions: 3, ...gate } }
    }
    if (url.endsWith('/optimized-plan')) {
      if (!plan) throw { response: { status: 404, data: { detail: 'Not found' } } }
      return { data: plan }
    }
    return { data: null }
  })
}

// Optional injection point so tests can keep ONE cache across rerenders.
let testClient: QueryClient | null = null

function wrapper({ children }: { children: React.ReactNode }) {
  const client =
    testClient ??
    new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    })
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

function tabElement(onOpenSystemConfig?: () => void) {
  return (
    <AgentOptimizedPlanTab
      agentTypeId="at-1"
      agentTypeName="Refund Agent"
      onError={vi.fn()}
      onViewScript={vi.fn()}
      onOpenSystemConfig={onOpenSystemConfig}
    />
  )
}

function renderTab(onOpenSystemConfig?: () => void) {
  return render(tabElement(onOpenSystemConfig), { wrapper })
}

describe('AgentOptimizedPlanTab — "Talk to optimizer" entry', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    testClient = null
    chatState.turnInFlight = false
    mockApiPost.mockResolvedValue({ data: {} })
  })

  it('offers the compact conversation entry for a TYPED agent (model + chat + help)', async () => {
    mockGet(PLAN, {
      can_optimize: true,
      is_conversational: false,
      optimization_conversation_available: true,
      optimizer_model_id: 'gpt-4o',
      optimizer_model_source: 'optimizer',
    })

    renderTab()

    const entry = await screen.findByTestId('talk-to-optimizer-entry')
    const button = screen.getByTestId('talk-to-optimizer') as HTMLButtonElement

    expect(button.disabled).toBe(false)
    expect(button.textContent).toBe('agents.optimizedPlan.talkToOptimizer')
    // Only the essentials: model + chat + help. The requirement-style scope
    // and identity copy are gone.
    expect(screen.getByTestId('optimization-help')).toBeDefined()
    expect(entry.textContent).not.toContain('agents.optimizedPlan.talkToOptimizerScope')
    expect(screen.queryByTestId('talk-to-optimizer-identity')).toBeNull()
    // The plan + lifecycle actions are retained beside the entry.
    await screen.findByTestId('optimized-plan-status')
    expect(screen.getByTestId('retire-optimized-plan')).toBeDefined()
    await waitFor(() => {
      expect(entry.textContent).toContain('agents.optimizedPlan.talkToOptimizerModelLabel')
      expect(entry.textContent).toContain('gpt-4o')
      expect(entry.textContent).not.toContain(
        'agents.optimizedPlan.talkToOptimizerModelInherited',
      )
    })
  })

  it('offers the SAME compact conversation entry for a CONVERSATIONAL agent', async () => {
    mockGet(PLAN, {
      can_optimize: false,
      reason_code: 'conversational_agent',
      is_conversational: true,
      optimization_conversation_available: true,
      optimizer_model_id: 'gpt-4o',
      optimizer_model_source: 'authoring',
    })

    renderTab()

    const entry = await screen.findByTestId('talk-to-optimizer-entry')
    const button = screen.getByTestId('talk-to-optimizer') as HTMLButtonElement

    expect(button.disabled).toBe(false)
    expect(entry.textContent).not.toContain('agents.optimizedPlan.talkToOptimizerScope')
    await waitFor(() => {
      expect(entry.textContent).toContain('agents.optimizedPlan.talkToOptimizerModelInherited')
    })
  })

  it('opens the optimization help dialog from the question-mark icon', async () => {
    mockGet(PLAN, {
      can_optimize: true,
      optimization_conversation_available: true,
      optimizer_model_id: 'gpt-4o',
      optimizer_model_source: 'optimizer',
    })

    renderTab()

    fireEvent.click(await screen.findByTestId('optimization-help'))
    expect(await screen.findByTestId('optimization-help-dialog')).toBeDefined()
  })

  it('shows an informational empty state when there is no plan, and the entry still opens', async () => {
    mockGet(null, {
      can_optimize: false,
      reason_code: 'no_successful_execution',
      optimization_conversation_available: true,
      optimizer_model_id: 'gpt-4o',
      optimizer_model_source: 'authoring',
    })

    renderTab()

    const absent = await screen.findByTestId('optimized-plan-absent')
    expect(absent.textContent).toContain('agents.optimizedPlan.talkToOptimizerEmptyTitle')
    expect(absent.textContent).toContain('agents.optimizedPlan.noPlan')
    expect(absent.textContent).toContain('agents.optimizedPlan.talkToOptimizerEmptyBody')

    // A missing plan never hides the entry.
    const button = screen.getByTestId('talk-to-optimizer') as HTMLButtonElement
    expect(button.disabled).toBe(false)

    fireEvent.click(button)

    // The conversation opens (starts no work on open).
    expect(
      await screen.findByTestId('optimization-conversation-dialog-optimization-mode-chip'),
    ).toBeDefined()
  })

  it('disables the entry with a permission explanation when the operator may not optimize', async () => {
    mockGet(PLAN, {
      can_optimize: true,
      optimization_conversation_available: false,
      optimization_conversation_reason_code: 'permission_denied',
      optimizer_model_id: 'gpt-4o',
    })

    renderTab()

    await waitFor(() => {
      expect(screen.getByTestId('talk-to-optimizer-blocked')).toBeDefined()
    })
    const button = screen.getByTestId('talk-to-optimizer') as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(screen.getByTestId('talk-to-optimizer-blocked').textContent).toBe(
      'agents.optimizedPlan.talkToOptimizerPermission',
    )

    fireEvent.click(button)
    expect(screen.queryByTestId('optimization-conversation-dialog')).toBeNull()
  })

  it('keeps the entry OPEN for an unusable optimizer model and points at System Config', async () => {
    const onOpenSystemConfig = vi.fn()
    mockGet(PLAN, {
      can_optimize: true,
      optimization_conversation_available: false,
      optimization_conversation_reason_code: 'optimizer_model_not_configured',
      optimizer_model_configured: false,
      optimizer_model_id: null,
      optimizer_model_reason_code: 'optimizer_model_not_configured',
    })

    renderTab(onOpenSystemConfig)

    await waitFor(() => {
      expect(screen.getByTestId('talk-to-optimizer-blocked')).toBeDefined()
    })

    // Missing model opens the conversation (which explains what is missing) —
    // only a permission blocks the entry.
    const button = screen.getByTestId('talk-to-optimizer') as HTMLButtonElement
    expect(button.disabled).toBe(false)

    // The reason is the shared optimizer-model sentence, not raw backend text.
    expect(screen.getByTestId('talk-to-optimizer-blocked').textContent).toContain(
      'agents.optimizer.modelReasons.optimizer_model_not_configured',
    )

    fireEvent.click(screen.getByTestId('talk-to-optimizer-system-config'))
    expect(onOpenSystemConfig).toHaveBeenCalledTimes(1)
  })

  it('shows a stale-model reason with the shared vocabulary', async () => {
    mockGet(PLAN, {
      can_optimize: true,
      optimization_conversation_available: false,
      optimization_conversation_reason_code: 'optimizer_model_not_enabled',
      optimizer_model_id: 'retired-model',
      optimizer_model_reason_code: 'optimizer_model_not_enabled',
    })

    renderTab()

    await waitFor(() => {
      expect(screen.getByTestId('talk-to-optimizer-blocked').textContent).toContain(
        'agents.optimizer.modelReasons.optimizer_model_not_enabled',
      )
    })
    expect(
      (screen.getByTestId('talk-to-optimizer') as HTMLButtonElement).disabled,
    ).toBe(false)
  })

  it('renders no separate "optimizer agent" chrome — the entry is a mode of this agent', async () => {
    mockGet(PLAN, {
      can_optimize: true,
      optimization_conversation_available: true,
      optimizer_model_id: 'gpt-4o',
    })

    renderTab()

    await screen.findByTestId('talk-to-optimizer-entry')
    const body = document.body.textContent ?? ''
    // No invented optimizer agent/identity/role anywhere on the surface.
    expect(body).not.toMatch(/separate optimizer agent/i)
    expect(body).not.toMatch(/optimizer agent type/i)
    expect(body).not.toMatch(/optimizer role/i)
    // Nor an assistant-style "configure the assistant model" banner.
    expect(screen.queryByTestId('assistant-model-not-configured')).toBeNull()
  })

  it('refreshes the optimized plan automatically when a conversation turn settles (7.5)', async () => {
    mockGet(PLAN, {
      can_optimize: true,
      optimization_conversation_available: true,
      optimizer_model_id: 'gpt-4o',
    })
    testClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    })

    const { rerender } = render(tabElement(), { wrapper })

    await screen.findByTestId('optimized-plan-status')
    fireEvent.click(screen.getByTestId('talk-to-optimizer'))
    await screen.findByTestId('optimization-conversation-dialog-optimization-mode-chip')

    const planFetchesBefore = mockApiGet.mock.calls.filter((call) =>
      String(call[0]).includes('optimized-plan'),
    ).length

    // A turn starts (the tab polls) and then settles…
    chatState.turnInFlight = true
    rerender(tabElement())
    await waitFor(() => {
      expect(mockApiGet.mock.calls.filter((call) =>
        String(call[0]).includes('optimization-gate'),
      ).length).toBeGreaterThan(0)
    })

    chatState.turnInFlight = false
    rerender(tabElement())

    // …and the plan is re-read without a manual reload.
    await waitFor(() => {
      const planFetchesAfter = mockApiGet.mock.calls.filter((call) =>
        String(call[0]).includes('optimized-plan'),
      ).length
      expect(planFetchesAfter).toBeGreaterThan(planFetchesBefore)
    })
  })

  it('warns that no usable model exists when the model label is missing', async () => {
    mockGet(PLAN, {
      can_optimize: true,
      optimization_conversation_available: true,
      optimizer_model_id: null,
      optimizer_model_source: null,
    })

    renderTab()

    const entry = await screen.findByTestId('talk-to-optimizer-entry')
    expect(entry.textContent).toContain('agents.optimizedPlan.talkToOptimizerModelMissing')
    // Still openable: the chat explains the model state before work starts.
    expect(
      (screen.getByTestId('talk-to-optimizer') as HTMLButtonElement).disabled,
    ).toBe(false)
  })
})
