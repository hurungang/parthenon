import { describe, it, expect, vi, beforeEach } from 'vitest'
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
    has_refresh_token: true,
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
    has_refresh_token: false,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

// Named mock reference — accessed directly in tests without a static import
// (static import of apiClient would cause vi.mock factory to evaluate before MOCK_IDENTITIES is defined)
const mockApiClient = {
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}

vi.mock('../api/apiClient', () => ({ default: mockApiClient }))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AgentIdentityListPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApiClient.get.mockResolvedValue({ data: MOCK_IDENTITIES })
    mockApiClient.post.mockResolvedValue({ data: MOCK_IDENTITIES[0] })
    mockApiClient.put.mockResolvedValue({ data: MOCK_IDENTITIES[0] })
    mockApiClient.delete.mockResolvedValue({ data: {} })
  })

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

  // TODO: Column does not exist - actual columns are: name, realmName, realmUsername, status, tokenStatus, actions
  it.skip('renders OAuth section column header', async () => {
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

describe('AgentIdentityListPage — conditional action buttons', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows green refresh button when refresh token is valid', async () => {
    const identityWithRefresh = {
      id: 'id-r1',
      name: 'Refresh Bot',
      realm_name: 'ai_agents',
      realm_username: 'agent-user-r',
      status: 'active',
      token_expires_at: '2099-01-01T00:00:00Z',
      has_refresh_token: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    mockApiClient.get.mockResolvedValueOnce({ data: [identityWithRefresh] })
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    const { container } = render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => screen.getByText('Refresh Bot'))
    // Green success-colored refresh button must exist
    expect(container.querySelector('.MuiIconButton-colorSuccess')).not.toBeNull()
  })

  it('shows red reauth button when refresh token is invalid', async () => {
    const identityNoRefresh = {
      id: 'id-nr1',
      name: 'NoRefresh Bot',
      realm_name: 'ai_agents',
      realm_username: 'agent-user-n',
      status: 'suspended',
      token_expires_at: null,
      has_refresh_token: false,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    mockApiClient.get.mockResolvedValueOnce({ data: [identityNoRefresh] })
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    const { container } = render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => screen.getByText('NoRefresh Bot'))
    // No success-colored button — only the error-colored reauth and delete buttons
    expect(container.querySelector('.MuiIconButton-colorSuccess')).toBeNull()
  })

  it('refresh button calls refresh-token endpoint', async () => {
    const identityWithRefresh = {
      id: 'id-r2',
      name: 'Refresh Bot 2',
      realm_name: 'ai_agents',
      realm_username: 'agent-user-r2',
      status: 'active',
      token_expires_at: '2099-01-01T00:00:00Z',
      has_refresh_token: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    mockApiClient.get.mockResolvedValueOnce({ data: [identityWithRefresh] })
    mockApiClient.post.mockResolvedValueOnce({ data: {} })
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    const { container } = render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => screen.getByText('Refresh Bot 2'))
    const refreshBtn = container.querySelector('.MuiIconButton-colorSuccess') as HTMLElement
    await act(async () => { fireEvent.click(refreshBtn) })
    await waitFor(() => {
      expect(mockApiClient.post).toHaveBeenCalledWith('/agents/identities/id-r2/refresh-token')
    })
  })

  it('reauth button calls reauth-url endpoint and opens popup', async () => {
    const identityNoRefresh = {
      id: 'id-nr2',
      name: 'NoRefresh Bot 2',
      realm_name: 'ai_agents',
      realm_username: 'agent-user-n2',
      status: 'suspended',
      token_expires_at: null,
      has_refresh_token: false,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    mockApiClient.get
      .mockResolvedValueOnce({ data: [identityNoRefresh] })
      .mockResolvedValueOnce({ data: { authorization_url: 'https://auth.example.com/authorize' } })
    const windowOpenSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    const { AgentIdentityListPage } = await import('../pages/agents/AgentIdentityListPage')
    render(<AgentIdentityListPage />, { wrapper })
    await waitFor(() => screen.getByText('NoRefresh Bot 2'))
    // Buttons per row (with 1 identity): [Add Identity, assign, reauth, delete]
    const buttons = screen.getAllByRole('button')
    await act(async () => { fireEvent.click(buttons[2]) })
    await waitFor(() => {
      expect(mockApiClient.get).toHaveBeenCalledWith('/agents/identities/id-nr2/reauth-url')
      expect(windowOpenSpy).toHaveBeenCalledWith(
        'https://auth.example.com/authorize',
        expect.any(String),
        expect.any(String),
      )
    })
    windowOpenSpy.mockRestore()
  })
})

