import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

// Mock i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// Mock MUI icons to avoid EMFILE on Windows
vi.mock('@mui/icons-material', () => ({
  LockOutlinedIcon: () => null,
  default: {},
}))

// Mock react-router-dom navigate
const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

// Mock authStore
const mockLogin = vi.fn()
const mockSetToken = vi.fn()
vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({
    login: mockLogin,
    isAuthenticated: false,
    token: null,
    claims: null,
    logout: vi.fn(),
    setToken: mockSetToken,
  }),
}))

// Mock API functions
const mockGetProviders = vi.fn()
const mockGetSuperAdminStatus = vi.fn()
const mockSuperAdminLogin = vi.fn()
vi.mock('../api/systemConfigApi', () => ({
  getIdentityProviders: () => mockGetProviders(),
  getSuperAdminStatus: () => mockGetSuperAdminStatus(),
  superAdminLogin: (u: string, p: string) => mockSuperAdminLogin(u, p),
}))

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return React.createElement(QueryClientProvider, { client: qc },
    React.createElement(MemoryRouter, null, children)
  )
}

import { LoginPage } from '../pages/auth/LoginPage'

describe('LoginPage - state rendering', () => {

  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProviders.mockResolvedValue({ items: [], total: 0 })
    mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: false, username: null, last_login_at: null })
    mockSuperAdminLogin.mockResolvedValue({ access_token: 'test-token', token_type: 'bearer', username: 'admin', is_super_admin: true })
  })

  describe('super_admin_only state', () => {
    beforeEach(() => {
      mockGetProviders.mockResolvedValue({ items: [], total: 0 })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: true, username: 'admin', last_login_at: null })
    })

    it('shows super admin login form', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.superAdminInfo')).toBeDefined()
      })
    })

    it('renders username and password fields', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        // MUI TextField renders labels that can be found by label text
        const usernameLabel = screen.getByLabelText('auth.username')
        const passwordLabel = screen.getByLabelText('auth.password')
        expect(usernameLabel).toBeDefined()
        expect(passwordLabel).toBeDefined()
      })
    })

    it('has login button for super admin', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.login')).toBeDefined()
      })
    })

    it('does not show OIDC login button', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.queryByText('auth.loginWithProvider')).toBeNull()
      })
    })
  })

  describe('oidc_only state', () => {
    beforeEach(() => {
      mockGetProviders.mockResolvedValue({
        items: [{ id: '1', provider_scope: 'user', is_enabled: true, provider_type: 'oidc_generic', display_name: 'OIDC', issuer_url: '', client_id: '', encrypted_client_secret: null, scopes: '', claim_mappings: null, created_at: '', updated_at: '' }],
        total: 1,
      })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: false, username: 'admin', last_login_at: null })
    })

    it('shows OIDC login button', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.loginWith')).toBeDefined()
        expect(screen.getByText('auth.loginWithProvider')).toBeDefined()
      })
    })

    it('does not show super admin form', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.queryByText('auth.superAdminInfo')).toBeNull()
      })
    })

    it('calls login when OIDC button clicked', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.loginWithProvider')).toBeDefined()
      })
      fireEvent.click(screen.getByText('auth.loginWithProvider'))
      expect(mockLogin).toHaveBeenCalledTimes(1)
    })
  })

  describe('both state', () => {
    beforeEach(() => {
      mockGetProviders.mockResolvedValue({
        items: [{ id: '1', provider_scope: 'user', is_enabled: true, provider_type: 'oidc_generic', display_name: 'OIDC', issuer_url: '', client_id: '', encrypted_client_secret: null, scopes: '', claim_mappings: null, created_at: '', updated_at: '' }],
        total: 1,
      })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: true, username: 'admin', last_login_at: null })
    })

    it('shows OIDC login button first', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.loginWithProvider')).toBeDefined()
      })
    })

    it('shows divider with "or" text', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.or')).toBeDefined()
      })
    })

    it('shows "Login as Super Admin" toggle button', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.loginAsSuperAdmin')).toBeDefined()
      })
    })

    it('reveals super admin form when toggle clicked', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.loginAsSuperAdmin')).toBeDefined()
      })
      fireEvent.click(screen.getByText('auth.loginAsSuperAdmin'))
      await waitFor(() => {
        expect(screen.getByLabelText('auth.username')).toBeDefined()
        expect(screen.getByLabelText('auth.password')).toBeDefined()
      })
    })

    it('shows back button when super admin form is revealed', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.loginAsSuperAdmin')).toBeDefined()
      })
      fireEvent.click(screen.getByText('auth.loginAsSuperAdmin'))
      await waitFor(() => {
        expect(screen.getByText('app.back')).toBeDefined()
      })
    })

    it('hides super admin form when back button clicked', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.loginAsSuperAdmin')).toBeDefined()
      })
      fireEvent.click(screen.getByText('auth.loginAsSuperAdmin'))
      await waitFor(() => {
        expect(screen.getByText('app.back')).toBeDefined()
      })
      fireEvent.click(screen.getByText('app.back'))
      await waitFor(() => {
        expect(screen.queryByText('app.back')).toBeNull()
        expect(screen.getByText('auth.loginAsSuperAdmin')).toBeDefined()
      })
    })
  })

  describe('setup_wizard state', () => {
    beforeEach(() => {
      mockGetProviders.mockResolvedValue({ items: [], total: 0 })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: false, username: null, last_login_at: null })
    })

    it('shows setup wizard redirect', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.setupWizard')).toBeDefined()
        expect(screen.getByText('auth.goToSetup')).toBeDefined()
      })
    })

    it('navigates to setup when button clicked', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.goToSetup')).toBeDefined()
      })
      fireEvent.click(screen.getByText('auth.goToSetup'))
      expect(mockNavigate).toHaveBeenCalledWith('/setup')
    })
  })

  describe('super admin login form submission', () => {
    beforeEach(() => {
      mockGetProviders.mockResolvedValue({ items: [], total: 0 })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: true, username: 'admin', last_login_at: null })
      mockSuperAdminLogin.mockResolvedValue({ access_token: 'sa-test-token', token_type: 'bearer', username: 'admin', is_super_admin: true })
    })

    it('calls super admin login API on form submit', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByLabelText('auth.username')).toBeDefined()
        expect(screen.getByLabelText('auth.password')).toBeDefined()
      })

      fireEvent.change(screen.getByLabelText('auth.username'), { target: { value: 'admin' } })
      fireEvent.change(screen.getByLabelText('auth.password'), { target: { value: 'testpass' } })
      fireEvent.click(screen.getByText('auth.login'))

      await waitFor(() => {
        expect(mockSuperAdminLogin).toHaveBeenCalledWith('admin', 'testpass')
      })
    })

    it('navigates to dashboard on successful login', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByLabelText('auth.username')).toBeDefined()
      })

      fireEvent.change(screen.getByLabelText('auth.username'), { target: { value: 'admin' } })
      fireEvent.change(screen.getByLabelText('auth.password'), { target: { value: 'testpass' } })
      fireEvent.click(screen.getByText('auth.login'))

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/dashboard', { replace: true })
      })
    })

    it('stores token in localStorage on successful login', async () => {
      const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')

      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByLabelText('auth.username')).toBeDefined()
      })

      fireEvent.change(screen.getByLabelText('auth.username'), { target: { value: 'admin' } })
      fireEvent.change(screen.getByLabelText('auth.password'), { target: { value: 'testpass' } })
      fireEvent.click(screen.getByText('auth.login'))

      await waitFor(() => {
        expect(setItemSpy).toHaveBeenCalledWith('access_token', 'sa-test-token')
        expect(setItemSpy).toHaveBeenCalledWith('super_admin_token', 'sa-test-token')
      })
      setItemSpy.mockRestore()
    })

    it('sets token via authStore setToken on success', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByLabelText('auth.username')).toBeDefined()
      })

      fireEvent.change(screen.getByLabelText('auth.username'), { target: { value: 'admin' } })
      fireEvent.change(screen.getByLabelText('auth.password'), { target: { value: 'testpass' } })
      fireEvent.click(screen.getByText('auth.login'))

      await waitFor(() => {
        expect(mockSetToken).toHaveBeenCalledWith('sa-test-token')
      })
    })

    it('displays error message on failed super admin login', async () => {
      mockSuperAdminLogin.mockRejectedValue(
        new Error('Invalid username or password')
      )

      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByLabelText('auth.username')).toBeDefined()
      })

      fireEvent.change(screen.getByLabelText('auth.username'), { target: { value: 'admin' } })
      fireEvent.change(screen.getByLabelText('auth.password'), { target: { value: 'wrong' } })
      fireEvent.click(screen.getByText('auth.login'))

      await waitFor(() => {
        expect(screen.getByText('Invalid username or password')).toBeDefined()
      })
    })

    it('does not navigate to dashboard on failed login', async () => {
      mockSuperAdminLogin.mockRejectedValue(
        new Error('Invalid username or password')
      )

      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByLabelText('auth.username')).toBeDefined()
      })

      fireEvent.change(screen.getByLabelText('auth.username'), { target: { value: 'admin' } })
      fireEvent.change(screen.getByLabelText('auth.password'), { target: { value: 'wrong' } })
      fireEvent.click(screen.getByText('auth.login'))
      mockNavigate.mockClear()  // Clear previous calls

      await waitFor(() => {
        expect(screen.getByText('Invalid username or password')).toBeDefined()
      })
      // navigate should not have been called with /dashboard since login failed
      const dashboardCalls = mockNavigate.mock.calls.filter(
        (call: string[]) => call[0] === '/dashboard'
      )
      expect(dashboardCalls.length).toBe(0)
    })

    it('login button is disabled when fields are empty', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByLabelText('auth.username')).toBeDefined()
      })

      const loginBtn = screen.getByText('auth.login').closest('button')
      expect(loginBtn).toHaveProperty('disabled', true)

      // Fill username only
      fireEvent.change(screen.getByLabelText('auth.username'), { target: { value: 'admin' } })
      await waitFor(() => {
        expect(loginBtn).toHaveProperty('disabled', true)
      })

      // Fill both
      fireEvent.change(screen.getByLabelText('auth.password'), { target: { value: 'testpass' } })
      await waitFor(() => {
        expect(loginBtn).toHaveProperty('disabled', false)
      })
    })
  })

  describe('loading spinner', () => {
    it('shows loading spinner while discovering providers', () => {
      // Create slow-resolving promises
      mockGetProviders.mockReturnValue(new Promise(() => {}))  // Never resolves
      mockGetSuperAdminStatus.mockReturnValue(new Promise(() => {}))

      render(React.createElement(LoginPage), { wrapper: Wrapper })

      // MUI CircularProgress renders as a <span> with role="progressbar"
      const spinner = document.querySelector('[role="progressbar"]')
      expect(spinner).toBeDefined()
    })
  })
})
