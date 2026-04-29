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

// Mock the hooks used by McpHubPage
vi.mock('../hooks/useMcpServers', () => ({
  useMcpServers: () => ({
    data: [
      { id: 'srv-1', name: 'My Tools', slug: 'my-tools', base_url: 'http://mcp.local', status: 'active', description: '' },
    ],
    isLoading: false,
  }),
  useSyncServer: () => ({ mutate: vi.fn(), isPending: false }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
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

describe('McpHubPage', () => {
  it('renders the page heading', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    expect(screen.getByText('mcp.title')).toBeDefined()
  })

  it('renders the server from mock data', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    expect(screen.getAllByText('My Tools')[0]).toBeDefined()
  })

  it('renders the server slug', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    expect(screen.getByText('my-tools')).toBeDefined()
  })

  it('renders Register Server button', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    expect(screen.getByRole('button', { name: /mcp\.registerServer/i })).toBeDefined()
  })

  it('opens dialog when Register Server is clicked', async () => {
    const { McpHubPage } = await import('../pages/mcp/McpHubPage')
    render(<McpHubPage />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: /mcp\.registerServer/i }))
    expect(screen.getByRole('dialog')).toBeDefined()
  })
})
