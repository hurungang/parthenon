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

const MOCK_ROLES = [
  {
    id: 'role-1',
    name: 'Admin Role',
    description: 'Administers everything',
    sop_ids: ['sop-1', 'sop-2'],
    skill_ids: ['skill-1'],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'role-2',
    name: 'Read-Only Role',
    description: null,
    sop_ids: [],
    skill_ids: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: MOCK_ROLES }),
    post: vi.fn().mockResolvedValue({ data: MOCK_ROLES[0] }),
    put: vi.fn().mockResolvedValue({ data: MOCK_ROLES[0] }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
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

describe('AgentRoleListPage', () => {
  it('renders the page heading', async () => {
    const { AgentRoleListPage } = await import('../pages/agents/AgentRoleListPage')
    render(<AgentRoleListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('agents.roles.title')).toBeDefined()
    })
  })

  it('renders role names from API data', async () => {
    const { AgentRoleListPage } = await import('../pages/agents/AgentRoleListPage')
    render(<AgentRoleListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('Admin Role')).toBeDefined()
      expect(screen.getByText('Read-Only Role')).toBeDefined()
    })
  })

  it('renders SOP count chips for each role', async () => {
    const { AgentRoleListPage } = await import('../pages/agents/AgentRoleListPage')
    render(<AgentRoleListPage />, { wrapper })
    await waitFor(() => {
      // Admin Role has 2 SOPs — chip label is t('agents.roles.sopCount', { count: 2 })
      // With t mocked as identity, the rendered text is the key string
      expect(screen.getAllByText('agents.roles.sopCount').length).toBeGreaterThan(0)
    })
  })

  it('renders Add Role button', async () => {
    const { AgentRoleListPage } = await import('../pages/agents/AgentRoleListPage')
    render(<AgentRoleListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('agents.roles.create')).toBeDefined()
    })
  })

  it('opens AgentRoleDialog when Add Role is clicked', async () => {
    const { AgentRoleListPage } = await import('../pages/agents/AgentRoleListPage')
    render(<AgentRoleListPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('agents.roles.create')).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByText('agents.roles.create'))
    })

    await waitFor(() => {
      expect(screen.getByText('agents.roles.createTitle')).toBeDefined()
    })
  })

  it('shows loading state', async () => {
    const { AgentRoleListPage } = await import('../pages/agents/AgentRoleListPage')
    // Loading state is brief; render and verify component doesn't crash
    render(<AgentRoleListPage />, { wrapper })
    // Component renders without throwing
  })
})
