import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

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

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the app title', async () => {
    const { LoginPage } = await import('../pages/auth/LoginPage')
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    )
    expect(screen.getByText('app.title')).toBeDefined()
  })

  it('renders the login button', async () => {
    const { LoginPage } = await import('../pages/auth/LoginPage')
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    )
    const btn = screen.getByRole('button', { name: 'auth.login' })
    expect(btn).toBeDefined()
  })

  it('calls login() when the button is clicked', async () => {
    const { LoginPage } = await import('../pages/auth/LoginPage')
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    )
    fireEvent.click(screen.getByRole('button', { name: 'auth.login' }))
    expect(mockLogin).toHaveBeenCalledTimes(1)
  })

  it('shows the loginWith subtitle text', async () => {
    const { LoginPage } = await import('../pages/auth/LoginPage')
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    )
    expect(screen.getByText('auth.loginWith')).toBeDefined()
  })
})
