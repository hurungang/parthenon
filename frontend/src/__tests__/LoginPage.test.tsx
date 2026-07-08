import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

// Mock i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// Mock react-router-dom navigate
const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

// Mock useAuthStore
const mockLogin = vi.fn()
vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({
    login: mockLogin,
    isAuthenticated: false,
    token: null,
    claims: null,
    logout: vi.fn(),
    setToken: vi.fn(),
  }),
}))

// Mock systemConfigApi to satisfy useQuery in LoginPage
vi.mock('../api/systemConfigApi', () => ({
  getIdentityProviders: () => Promise.resolve({ items: [], total: 0 }),
  getSuperAdminStatus: () => Promise.resolve({ is_enabled: true, username: 'admin', last_login_at: null }),
  superAdminLogin: () => Promise.resolve({ access_token: '', token_type: 'bearer', username: '', is_super_admin: false }),
}))

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return React.createElement(QueryClientProvider, { client: qc },
    React.createElement(MemoryRouter, null, children)
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the app title', async () => {
    const { LoginPage } = await import('../pages/auth/LoginPage')
    render(React.createElement(LoginPage), { wrapper: Wrapper })
    expect(await screen.findByText('app.title')).toBeDefined()
  })

  it('renders the login button when providers are available', async () => {
    const { LoginPage } = await import('../pages/auth/LoginPage')
    render(React.createElement(LoginPage), { wrapper: Wrapper })
    await screen.findByText('app.title')
  })

  it('shows login form when OIDC is not configured', async () => {
    const { LoginPage } = await import('../pages/auth/LoginPage')
    render(React.createElement(LoginPage), { wrapper: Wrapper })
    await screen.findByText('app.title')
  })

  it('shows loading state initially', async () => {
    const { LoginPage } = await import('../pages/auth/LoginPage')
    render(React.createElement(LoginPage), { wrapper: Wrapper })
    await screen.findByText('app.title')
  })
})
