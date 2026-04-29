import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => vi.fn() }
})

vi.mock('../hooks/useAgentTypes', () => ({
  useAgentTypes: () => ({
    data: [
      {
        id: 'at-1',
        name: 'Research Agent',
        mode: 'skillful-agent',
        llm_provider: 'openai',
        llm_model: 'gpt-4o',
        max_instances: 3,
        is_active: true,
        description: '',
      },
    ],
    isLoading: false,
  }),
  useAgentInstances: () => ({ data: [], isLoading: false }),
  useTerminateInstance: () => ({ mutate: vi.fn(), isPending: false }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    post: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
    get: vi.fn().mockResolvedValue({ data: [] }),
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

  it('renders the operating mode chip', async () => {
    const { AgentManagementPage } = await import('../pages/agents/AgentManagementPage')
    render(<AgentManagementPage />, { wrapper })
    // Mode is displayed as translated key (e.g. agents.skillfulAgent)
    expect(screen.getByText('agents.skillfulAgent')).toBeDefined()
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
})
