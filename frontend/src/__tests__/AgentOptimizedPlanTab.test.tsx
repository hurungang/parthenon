import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { OptimizedPlanView } from '../components/agents/AgentOptimizedPlanTab'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, params?: Record<string, unknown>) => {
    let out = k
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        out = out.replace(`{{${key}}}`, String(value))
      }
    }
    return out
  } }),
}))

const mockApiGet = vi.fn()
const mockApiPost = vi.fn()

vi.mock('../api/apiClient', () => ({
  default: {
    get: (...args: unknown[]) => mockApiGet(...args),
    post: (...args: unknown[]) => mockApiPost(...args),
  },
}))

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const client =
    testQueryClient ??
    new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

// Optional injection point so tests can spy on the real QueryClient.
let testQueryClient: QueryClient | null = null

const PLAN: OptimizedPlanView = {
  id: 'op-1',
  agent_type_id: 'at-1',
  agent_plan_id: 'ap-1',
  status: 'ready',
  fully_scripted: true,
  error: null,
  steps: [
    {
      order: 1,
      type: 'tool_call',
      name: 'Fetch contact',
      description: 'Fetch the contact from the CRM',
      python_source: 'def run(context, tools):\n    ...',
      scriptable: true,
    },
    {
      order: 2,
      type: 'semantic_bridge',
      name: 'Summarise',
      description: 'LLM bridge step',
      python_source: null,
      scriptable: false,
    },
  ],
  steps_count: 2,
  scripts_authored: 1,
  feedback_comments: [
    {
      created_at: '2026-10-21T00:00:00+00:00',
      raw_feedback: 'Make the output a table.',
      summary: 'Make the output a table.',
    },
  ],
  generated_at: null,
}

import { AgentOptimizedPlanTab } from '../components/agents/AgentOptimizedPlanTab'

describe('AgentOptimizedPlanTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    testQueryClient = null
    mockApiGet.mockResolvedValue({ data: PLAN })
    mockApiPost.mockResolvedValue({ data: {} })
  })

  it('fetches and renders the optimized plan steps with names and descriptions', async () => {
    render(
      <AgentOptimizedPlanTab agentTypeId="at-1" onError={vi.fn()} onViewScript={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith('/agents/types/at-1/optimized-plan')
    })
    expect(await screen.findByText('Fetch contact')).toBeDefined()
    expect(screen.getByText('Fetch the contact from the CRM')).toBeDefined()
    expect(screen.getByText('Summarise')).toBeDefined()
    expect(screen.getByTestId('optimized-plan-status').textContent).toBe('ready')
  })

  it('renders a View script button only on script-backed steps and calls onViewScript', async () => {
    const onViewScript = vi.fn()
    render(
      <AgentOptimizedPlanTab agentTypeId="at-1" onError={vi.fn()} onViewScript={onViewScript} />,
      { wrapper },
    )

    const button = await screen.findByTestId('view-script-1')
    expect(button.tagName).toBe('BUTTON')
    expect(screen.queryByTestId('view-script-2')).toBeNull()
    fireEvent.click(button)
    expect(onViewScript).toHaveBeenCalledOnce()
    // The step is passed so the direct script dialog can show its source.
    expect(onViewScript).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Fetch contact', python_source: expect.any(String) }),
    )
  })

  it('no longer renders the manual feedback form', async () => {
    render(
      <AgentOptimizedPlanTab agentTypeId="at-1" onError={vi.fn()} onViewScript={vi.fn()} />,
      { wrapper },
    )

    expect(await screen.findByTestId('optimized-plan-status')).toBeDefined()
    expect(screen.queryByTestId('optimized-plan-feedback-input')).toBeNull()
    expect(screen.queryByTestId('optimized-plan-feedback-submit')).toBeNull()
  })

  it('shows the empty state when no optimized plan exists (404)', async () => {
    mockApiGet.mockRejectedValue({
      response: { status: 404 },
      isAxiosError: true,
    })
    render(
      <AgentOptimizedPlanTab agentTypeId="at-1" onError={vi.fn()} onViewScript={vi.fn()} />,
      { wrapper },
    )

    expect(
      await screen.findByText('agents.optimizedPlan.noPlan'),
    ).toBeDefined()
  })

  it('renders the needs_feedback state distinctly with the failure and a steer prompt', async () => {
    mockApiGet.mockResolvedValue({
      data: {
        ...PLAN,
        status: 'needs_feedback' as OptimizedPlanView['status'],
        error: 'verification failed after 3 attempt(s) — the last failure was: sandbox compile failed: import os',
      },
    })
    render(
      <AgentOptimizedPlanTab agentTypeId="at-1" onError={vi.fn()} onViewScript={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByTestId('optimized-plan-status').textContent).toBe('needs_feedback')
    })
    // The failure info is surfaced...
    expect(screen.getByText(/verification failed after 3 attempt/)).toBeDefined()
    // ...and the user is prompted to continue in the conversation.
    expect(screen.getByTestId('needs-feedback-prompt')).toBeDefined()
    expect(screen.getByText('agents.optimizedPlan.needsInputTitle')).toBeDefined()
    expect(screen.getByTestId('continue-in-conversation')).toBeDefined()
    // The removed manual feedback form is gone.
    expect(screen.queryByTestId('optimized-plan-feedback-input')).toBeNull()
  })

  it('retire invalidates the whole agent-type query scope so Run Agent re-gates', async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    testQueryClient = client
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries')

    render(
      <AgentOptimizedPlanTab agentTypeId="at-1" onError={vi.fn()} onViewScript={vi.fn()} />,
      { wrapper },
    )

    fireEvent.click(await screen.findByTestId('retire-optimized-plan'))

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        '/agents/types/at-1/optimized-plan/retire',
      )
    })
    // The WHOLE agent-type scope is invalidated (optimized plan + base plan
    // + cached run-gate state), refetching even inactive queries, so the
    // Run Agent launch dialog immediately re-evaluates and shows the
    // opt-in optimization dialog instead of silently using a stale plan.
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['agents', 'types', 'at-1'],
        refetchType: 'all',
      })
    })
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['scripts'] })
    await waitFor(() => {
      expect(screen.getByTestId('retire-success')).toBeDefined()
    })
  })

  it('does not render the removed verification-log surface', async () => {
    render(
      <AgentOptimizedPlanTab agentTypeId="at-1" onError={vi.fn()} onViewScript={vi.fn()} />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.queryByRole('progressbar')).toBeNull()
    })
    // Verification happens inside the agent's REAL execution — the
    // user-facing verification log section and raw-log dialog are gone.
    expect(screen.queryByTestId('view-optimize-log-button')).toBeNull()
    expect(screen.queryByTestId('optimize-log-dialog')).toBeNull()
  })

  // ── requires_fix: self-healing human-in-the-loop surface ────────────────────

  const REQUIRES_FIX_PLAN: OptimizedPlanView = {
    ...PLAN,
    status: 'requires_fix',
    feedback_comments: [
      {
        created_at: '2026-10-22T00:00:00+00:00',
        raw_feedback: 'Script failed: the CRM tool returned a schema mismatch.',
        summary: 'Script failed: the CRM tool returned a schema mismatch.',
        source: 'execution_derived',
        source_execution_id: 'sess-failed-1',
        source_fallback_event_id: 'fb-1',
      },
      {
        created_at: '2026-10-21T00:00:00+00:00',
        raw_feedback: 'Make the output a table.',
        summary: 'Make the output a table.',
        source: 'manual',
      },
    ],
  }

  it('renders the requires_fix status and a concise re-optimize entry (no feedback dump)', async () => {
    mockApiGet.mockResolvedValue({ data: REQUIRES_FIX_PLAN })

    render(
      <AgentOptimizedPlanTab
        agentTypeId="at-1"
        agentTypeName="Test Agent"
        onError={vi.fn()}
        onViewScript={vi.fn()}
      />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByTestId('optimized-plan-status').textContent).toBe('requires_fix')
    })

    // Prominent alert with the human-readable explanation.
    expect(screen.getByTestId('requires-fix-alert')).toBeDefined()
    expect(screen.getByText('agents.optimizedPlan.requiresFixTitle')).toBeDefined()
    expect(screen.getByText('agents.optimizedPlan.requiresFixReason')).toBeDefined()

    // The alert points at the conversation; the auto-feedback dump is gone.
    expect(screen.getByTestId('reoptimize-from-alert')).toBeDefined()
    expect(screen.queryByTestId('requires-fix-feedback-0')).toBeNull()
    expect(screen.queryByTestId('feedback-source-0')).toBeNull()
  })

  it('re-optimize from the alert opens the optimizer conversation (no one-shot confirmation)', async () => {
    mockApiGet.mockResolvedValue({ data: REQUIRES_FIX_PLAN })

    render(
      <AgentOptimizedPlanTab
        agentTypeId="at-1"
        agentTypeName="Test Agent"
        onError={vi.fn()}
        onViewScript={vi.fn()}
      />,
      { wrapper },
    )

    const reoptimize = await screen.findByTestId('reoptimize-from-alert')
    fireEvent.click(reoptimize)

    // The old pre-start confirmation dialog and its one-shot run are gone.
    expect(screen.queryByText('agents.optimize.reoptimizeTitle')).toBeNull()
    expect(mockApiPost).not.toHaveBeenCalledWith('/agents/sessions/optimize', {
      agent_type_id: 'at-1',
    })
  })

  it('does not offer re-optimize for a ready plan', async () => {
    render(
      <AgentOptimizedPlanTab agentTypeId="at-1" onError={vi.fn()} onViewScript={vi.fn()} />,
      { wrapper },
    )

    expect(await screen.findByTestId('optimized-plan-status')).toBeDefined()
    expect(screen.queryByTestId('reoptimize-optimized-plan')).toBeNull()
    expect(screen.queryByTestId('reoptimize-from-alert')).toBeNull()
    expect(screen.queryByTestId('requires-fix-alert')).toBeNull()
  })

  it('shows a "nothing to retire" state and disables retire when the plan is already retired', async () => {
    mockApiGet.mockResolvedValue({ data: { ...PLAN, status: 'retired' } })

    render(
      <AgentOptimizedPlanTab agentTypeId="at-1" onError={vi.fn()} onViewScript={vi.fn()} />,
      { wrapper },
    )

    // The retired plan renders a clear "nothing to retire" indication instead
    // of a silent no-op, and the retire button is disabled.
    expect(await screen.findByTestId('nothing-to-retire')).toBeDefined()
    const retireButton = screen.getByTestId('retire-optimized-plan') as HTMLButtonElement
    expect(retireButton.disabled).toBe(true)
    fireEvent.click(retireButton)
    expect(mockApiPost).not.toHaveBeenCalled()
  })
})
