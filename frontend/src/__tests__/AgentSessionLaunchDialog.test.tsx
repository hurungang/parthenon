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

  it('calls onLaunched with session ID on successful submit', async () => {
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

    await act(async () => {
      fireEvent.click(screen.getByText('agents.sessions.launch'))
    })

    // No verified optimized plan → the opt-in optimization dialog appears.
    await waitFor(() => {
      expect(screen.getByText('agents.sessions.skipOptimization')).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByText('agents.sessions.skipOptimization'))
    })

    await waitFor(() => {
      expect(onLaunched).toHaveBeenCalledWith(sessionId)
    })
    expect(mockPost).toHaveBeenCalledWith(
      '/agents/sessions',
      expect.objectContaining({ optimize: false }),
    )
  })

  it('launches directly when a ready optimized plan exists', async () => {
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

    await act(async () => {
      fireEvent.click(screen.getByText('agents.sessions.launch'))
    })

    await waitFor(() => {
      expect(onLaunched).toHaveBeenCalledWith(sessionId)
    })
    // The opt-in dialog never appears when a verified plan exists.
    expect(screen.queryByText('agents.sessions.runWithOptimization')).toBeNull()
    expect(mockPost).toHaveBeenCalledWith(
      '/agents/sessions',
      expect.objectContaining({ optimize: false }),
    )
  })

  it('passes optimize: true when the user opts in', async () => {
    const { AgentJobLaunchDialog } = await import('../pages/agents/AgentJobLaunchDialog')
    const sessionId = 'sess-opt'
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

    await act(async () => {
      fireEvent.click(screen.getByText('agents.sessions.launch'))
    })

    await waitFor(() => {
      expect(screen.getByText('agents.sessions.runWithOptimization')).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByTestId('run-with-optimization'))
    })

    await waitFor(() => {
      expect(onLaunched).toHaveBeenCalledWith(sessionId)
    })
    expect(mockPost).toHaveBeenCalledWith(
      '/agents/sessions',
      expect.objectContaining({ optimize: true }),
    )
  })

  it('shows PermissionDeniedAlert when API call fails', async () => {
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

    await waitFor(() => {
      expect(screen.getByText('agents.sessions.skipOptimization')).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByText('agents.sessions.skipOptimization'))
    })

    await waitFor(() => {
      const alerts = screen.getAllByRole('alert')
      expect(alerts.length).toBeGreaterThan(0)
    })
  })

  it('clears error on dialog open', async () => {
    const { AgentJobLaunchDialog } = await import('../pages/agents/AgentJobLaunchDialog')
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
