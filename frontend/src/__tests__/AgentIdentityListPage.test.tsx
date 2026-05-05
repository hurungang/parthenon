import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// Identities using the new realm_user model (realm_name + realm_username + token fields)
const MOCK_IDENTITIES = [
  {
    id: 'id-1',
    name: 'OAuth Bot',
    realm_name: 'ai_agents',
    realm_username: 'agent-user-1',
    status: 'active',
    token_expires_at: '2099-01-01T00:00:00Z',  // active token
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'id-2',
    name: 'Suspended Bot',
    realm_name: 'ai_agents',
    realm_username: 'agent-user-2',
    status: 'suspended',
    token_expires_at: null,  // no token
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: MOCK_IDENTITIES }),
    post: vi.fn().mockResolvedValue({ data: MOCK_IDENTITIES[0] }),
    put: vi.fn().mockResolvedValue({ data: MOCK_IDENTITIES[0] }),
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

describe('AgentIdentityListPage', () => {
  it('renders the page heading', async () => {
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('agents.identities.title')).toBeDefined()
    })
  })

  it('renders identity names from API data', async () => {
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('OAuth Bot')).toBeDefined()
      expect(screen.getByText('Suspended Bot')).toBeDefined()
    })
  })

  it('renders realm_name column', async () => {
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('agents.identities.realmName')).toBeDefined()
    })
  })

  it('renders realm_username column', async () => {
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('agents.identities.realmUsername')).toBeDefined()
    })
  })

  it('renders realm values for each identity row', async () => {
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => {
      // Both identities share the same realm name
      const realmCells = screen.getAllByText('ai_agents')
      expect(realmCells.length).toBeGreaterThanOrEqual(2)
    })
  })

  it('renders status chips', async () => {
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('agents.identities.statusActive')).toBeDefined()
      expect(screen.getByText('agents.identities.statusSuspended')).toBeDefined()
    })
  })

  it('renders token active chip when token_expires_at is in the future', async () => {
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('agents.identities.tokenActive')).toBeDefined()
    })
  })

  it('renders no-token indicator when token_expires_at is null', async () => {
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('agents.identities.noToken')).toBeDefined()
    })
  })

  it('renders OAuth section column header', async () => {
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('agents.identities.oauthSection')).toBeDefined()
    })
  })

  it('renders Add Identity button', async () => {
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('agents.identities.create')).toBeDefined()
    })
  })

  it('opens AgentIdentityDialog when Add Identity is clicked', async () => {
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    render(<AgentIdentityListPage />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('agents.identities.create')).toBeDefined()
    })

    await act(async () => {
      fireEvent.click(screen.getByText('agents.identities.create'))
    })

    await waitFor(() => {
      expect(screen.getByText('agents.identities.createTitle')).toBeDefined()
    })
  })
})

