import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

const MOCK_AGENT_TYPES = [
  {
    id: 'at-1',
    name: 'Research Agent',
    description: null,
    identity_id: null,
    role_id: null,
    llm_provider: 'openai',
    llm_model: 'gpt-4o',
    system_instruction: null,
    input_type: 'typed',
    input_schema: null,
    output_type: 'markdown',
    output_schema: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

vi.mock('../hooks/useAgentTypes', () => ({
  useAgentTypes: () => ({
    data: MOCK_AGENT_TYPES,
    isLoading: false,
    error: null,
  }),
  useAgentInstances: () => ({ data: [], isLoading: false }),
  useTerminateInstance: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    post: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
    get: vi.fn().mockResolvedValue({ data: [] }),
    put: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AgentManagementPage', () => {
  it('renders the page heading', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.getByText('agents.title')).toBeDefined()
  })

  it('renders the agent type from mock data', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.getByText('Research Agent')).toBeDefined()
  })

  it('renders input_type chip for agent type', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    // input_type 'typed' shown as chip
    expect(screen.getByText('typed')).toBeDefined()
  })

  it('does not render old mode or max_instances fields', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.queryByText('agents.skillfulAgent')).toBeNull()
    expect(screen.queryByText('max_instances')).toBeNull()
  })

  it('renders Create Agent Type button', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.getByRole('button', { name: /agents\.createType/i })).toBeDefined()
  })

  it('opens dialog when Create Agent Type is clicked', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: /agents\.createType/i }))
    expect(screen.getByRole('dialog')).toBeDefined()
  })

  it('renders Launch (PlayArrow) button per agent type row', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    // Tooltip wraps icon button with aria-label agents.types.launch
    expect(screen.getByRole('button', { name: 'agents.types.launch' })).toBeDefined()
  })

  it('opens AgentJobLaunchDialog when Launch is clicked', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })

    // Find and click the launch button by its accessible name
    const launchBtn = screen.getByRole('button', { name: 'agents.types.launch' })
    await act(async () => {
      fireEvent.click(launchBtn)
    })

    // Launch dialog should open
    await waitFor(() => {
      expect(screen.getByText('agents.sessions.launch')).toBeDefined()
    })
  })

  it('renders Edit button per agent type row', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    expect(screen.getByRole('button', { name: 'app.edit' })).toBeDefined()
  })
})
