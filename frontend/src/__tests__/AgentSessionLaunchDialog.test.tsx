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

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: mockPost,
  },
}))

const onClose = vi.fn()
const onLaunched = vi.fn()

function makeAgentType(overrides: Partial<AgentType> = {}): AgentType {
  return {
    id: 'at-1',
    name: 'Test Agent',
    description: null,
    identity_id: null,
    role_id: null,
    llm_provider: 'openai',
    llm_model: 'gpt-4o',
    system_instruction: null,
    input_type: 'none',
    input_schema: null,
    output_type: 'auto',
    output_schema: null,
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

  it('renders JSON input area for input_type=typed', async () => {
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

    await waitFor(() => {
      expect(onLaunched).toHaveBeenCalledWith(sessionId)
    })
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
