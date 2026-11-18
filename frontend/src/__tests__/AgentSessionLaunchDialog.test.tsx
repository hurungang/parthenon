import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import type { AgentType } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockPost = vi.fn()
const mockGet = vi.fn()

vi.mock('../api/apiClient', () => ({
  default: {
    get: mockGet,
    post: mockPost,
  },
}))

/** Default GET routing: the optimized-plan lookup 404s (no plan yet). */
function defaultGetRouting() {
  mockGet.mockImplementation((url: string) => {
    if (url.includes('optimized-plan')) {
      return Promise.reject({ response: { status: 404 } })
    }
    return Promise.resolve({ data: {} })
  })
}

function mockReadyOptimizedPlan() {
  mockGet.mockImplementation((url: string) => {
    if (url.includes('optimized-plan')) {
      return Promise.resolve({ data: { status: 'ready' } })
    }
    return Promise.resolve({ data: {} })
  })
}

const onClose = vi.fn()
const onLaunched = vi.fn()

function makeAgentType(overrides: Partial<AgentType> = {}): AgentType {
  return {
    id: 'at-1',
    name: 'Test Agent',
    description: null,
    identity_id: null,
    role_id: null,
    model_id: 'gpt-4o',
    system_instruction: null,
    input_type: 'none',
    input_schema: null,
    output_type: 'auto',
    output_schema: null,
    output_data_type_id: null,
    output_data_type_name: null,
    sop_bindings: [],
    skill_bindings: [],
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AgentJobLaunchDialog', () => {
  afterEach(() => {
    vi.clearAllMocks()
    defaultGetRouting()
  })

  it('renders launch button for input_type=none (no input fields)', async () => {
    const { AgentJobLaunchDialog } = await import('../pages/agents/AgentJobLaunchDialog')
    const agentType = makeAgentType({ input_type: 'none' })

    render(
      <AgentJobLaunchDialog
        open={true}
        agentType={agentType}
        onClose={onClose}
        onLaunched={onLaunched}
      />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.sessions.launch')).toBeDefined()
    })

    // No text area or input field for input_type=none
    const textareas = screen.queryAllByRole('textbox')
    expect(textareas.length).toBe(0)
  })

  // TODO: Fix test - component uses DynamicSchemaForm by default (not textbox), only shows textbox when useRawJson=true
  it.skip('renders JSON input area for input_type=typed', async () => {
    const { AgentJobLaunchDialog } = await import('../pages/agents/AgentJobLaunchDialog')
    const agentType = makeAgentType({ input_type: 'typed' })

    render(
      <AgentJobLaunchDialog
        open={true}
        agentType={agentType}
        onClose={onClose}
        onLaunched={onLaunched}
      />,
      { wrapper },
    )

    await waitFor(() => {
      // Typed input renders a JSON text field
      const textarea = screen.getByRole('textbox')
      expect(textarea).toBeDefined()
    })
  })

  it('renders message textarea for input_type=conversation', async () => {
    const { AgentJobLaunchDialog } = await import('../pages/agents/AgentJobLaunchDialog')
    const agentType = makeAgentType({ input_type: 'conversation' })

    render(
      <AgentJobLaunchDialog
        open={true}
        agentType={agentType}
        onClose={onClose}
        onLaunched={onLaunched}
      />,
      { wrapper },
    )

    await waitFor(() => {
      const textarea = screen.getByRole('textbox')
      expect(textarea).toBeDefined()
    })
  })

  it('calls onLaunched with session ID on successful submit (execution-only, no optimize field)', async () => {
    const { AgentJobLaunchDialog } = await import('../pages/agents/AgentJobLaunchDialog')
    const sessionId = 'sess-123'
    mockPost.mockResolvedValue({ data: { id: sessionId, status: 'queued' } })
    const agentType = makeAgentType({ input_type: 'none' })

    render(
      <AgentJobLaunchDialog
        open={true}
        agentType={agentType}
        onClose={onClose}
        onLaunched={onLaunched}
      />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.sessions.launch')).toBeDefined()
    })

    // Run launches IMMEDIATELY — no opt-in optimization sub-dialog interrupts it.
    await act(async () => {
      fireEvent.click(screen.getByText('agents.sessions.launch'))
    })

    await waitFor(() => {
      expect(onLaunched).toHaveBeenCalledWith(sessionId)
    })

    // No optimization sub-step appeared at any point.
    expect(screen.queryByText('agents.sessions.skipOptimization')).toBeNull()
    expect(screen.queryByText('agents.sessions.runWithOptimization')).toBeNull()

    // The launch payload is execution-only: no `optimize` discriminator.
    expect(mockPost).toHaveBeenCalledTimes(1)
    expect(mockPost).toHaveBeenCalledWith('/agents/sessions', expect.any(Object))
    const body = mockPost.mock.calls[0][1] as Record<string, unknown>
    expect(body.agent_type_id).toBe('at-1')
    expect(Object.prototype.hasOwnProperty.call(body, 'optimize')).toBe(false)
  })

  it('launches directly when a ready optimized plan exists (no opt-in dialog)', async () => {
    const { AgentJobLaunchDialog } = await import('../pages/agents/AgentJobLaunchDialog')
    const sessionId = 'sess-ready'
    mockReadyOptimizedPlan()
    mockPost.mockResolvedValue({ data: { id: sessionId, status: 'queued' } })
    const agentType = makeAgentType({ input_type: 'none' })

    render(
      <AgentJobLaunchDialog
        open={true}
        agentType={agentType}
        onClose={onClose}
        onLaunched={onLaunched}
      />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.sessions.launch')).toBeDefined()
    })

    // Let the optimized-plan query resolve before launching.
    await waitFor(() => {
      expect(mockGet.mock.calls.some((c) => String(c[0]).includes('optimized-plan'))).toBe(true)
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })

    // The ready-plan presence is informational only — it says the run will
    // try the plan first, not that the run optimizes.
    expect(await screen.findByTestId('run-execution-only-hint')).toBeDefined()
    expect(screen.getByText('agents.sessions.optimizedPlanPresent')).toBeDefined()

    await act(async () => {
      fireEvent.click(screen.getByText('agents.sessions.launch'))
    })

    await waitFor(() => {
      expect(onLaunched).toHaveBeenCalledWith(sessionId)
    })
    // The opt-in dialog never appears when a verified plan exists.
    expect(screen.queryByText('agents.sessions.runWithOptimization')).toBeNull()
    expect(screen.queryByText('agents.sessions.skipOptimization')).toBeNull()
    const body = mockPost.mock.calls[0][1] as Record<string, unknown>
    expect(Object.prototype.hasOwnProperty.call(body, 'optimize')).toBe(false)
  })

  it('shows the model-path hint and never offers "run with optimization" without a ready plan', async () => {
    const { AgentJobLaunchDialog } = await import('../pages/agents/AgentJobLaunchDialog')
    const sessionId = 'sess-model'
    mockPost.mockResolvedValue({ data: { id: sessionId, status: 'queued' } })
    const agentType = makeAgentType({ input_type: 'none' })

    render(
      <AgentJobLaunchDialog
        open={true}
        agentType={agentType}
        onClose={onClose}
        onLaunched={onLaunched}
      />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.sessions.launch')).toBeDefined()
    })

    // The removed opt-in affordances are gone from the surface entirely.
    expect(screen.queryByText('agents.sessions.runWithOptimization')).toBeNull()
    expect(screen.queryByTestId('run-with-optimization')).toBeNull()
    expect(screen.queryByText('agents.sessions.skipOptimization')).toBeNull()
    expect(screen.getByText('agents.sessions.modelPath')).toBeDefined()
  })

  it('shows PermissionDeniedAlert inline when the API call fails (no sub-dialog)', async () => {
    const { AgentJobLaunchDialog } = await import('../pages/agents/AgentJobLaunchDialog')
    const mockError = { response: { status: 403, data: { detail: 'Forbidden' } } }
    mockPost.mockRejectedValue(mockError)
    const agentType = makeAgentType({ input_type: 'none' })

    render(
      <AgentJobLaunchDialog
        open={true}
        agentType={agentType}
        onClose={onClose}
        onLaunched={onLaunched}
      />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.sessions.launch')).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByText('agents.sessions.launch'))
    })

    // The failure is reported in the launch dialog itself — execution never
    // took a detour through a removed optimization sub-dialog.
    await waitFor(() => {
      const alerts = screen.getAllByRole('alert')
      expect(alerts.length).toBeGreaterThan(0)
    })
    expect(screen.getByText('Forbidden')).toBeDefined()
    expect(screen.queryByText('agents.sessions.skipOptimization')).toBeNull()
    expect(onLaunched).not.toHaveBeenCalled()
  })

  it('offers no plan-generation action — Run is execution-only', async () => {
    const { AgentJobLaunchDialog } = await import('../pages/agents/AgentJobLaunchDialog')
    const agentType = makeAgentType({ input_type: 'none' })

    render(
      <AgentJobLaunchDialog
        open={true}
        agentType={agentType}
        onClose={onClose}
        onLaunched={onLaunched}
      />,
      { wrapper },
    )

    await waitFor(() => {
      expect(screen.getByText('agents.sessions.launch')).toBeDefined()
    })

    // No generate/regenerate affordances on the launch surface.
    expect(screen.queryByText('agents.plan.generate')).toBeNull()
    expect(screen.queryByText('agents.plan.regenerate')).toBeNull()
    expect(screen.queryByTestId('plan-generate')).toBeNull()
    expect(screen.queryByTestId('plan-regenerate')).toBeNull()

    // Opening (and settling) the dialog never fires a plan-generation request.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('keeps the stale-plan note informational and points at Plan Preview', async () => {
    const { AgentJobLaunchDialog } = await import('../pages/agents/AgentJobLaunchDialog')
    mockGet.mockImplementation((url: string) => {
      if (url === '/agents/roles') {
        return Promise.resolve({
          data: [
            {
              id: 'role-1',
              name: 'Research Role',
              description: null,
              sop_ids: [],
              skill_ids: [],
              allowed_identity_types: [],
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-02-01T00:00:00Z',
            },
          ],
        })
      }
      if (url === '/sops' || url === '/skills') {
        return Promise.resolve({ data: [] })
      }
      if (url.includes('optimized-plan')) {
        return Promise.reject({ response: { status: 404 } })
      }
      return Promise.resolve({ data: {} })
    })

    const agentType = makeAgentType({
      input_type: 'none',
      role_id: 'role-1',
      plan: {
        id: 'plan-1',
        agent_type_id: 'at-1',
        plan_steps: [
          { order: 1, type: 'tool_call', name: 'Search', description: null },
        ],
        topology_nodes: [],
        topology_edges: [],
        generation_status: 'success',
        generation_error: null,
        agent_config_hash: 'hash',
        generated_at: '2026-01-01T00:00:00Z',
      },
    })

    render(
      <AgentJobLaunchDialog
        open={true}
        agentType={agentType}
        onClose={onClose}
        onLaunched={onLaunched}
      />,
      { wrapper },
    )

    const note = await screen.findByTestId('stale-plan-note')
    // The note explains staleness AND how to fix it (explicit regeneration in
    // the Plan Preview tab) — it is not an action here.
    expect(note.textContent).toContain('This plan is older than the current role definition.')
    expect(note.textContent).toContain('agents.sessions.stalePlanHint')
    expect(screen.queryByTestId('plan-regenerate')).toBeNull()

    // Informational only: opening the dialog regenerates nothing.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('clears error on dialog open', async () => {    const { AgentJobLaunchDialog } = await import('../pages/agents/AgentJobLaunchDialog')
    const agentType = makeAgentType({ input_type: 'none' })

    const { rerender } = render(
      <AgentJobLaunchDialog
        open={false}
        agentType={agentType}
        onClose={onClose}
        onLaunched={onLaunched}
      />,
      { wrapper },
    )

    // Reopen — rerender uses the same wrapper, don't double-wrap
    await act(async () => {
      rerender(
        <AgentJobLaunchDialog
          open={true}
          agentType={agentType}
          onClose={onClose}
          onLaunched={onLaunched}
        />
      )
    })

    await waitFor(() => {
      // The info confirmation alert is expected for input_type=none
      // Verify no dialogError/permission denied alert is shown
      expect(screen.queryByText('app.error')).toBeNull()
    })
  })
})
