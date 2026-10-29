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

  it('renders a View script link only on script-backed steps and calls onViewScript', async () => {
    const onViewScript = vi.fn()
    render(
      <AgentOptimizedPlanTab agentTypeId="at-1" onError={vi.fn()} onViewScript={onViewScript} />,
      { wrapper },
    )

    const link = await screen.findByTestId('view-script-link-0')
    expect(screen.queryByTestId('view-script-link-1')).toBeNull()
    fireEvent.click(link)
    expect(onViewScript).toHaveBeenCalledOnce()
    // The step is passed so the direct script dialog can show its source.
    expect(onViewScript).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Fetch contact', python_source: expect.any(String) }),
    )
  })

  it('renders accumulated feedback comments', async () => {
    render(
      <AgentOptimizedPlanTab agentTypeId="at-1" onError={vi.fn()} onViewScript={vi.fn()} />,
      { wrapper },
    )

    expect(await screen.findByText('Make the output a table.')).toBeDefined()
  })

  it('submits feedback via the feedback endpoint and refreshes the plan', async () => {
    render(
      <AgentOptimizedPlanTab agentTypeId="at-1" onError={vi.fn()} onViewScript={vi.fn()} />,
      { wrapper },
    )

    const input = (await screen.findByTestId(
      'optimized-plan-feedback-input',
    )) as HTMLElement
    const textarea = input.querySelector('textarea') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: 'Make the output a table.' } })
    fireEvent.click(screen.getByTestId('optimized-plan-feedback-submit'))

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        '/agents/types/at-1/optimize-plan/feedback',
        { feedback: 'Make the output a table.' },
      )
    })
    // Plan re-fetched after the feedback mutation succeeds.
    await waitFor(() => {
      expect(mockApiGet.mock.calls.length).toBeGreaterThanOrEqual(2)
    })
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
    // ...and the user is prompted to steer via feedback.
    expect(screen.getByTestId('needs-feedback-prompt')).toBeDefined()
    expect(
      screen.getByText('agents.optimizedPlan.needsFeedbackPrompt'),
    ).toBeDefined()
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
