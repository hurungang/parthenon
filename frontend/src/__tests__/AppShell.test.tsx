import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({
    login: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    token: 'mock-token',
    claims: { sub: 'user1', exp: 9999999999, iat: 0, name: 'Admin' },
    setToken: vi.fn(),
  }),
}))

// Mock react-router-dom keeping Outlet etc but stubbing useNavigate/useLocation
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useLocation: () => ({ pathname: '/dashboard' }),
    Outlet: () => <div data-testid="outlet-content" />,
  }
})

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient()
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/dashboard']}>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AppShell', () => {
  it('renders navigation drawer with dashboard item', async () => {
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    // Nav items appear in both permanent and temporary drawers — use getAllByText
    const items = screen.getAllByText('nav.dashboard')
    expect(items.length).toBeGreaterThanOrEqual(1)
  })

  it('renders MCP Hub nav item', async () => {
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    const items = screen.getAllByText('nav.mcpHub')
    expect(items.length).toBeGreaterThanOrEqual(1)
  })

  it('renders Agents nav item', async () => {
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    const items = screen.getAllByText('nav.agents')
    expect(items.length).toBeGreaterThanOrEqual(1)
  })

  it('renders the app bar title', async () => {
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    const titles = screen.getAllByText('app.title')
    expect(titles.length).toBeGreaterThanOrEqual(1)
  })

  it('renders the outlet placeholder', async () => {
    const { AppShell } = await import('../app/AppShell')
    render(<AppShell />, { wrapper })
    expect(screen.getByTestId('outlet-content')).toBeDefined()
  })
})
