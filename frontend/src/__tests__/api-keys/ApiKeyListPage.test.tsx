import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

const { mockApiClient } = vi.hoisted(() => {
  return {
    mockApiClient: {
      get: vi.fn(),
      post: vi.fn(),
    },
  }
})

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../../api/apiClient', () => ({ default: mockApiClient }))

import { ApiKeyListPage } from '../../pages/api-keys/ApiKeyListPage'

const MOCK_KEYS = [
  {
    id: 'key-1',
    name: 'Test Agent Key',
    key_prefix: 'phn_sk_',
    agent_identity_id: 'identity-1',
    agent_identity_name: 'Agent X',
    agent_role_id: 'role-1',
    agent_role_name: 'Developer',
    status: 'active',
    created_at: '2026-01-01T00:00:00Z',
    last_used_at: '2026-06-01T00:00:00Z',
  },
  {
    id: 'key-2',
    name: 'Revoked Key',
    key_prefix: 'phn_sk_',
    agent_identity_id: 'identity-2',
    agent_identity_name: 'Agent Y',
    agent_role_id: 'role-2',
    agent_role_name: 'Viewer',
    status: 'revoked',
    created_at: '2026-01-15T00:00:00Z',
    last_used_at: null,
  },
]

const MOCK_IDENTITIES = [
  {
    identity_id: 'identity-1',
    identity_name: 'Agent X',
    roles: [
      { role_id: 'role-1', role_name: 'Developer' },
      { role_id: 'role-2', role_name: 'Viewer' },
    ],
  },
]

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('ApiKeyListPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApiClient.get.mockImplementation((url: string) => {
      if (url === '/api-keys') {
        return Promise.resolve({ data: MOCK_KEYS })
      }
      if (url === '/api-keys/identities-with-roles') {
        return Promise.resolve({ data: MOCK_IDENTITIES })
      }
      return Promise.resolve({ data: [] })
    })
  })

  it('renders the page title', async () => {
    render(<ApiKeyListPage />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText('apiKeys.title')).toBeDefined()
    })
  })

  it('renders the create button', async () => {
    render(<ApiKeyListPage />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText('apiKeys.createKey')).toBeDefined()
    })
  })

  it('renders key rows after loading', async () => {
    render(<ApiKeyListPage />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText('Test Agent Key')).toBeDefined()
      expect(screen.getByText('Revoked Key')).toBeDefined()
    })
  })

  it('renders agent identity names', async () => {
    render(<ApiKeyListPage />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText('Agent X')).toBeDefined()
      expect(screen.getByText('Agent Y')).toBeDefined()
    })
  })

  it('shows info banner', async () => {
    render(<ApiKeyListPage />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText('apiKeys.infoBanner')).toBeDefined()
    })
  })

  it('shows error state on API failure', async () => {
    mockApiClient.get.mockRejectedValue(new Error('Network error'))
    render(<ApiKeyListPage />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeDefined()
    })
  })

  it('shows empty state when no keys', async () => {
    mockApiClient.get.mockResolvedValue({ data: [] })
    render(<ApiKeyListPage />, { wrapper: Wrapper })
    await waitFor(() => {
      expect(screen.getByText('apiKeys.emptyTitle')).toBeDefined()
    })
  })
})
