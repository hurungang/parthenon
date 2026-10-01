/**
 * SignUpPage — PUBLIC account-first self-serve registration (Phase 10.18).
 *
 * Covers the planned sign-up page scenarios:
 * - page/link absent (inert) when the tenancy switch is off; spinner
 *   while discovery resolves
 * - client validation errors (email, password, mismatch, blank org,
 *   malformed slug)
 * - server rejections surfaced clearly: duplicate email, address taken,
 *   one-tenant-per-user
 * - success: token stored, per-tab slug set, routed into guided
 *   onboarding as the root user
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual =
    await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

// Auth store: multiTenancyEnabled is tri-state (null = resolving)
const mockSetToken = vi.fn()
let mockTenancyState: boolean | null = true
vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({
    setToken: mockSetToken,
    multiTenancyEnabled: mockTenancyState,
  }),
}))

vi.mock('../api/tenantAuthApi', () => ({
  registerAccount: vi.fn(),
  setResolvedTenantSlug: vi.fn(),
}))

import { registerAccount, setResolvedTenantSlug } from '../api/tenantAuthApi'
import { SignUpPage } from '../pages/auth/SignUpPage'

const mocked = vi.mocked

function renderPage() {
  return render(
    <MemoryRouter>
      <SignUpPage />
    </MemoryRouter>,
  )
}

describe('SignUpPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockTenancyState = true
    localStorage.clear()
  })

  it('renders a spinner while the tenancy switch is unresolved', () => {
    mockTenancyState = null
    renderPage()
    expect(screen.queryByLabelText('signup.email')).toBeNull()
    expect(screen.queryByText('signup.title')).toBeNull()
  })

  it('is inert when the tenancy switch is off — no form, unavailable note', () => {
    mockTenancyState = false
    renderPage()
    expect(screen.getByText('signup.title')).toBeDefined()
    expect(screen.getByText('signup.unavailable')).toBeDefined()
    expect(screen.queryByLabelText('signup.email')).toBeNull()
    expect(screen.queryByRole('button', { name: 'signup.createWorkspace' })).toBeNull()
  })

  it('renders the account step when the switch is on', () => {
    renderPage()
    expect(screen.getByTestId('signup-step-account')).toBeDefined()
    expect(screen.getByLabelText('signup.email')).toBeDefined()
    expect(screen.getByLabelText('signup.password')).toBeDefined()
  })

  it('rejects an invalid email with a clear client-side error', () => {
    renderPage()
    fireEvent.change(screen.getByLabelText('signup.email'), {
      target: { value: 'not-an-email' },
    })
    fireEvent.change(screen.getByLabelText('signup.password'), {
      target: { value: 'Sup3rSecret' },
    })
    fireEvent.change(screen.getByLabelText('signup.confirmPassword'), {
      target: { value: 'Sup3rSecret' },
    })
    fireEvent.click(screen.getByText('signup.continue'))
    expect(screen.getByTestId('signup-error').textContent).toBe(
      'signup.error.email',
    )
    // Still on the account step.
    expect(screen.getByTestId('signup-step-account')).toBeDefined()
  })

  it('rejects a weak password and a confirmation mismatch', () => {
    renderPage()
    fireEvent.change(screen.getByLabelText('signup.email'), {
      target: { value: 'owner@test.dev' },
    })
    fireEvent.change(screen.getByLabelText('signup.password'), {
      target: { value: 'nodigits' },
    })
    fireEvent.change(screen.getByLabelText('signup.confirmPassword'), {
      target: { value: 'nodigits' },
    })
    fireEvent.click(screen.getByText('signup.continue'))
    expect(screen.getByTestId('signup-error').textContent).toBe(
      'signup.error.password',
    )

    fireEvent.change(screen.getByLabelText('signup.password'), {
      target: { value: 'Sup3rSecret' },
    })
    fireEvent.click(screen.getByText('signup.continue'))
    expect(screen.getByTestId('signup-error').textContent).toBe(
      'signup.error.passwordMismatch',
    )
  })

  it('advances to the organization step and auto-derives the address', () => {
    renderPage()
    fireEvent.change(screen.getByLabelText('signup.email'), {
      target: { value: 'owner@test.dev' },
    })
    fireEvent.change(screen.getByLabelText('signup.password'), {
      target: { value: 'Sup3rSecret' },
    })
    fireEvent.change(screen.getByLabelText('signup.confirmPassword'), {
      target: { value: 'Sup3rSecret' },
    })
    fireEvent.click(screen.getByText('signup.continue'))

    expect(screen.getByTestId('signup-step-organization')).toBeDefined()
    fireEvent.change(screen.getByLabelText('signup.orgName'), {
      target: { value: 'Acme Corp!' },
    })
    // Slug auto-derived, lowercased, non-alphanumerics dashed.
    expect(
      (screen.getByLabelText('signup.orgAddress') as HTMLInputElement).value,
    ).toBe('acme-corp')
  })

  it('registers successfully and lands in guided onboarding as the root', async () => {
    mocked(registerAccount).mockResolvedValue({
      tenant_id: 't-1',
      name: 'Acme Corp',
      slug: 'acme-corp',
      your_role: 'tenant_admin',
      is_root: true,
      access_token: 'TOKEN-123',
      token_type: 'bearer',
    })
    renderPage()
    fireEvent.change(screen.getByLabelText('signup.email'), {
      target: { value: 'owner@test.dev' },
    })
    fireEvent.change(screen.getByLabelText('signup.password'), {
      target: { value: 'Sup3rSecret' },
    })
    fireEvent.change(screen.getByLabelText('signup.confirmPassword'), {
      target: { value: 'Sup3rSecret' },
    })
    fireEvent.click(screen.getByText('signup.continue'))
    fireEvent.change(screen.getByLabelText('signup.orgName'), {
      target: { value: 'Acme Corp' },
    })
    fireEvent.click(screen.getByTestId('signup-submit'))

    await waitFor(() => {
      expect(mocked(registerAccount)).toHaveBeenCalledWith({
        email: 'owner@test.dev',
        password: 'Sup3rSecret',
        organization_name: 'Acme Corp',
        slug: 'acme-corp',
      })
    })
    // Session stored + tenant-bound per-tab slug + onboarding redirect.
    await waitFor(() => {
      expect(mockSetToken).toHaveBeenCalledWith('TOKEN-123')
      expect(localStorage.getItem('access_token')).toBe('TOKEN-123')
      expect(mocked(setResolvedTenantSlug)).toHaveBeenCalledWith('acme-corp')
      expect(mockNavigate).toHaveBeenCalledWith('/tenant/onboarding', {
        replace: true,
      })
    })
  })

  it('surfaces a duplicate-email rejection clearly', async () => {
    mocked(registerAccount).mockRejectedValue(
      Object.assign(new Error('conflict'), {
        isAxiosError: true,
        response: {
          status: 409,
          data: { detail: 'An account with this email already exists' },
        },
      }),
    )
    renderPage()
    fireEvent.change(screen.getByLabelText('signup.email'), {
      target: { value: 'owner@test.dev' },
    })
    fireEvent.change(screen.getByLabelText('signup.password'), {
      target: { value: 'Sup3rSecret' },
    })
    fireEvent.change(screen.getByLabelText('signup.confirmPassword'), {
      target: { value: 'Sup3rSecret' },
    })
    fireEvent.click(screen.getByText('signup.continue'))
    fireEvent.change(screen.getByLabelText('signup.orgName'), {
      target: { value: 'Acme Corp' },
    })
    fireEvent.click(screen.getByTestId('signup-submit'))

    await waitFor(() => {
      expect(screen.getByTestId('signup-error').textContent).toBe(
        'signup.error.emailExists',
      )
    })
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('surfaces an address-taken rejection clearly', async () => {
    mocked(registerAccount).mockRejectedValue(
      Object.assign(new Error('conflict'), {
        isAxiosError: true,
        response: {
          status: 409,
          data: { detail: "The address 'acme-corp' is already taken" },
        },
      }),
    )
    renderPage()
    fireEvent.change(screen.getByLabelText('signup.email'), {
      target: { value: 'owner@test.dev' },
    })
    fireEvent.change(screen.getByLabelText('signup.password'), {
      target: { value: 'Sup3rSecret' },
    })
    fireEvent.change(screen.getByLabelText('signup.confirmPassword'), {
      target: { value: 'Sup3rSecret' },
    })
    fireEvent.click(screen.getByText('signup.continue'))
    fireEvent.change(screen.getByLabelText('signup.orgName'), {
      target: { value: 'Acme Corp' },
    })
    fireEvent.click(screen.getByTestId('signup-submit'))

    await waitFor(() => {
      expect(screen.getByTestId('signup-error').textContent).toBe(
        'signup.error.slugTaken',
      )
    })
  })

  it('surfaces the one-tenant-per-user block clearly', async () => {
    mocked(registerAccount).mockRejectedValue(
      Object.assign(new Error('conflict'), {
        isAxiosError: true,
        response: {
          status: 409,
          data: { detail: 'Each user can own only one organization' },
        },
      }),
    )
    renderPage()
    fireEvent.change(screen.getByLabelText('signup.email'), {
      target: { value: 'owner@test.dev' },
    })
    fireEvent.change(screen.getByLabelText('signup.password'), {
      target: { value: 'Sup3rSecret' },
    })
    fireEvent.change(screen.getByLabelText('signup.confirmPassword'), {
      target: { value: 'Sup3rSecret' },
    })
    fireEvent.click(screen.getByText('signup.continue'))
    fireEvent.change(screen.getByLabelText('signup.orgName'), {
      target: { value: 'Acme Corp' },
    })
    fireEvent.click(screen.getByTestId('signup-submit'))

    await waitFor(() => {
      expect(screen.getByTestId('signup-error').textContent).toBe(
        'signup.error.oneTenantPerUser',
      )
    })
    expect(mockNavigate).not.toHaveBeenCalled()
  })
})
