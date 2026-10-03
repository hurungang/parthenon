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

// Mock authStore — tenancy state is mutable per test (null = discovery in flight)
const mockLogin = vi.fn()
const mockSetToken = vi.fn()
const mockRefreshProviders = vi.fn()
let mockMultiTenancyEnabled: boolean | null = false
// FIX-20261001-235247: mutable so tests can simulate a HOST-derived tenant
// (AuthProvider resolved it from the host) and clear it like the real
// clearResolvedTenant would.
let mockResolvedTenant: { slug: string; name: string; status: string; sign_in_ready: boolean } | null = null
const mockClearResolvedTenant = vi.fn(() => { mockResolvedTenant = null })
vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({
    login: mockLogin,
    isAuthenticated: false,
    token: null,
    claims: null,
    logout: vi.fn(),
    setToken: mockSetToken,
    multiTenancyEnabled: mockMultiTenancyEnabled,
    resolvedTenant: mockResolvedTenant,
    refreshProviders: mockRefreshProviders,
    clearResolvedTenant: mockClearResolvedTenant,
  }),
}))

// Mock system config API functions (providers, super admin)
const mockGetProviders = vi.fn()
const mockGetSuperAdminStatus = vi.fn()
const mockSuperAdminLogin = vi.fn()
vi.mock('../api/systemConfigApi', () => ({
  getIdentityProviders: () => mockGetProviders(),
  getSuperAdminStatus: () => mockGetSuperAdminStatus(),
  superAdminLogin: (u: string, p: string) => mockSuperAdminLogin(u, p),
}))

// Mock tenant auth API functions (platform password sign-in + workspace discovery)
const mockLoginPassword = vi.fn()
const mockSetResolvedTenantSlug = vi.fn()
const mockDiscoverTenant = vi.fn()
const mockGetRememberedTenantSlug = vi.fn()
const mockSetRememberedTenantSlug = vi.fn()
vi.mock('../api/tenantAuthApi', () => ({
  loginPassword: (e: string, p: string) => mockLoginPassword(e, p),
  setResolvedTenantSlug: (slug: string | null) => mockSetResolvedTenantSlug(slug),
  discoverTenant: (slug?: string) => mockDiscoverTenant(slug),
  getRememberedTenantSlug: () => mockGetRememberedTenantSlug(),
  setRememberedTenantSlug: (slug: string | null) => mockSetRememberedTenantSlug(slug),
}))

const OIDC_PROVIDER_ITEM = {
  id: '1',
  provider_scope: 'user',
  is_enabled: true,
  provider_type: 'oidc_generic',
  display_name: 'OIDC',
  issuer_url: '',
  client_id: '',
  encrypted_client_secret: null,
  scopes: '',
  claim_mappings: null,
  created_at: '',
  updated_at: '',
}

function Wrapper({ children, initialEntries }: { children?: React.ReactNode; initialEntries?: string[] }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return React.createElement(QueryClientProvider, { client: qc },
    React.createElement(MemoryRouter, { initialEntries }, children)
  )
}

const ACTIVE_TENANT = {
  slug: 'acme',
  name: 'Acme Corp',
  status: 'active',
  sign_in_ready: true,
}

const SUSPENDED_TENANT = {
  slug: 'acme',
  name: 'Acme Corp',
  status: 'suspended',
  sign_in_ready: false,
}

import { LoginPage } from '../pages/auth/LoginPage'

describe('LoginPage - state rendering', () => {

  beforeEach(() => {
    vi.clearAllMocks()
    mockMultiTenancyEnabled = false
    mockResolvedTenant = null
    mockGetProviders.mockResolvedValue({ items: [], total: 0 })
    mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: false, username: null, last_login_at: null })
    mockSuperAdminLogin.mockResolvedValue({ access_token: 'test-token', token_type: 'bearer', username: 'admin', is_super_admin: true })
    mockLoginPassword.mockResolvedValue({
      access_token: 'pw-token', token_type: 'bearer',
      tenant_id: 't1', tenant_slug: 'acme', tenant_name: 'Acme', your_role: 'platform_admin',
    })
    mockDiscoverTenant.mockResolvedValue({ multi_tenancy_enabled: true, tenant: ACTIVE_TENANT })
    mockGetRememberedTenantSlug.mockReturnValue(null)
  })

  describe('oidc_only state (tenancy off)', () => {
    beforeEach(() => {
      mockGetProviders.mockResolvedValue({ items: [OIDC_PROVIDER_ITEM], total: 1 })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: false, username: 'admin', last_login_at: null })
    })

    it('shows OIDC login button', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.loginWith')).toBeDefined()
        expect(screen.getByText('auth.loginWithProvider')).toBeDefined()
      })
    })

    it('shows the OIDC button as the primary (contained) action when no password form exists', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        const btn = screen.getByText('auth.loginWithProvider').closest('button')
        expect(btn?.className).toContain('MuiButton-contained')
      })
    })

    it('does not show super admin entry when super admin is disabled', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.queryByText('auth.superAdminInfo')).toBeNull()
        expect(screen.queryByTestId('super-admin-entry')).toBeNull()
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

  describe('super admin only (tenancy off, no OIDC)', () => {
    beforeEach(() => {
      mockGetProviders.mockResolvedValue({ items: [], total: 0 })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: true, username: 'admin', last_login_at: null })
    })

    it('shows a discreet platform admin entry instead of the form', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('super-admin-entry')).toBeDefined()
      })
      // Form fields are hidden until the entry is used
      expect(screen.queryByLabelText('auth.username')).toBeNull()
    })

    it('does not show OIDC login button', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.queryByText('auth.loginWithProvider')).toBeNull()
      })
    })

    it('reveals the super admin form with first-run info when the entry is clicked', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('super-admin-entry')).toBeDefined()
      })
      fireEvent.click(screen.getByTestId('super-admin-entry'))
      await waitFor(() => {
        expect(screen.getByLabelText('auth.username')).toBeDefined()
        expect(screen.getByLabelText('auth.password')).toBeDefined()
        expect(screen.getByText('auth.login')).toBeDefined()
        // First-run guidance lives inside the expanded form, not on the page
        expect(screen.getByText('auth.superAdminInfo')).toBeDefined()
      })
    })

    it('hides the super admin form when back is clicked', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('super-admin-entry')).toBeDefined()
      })
      fireEvent.click(screen.getByTestId('super-admin-entry'))
      await waitFor(() => {
        expect(screen.getByText('app.back')).toBeDefined()
      })
      fireEvent.click(screen.getByText('app.back'))
      await waitFor(() => {
        expect(screen.queryByText('app.back')).toBeNull()
        expect(screen.getByTestId('super-admin-entry')).toBeDefined()
      })
    })
  })

  describe('oidc + super admin (tenancy off)', () => {
    beforeEach(() => {
      mockGetProviders.mockResolvedValue({ items: [OIDC_PROVIDER_ITEM], total: 1 })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: true, username: 'admin', last_login_at: null })
    })

    it('shows the OIDC login button', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.loginWithProvider')).toBeDefined()
      })
    })

    it('shows the discreet platform admin entry and no password form or divider (tenancy off)', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('super-admin-entry')).toBeDefined()
        expect(screen.queryByTestId('password-signin-form')).toBeNull()
        expect(screen.queryByText('auth.or')).toBeNull()
      })
    })

    it('reveals the super admin form without the info alert when OIDC is configured', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('super-admin-entry')).toBeDefined()
      })
      fireEvent.click(screen.getByTestId('super-admin-entry'))
      await waitFor(() => {
        expect(screen.getByLabelText('auth.username')).toBeDefined()
        expect(screen.queryByText('auth.superAdminInfo')).toBeNull()
      })
    })

    it('hides and re-reveals the super admin form', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('super-admin-entry')).toBeDefined()
      })
      fireEvent.click(screen.getByTestId('super-admin-entry'))
      await waitFor(() => {
        expect(screen.getByText('app.back')).toBeDefined()
      })
      fireEvent.click(screen.getByText('app.back'))
      await waitFor(() => {
        expect(screen.queryByText('app.back')).toBeNull()
        expect(screen.getByTestId('super-admin-entry')).toBeDefined()
      })
    })
  })

  describe('no providers configured (tenancy off)', () => {
    beforeEach(() => {
      mockGetProviders.mockResolvedValue({ items: [], total: 0 })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: false, username: null, last_login_at: null })
    })

    it('does NOT show the setup wizard prompt or navigate to /setup', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('app.title')).toBeDefined()
      })
      expect(screen.queryByText('auth.setupWizard')).toBeNull()
      expect(screen.queryByText('auth.goToSetup')).toBeNull()
      expect(mockNavigate).not.toHaveBeenCalledWith('/setup')
    })

    it('explains that no sign-in method is available', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByText('auth.noSignInAvailable')).toBeDefined()
      })
    })
  })

  describe('password sign-in (tenancy on)', () => {
    beforeEach(() => {
      mockMultiTenancyEnabled = true
      // A remembered workspace skips the find-workspace step, landing the
      // page directly on the tenant-branded sign-in card these tests cover.
      mockGetRememberedTenantSlug.mockReturnValue('acme')
      mockGetProviders.mockResolvedValue({ items: [], total: 0 })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: false, username: null, last_login_at: null })
    })

    it('shows the email + password form even with no OIDC provider configured', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('password-signin-form')).toBeDefined()
        expect(screen.getByLabelText('auth.email')).toBeDefined()
        expect(screen.getByLabelText('auth.password')).toBeDefined()
      })
      // Absence of OIDC must NOT produce the setup wizard prompt
      expect(screen.queryByText('auth.setupWizard')).toBeNull()
      expect(screen.queryByText('auth.goToSetup')).toBeNull()
    })

    it('shows the signup entry link', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('signup-entry-link')).toBeDefined()
        expect(screen.getByText('auth.noWorkspaceYet')).toBeDefined()
      })
    })

    it('shows the OIDC button with a divider when a provider is configured', async () => {
      mockGetProviders.mockResolvedValue({ items: [OIDC_PROVIDER_ITEM], total: 1 })
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('password-signin-form')).toBeDefined()
        expect(screen.getByText('auth.loginWithProvider')).toBeDefined()
        expect(screen.getByText('auth.or')).toBeDefined()
      })
    })

    it('renders the password submit as the primary action next to a outlined OIDC button', async () => {
      mockGetProviders.mockResolvedValue({ items: [OIDC_PROVIDER_ITEM], total: 1 })
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        const submit = screen.getByText('auth.login').closest('button')
        const oidc = screen.getByText('auth.loginWithProvider').closest('button')
        expect(submit?.className).toContain('MuiButton-contained')
        expect(oidc?.className).toContain('MuiButton-outlined')
      })
    })

    it('disables the submit button while fields are empty', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByLabelText('auth.email')).toBeDefined()
      })

      const submitBtn = screen.getByText('auth.login').closest('button')
      expect(submitBtn).toHaveProperty('disabled', true)

      fireEvent.change(screen.getByLabelText('auth.email'), { target: { value: 'owner@acme.io' } })
      await waitFor(() => {
        expect(submitBtn).toHaveProperty('disabled', true)
      })

      fireEvent.change(screen.getByLabelText('auth.password'), { target: { value: 'secret123' } })
      await waitFor(() => {
        expect(submitBtn).toHaveProperty('disabled', false)
      })
    })

    it('calls loginPassword with the trimmed, lowercased email', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByLabelText('auth.email')).toBeDefined()
      })

      fireEvent.change(screen.getByLabelText('auth.email'), { target: { value: ' Owner@Acme.IO ' } })
      fireEvent.change(screen.getByLabelText('auth.password'), { target: { value: 'secret123' } })
      fireEvent.click(screen.getByText('auth.login'))

      await waitFor(() => {
        expect(mockLoginPassword).toHaveBeenCalledWith('owner@acme.io', 'secret123')
      })
    })

    it('stores the token, binds the tenant slug and navigates to the dashboard on success', async () => {
      const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')

      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByLabelText('auth.email')).toBeDefined()
      })

      fireEvent.change(screen.getByLabelText('auth.email'), { target: { value: 'owner@acme.io' } })
      fireEvent.change(screen.getByLabelText('auth.password'), { target: { value: 'secret123' } })
      fireEvent.click(screen.getByText('auth.login'))

      await waitFor(() => {
        expect(mockSetToken).toHaveBeenCalledWith('pw-token')
        expect(mockSetResolvedTenantSlug).toHaveBeenCalledWith('acme')
        expect(mockNavigate).toHaveBeenCalledWith('/dashboard', { replace: true })
      })
      expect(setItemSpy).toHaveBeenCalledWith('access_token', 'pw-token')
      setItemSpy.mockRestore()
    })

    it('shows an inline error and does not navigate on wrong credentials', async () => {
      mockLoginPassword.mockRejectedValue(new Error('Invalid email or password'))

      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByLabelText('auth.email')).toBeDefined()
      })

      fireEvent.change(screen.getByLabelText('auth.email'), { target: { value: 'owner@acme.io' } })
      fireEvent.change(screen.getByLabelText('auth.password'), { target: { value: 'wrong' } })
      fireEvent.click(screen.getByText('auth.login'))

      await waitFor(() => {
        expect(screen.getByText('Invalid email or password')).toBeDefined()
      })
      expect(mockNavigate).not.toHaveBeenCalledWith('/dashboard', { replace: true })
      expect(mockSetToken).not.toHaveBeenCalled()
    })

    it('shows the generic failure message for non-Error rejections', async () => {
      mockLoginPassword.mockRejectedValue({ response: { data: {} } })

      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByLabelText('auth.email')).toBeDefined()
      })

      fireEvent.change(screen.getByLabelText('auth.email'), { target: { value: 'owner@acme.io' } })
      fireEvent.change(screen.getByLabelText('auth.password'), { target: { value: 'wrong' } })
      fireEvent.click(screen.getByText('auth.login'))

      await waitFor(() => {
        expect(screen.getByText('auth.loginFailed')).toBeDefined()
      })
    })
  })

  describe('super admin entry (tenancy on)', () => {
    beforeEach(() => {
      mockMultiTenancyEnabled = true
      // Remembered workspace → straight to the tenant-branded card
      mockGetRememberedTenantSlug.mockReturnValue('acme')
      mockGetProviders.mockResolvedValue({ items: [OIDC_PROVIDER_ITEM], total: 1 })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: true, username: 'admin', last_login_at: null })
    })

    it('is NOT available on a customer workspace and shows only at root', async () => {
      // CHANGED ASSERTION (Phase 11 task 11.6): the discreet platform-admin
      // expansion was removed from tenant workspaces — the super-admin
      // break-glass entry is available ONLY when the resolved workspace
      // is `root`.  The remembered workspace here is `acme`.
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('password-signin-form')).toBeDefined()
        expect(screen.getByText('auth.loginWithProvider')).toBeDefined()
      })
      expect(screen.queryByTestId('super-admin-entry')).toBeNull()
      // Never prominent even at root: hidden form fields until the entry is used
      expect(screen.queryByLabelText('auth.username')).toBeNull()
    })

    it('stays available and discreet on the ROOT workspace', async () => {
      mockGetRememberedTenantSlug.mockReturnValue('root')
      mockDiscoverTenant.mockResolvedValue({
        multi_tenancy_enabled: true,
        tenant: { ...ACTIVE_TENANT, slug: 'root', name: 'Root' },
      })
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('password-signin-form')).toBeDefined()
        expect(screen.getByTestId('super-admin-entry')).toBeDefined()
      })
      expect(screen.queryByLabelText('auth.username')).toBeNull()
    })
  })

  describe('super admin login form submission', () => {
    beforeEach(() => {
      mockGetProviders.mockResolvedValue({ items: [], total: 0 })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: true, username: 'admin', last_login_at: null })
      mockSuperAdminLogin.mockResolvedValue({ access_token: 'sa-test-token', token_type: 'bearer', username: 'admin', is_super_admin: true })
    })

    const expandSuperAdminForm = async () => {
      await waitFor(() => {
        expect(screen.getByTestId('super-admin-entry')).toBeDefined()
      })
      fireEvent.click(screen.getByTestId('super-admin-entry'))
      await waitFor(() => {
        expect(screen.getByLabelText('auth.username')).toBeDefined()
        expect(screen.getByLabelText('auth.password')).toBeDefined()
      })
    }

    it('calls super admin login API on form submit', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await expandSuperAdminForm()

      fireEvent.change(screen.getByLabelText('auth.username'), { target: { value: 'admin' } })
      fireEvent.change(screen.getByLabelText('auth.password'), { target: { value: 'testpass' } })
      fireEvent.click(screen.getByText('auth.login'))

      await waitFor(() => {
        expect(mockSuperAdminLogin).toHaveBeenCalledWith('admin', 'testpass')
      })
    })

    it('navigates to dashboard on successful login', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await expandSuperAdminForm()

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
      await expandSuperAdminForm()

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
      await expandSuperAdminForm()

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
      await expandSuperAdminForm()

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
      await expandSuperAdminForm()

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
      await expandSuperAdminForm()

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

  describe('workspace address sign-in (tenancy on, no workspace bound)', () => {
    beforeEach(() => {
      mockMultiTenancyEnabled = true
      mockGetRememberedTenantSlug.mockReturnValue(null)
      mockGetProviders.mockResolvedValue({ items: [], total: 0 })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: false, username: null, last_login_at: null })
    })

    it('shows the find-workspace card first when nothing is bound', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('workspace-finder-form')).toBeDefined()
      })
      expect(screen.queryByTestId('password-signin-form')).toBeNull()
      expect(screen.getByLabelText('auth.findWorkspace.addressLabel')).toBeDefined()
      // "Remember this workspace" defaults to checked
      const checkbox = screen.getByTestId('remember-workspace-checkbox').querySelector('input')
      expect(checkbox).toHaveProperty('checked', true)
      // Continue is disabled while the address is empty
      expect(screen.getByText('auth.findWorkspace.continue').closest('button')).toHaveProperty('disabled', true)
    })

    it('resolves a bare slug to the tenant-branded sign-in card', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('workspace-finder-form')).toBeDefined()
      })
      fireEvent.change(screen.getByLabelText('auth.findWorkspace.addressLabel'), { target: { value: 'acme' } })
      fireEvent.click(screen.getByTestId('find-workspace-submit'))
      await waitFor(() => {
        expect(screen.getByTestId('password-signin-form')).toBeDefined()
        expect(screen.getByText('auth.tenantWorkspaceOf')).toBeDefined()
      })
      expect(mockDiscoverTenant).toHaveBeenCalledWith('acme')
      expect(mockSetResolvedTenantSlug).toHaveBeenCalledWith('acme')
      expect(mockSetRememberedTenantSlug).toHaveBeenCalledWith('acme')
      // OIDC start config re-resolves for the newly bound tenant context
      expect(mockRefreshProviders).toHaveBeenCalled()
    })

    it('derives the slug from a full host address and shows a hint', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('workspace-finder-form')).toBeDefined()
      })
      fireEvent.change(screen.getByLabelText('auth.findWorkspace.addressLabel'), { target: { value: 'acme.example.com' } })
      await waitFor(() => {
        expect(screen.getByText('auth.findWorkspace.slugHint')).toBeDefined()
      })
      fireEvent.click(screen.getByTestId('find-workspace-submit'))
      await waitFor(() => {
        expect(screen.getByTestId('password-signin-form')).toBeDefined()
      })
      expect(mockDiscoverTenant).toHaveBeenCalledWith('acme')
    })

    it('shows a neutral error and stays on the finder for an unknown workspace', async () => {
      mockDiscoverTenant.mockResolvedValue({ multi_tenancy_enabled: true, tenant: null })
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('workspace-finder-form')).toBeDefined()
      })
      fireEvent.change(screen.getByLabelText('auth.findWorkspace.addressLabel'), { target: { value: 'acme' } })
      fireEvent.click(screen.getByTestId('find-workspace-submit'))
      await waitFor(() => {
        expect(screen.getByText('auth.findWorkspace.notFound')).toBeDefined()
      })
      expect(screen.queryByTestId('password-signin-form')).toBeNull()
      expect(mockSetResolvedTenantSlug).not.toHaveBeenCalled()
    })

    it('does not remember the workspace when the checkbox is unchecked', async () => {
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('workspace-finder-form')).toBeDefined()
      })
      fireEvent.click(screen.getByTestId('remember-workspace-checkbox'))
      fireEvent.change(screen.getByLabelText('auth.findWorkspace.addressLabel'), { target: { value: 'acme' } })
      fireEvent.click(screen.getByTestId('find-workspace-submit'))
      await waitFor(() => {
        expect(screen.getByTestId('password-signin-form')).toBeDefined()
      })
      expect(mockSetRememberedTenantSlug).toHaveBeenCalledWith(null)
    })

    it('skips the find step for a remembered workspace', async () => {
      mockGetRememberedTenantSlug.mockReturnValue('acme')
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('password-signin-form')).toBeDefined()
        expect(screen.getByText('auth.tenantWorkspaceOf')).toBeDefined()
      })
      expect(screen.queryByTestId('workspace-finder-form')).toBeNull()
      expect(mockDiscoverTenant).toHaveBeenCalledWith('acme')
    })

    it('falls back to the finder when the remembered workspace is gone', async () => {
      mockGetRememberedTenantSlug.mockReturnValue('acme')
      mockDiscoverTenant.mockResolvedValue({ multi_tenancy_enabled: true, tenant: null })
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('workspace-finder-form')).toBeDefined()
      })
      expect(screen.queryByTestId('password-signin-form')).toBeNull()
      // Stale hint is cleaned up
      expect(mockSetRememberedTenantSlug).toHaveBeenCalledWith(null)
    })

    it('pre-resolves ?workspace= straight to the branded card without remembering', async () => {
      render(
        React.createElement(Wrapper, { initialEntries: ['/login?workspace=acme'] },
          React.createElement(LoginPage)
        )
      )
      await waitFor(() => {
        expect(screen.getByTestId('password-signin-form')).toBeDefined()
        expect(screen.getByText('auth.tenantWorkspaceOf')).toBeDefined()
      })
      expect(screen.queryByTestId('workspace-finder-form')).toBeNull()
      expect(mockDiscoverTenant).toHaveBeenCalledWith('acme')
      // Deep links never write the remember hint implicitly
      expect(mockSetRememberedTenantSlug).not.toHaveBeenCalled()
    })

    it('clears stored workspaces and returns to the finder via the switch link', async () => {
      mockGetRememberedTenantSlug.mockReturnValue('acme')
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('switch-workspace-link')).toBeDefined()
      })
      fireEvent.click(screen.getByTestId('switch-workspace-link'))
      await waitFor(() => {
        expect(screen.getByTestId('workspace-finder-form')).toBeDefined()
      })
      expect(mockSetRememberedTenantSlug).toHaveBeenCalledWith(null)
      expect(mockSetResolvedTenantSlug).toHaveBeenCalledWith(null)
      expect(screen.queryByTestId('password-signin-form')).toBeNull()
    })

    it('shows the blocked state for a suspended workspace address', async () => {
      mockDiscoverTenant.mockResolvedValue({ multi_tenancy_enabled: true, tenant: SUSPENDED_TENANT })
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('workspace-finder-form')).toBeDefined()
      })
      fireEvent.change(screen.getByLabelText('auth.findWorkspace.addressLabel'), { target: { value: 'acme' } })
      fireEvent.click(screen.getByTestId('find-workspace-submit'))
      await waitFor(() => {
        expect(screen.getByText('auth.tenantBlocked')).toBeDefined()
      })
      expect(screen.queryByTestId('password-signin-form')).toBeNull()
    })

    it('keeps the signup link and the discreet super admin entry on the finder', async () => {
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: true, username: 'admin', last_login_at: null })
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('workspace-finder-form')).toBeDefined()
      })
      expect(screen.getByTestId('signup-entry-link')).toBeDefined()
      expect(screen.getByTestId('super-admin-entry')).toBeDefined()
    })
  })

  // FIX-20261001-235247 (Defect 1): the "Use a different workspace" escape
  // hatch must be reachable in EVERY tenant-bound sign-in state.
  describe('switch workspace (FIX-20261001-235247)', () => {
    beforeEach(() => {
      mockMultiTenancyEnabled = true
      mockGetProviders.mockResolvedValue({ items: [], total: 0 })
      mockGetSuperAdminStatus.mockResolvedValue({ is_enabled: true, username: 'admin', last_login_at: null })
    })

    it('shows the switch link on the ROOT workspace card (break-glass preserved)', async () => {
      mockGetRememberedTenantSlug.mockReturnValue('root')
      mockDiscoverTenant.mockResolvedValue({
        multi_tenancy_enabled: true,
        tenant: { ...ACTIVE_TENANT, slug: 'root', name: 'Root' },
      })
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('password-signin-form')).toBeDefined()
        // Root workspace: the super-admin break-glass entry must co-exist
        expect(screen.getByTestId('super-admin-entry')).toBeDefined()
      })
      expect(screen.getByTestId('switch-workspace-link')).toBeDefined()
    })

    it('shows the switch link when a remembered workspace auto-resolves to a card', async () => {
      mockGetRememberedTenantSlug.mockReturnValue('acme')
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('password-signin-form')).toBeDefined()
        expect(screen.getByTestId('switch-workspace-link')).toBeDefined()
      })
    })

    it('shows the switch link on a HOST-derived tenant (idle phase — the regression)', async () => {
      // AuthProvider resolved the tenant from the host before /login — the
      // phase never leaves `idle`, which previously hid the link entirely.
      mockResolvedTenant = { ...ACTIVE_TENANT, slug: 'acme', name: 'Acme Corp' }
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('password-signin-form')).toBeDefined()
      })
      expect(screen.getByTestId('switch-workspace-link')).toBeDefined()
    })

    it('clicking the link on a host-derived tenant clears the tenant and lands on the finder', async () => {
      mockResolvedTenant = { ...ACTIVE_TENANT, slug: 'acme', name: 'Acme Corp' }
      render(React.createElement(LoginPage), { wrapper: Wrapper })
      await waitFor(() => {
        expect(screen.getByTestId('switch-workspace-link')).toBeDefined()
      })
      fireEvent.click(screen.getByTestId('switch-workspace-link'))
      await waitFor(() => {
        expect(screen.getByTestId('workspace-finder-form')).toBeDefined()
      })
      // Both the remembered hint and the host-derived store tenant are cleared
      expect(mockSetRememberedTenantSlug).toHaveBeenCalledWith(null)
      expect(mockClearResolvedTenant).toHaveBeenCalled()
      expect(screen.queryByTestId('password-signin-form')).toBeNull()
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
